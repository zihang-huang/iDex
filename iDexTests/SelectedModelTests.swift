import CoreML
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
        #expect(logits.shape.map(\.intValue) == [1, 151])
        #expect(logits.dataType == .float32)
        let metadata = try #require(model.modelDescription.metadata[.creatorDefinedKey] as? [String: String])
        #expect(metadata["checkpoint_sha256"] == "b24cf5301ad97bd1f1f721bffa3c40ec0242bf1efac68435a3752850f624fa6f")
        #expect(metadata["app_labels_sha256"] == "13bd2345fa10f8a7d04363772bb6ef7871c0a6c0635d8c907a77e6cb93f78725")
    }
}
