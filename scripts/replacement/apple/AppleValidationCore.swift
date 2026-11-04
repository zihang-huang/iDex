// Standalone validation support. Do not add this file to the production app target.
import CoreGraphics
import CoreML
import CoreVideo
import Foundation
import ImageIO
import Vision
import os

enum AppleValidationError: LocalizedError {
    case invalid(String)
    var errorDescription: String? {
        switch self { case .invalid(let message): return message }
    }
}

struct ValidationLabel: Codable {
    let id: Int
    let name: String
}

struct ValidationFixture: Decodable {
    let id: String
    let image: String
    let referenceLogits: String?
    let baselineReferenceLogits: String?
    let candidateReferenceLogits: String?
    let group: String?
    let targetID: Int?

    enum CodingKeys: String, CodingKey {
        case id, image, group
        case referenceLogits = "reference_logits"
        case baselineReferenceLogits = "baseline_reference_logits"
        case candidateReferenceLogits = "candidate_reference_logits"
        case targetID = "target_id"
    }

    func referencePath(for role: String) -> String? {
        (role == "baseline" ? baselineReferenceLogits : candidateReferenceLogits) ?? referenceLogits
    }
}

struct ValidationManifest: Decodable {
    let fixtures: [ValidationFixture]
}

struct ValidationContract: Codable {
    let inputName: String
    let width: Int
    let height: Int
    let pixelFormat: UInt32
    let outputName: String
    let outputShape: [Int]
    let outputDataType: Int
    let metadata: [String: String]
}

struct ValidationParity: Codable {
    let reference: String
    let absoluteTolerance: Double
    let relativeTolerance: Double
    let maxAbsoluteError: Double
    let meanAbsoluteError: Double
    let rootMeanSquareError: Double
    let failingElements: Int
    let top1Matches: Bool
    let passed: Bool
}

struct ValidationPrediction: Codable {
    let model: String
    let fixtureID: String
    let group: String?
    let targetID: Int?
    let logits: [Double]
    let topLabelID: Int
    let topLabelName: String
    let topSoftmax: Double
    let margin: Double
    let acceptedByCurrentAppHeuristics: Bool
    let parity: ValidationParity?
}

enum ValidationClock {
    static let log = OSLog(subsystem: "iDex.replacement.validation", category: .pointsOfInterest)

    static func measure<T>(_ name: StaticString, _ body: () throws -> T) rethrows -> (T, Double) {
        let signpostID = OSSignpostID(log: log)
        os_signpost(.begin, log: log, name: name, signpostID: signpostID)
        let start = DispatchTime.now().uptimeNanoseconds
        defer { os_signpost(.end, log: log, name: name, signpostID: signpostID) }
        let value = try body()
        return (value, Double(DispatchTime.now().uptimeNanoseconds - start) / 1_000_000)
    }
}

/// Reproduces ScanImagePreparer.preparePhoto(data:) without app-only error types.
/// Keep in sync by reviewing that source before recording a new result.
enum ValidationImagePreparer {
    static let maximumSide = 1200
    static let maximumDecodedPixelCount = 2048 * 2048

