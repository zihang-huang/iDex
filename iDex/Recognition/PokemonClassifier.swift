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
    /// Automatic discovery needs both; heuristics, not a calibrated probability (see MODEL.md).
    static let minimumConfidence = 0.25
    static let minimumLogitMargin = 0.5

    private var model: MLModel?
    private var labels: [Label] = []

    private struct Label: Decodable {
        let id: Int
        let name: String
    }

    func classify(image: CGImage) async throws -> RecognitionResult {
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
        guard logits.allSatisfy(\.isFinite), let maximum = logits.max() else {
            throw RecognitionError.invalidOutput
        }
        let exponents = logits.map { exp($0 - maximum) }
        let denominator = exponents.reduce(0, +)
        let indices = logits.indices.sorted { logits[$0] > logits[$1] }
        let candidates = indices.prefix(3).map { index in
            RecognitionCandidate(dexID: labels[index].id,
                                 name: labels[index].name,
                                 confidence: exponents[index] / denominator,
                                 logit: logits[index])
        }
        let margin = logits[indices[0]] - logits[indices[1]]
        let first = candidates[0]
        // Always offer the top candidate. Acceptance only controls automatic discovery
        // and narration; these relaxed heuristics are not an unknown-object detector.
        let accepted = first.confidence >= Self.minimumConfidence && margin >= Self.minimumLogitMargin ? first : nil
        return RecognitionResult(candidates: candidates, accepted: accepted, logitMargin: margin)
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
