// Compile together with AppleValidationCore.swift on macOS. See README.md.
import Foundation

private struct ModelReport: Encodable {
    let role: String
    let source: String
    let requestedComputeUnits: String
    let compileMS: Double?
    let loadMS: Double
    let contract: ValidationContract
    let predictions: [ValidationPrediction]
}

private struct ValidationReport: Encodable {
    let schemaVersion = 1
    let createdAt: String
    let platform: String
    let operatingSystem: String
    let preprocessing = "ScanImagePreparer import path: EXIF thumbnail, center square, sRGB, opaque white, Core ML scaleFill"
    let labels: [ValidationLabel]
    let modelReports: [ModelReport]
    let comparedPredictions: Int
    let missingReferences: Int
    let parityFailures: Int
    let parityStatus: String
    let placementEvidence = "Requested compute units do not establish operator placement. Record Instruments evidence separately."
}

@main
struct ValidateModels {
    static let usage = """
    Usage: validate-models --baseline PATH --candidate PATH --labels PATH --manifest PATH --output PATH
      [--compute-units cpuOnly|cpuAndGPU|cpuAndNeuralEngine|all] [--atol 0.05] [--rtol 0.01]
      [--require-references] [--dump-inputs DIRECTORY]

    PATH models: .mlpackage or .mlmodelc. Relative fixture/reference paths resolve beside the manifest.
    Logits output preserves the supplied labels' exact order. Tolerances are configurable smoke-test
    defaults, not accuracy or equivalence criteria. Supply model-specific source references.
    Exit 0: all supplied comparisons passed (possibly incomplete without --require-references).
    Exit 1: parity failure. Exit 2: invalid invocation, model, data, or missing required reference.
    """

    static func main() {
        do {
            let args = Array(CommandLine.arguments.dropFirst())
            if args.contains("--help") { print(usage); return }
            var options: [String: String] = [:]
            var requireReferences = false
            var index = 0
            let known = Set(["--baseline", "--candidate", "--labels", "--manifest", "--output",
                             "--compute-units", "--atol", "--rtol", "--dump-inputs"])
            while index < args.count {
                let key = args[index]
                if key == "--require-references" {
                    requireReferences = true
                    index += 1
                } else {
                    guard known.contains(key), options[key] == nil, index + 1 < args.count,
                          !args[index + 1].hasPrefix("--") else {
                        throw AppleValidationError.invalid("Unknown, duplicate, or incomplete option: \(key)\n\(usage)")
                    }
                    options[key] = args[index + 1]
                    index += 2
                }
            }
            func required(_ key: String) throws -> URL {
                guard let value = options[key], !value.isEmpty else {
                    throw AppleValidationError.invalid("Missing \(key)\n\(usage)")
                }
                return URL(fileURLWithPath: value)
            }
            let baseline = try required("--baseline")
            let candidate = try required("--candidate")
            let labels = try AppleValidation.labels(at: URL(fileURLWithPath: options["--labels"] ?? "iDex/Recognition/pokemon_labels.json"))
            let manifestURL = try required("--manifest")
            let manifest = try AppleValidation.manifest(at: manifestURL, labels: labels)
            let directory = manifestURL.deletingLastPathComponent()
            let output = try required("--output")
            let dumpDirectory = options["--dump-inputs"].map { URL(fileURLWithPath: $0) }
            if let dumpDirectory {
                try FileManager.default.createDirectory(at: dumpDirectory, withIntermediateDirectories: true)
            }
            let computeName = options["--compute-units"] ?? "cpuOnly"
            let computeUnits = try AppleValidation.computeUnits(computeName)
            guard let atol = Double(options["--atol"] ?? "0.05"),
                  let rtol = Double(options["--rtol"] ?? "0.01"),
                  atol.isFinite, rtol.isFinite, atol >= 0, rtol >= 0 else {
                throw AppleValidationError.invalid("Tolerances must be finite nonnegative numbers")
            }
            var reports: [ModelReport] = []
            for (role, url) in [("baseline", baseline), ("candidate", candidate)] {
                let report = try autoreleasepool { () throws -> ModelReport in
                    let session = try ValidationModelSession(url: url, computeUnits: computeUnits, classCount: labels.count)
                    var predictions: [ValidationPrediction] = []
                    for (fixtureIndex, fixture) in manifest.fixtures.enumerated() {
                        let prediction = try autoreleasepool { () throws -> ValidationPrediction in
                            let data = try Data(contentsOf: AppleValidation.resolve(fixture.image, relativeTo: directory))
                            let input = try session.prepare(data: data)
                            if let dumpDirectory {
                                let filename = "\(role)-\(fixtureIndex)-\(session.contract.width)x\(session.contract.height).rgb"
                                try AppleValidation.writeRGBInput(input, to: dumpDirectory.appendingPathComponent(filename))
                            }
                            let logits = try session.predict(input: input)
                            return try AppleValidation.prediction(role: role, fixture: fixture, logits: logits,
                                labels: labels, directory: directory, atol: atol, rtol: rtol,
                                requireReference: requireReferences)
                        }
                        predictions.append(prediction)
                    }
                    return ModelReport(role: role, source: url.path, requestedComputeUnits: computeName,
                        compileMS: session.compileMS, loadMS: session.loadMS,
                        contract: session.contract, predictions: predictions)
                }
                reports.append(report)
            }
            let predictions = reports.flatMap(\.predictions)
            let compared = predictions.compactMap(\.parity)
            let failures = compared.filter { !$0.passed }.count
            let missing = predictions.count - compared.count
            let status = failures > 0 ? "failed" : (missing > 0 ? "incomplete" : "passed")
            let report = ValidationReport(createdAt: ISO8601DateFormatter().string(from: Date()),
                platform: "macOS", operatingSystem: ProcessInfo.processInfo.operatingSystemVersionString,
                labels: labels, modelReports: reports, comparedPredictions: compared.count,
                missingReferences: missing, parityFailures: failures, parityStatus: status)
            try AppleValidation.writeJSON(report, to: output)
            print("Wrote \(output.path): parity \(status); \(compared.count) compared, \(missing) missing, \(failures) failed")
            if failures > 0 { exit(1) }
        } catch {
            FileHandle.standardError.write(Data("Validation error: \(error.localizedDescription)\n".utf8))
            exit(2)
        }
    }
}
