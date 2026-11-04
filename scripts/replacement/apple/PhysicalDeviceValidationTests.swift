// Add this and AppleValidationCore.swift to a NEW iOS XCTest target manually.
// Do not add ValidateModels.swift (@main), or modify the production app target.
import CoreML
import Darwin
import Foundation
import XCTest

private struct DeviceValidationConfig: Decodable {
    let baseline: String
    let candidate: String
    let labels: String
    let manifest: String
    let warmups: Int?
    let iterations: Int?
    let loadIterations: Int?
    let absoluteTolerance: Double?
    let relativeTolerance: Double?
    let requireReferences: Bool?
    let runTag: String?
    let deviceNotes: String?
    let modelOrder: [String]?
    let computeUnitOrder: [String]?
}

private struct TimingDistribution: Encodable {
    let count: Int
    let minimumMS: Double
    let meanMS: Double
    let p50MS: Double
    let p90MS: Double
    let p95MS: Double
    let maximumMS: Double

    init(_ values: [Double]) {
        precondition(!values.isEmpty)
        let sorted = values.sorted()
        func percentile(_ p: Double) -> Double {
            sorted[max(0, min(sorted.count - 1, Int(ceil(Double(sorted.count) * p)) - 1))]
        }
        count = sorted.count
        minimumMS = sorted[0]
        meanMS = sorted.reduce(0, +) / Double(sorted.count)
        p50MS = percentile(0.50)
        p90MS = percentile(0.90)
        p95MS = percentile(0.95)
        maximumMS = sorted[sorted.count - 1]
    }
}

private struct DeviceTimingSample: Encodable {
    let iteration: Int
    let fixtureID: String
    let prepareMS: Double
    let predictMS: Double
    let endToEndMS: Double
    let residentBytes: UInt64?
    let thermalBefore: String
    let thermalAfter: String
}

private struct DeviceModelRun: Encodable {
    let model: String
    let requestedComputeUnits: String
    let contract: ValidationContract
    let compileMS: Double?
    let loadMS: Double
    let loadSamplesMS: [Double]
    let load: TimingDistribution
    let residentBeforeLoad: UInt64?
    let residentAfterLoad: UInt64?
    let maxObservedResidentBytes: UInt64?
    let thermalBeforeLoad: String
    let thermalAfterWarmup: String
    let loadCacheState: String
    let warmups: Int
    let prepare: TimingDistribution
    let predict: TimingDistribution
    let endToEnd: TimingDistribution
    let samples: [DeviceTimingSample]
    let predictions: [ValidationPrediction]
}

private struct DeviceValidationReport: Encodable {
    let schemaVersion = 1
    let createdAt: String
    let runTag: String?
    let userDeviceNotes: String?
    let actualHardwareIdentifier: String
    let operatingSystem: String
    let processorCount: Int
    let physicalMemoryBytes: UInt64
    let lowPowerModeEnabled: Bool
    let processUptimeSeconds: Double
    let labels: [ValidationLabel]
    let imageBytesResidentBeforeTiming: Int
    let fixtureCount: Int
    let modelOrder: [String]
    let computeUnitOrder: [String]
    let runs: [DeviceModelRun]
    let parityFailures: Int
    let missingReferences: Int
    let parityStatus: String
    let executionErrors: [String]
    let timingScope = "Serial synchronous prediction, image bytes already resident; prepare includes import decode/crop/color/alpha and MLFeatureValue scaleFill; endToEnd includes prepare plus prediction and nested signposts; excludes file I/O, UI, camera capture and model load."
    let memoryScope = "Process resident bytes sampled before/after load and after each measured iteration; maximum observed sample, not allocator delta, OS peak footprint, or model-only memory."
    let placementEvidence = "Requested compute units are policy only. Instruments Core ML / Neural Engine / Metal traces are needed for operator/backend placement evidence."
}

private enum DeviceObservation {
    static func residentBytes() -> UInt64? {
        var info = mach_task_basic_info()
        var count = mach_msg_type_number_t(MemoryLayout<mach_task_basic_info>.size / MemoryLayout<integer_t>.size)
        let result = withUnsafeMutablePointer(to: &info) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(MACH_TASK_BASIC_INFO), $0, &count)
            }
        }
        return result == KERN_SUCCESS ? UInt64(info.resident_size) : nil
    }

    static func hardwareIdentifier() -> String {
        var size = 0
        guard sysctlbyname("hw.machine", nil, &size, nil, 0) == 0, size > 0 else { return "unavailable" }
        var bytes = [CChar](repeating: 0, count: size)
        guard sysctlbyname("hw.machine", &bytes, &size, nil, 0) == 0 else { return "unavailable" }
        return String(cString: bytes)
    }

    static func thermal() -> String {
        switch ProcessInfo.processInfo.thermalState {
        case .nominal: return "nominal"
        case .fair: return "fair"
        case .serious: return "serious"
        case .critical: return "critical"
        @unknown default: return "unknown"
        }
    }
}

