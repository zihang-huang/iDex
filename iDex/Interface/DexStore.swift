import SwiftUI
import PhotosUI
import Observation

@MainActor @Observable
final class DexStore {
    var language: AppLanguage {
        didSet {
            UserDefaults.standard.set(language.rawValue, forKey: "idex.language")
            audio.stopSpeaking()
            message = nil
        }
    }
    var selected: Pokemon? {
        didSet { if let selected { UserDefaults.standard.set(selected.id, forKey: "idex.lastViewed") } }
    }
    var isScanning = false
    var message: String?
    var candidates: [RecognitionCandidate] = []
    var capturedImage: UIImage?
    private(set) var scanResult: RecognitionResult?
    #if targetEnvironment(simulator)
    var useSample = true
    #else
    var useSample = false
    #endif
    var sampleID = 25
    var showingCatalog = false
    var showingSettings = false
    var showingCompactEntry = false
    var confidence: Double?
    var identified = false
    var seenIDs: Set<Int> = []
    let audio: DeviceAudio
    let camera = CameraController()
    private let classifier = PokemonClassifier()
    private var operationID = UUID()
    private var isActive = true

    init(audio: DeviceAudio? = nil) {
        self.audio = audio ?? .shared
        PixelFont.register()
        language = UserDefaults.standard.string(forKey: "idex.language").flatMap(AppLanguage.init(rawValue:)) ?? .systemDefault
        selected = PokemonCatalog.shared.pokemon(id: UserDefaults.standard.integer(forKey: "idex.lastViewed")) ?? PokemonCatalog.shared.pokemon(id: 25)
        seenIDs = Set(UserDefaults.standard.array(forKey: "idex.seen") as? [Int] ?? [])
    }

    func text(_ en: String, _ zh: String, _ ja: String) -> String { language.text(en, zh, ja) }
    var sample: Pokemon? { PokemonCatalog.shared.pokemon(id: sampleID) }
    var scannedPokemon: Pokemon? {
        scanResult?.candidates.first.flatMap { PokemonCatalog.shared.pokemon(id: $0.dexID) }
    }
    var scanStatusTitle: String {
        scanResult?.accepted != nil ? text("IDENTIFIED", "已识别", "識別完了") : text("BEST MATCH", "最可能匹配", "最有力候補")
    }
    var entryStatusTitle: String {
        if identified { return text("IDENTIFIED", "已识别", "識別完了") }
        if confidence != nil { return text("BEST MATCH", "最可能匹配", "最有力候補") }
        return text("ARCHIVE", "档案", "図鑑")
    }

    func chooseCamera() {
        resetScanner()
        useSample = false
        camera.start()
        audio.play(.button)
    }

    func rescan() {
        resetScanner()
        if !useSample { camera.start() }
        audio.play(.button)
    }

    private func resetScanner() {
        audio.stopSpeaking()
        cancelScan()
        showingCompactEntry = false
        capturedImage = nil
        scanResult = nil
        confidence = nil
        candidates = []
        message = nil
        identified = false
    }

    func scan() async {
        guard !isScanning, isActive else { return }
        let interval = DexPerformance.begin("Scan")
        defer { DexPerformance.end("Scan", interval) }
        let operation = UUID()
        operationID = operation
        isScanning = true
        confidence = nil
        message = nil
        candidates = []
        identified = false
        capturedImage = nil
        scanResult = nil
        audio.stopSpeaking()
        audio.play(.scan)
        defer { finishScan(operation) }
        do {
            let image: CGImage
            if useSample {
                guard let name = sample?.spriteName, let sprite = UIImage(named: name), let cg = sprite.cgImage else { throw ScanError.imageUnavailable }
                // Composite transparent game sprites onto the same neutral background used by image classifiers.
                image = Self.opaqueImage(cg)
            } else {
                image = try await camera.capture()
                guard operation == operationID, isActive else { return }
            }
            capturedImage = UIImage(cgImage: image)
            if !useSample { camera.stop() }
            try await recognize(image, operation: operation)
        } catch is CancellationError {
            // Cancellation leaves the captured image available until Rescan.
        } catch {
            guard operation == operationID, isActive else { return }
            message = error is RecognitionError
                ? text("Recognition is unavailable. Restart iDex and try again.", "识别暂不可用，请重启 iDex 后重试。", "識別を利用できません。iDex を再起動して、もう一度お試しください。")
                : text("Couldn't scan. Try a photo or enable the camera.", "未能扫描，请导入照片或启用相机。", "スキャンできませんでした。写真を読み込むか、カメラを有効にしてください。")
            audio.play(.error)
        }
    }

