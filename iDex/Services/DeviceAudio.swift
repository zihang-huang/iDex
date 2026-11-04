import Foundation
import Observation
import UIKit

nonisolated enum DeviceSound: Hashable, Sendable, CaseIterable {
    case button, scan, success, error, open
}

/// Local PCM chimes, bundled Pokémon cries, and Apple's on-device speech
/// synthesis. No network requests are needed. A selected voice may need to be installed
/// in iOS Settings before its first offline use.
@MainActor @Observable
final class DeviceAudio {
    static let shared = DeviceAudio()

    private(set) var isSpeaking = false

    var isSoundEnabled: Bool {
        didSet {
            defaults.set(isSoundEnabled, forKey: "idex.soundEnabled")
            if isSoundEnabled { prepareWhenActive() }
            else { stopAll() }
        }
    }

    @ObservationIgnored private let worker: any DeviceAudioPlayback
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private var isActive = false
    @ObservationIgnored private var soundRequest: AudioPlaybackRequest?
    @ObservationIgnored private var speechRequest: AudioPlaybackRequest?
    @ObservationIgnored private var sessionConfigured = false
    @ObservationIgnored private var activationTask: Task<Bool, Never>?
    @ObservationIgnored private var deactivationTask: Task<Void, Never>?
    @ObservationIgnored private var soundTask: Task<Void, Never>?
    @ObservationIgnored private var speechTask: Task<Void, Never>?
    @ObservationIgnored private var soundGeneration = 0
    @ObservationIgnored private var speechGeneration = 0
    @ObservationIgnored private var currentSound: DeviceSound?

    init(worker: any DeviceAudioPlayback = AudioPlaybackWorker(), defaults: UserDefaults = .standard) {
        self.worker = worker
        self.defaults = defaults
        isSoundEnabled = defaults.object(forKey: "idex.soundEnabled") != nil
            ? defaults.bool(forKey: "idex.soundEnabled") : true
    }

    func resume() {
        isActive = true
        prepareWhenActive()
    }

    @discardableResult
    func suspend() -> Task<Void, Never>? {
        isActive = false
        stopAll()
        return deactivationTask
    }

    /// Warm the session and chime players before the first interaction. Capture
    /// and inference never wait on this; pending playback joins the same task.
    func prepare() async -> Bool {
        guard isActive, isSoundEnabled else { return false }
        let ready = await ensureSession()
        return ready && isActive && isSoundEnabled
    }

    private func prepareWhenActive() {
        guard isActive, isSoundEnabled else { return }
        Task { [weak self] in _ = await self?.prepare() }
    }

    func play(_ cue: DeviceSound) {
        // Hinge and navigation feedback must not interrupt the active scan loop.
        if currentSound == .scan && (cue == .open || cue == .button) { return }
        switch cue {
        case .success: UINotificationFeedbackGenerator().notificationOccurred(.success)
        case .error: UINotificationFeedbackGenerator().notificationOccurred(.warning)
        case .scan: UIImpactFeedbackGenerator(style: .rigid).impactOccurred(intensity: 0.7)
        case .open: UIImpactFeedbackGenerator(style: .medium).impactOccurred(intensity: 0.6)
        case .button: UIImpactFeedbackGenerator(style: .light).impactOccurred(intensity: 0.6)
        }
        guard isActive, isSoundEnabled else { return }
        currentSound = cue
        soundGeneration += 1
        let generation = soundGeneration
        soundTask?.cancel()
        soundRequest?.cancel()
        let request = AudioPlaybackRequest()
        soundRequest = request
        worker.stopSound()
        soundTask = Task { [weak self] in
            guard let self, !Task.isCancelled else { return }
            guard await self.ensureSession(),
                  !Task.isCancelled, self.isSoundEnabled,
                  generation == self.soundGeneration, self.isActive else { return }
            self.worker.play(cue, request: request)
        }
    }

    func speak(_ text: String, languageCode: String) {
        guard isActive, isSoundEnabled, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        stopSpeaking()
        let generation = speechGeneration
        let request = AudioPlaybackRequest { [weak self] speaking in
            Task { @MainActor [weak self] in
                guard let self, generation == self.speechGeneration,
                      self.isActive, self.isSoundEnabled else { return }
                self.isSpeaking = speaking
            }
        }
        speechRequest = request
        speechTask = Task { [weak self] in
            guard let self, !Task.isCancelled else { return }
            guard await self.ensureSession(),
                  !Task.isCancelled, self.isSoundEnabled,
                  generation == self.speechGeneration, self.isActive else { return }
            self.worker.speak(text, languageCode: languageCode, request: request)
        }
    }