    static func preparePhoto(data: Data) throws -> CGImage {
        try autoreleasepool {
            guard let source = CGImageSourceCreateWithData(data as CFData,
                    [kCGImageSourceShouldCache: false] as CFDictionary),
                  let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
                  let width = properties[kCGImagePropertyPixelWidth] as? NSNumber,
                  let height = properties[kCGImagePropertyPixelHeight] as? NSNumber,
                  width.doubleValue > 0, height.doubleValue > 0 else {
                throw AppleValidationError.invalid("Image decode failed or has invalid dimensions")
            }
            let shortSide = min(width.doubleValue, height.doubleValue)
            let longSide = max(width.doubleValue, height.doubleValue)
            let decodeScale = min(1, Double(maximumSide) / shortSide,
                                  sqrt(Double(maximumDecodedPixelCount) / (longSide * shortSide)))
            let decodedDimension = max(1, floor(longSide * decodeScale))
            let options: [CFString: Any] = [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceCreateThumbnailWithTransform: true,
                kCGImageSourceThumbnailMaxPixelSize: decodedDimension,
                kCGImageSourceShouldCacheImmediately: true
            ]
            guard let image = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else {
                throw AppleValidationError.invalid("Image thumbnail decode failed")
            }
            let side = min(maximumSide, image.width, image.height)
            guard let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
                  let context = CGContext(data: nil, width: side, height: side, bitsPerComponent: 8,
                    bytesPerRow: 0, space: colorSpace,
                    bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else {
                throw AppleValidationError.invalid("Cannot allocate sRGB preparation context")
            }
            context.setFillColor(CGColor(gray: 1, alpha: 1))
            context.fill(CGRect(x: 0, y: 0, width: side, height: side))
            let scale = Double(side) / Double(min(image.width, image.height))
            let drawWidth = Double(image.width) * scale
            let drawHeight = Double(image.height) * scale
            context.interpolationQuality = .high
            context.draw(image, in: CGRect(x: (Double(side) - drawWidth) / 2,
                y: (Double(side) - drawHeight) / 2, width: drawWidth, height: drawHeight))
            guard let result = context.makeImage() else {
                throw AppleValidationError.invalid("Cannot create prepared image")
            }
            return result
        }
    }
}

final class ValidationModelSession {
    let model: MLModel
    let classCount: Int
    let contract: ValidationContract
    let compileMS: Double?
    let loadMS: Double
    private let ownedCompiledURL: URL?

    init(url: URL, computeUnits: MLComputeUnits, classCount: Int) throws {
        guard classCount >= 2 else { throw AppleValidationError.invalid("Need at least two labels") }
        self.classCount = classCount
        let ext = url.pathExtension.lowercased()
        guard ext == "mlpackage" || ext == "mlmodelc" else {
            throw AppleValidationError.invalid("Expected .mlpackage or .mlmodelc: \(url.path)")
        }
        let compiledURL: URL
        let temporaryCompilation: URL?
        if ext == "mlpackage" {
            let (result, elapsed) = try ValidationClock.measure("Compile") {
                try MLModel.compileModel(at: url)
            }
            compiledURL = result
            ownedCompiledURL = result
            temporaryCompilation = result
            compileMS = elapsed
        } else {
            compiledURL = url
            ownedCompiledURL = nil
            temporaryCompilation = nil
            compileMS = nil
        }
        let configuration = MLModelConfiguration()
        configuration.computeUnits = computeUnits
        do {
            let (loadedModel, elapsed) = try ValidationClock.measure("ModelLoad") {
                try MLModel(contentsOf: compiledURL, configuration: configuration)
            }
            let inspectedContract = try Self.inspect(loadedModel, classCount: classCount)
            model = loadedModel
            loadMS = elapsed
            contract = inspectedContract
        } catch {
            if let temporaryCompilation { try? FileManager.default.removeItem(at: temporaryCompilation) }
            throw error
        }
    }

    deinit {
        // Only Core ML's returned temporary compilation is owned by this session.
        if let ownedCompiledURL { try? FileManager.default.removeItem(at: ownedCompiledURL) }
    }

    private static func inspect(_ model: MLModel, classCount: Int) throws -> ValidationContract {
        let description = model.modelDescription
        guard Set(description.inputDescriptionsByName.keys) == Set(["image"]),
              let input = description.inputDescriptionsByName["image"], input.type == .image,
              let image = input.imageConstraint,
              image.pixelsWide == image.pixelsHigh,
              image.pixelFormatType == kCVPixelFormatType_32BGRA,
              [224, 256, 320].contains(image.pixelsWide) else {
            throw AppleValidationError.invalid("Input must be a single square image named image at 224/256/320 px")
        }
        guard let output = description.outputDescriptionsByName["logits"], output.type == .multiArray,
              let constraint = output.multiArrayConstraint else {
            throw AppleValidationError.invalid("Output logits must be an MLMultiArray")
        }
        let shape = constraint.shape.map(\.intValue)
        // Labels define the fixed output shape; reject flexible/ambiguous shapes.
        guard !shape.isEmpty, shape.allSatisfy({ $0 > 0 && $0 <= classCount }),
              shape.filter({ $0 != 1 }) == [classCount] else {
            throw AppleValidationError.invalid("Output shape must contain exactly \(classCount) elements: \(shape)")
        }
        let metadata = Dictionary(uniqueKeysWithValues: description.metadata.map {
            (String(describing: $0.key), String(describing: $0.value))
        })
        return ValidationContract(inputName: "image", width: image.pixelsWide,
            height: image.pixelsHigh, pixelFormat: image.pixelFormatType, outputName: "logits",
            outputShape: shape, outputDataType: constraint.dataType.rawValue, metadata: metadata)
    }

