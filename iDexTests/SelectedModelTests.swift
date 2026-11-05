import CoreML
import CryptoKit
import Foundation
import Testing
@testable import iDex

@Suite("Selected local FP32 classifier")
@MainActor
struct SelectedModelTests {
    @Test func bundledModelIsTheVerifiedFP32Checkpoint() throws {
        let url = try #require(Bundle.main.url(forResource: PokemonClassifier.modelName, withExtension: "mlmodelc"))
        let configuration = MLModelConfiguration()
        #if targetEnvironment(simulator)
        configuration.computeUnits = .cpuOnly
        #else
        configuration.computeUnits = .all
        #endif
        let model = try MLModel(contentsOf: url, configuration: configuration)
        let image = try #require(model.modelDescription.inputDescriptionsByName["image"]?.imageConstraint)
        #expect(image.pixelsWide == 224 && image.pixelsHigh == 224)
        let logits = try #require(model.modelDescription.outputDescriptionsByName["logits"]?.multiArrayConstraint)
        #expect(logits.shape.map(\.intValue) == [1, 1025])
        #expect(logits.dataType == .float32)
        let metadata = try #require(model.modelDescription.metadata[.creatorDefinedKey] as? [String: String])
        #expect(metadata["checkpoint_sha256"] == "2022deef65a694f9ce51701832c9793574dbc4c62bf6ffd6258725d22a32b5fe")
        #expect(metadata["manifest_sha256"] == "a6ce4a0fb819b273d8a1593acc37bc90710f762949665088a63c34e06e612d82")
        // The export does not embed a label hash, so pin the bundled labels the model was exported with.
        let labels = try Data(contentsOf: try #require(Bundle.main.url(forResource: "pokemon_labels", withExtension: "json")))
        let digest = SHA256.hash(data: labels).map { String(format: "%02x", $0) }.joined()
        #expect(digest == "8997df2be5630e1af2f5e77019dbda51170732cb5c205e94828a17cb1cb9faa1")
    }
}
