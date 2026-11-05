import CoreML
import CoreGraphics
import CoreVideo
import Foundation
import Vision

/// A model score, not a calibrated probability that a Pokémon is present.
struct RecognitionCandidate: Identifiable, Sendable {
    let dexID: Int
    let name: String
    let confidence: Double
    let logit: Double
    var id: Int { dexID }
}

struct RecognitionResult: Sendable {
    let candidates: [RecognitionCandidate]
    let accepted: RecognitionCandidate?
    let logitMargin: Double
}

/// Which scans count as an automatic identification (discovery and narration). Every scan still
/// shows its best match. Both tiers are heuristics, not calibrated probabilities (see MODEL.md).
/// Nonisolated so the classifier actor can read it under the project's MainActor default.
nonisolated enum RecognitionThreshold: String, CaseIterable, Identifiable, Sendable {
    /// Chosen on the national model's validation split: fewer automatic matches, rarely wrong.
    case strict
    /// The original iDex heuristic: more automatic matches, and unrelated objects often pass.
    case relaxed

    static let standard = RecognitionThreshold.strict

    var id: String { rawValue }
    /// Divides the logits before softmax; the displayed confidence uses the same value.
    var temperature: Double { self == .strict ? 0.75 : 1 }
    var minimumConfidence: Double { self == .strict ? 0.95 : 0.25 }
    /// Compared with the raw logits, independent of the temperature.
    var minimumLogitMargin: Double { self == .strict ? 3 : 0.5 }
}

enum RecognitionError: LocalizedError {
    case missingModel
    case invalidLabels
    case invalidOutput

    var errorDescription: String? {
        switch self {
        case .missingModel: return "The bundled recognition model is unavailable."
        case .invalidLabels: return "The recognition label data is invalid."
        case .invalidOutput: return "The recognition model returned invalid scores."
        }
    }
}

/// Serializes model loading and inference away from the UI actor. No image leaves the device.
actor PokemonClassifier {
    /// Bundled Core ML model; its logits follow `pokemon_labels.json` order.
    static let modelName = "KantoClassifier"

    private var model: MLModel?
    private var labels: [Label] = []

    private struct Label: Decodable {
        let id: Int
        let name: String
    }

    func classify(image: CGImage, threshold: RecognitionThreshold) async throws -> RecognitionResult {
        try loadIfNecessary()
        guard let model else { throw RecognitionError.missingModel }
        let imageValue = try MLFeatureValue(
            cgImage: image,
            pixelsWide: 224,
            pixelsHigh: 224,
            pixelFormatType: kCVPixelFormatType_32BGRA,
            options: [.cropAndScale: VNImageCropAndScaleOption.scaleFill.rawValue]
        )
        let input = try MLDictionaryFeatureProvider(dictionary: ["image": imageValue])
        let output = try await model.prediction(from: input)
        guard let values = output.featureValue(for: "logits")?.multiArrayValue,
              values.count == labels.count else { throw RecognitionError.invalidOutput }
        let logits = (0..<values.count).map { values[$0].doubleValue }
        #if DEBUG
        print("iDex model: image \(image.width)x\(image.height), output type \(values.dataType.rawValue), logits range \(logits.min() ?? 0)...\(logits.max() ?? 0)")
        #endif
        guard let ranking = Self.rank(logits, threshold: threshold) else { throw RecognitionError.invalidOutput }
        let candidates = ranking.top.map { entry in
            RecognitionCandidate(dexID: labels[entry.index].id,
                                 name: labels[entry.index].name,
                                 confidence: entry.confidence,
                                 logit: logits[entry.index])
        }
        // Always offer the top candidate. Acceptance only controls automatic discovery
        // and narration; neither tier is an unknown-object detector.
        return RecognitionResult(candidates: candidates, accepted: ranking.accepted ? candidates[0] : nil,
                                 logitMargin: ranking.margin)
    }

    /// The three best logit indices with their tempered softmax scores, the raw top-two margin,
    /// and whether the first passes `threshold`. Nil unless there are two or more finite logits.
    nonisolated static func rank(_ logits: [Double], threshold: RecognitionThreshold)
        -> (top: [(index: Int, confidence: Double)], margin: Double, accepted: Bool)? {
        guard logits.count >= 2, logits.allSatisfy(\.isFinite), let maximum = logits.max() else { return nil }
        let exponents = logits.map { exp(($0 - maximum) / threshold.temperature) }
        let denominator = exponents.reduce(0, +)
        let indices = logits.indices.sorted { logits[$0] > logits[$1] }
        let top = indices.prefix(3).map { (index: $0, confidence: exponents[$0] / denominator) }
        let margin = logits[indices[0]] - logits[indices[1]]
        let accepted = top[0].confidence >= threshold.minimumConfidence && margin >= threshold.minimumLogitMargin
        return (top, margin, accepted)
    }

    private func loadIfNecessary() throws {
        guard model == nil else { return }
        let interval = DexPerformance.begin("Model Load")
        defer { DexPerformance.end("Model Load", interval) }
        guard let url = Bundle.main.url(forResource: Self.modelName, withExtension: "mlmodelc") else {
            throw RecognitionError.missingModel
        }
        // Labels must be dex IDs 1...N in order; the output count is checked per prediction.
        guard let labelURL = Bundle.main.url(forResource: "pokemon_labels", withExtension: "json"),
              let loadedLabels = try? JSONDecoder().decode([Label].self, from: Data(contentsOf: labelURL)),
              !loadedLabels.isEmpty,
              loadedLabels.map(\.id) == Array(1...loadedLabels.count) else {
            throw RecognitionError.invalidLabels
        }
        let configuration = MLModelConfiguration()
        #if targetEnvironment(simulator)
        configuration.computeUnits = .cpuOnly
        #else
        configuration.computeUnits = .all
        #endif
        model = try MLModel(contentsOf: url, configuration: configuration)
        labels = loadedLabels
    }
}