    func prepare(data: Data) throws -> MLFeatureProvider {
        let image = try ValidationImagePreparer.preparePhoto(data: data)
        // Model embeds RGB scale/ImageNet normalization. Do not normalize again here.
        let value = try MLFeatureValue(cgImage: image, pixelsWide: contract.width,
            pixelsHigh: contract.height, pixelFormatType: kCVPixelFormatType_32BGRA,
            options: [.cropAndScale: VNImageCropAndScaleOption.scaleFill.rawValue])
        return try MLDictionaryFeatureProvider(dictionary: ["image": value])
    }

    /// Synchronous Core ML API: returns only when this prediction's output is ready.
    func predict(input: MLFeatureProvider) throws -> [Double] {
        let output = try model.prediction(from: input)
        guard let values = output.featureValue(for: "logits")?.multiArrayValue,
              values.count == classCount else {
            throw AppleValidationError.invalid("Prediction must return exactly \(classCount) logits")
        }
        let logits = (0..<classCount).map { values[$0].doubleValue }
        guard logits.allSatisfy(\.isFinite) else {
            throw AppleValidationError.invalid("Prediction contains non-finite logits")
        }
        return logits
    }
}

enum AppleValidation {
    static func labels(at url: URL) throws -> [ValidationLabel] {
        let labels = try JSONDecoder().decode([ValidationLabel].self, from: Data(contentsOf: url))
        guard labels.count >= 2, Set(labels.map(\.id)) == Set(1...labels.count),
              labels.allSatisfy({ !$0.name.isEmpty }) else {
            throw AppleValidationError.invalid("Labels must contain exactly IDs 1...class_count, once each, in model order")
        }
        return labels // Preserve file order. Never sort labels by ID or name.
    }

    static func manifest(at url: URL, labels: [ValidationLabel]) throws -> ValidationManifest {
        let manifest = try JSONDecoder().decode(ValidationManifest.self, from: Data(contentsOf: url))
        guard !manifest.fixtures.isEmpty,
              Set(manifest.fixtures.map(\.id)).count == manifest.fixtures.count,
              manifest.fixtures.allSatisfy({ !$0.id.isEmpty && !$0.image.isEmpty &&
                ($0.targetID == nil || Set(labels.map(\.id)).contains($0.targetID!)) }) else {
            throw AppleValidationError.invalid("Manifest needs nonempty unique fixture IDs and valid optional target_id")
        }
        return manifest
    }

    static func resolve(_ path: String, relativeTo directory: URL) -> URL {
        if (path as NSString).isAbsolutePath { return URL(fileURLWithPath: path) }
        return directory.appendingPathComponent(path)
    }

    static func computeUnits(_ name: String) throws -> MLComputeUnits {
        switch name {
        case "cpuOnly": return .cpuOnly
        case "cpuAndGPU": return .cpuAndGPU
        case "cpuAndNeuralEngine": return .cpuAndNeuralEngine
        case "all": return .all
        default: throw AppleValidationError.invalid("Unknown compute units: \(name)")
        }
    }