    func importPhoto(_ item: PhotosPickerItem) async {
        guard !isScanning, isActive else { return }
        let operation = UUID()
        operationID = operation
        isScanning = true
        confidence = nil
        message = nil
        candidates = []
        identified = false
        capturedImage = nil
        scanResult = nil
        audio.stopSpeaking()
        audio.play(.scan)
        defer { finishScan(operation) }
        do {
            guard let data = try await item.loadTransferable(type: Data.self) else { throw ScanError.imageUnavailable }
            guard operation == operationID, isActive, !Task.isCancelled else { return }
            let image = try await ScanImagePreparer.photo(data: data)
            guard operation == operationID, isActive else { return }
            camera.stop()
            useSample = false
            capturedImage = UIImage(cgImage: image)
            try await recognize(image, operation: operation)
        } catch is CancellationError {
            // Cancelled imports must not surface an unreadable-photo error.
        } catch {
            guard operation == operationID, isActive else { return }
            message = text("This photo couldn't be read. Choose another image.", "无法读取这张照片，请选择其他图片。", "この写真を読み込めませんでした。別の画像を選んでください。")
            audio.play(.error)
        }
    }

    private func recognize(_ image: CGImage, operation: UUID) async throws {
        // Reveal a finished prediction immediately. The sweep accompanies real
        // work and must not impose its own minimum wait on a warm classifier.
        let interval = DexPerformance.begin("Recognition")
        defer { DexPerformance.end("Recognition", interval) }
        let result = try await classifier.classify(image: image)
        guard operation == operationID, isActive, !Task.isCancelled else { return }
        finishScan(operation)
        try applyRecognition(result)
    }

    private func finishScan(_ operation: UUID) {
        guard operation == operationID else { return }
        isScanning = false
        audio.stopScanning()
    }

    func applyRecognition(_ result: RecognitionResult) throws {
        guard let match = result.candidates.first,
              let pokemon = PokemonCatalog.shared.pokemon(id: match.dexID) else {
            throw RecognitionError.invalidOutput
        }
        candidates = result.candidates
        selected = pokemon
        scanResult = result
        // The result displays the sprite. Release the reviewed photo once
        // recognition finishes instead of retaining it until the next scan.
        capturedImage = nil
        confidence = match.confidence
        identified = result.accepted != nil
        guard identified else {
            message = text("Best match; low confidence.", "最可能的匹配，置信度较低。", "最有力候補ですが、確信度が低い結果です。")
            audio.play(.button)
            return
        }
        message = nil
        seenIDs.insert(pokemon.id)
        UserDefaults.standard.set(seenIDs.sorted(), forKey: "idex.seen")
        audio.announce(pokemon, language: language)
    }

    func browse(_ pokemon: Pokemon) {
        audio.stopSpeaking()
        cancelScan()
        selected = pokemon
        confidence = nil
        identified = false
        showingCatalog = false
        audio.play(.button)
    }

    func step(_ delta: Int) {
        audio.stopSpeaking()
        cancelScan()
        guard let selected else { return }
        let count = PokemonCatalog.shared.entries.count
        let id = ((selected.id - 1 + delta + count) % count) + 1
        self.selected = PokemonCatalog.shared.pokemon(id: id)
        confidence = nil
        identified = false
        audio.play(.button)
    }

    func cancelScan() {
        operationID = UUID()
        isScanning = false
        audio.stopScanning()
    }

    func suspend() {
        isActive = false
        cancelScan()
        camera.stop()
        audio.suspend()
    }

    func resume() {
        isActive = true
        audio.resume()
        if !useSample && capturedImage == nil && scanResult == nil { camera.start() }
    }

    func speak() {
        guard isActive, let selected else { return }
        audio.speak(selected.spokenEntry(in: language), languageCode: language.speechLocale)
    }

    private static func opaqueImage(_ image: CGImage) -> CGImage {
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = true
        return UIGraphicsImageRenderer(size: CGSize(width: 384, height: 384), format: format).image { context in
            UIColor.white.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 384, height: 384))
            context.cgContext.interpolationQuality = .none
            UIImage(cgImage: image).draw(in: CGRect(x: 0, y: 0, width: 384, height: 384))
        }.cgImage ?? image
    }
}

enum ScanError: Error { case imageUnavailable }
