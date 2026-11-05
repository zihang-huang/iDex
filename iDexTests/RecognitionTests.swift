import CoreGraphics
import Foundation
import Testing
import UIKit
@testable import iDex

@Suite("Bundled offline Pokémon recognition", .serialized)
@MainActor
struct RecognitionTests {
    @Test func scanningFreezesTheSampleBeforeRevealingItsSpriteAndAllowsRescanning() async throws {
        let soundWasEnabled = DeviceAudio.shared.isSoundEnabled
        let savedViewed = UserDefaults.standard.object(forKey: "idex.lastViewed")
        let savedSeen = UserDefaults.standard.object(forKey: "idex.seen")
        DeviceAudio.shared.isSoundEnabled = false
        let store = DexStore()
        store.useSample = true
        defer {
            store.suspend()
            DeviceAudio.shared.isSoundEnabled = soundWasEnabled
            UserDefaults.standard.set(savedViewed, forKey: "idex.lastViewed")
            UserDefaults.standard.set(savedSeen, forKey: "idex.seen")
        }
        let task = Task { await store.scan() }
        for _ in 0..<100 {
            if store.capturedImage != nil { break }
            try await Task.sleep(for: .milliseconds(5))
        }
        #expect(store.isScanning)
        #expect(store.scannedPokemon == nil)
        #expect(store.confidence == nil)
        await task.value

        #expect(!store.isScanning)
        #expect(store.scannedPokemon?.id == 25)
        #expect(store.identified)
        #expect(!store.showingCompactEntry)
        let seen = store.seenIDs
        store.rescan()
        #expect(store.useSample)
        #expect(store.capturedImage == nil)
        #expect(store.scannedPokemon == nil)
        #expect(store.confidence == nil)
        #expect(store.candidates.isEmpty)
        #expect(store.message == nil)
        #expect(store.seenIDs == seen)
        await store.scan()
        #expect(store.scannedPokemon?.id == 25)
    }

    @Test func cancellingAScanPreventsItsLateResultFromReplacingTheNextTarget() async {
        let soundWasEnabled = DeviceAudio.shared.isSoundEnabled
        DeviceAudio.shared.isSoundEnabled = false
        let store = DexStore()
        store.useSample = true
        defer {
            store.suspend()
            DeviceAudio.shared.isSoundEnabled = soundWasEnabled
        }
        let originalSeen = store.seenIDs
        let task = Task { await store.scan() }
        for _ in 0..<100 {
            if store.capturedImage != nil { break }
            try? await Task.sleep(for: .milliseconds(5))
        }
        store.rescan()
        store.sampleID = 6
        await task.value
        #expect(!store.isScanning)
        #expect(store.scannedPokemon == nil)
        #expect(store.capturedImage == nil)
        #expect(store.confidence == nil)
        #expect(store.message == nil)
        #expect(store.seenIDs == originalSeen)
    }