    /// Export the exact post-scaleFill RGB uint8 pixels passed to Core ML, row-major,
    /// without row padding. These pixels still need the model's embedded normalization
    /// when run through its source framework. Conversion never changes source labels.
    static func writeRGBInput(_ input: MLFeatureProvider, to url: URL) throws {
        guard let buffer = input.featureValue(for: "image")?.imageBufferValue,
              CVPixelBufferGetPixelFormatType(buffer) == kCVPixelFormatType_32BGRA else {
            throw AppleValidationError.invalid("Expected a BGRA image buffer for RGB export")
        }
        guard CVPixelBufferLockBaseAddress(buffer, .readOnly) == kCVReturnSuccess else {
            throw AppleValidationError.invalid("Cannot lock image buffer for RGB export")
        }
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(buffer) else {
            throw AppleValidationError.invalid("Image buffer has no base address")
        }
        let width = CVPixelBufferGetWidth(buffer)
        let height = CVPixelBufferGetHeight(buffer)
        let rowBytes = CVPixelBufferGetBytesPerRow(buffer)
        let pixels = base.assumingMemoryBound(to: UInt8.self)
        var rgb = Data(count: width * height * 3)
        rgb.withUnsafeMutableBytes { (destination: UnsafeMutableRawBufferPointer) in
            let result = destination.bindMemory(to: UInt8.self)
            for y in 0..<height {
                for x in 0..<width {
                    let source = y * rowBytes + x * 4
                    let target = (y * width + x) * 3
                    result[target] = pixels[source + 2]
                    result[target + 1] = pixels[source + 1]
                    result[target + 2] = pixels[source]
                }
            }
        }
        try rgb.write(to: url, options: .atomic)
    }

    static func prediction(role: String, fixture: ValidationFixture, logits: [Double],
                           labels: [ValidationLabel], directory: URL,
                           atol: Double, rtol: Double, requireReference: Bool) throws -> ValidationPrediction {
        guard labels.count >= 2, logits.count == labels.count, logits.allSatisfy(\.isFinite),
              atol.isFinite, rtol.isFinite, atol >= 0, rtol >= 0 else {
            throw AppleValidationError.invalid("Invalid logits, labels, or parity tolerances")
        }
        let indices = logits.indices.sorted { logits[$0] == logits[$1] ? $0 < $1 : logits[$0] > logits[$1] }
        let first = indices[0]
        let maximum = logits[first]
        let denominator = logits.map { exp($0 - maximum) }.reduce(0, +)
        let confidence = 1 / denominator
        let margin = maximum - logits[indices[1]]
        guard confidence.isFinite, margin.isFinite else {
            throw AppleValidationError.invalid("Non-finite derived score")
        }
        var parity: ValidationParity?
        if let path = fixture.referencePath(for: role) {
            let reference = try JSONDecoder().decode([Double].self,
                from: Data(contentsOf: resolve(path, relativeTo: directory)))
            guard reference.count == labels.count, reference.allSatisfy(\.isFinite) else {
                throw AppleValidationError.invalid("Reference \(path) needs \(labels.count) finite logits in label order")
            }
            let errors = zip(logits, reference).map { abs($0.0 - $0.1) }
            guard errors.allSatisfy(\.isFinite), errors.reduce(0, +).isFinite,
                  errors.map({ $0 * $0 }).reduce(0, +).isFinite else {
                throw AppleValidationError.invalid("Non-finite parity error for \(path)")
            }
            let failures = zip(errors, reference).filter { $0.0 > atol + rtol * abs($0.1) }.count
            let referenceTop = reference.indices.max { reference[$0] == reference[$1] ? $0 > $1 : reference[$0] < reference[$1] }!
            parity = ValidationParity(reference: path, absoluteTolerance: atol, relativeTolerance: rtol,
                maxAbsoluteError: errors.max()!, meanAbsoluteError: errors.reduce(0, +) / Double(labels.count),
                rootMeanSquareError: sqrt(errors.map { $0 * $0 }.reduce(0, +) / Double(labels.count)),
                failingElements: failures, top1Matches: first == referenceTop,
                passed: failures == 0 && first == referenceTop)
        } else if requireReference {
            throw AppleValidationError.invalid("Missing \(role) reference logits for fixture \(fixture.id)")
        }
        return ValidationPrediction(model: role, fixtureID: fixture.id, group: fixture.group,
            targetID: fixture.targetID, logits: logits, topLabelID: labels[first].id,
            topLabelName: labels[first].name, topSoftmax: confidence, margin: margin,
            acceptedByCurrentAppHeuristics: confidence >= 0.25 && margin >= 0.5, parity: parity)
    }

    static func writeJSON<T: Encodable>(_ value: T, to url: URL) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try encoder.encode(value).write(to: url, options: .atomic)
    }
}