final class PhysicalDeviceValidationTests: XCTestCase {
    func testBaselineAndCandidateOnPhysicalDevice() throws {
        #if targetEnvironment(simulator)
        throw XCTSkip("Physical-device timing is required; simulator results cannot satisfy this benchmark")
        #else
        let bundle = Bundle(for: PhysicalDeviceValidationTests.self)
        guard let resources = bundle.resourceURL else {
            throw AppleValidationError.invalid("Test bundle has no resources")
        }
        let configPath = ProcessInfo.processInfo.environment["IDEX_APPLE_CONFIG"] ?? "AppleValidationConfig.json"
        let configURL = AppleValidation.resolve(configPath, relativeTo: resources)
        let root = configURL.deletingLastPathComponent()
        let config = try JSONDecoder().decode(DeviceValidationConfig.self, from: Data(contentsOf: configURL))
        let warmups = config.warmups ?? 10
        let iterations = config.iterations ?? 50
        let loadIterations = config.loadIterations ?? 5
        guard warmups >= 5, iterations >= 50, loadIterations >= 1 else {
            throw AppleValidationError.invalid("Use at least 5 warmups, 50 measured iterations and 1 load iteration per model/policy")
        }
        let atol = config.absoluteTolerance ?? 0.05
        let rtol = config.relativeTolerance ?? 0.01
        guard atol.isFinite, rtol.isFinite, atol >= 0, rtol >= 0 else {
            throw AppleValidationError.invalid("Tolerances must be finite nonnegative numbers")
        }
        let modelOrder = config.modelOrder ?? ["baseline", "candidate"]
        let computeOrder = config.computeUnitOrder ?? ["cpuOnly", "cpuAndGPU", "cpuAndNeuralEngine", "all"]
        guard modelOrder.count == 2, Set(modelOrder) == Set(["baseline", "candidate"]),
              computeOrder.count == 4,
              Set(computeOrder) == Set(["cpuOnly", "cpuAndGPU", "cpuAndNeuralEngine", "all"]) else {
            throw AppleValidationError.invalid("Orders must contain each model and each of the four compute policies exactly once")
        }
        let labels = try AppleValidation.labels(at: AppleValidation.resolve(config.labels, relativeTo: root))
        let manifestURL = AppleValidation.resolve(config.manifest, relativeTo: root)
        let directory = manifestURL.deletingLastPathComponent()
        let manifest = try AppleValidation.manifest(at: manifestURL, labels: labels)
        // Preload file bytes: the production import path receives in-memory photo data.
        let fixtureData = try manifest.fixtures.map {
            try Data(contentsOf: AppleValidation.resolve($0.image, relativeTo: directory))
        }
        var runs: [DeviceModelRun] = []
        var executionErrors: [String] = []
        for computeName in computeOrder {
            let units = try AppleValidation.computeUnits(computeName)
            for role in modelOrder {
                do {
                let run = try autoreleasepool { () throws -> DeviceModelRun in
                    let memoryBefore = DeviceObservation.residentBytes()
                    let thermalBefore = DeviceObservation.thermal()
                    let path = role == "baseline" ? config.baseline : config.candidate
                    let modelURL = AppleValidation.resolve(path, relativeTo: root)
                    var loadSamplesMS: [Double] = []
                    // Uncontrolled-cache reloads, NOT cold-start measurements. Release
                    // each probe before loading the next. No prediction during probes.
                    for _ in 0..<(loadIterations - 1) {
                        let elapsed = try autoreleasepool { () throws -> Double in
                            let probe = try ValidationModelSession(url: modelURL, computeUnits: units, classCount: labels.count)
                            return probe.loadMS
                        }
                        loadSamplesMS.append(elapsed)
                    }
                    let session = try ValidationModelSession(
                        url: modelURL, computeUnits: units, classCount: labels.count)
                    loadSamplesMS.append(session.loadMS)
                    let memoryAfter = DeviceObservation.residentBytes()
                    var predictions: [ValidationPrediction] = []
                    // Reference checks are deliberately outside measured samples.
                    for (index, fixture) in manifest.fixtures.enumerated() {
                        let prediction = try autoreleasepool { () throws -> ValidationPrediction in
                            let input = try session.prepare(data: fixtureData[index])
                            let logits = try session.predict(input: input)
                            return try AppleValidation.prediction(role: role, fixture: fixture,
                                logits: logits, labels: labels, directory: directory,
                                atol: atol, rtol: rtol, requireReference: config.requireReferences ?? true)
                        }
                        predictions.append(prediction)
                    }
                    for index in 0..<warmups {
                        try autoreleasepool {
                            let input = try session.prepare(data: fixtureData[index % fixtureData.count])
                            _ = try session.predict(input: input)
                        }
                    }
                    let thermalAfterWarmup = DeviceObservation.thermal()
                    var samples: [DeviceTimingSample] = []
                    for index in 0..<iterations {
                        let fixtureIndex = index % manifest.fixtures.count
                        let sample = try autoreleasepool { () throws -> DeviceTimingSample in
                            let thermalStart = DeviceObservation.thermal()
                            var prepareMS = 0.0
                            var predictMS = 0.0
                            let (_, elapsed) = try ValidationClock.measure("EndToEnd") {
                                let (input, preparation) = try ValidationClock.measure("Prepare") {
                                    try session.prepare(data: fixtureData[fixtureIndex])
                                }
                                prepareMS = preparation
                                let (_, prediction) = try ValidationClock.measure("Predict") {
                                    try session.predict(input: input)
                                }
                                predictMS = prediction
                            }
                            return DeviceTimingSample(iteration: index, fixtureID: manifest.fixtures[fixtureIndex].id,
                                prepareMS: prepareMS, predictMS: predictMS, endToEndMS: elapsed,
                                residentBytes: DeviceObservation.residentBytes(), thermalBefore: thermalStart,
                                thermalAfter: DeviceObservation.thermal())
                        }
                        samples.append(sample)
                    }
                    let memorySamples = [memoryBefore, memoryAfter] + samples.map(\.residentBytes)
                    return DeviceModelRun(model: role, requestedComputeUnits: computeName,
                        contract: session.contract, compileMS: session.compileMS, loadMS: session.loadMS,
                        loadSamplesMS: loadSamplesMS, load: TimingDistribution(loadSamplesMS),
                        residentBeforeLoad: memoryBefore, residentAfterLoad: memoryAfter,
                        maxObservedResidentBytes: memorySamples.compactMap { $0 }.max(),
                        thermalBeforeLoad: thermalBefore, thermalAfterWarmup: thermalAfterWarmup,
                        loadCacheState: "uncontrolled; not established as cold", warmups: warmups,
                        prepare: TimingDistribution(samples.map(\.prepareMS)),
                        predict: TimingDistribution(samples.map(\.predictMS)),
                        endToEnd: TimingDistribution(samples.map(\.endToEndMS)),
                        samples: samples, predictions: predictions)
                }
                runs.append(run)
                print("\(role) \(computeName): predict p50=\(run.predict.p50MS) p90=\(run.predict.p90MS) p95=\(run.predict.p95MS) ms; thermal=\(run.thermalAfterWarmup)")
                } catch {
                    let message = "\(role) / \(computeName): \(error.localizedDescription)"
                    executionErrors.append(message)
                    print("Validation configuration failed: \(message)")
                }
            }
        }
        let predictions = runs.flatMap(\.predictions)
        let compared = predictions.compactMap(\.parity)
        let failures = compared.filter { !$0.passed }.count
        let missing = predictions.count - compared.count
        let info = ProcessInfo.processInfo
        let report = DeviceValidationReport(createdAt: ISO8601DateFormatter().string(from: Date()),
            runTag: config.runTag, userDeviceNotes: config.deviceNotes,
            actualHardwareIdentifier: DeviceObservation.hardwareIdentifier(),
            operatingSystem: info.operatingSystemVersionString, processorCount: info.processorCount,
            physicalMemoryBytes: info.physicalMemory, lowPowerModeEnabled: info.isLowPowerModeEnabled,
            processUptimeSeconds: info.systemUptime, labels: labels,
            imageBytesResidentBeforeTiming: fixtureData.reduce(0) { $0 + $1.count },
            fixtureCount: manifest.fixtures.count, modelOrder: modelOrder,
            computeUnitOrder: computeOrder, runs: runs, parityFailures: failures,
            missingReferences: missing,
            parityStatus: !executionErrors.isEmpty || failures > 0 ? "failed" : (missing > 0 ? "incomplete" : "passed"),
            executionErrors: executionErrors)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(report)
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        attachment.name = "AppleValidationResults.json"
        attachment.lifetime = .keepAlways
        add(attachment)
        let output = FileManager.default.temporaryDirectory.appendingPathComponent("AppleValidationResults-\(UUID().uuidString).json")
        try data.write(to: output, options: .atomic)
        print("Device results: \(output.path) (also attached to xcresult)")
        XCTAssertEqual(failures, 0, "See per-model/source parity comparisons in JSON attachment")
        XCTAssertTrue(executionErrors.isEmpty, "\(executionErrors.joined(separator: "\n"))")
        if config.requireReferences ?? true {
            XCTAssertEqual(missing, 0, "Source-reference parity must cover every fixture/model/policy")
        }
        #endif
    }
}