    @Test func browsingTheArchiveKeepsTheScannedSpriteAndItsConfidence() throws {
        let soundWasEnabled = DeviceAudio.shared.isSoundEnabled
        let savedViewed = UserDefaults.standard.object(forKey: "idex.lastViewed")
        DeviceAudio.shared.isSoundEnabled = false
        defer {
            DeviceAudio.shared.isSoundEnabled = soundWasEnabled
            UserDefaults.standard.set(savedViewed, forKey: "idex.lastViewed")
        }
        let store = DexStore()
        let candidate = RecognitionCandidate(dexID: 25, name: "pikachu", confidence: 0.1, logit: 1)
        try store.applyRecognition(RecognitionResult(candidates: [candidate], accepted: nil, logitMargin: 0))
        store.browse(try #require(PokemonCatalog.shared.pokemon(id: 6)))
        #expect(store.selected?.id == 6)
        #expect(store.scannedPokemon?.id == 25)
        #expect(store.scanResult?.candidates.first?.confidence == 0.1)
        #expect(store.scanResult?.accepted == nil)
    }

    @Test func completedScansReleaseThePhotoAndKeepTheCameraStoppedOnResume() throws {
        let soundWasEnabled = DeviceAudio.shared.isSoundEnabled
        let savedViewed = UserDefaults.standard.object(forKey: "idex.lastViewed")
        DeviceAudio.shared.isSoundEnabled = false
        let store = DexStore()
        defer {
            store.suspend()
            DeviceAudio.shared.isSoundEnabled = soundWasEnabled
            UserDefaults.standard.set(savedViewed, forKey: "idex.lastViewed")
        }
        store.useSample = false
        store.capturedImage = UIImage(named: "pokemon-025")
        let match = RecognitionCandidate(dexID: 25, name: "pikachu", confidence: 0.1, logit: 1)
        try store.applyRecognition(RecognitionResult(candidates: [match], accepted: nil, logitMargin: 0))

        #expect(store.capturedImage == nil)
        #expect(store.scannedPokemon?.id == 25)
        store.suspend()
        store.resume()
        #expect(store.camera.status == .idle)
        #expect(store.scannedPokemon?.id == 25)
    }

    // The first seven were once rejected by the Kanto model; the rest span generations II–IX.
    @Test("Core ML identifies opaque sprites under both thresholds",
          arguments: [25, 6, 65, 83, 86, 98, 129, 152, 387, 494, 650, 722, 810, 906, 1025], RecognitionThreshold.allCases)
    func identifiesKnownPokemon(dexID: Int, threshold: RecognitionThreshold) async throws {
        let sprite = try #require(UIImage(named: String(format: "pokemon-%03d", dexID)))
        let image = try #require(renderOpaque(sprite: sprite))
        let classifier = PokemonClassifier()

        let result = try await classifier.classify(image: image, threshold: threshold)

        let accepted = try #require(result.accepted)
        #expect(accepted.dexID == dexID)
        #expect(result.candidates.first?.dexID == dexID)
        #expect(result.candidates.count == 3)
        #expect(accepted.confidence >= threshold.minimumConfidence)
        #expect(result.logitMargin >= threshold.minimumLogitMargin)
    }

    @Test("Blank images still offer a best match without confirming a discovery",
          arguments: [false, true], RecognitionThreshold.allCases)
    func rejectsBlankImages(black: Bool, threshold: RecognitionThreshold) async throws {
        let image = try #require(renderOpaque(sprite: nil, background: black ? .black : .white))
        let result = try await PokemonClassifier().classify(image: image, threshold: threshold)

        #expect(result.accepted == nil)
        #expect(result.candidates.count == 3)
        #expect(result.candidates.allSatisfy { (1...1025).contains($0.dexID) })
        #expect(result.candidates.allSatisfy { $0.confidence.isFinite && (0...1).contains($0.confidence) })

        let soundWasEnabled = DeviceAudio.shared.isSoundEnabled
        let savedLanguage = UserDefaults.standard.object(forKey: "idex.language")
        let savedViewed = UserDefaults.standard.object(forKey: "idex.lastViewed")
        DeviceAudio.shared.isSoundEnabled = false
        defer {
            DeviceAudio.shared.isSoundEnabled = soundWasEnabled
            UserDefaults.standard.set(savedLanguage, forKey: "idex.language")
            UserDefaults.standard.set(savedViewed, forKey: "idex.lastViewed")
        }
        let store = DexStore()
        let originalSeen = store.seenIDs
        // A blank frame must replace the previous record with its top prediction.
        store.selected = PokemonCatalog.shared.pokemon(id: result.candidates[0].dexID == 25 ? 6 : 25)
        try store.applyRecognition(result)
        #expect(store.selected?.id == result.candidates.first?.dexID)
        #expect(store.confidence == result.candidates.first?.confidence)
        #expect(!store.identified)
        #expect(store.seenIDs == originalSeen)
        store.language = .en
        #expect(store.entryStatusTitle == "BEST MATCH")
        store.language = .zhHans
        #expect(store.entryStatusTitle == "最可能匹配")
    }

    @Test("Strict acceptance needs a tempered score of .95 and a raw margin of 3")
    func strictThresholdNeedsScoreAndMargin() throws {
        let clear = try #require(PokemonClassifier.rank([10, 6.5, 0, -1], threshold: .strict))
        #expect(clear.accepted)
        #expect(clear.top.map(\.index) == [0, 1, 2])
        #expect(abs(clear.margin - 3.5) < 1e-12)
        // A margin of 2 clears the relaxed tier but not the strict one.
        let close = try #require(PokemonClassifier.rank([5, 3, 0, 0], threshold: .strict))
        #expect(!close.accepted)
        #expect(try #require(PokemonClassifier.rank([5, 3, 0, 0], threshold: .relaxed)).accepted)
        // A large margin with a diffuse score still fails strict.
        let diffuse = try #require(PokemonClassifier.rank([4, 0.9] + Array(repeating: 0.9, count: 40), threshold: .strict))
        #expect(diffuse.margin >= 3)
        #expect(!diffuse.accepted)
    }

    @Test("The strict temperature sharpens the displayed score; the margin stays raw")
    func temperatureAppliesToScoresOnly() throws {
        let logits = [2.0, 1.0, 0.5]
        let strict = try #require(PokemonClassifier.rank(logits, threshold: .strict))
        let relaxed = try #require(PokemonClassifier.rank(logits, threshold: .relaxed))
        #expect(strict.margin == relaxed.margin)
        #expect(strict.top[0].confidence > relaxed.top[0].confidence)
        let expected = 1 / (1 + exp(-1 / 0.75) + exp(-1.5 / 0.75))
        #expect(abs(strict.top[0].confidence - expected) < 1e-12)
        #expect(abs(strict.top.map(\.confidence).reduce(0, +) - 1) < 1e-12)
    }

    @Test("Ranking rejects outputs that cannot form a top-two margin")
    func rankRejectsInvalidOutputs() {
        for logits in [[], [1], [1, .nan], [1, .infinity]] as [[Double]] {
            #expect(PokemonClassifier.rank(logits, threshold: .strict)?.margin == nil)
        }
    }

    @Test("The chosen threshold persists and defaults to strict")
    func thresholdPersists() {
        let key = "idex.recognitionThreshold"
        let saved = UserDefaults.standard.object(forKey: key)
        defer { UserDefaults.standard.set(saved, forKey: key) }
        UserDefaults.standard.removeObject(forKey: key)
        #expect(DexStore().recognitionThreshold == .strict)
        let store = DexStore()
        store.recognitionThreshold = .relaxed
        #expect(UserDefaults.standard.string(forKey: key) == "relaxed")
        #expect(DexStore().recognitionThreshold == .relaxed)
        UserDefaults.standard.set("unknown", forKey: key)
        #expect(DexStore().recognitionThreshold == .strict)
    }

    @Test("Model labels map to bundled catalog entries")
    func labelCoverageMatchesCatalog() throws {
        struct Label: Decodable {
            let id: Int
            let name: String
        }
        let url = try #require(Bundle.main.url(forResource: "pokemon_labels", withExtension: "json"))
        let labels = try JSONDecoder().decode([Label].self, from: Data(contentsOf: url))

        // The bundled model and the catalog both cover the full National Pokédex.
        #expect(labels.count == 1025)
        #expect(labels.map(\.id) == PokemonCatalog.shared.entries.map(\.id))
        #expect(labels.enumerated().allSatisfy { $0.element.id == $0.offset + 1 })
        #expect(labels.allSatisfy { !$0.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty })
        #expect(labels[24].name == "pikachu")
        #expect(labels[5].name == "charizard")
        #expect(labels[1024].name == "pecharunt")
    }

    // Match the app's sample path: a 96px transparent sprite becomes an opaque
    // white 384px image before Core ML performs its 224px image conversion.
    private func renderOpaque(sprite: UIImage?, background: UIColor = .white) -> CGImage? {
        let size = CGSize(width: 384, height: 384)
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = true
        return UIGraphicsImageRenderer(size: size, format: format).image { context in
            background.setFill()
            context.fill(CGRect(origin: .zero, size: size))
            context.cgContext.interpolationQuality = .none
            sprite?.draw(in: CGRect(origin: .zero, size: size))
        }.cgImage
    }
}