    /// Use the species' actual cry as confirmation, then read the entry only
    /// after playback finishes. Result presentation never waits for audio.
    func announce(_ pokemon: Pokemon, language: AppLanguage) {
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        stopSound()
        stopSpeaking()
        guard isActive, isSoundEnabled else { return }
        let generation = soundGeneration
        let readingGeneration = speechGeneration
        let request = AudioPlaybackRequest()
        soundRequest = request
        soundTask = Task { [weak self] in
            guard let self, !Task.isCancelled else { return }
            guard await self.ensureSession(), !Task.isCancelled,
                  generation == self.soundGeneration, self.isActive, self.isSoundEnabled else { return }
            self.worker.playCry(dexID: pokemon.id, request: request) { [weak self] in
                Task { @MainActor [weak self] in
                    guard let self, !request.isCancelled,
                          generation == self.soundGeneration,
                          readingGeneration == self.speechGeneration,
                          self.isActive, self.isSoundEnabled else { return }
                    self.speak(pokemon.spokenEntry(in: language), languageCode: language.speechLocale)
                }
            }
        }
    }

    /// Play only the species' cry, for the record's cry button; no reading follows.
    func playCry(_ pokemon: Pokemon) {
        UIImpactFeedbackGenerator(style: .light).impactOccurred(intensity: 0.6)
        stopSound()
        stopSpeaking()
        guard isActive, isSoundEnabled else { return }
        let generation = soundGeneration
        let request = AudioPlaybackRequest()
        soundRequest = request
        soundTask = Task { [weak self] in
            guard let self, !Task.isCancelled else { return }
            guard await self.ensureSession(), !Task.isCancelled,
                  generation == self.soundGeneration, self.isActive, self.isSoundEnabled else { return }
            self.worker.playCry(dexID: pokemon.id, request: request) {}
        }
    }

    func stopSpeaking() {
        speechGeneration += 1
        isSpeaking = false
        speechTask?.cancel()
        speechTask = nil
        speechRequest?.cancel()
        speechRequest = nil
        worker.stopSpeaking()
    }

    func stopAll() {
        stopSound()
        stopSpeaking()
        releaseSession()
    }

    func stopScanning() {
        guard currentSound == .scan else { return }
        stopSound()
    }

    private func stopSound() {
        soundGeneration += 1
        soundTask?.cancel()
        soundTask = nil
        soundRequest?.cancel()
        soundRequest = nil
        worker.stopSound()
        currentSound = nil
    }

    /// Coalesce simultaneous chime/speech requests onto a single nonblocking
    /// activation. A pending release always finishes before another activation.
    private func ensureSession() async -> Bool {
        if let release = deactivationTask { await release.value }
        if sessionConfigured { return true }
        if let activation = activationTask { return await activation.value }
        let activation = Task { @MainActor [weak self] () -> Bool in
            guard let self else { return false }
            let active = await self.worker.activate()
            self.sessionConfigured = active
            self.activationTask = nil
            return active
        }
        activationTask = activation
        return await activation.value
    }

    private func releaseSession() {
        guard deactivationTask == nil,
              sessionConfigured || activationTask != nil else { return }
        let pendingActivation = activationTask
        deactivationTask = Task { @MainActor [weak self] in
            // If mute/background arrives mid-activation, release it afterward.
            // Cancelled play/speech requests cannot emit a delayed sound.
            if let activation = pendingActivation { _ = await activation.value }
            guard let self else { return }
            await self.worker.deactivate()
            self.sessionConfigured = false
            self.deactivationTask = nil
        }
    }
}

nonisolated enum DeviceSoundWave {
    static let sampleRate = 22_050.0

    static func samples(for cue: DeviceSound) -> [Float] {
        let notes: [(frequency: Double, duration: Double)]
        switch cue {
        case .button: notes = [(1_046.5, 0.045), (1_568, 0.045)]
        case .scan: notes = [(523.25, 0.065), (783.99, 0.065), (1_046.5, 0.11)]
        case .success: notes = [(659.25, 0.075), (783.99, 0.075), (1_046.5, 0.075), (1_318.5, 0.18)]
        case .error: notes = [(329.63, 0.10), (246.94, 0.15)]
        case .open: notes = [(392, 0.05), (523.25, 0.05), (659.25, 0.10)]
        }
        var samples = [Float]()
        for note in notes {
            let count = Int(note.duration * Double(sampleRate))
            for index in 0..<count {
                let time = Double(index) / Double(sampleRate)
                let phase = (time * note.frequency).truncatingRemainder(dividingBy: 1)
                let square = phase < 0.5 ? 0.65 : -0.65
                let triangle = 1 - 4 * abs(phase - 0.5)
                let attack = min(1, Double(index) / 100)
                let release = min(1, Double(count - index) / 200)
                let value = (square * 0.6 + triangle * 0.4) * attack * release
                samples.append(Float(Int16(value * 16_000)) / 32_768)
            }
        }
        return samples
    }
}
