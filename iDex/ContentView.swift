import SwiftUI
import PhotosUI

struct ContentView: View {
    @State var store = DexStore()
    @State private var photo: PhotosPickerItem?
    @State private var hingeIsOpen: Bool?

    var body: some View {
        GeometryReader { proxy in
            let geometry = DuoGeometry(size: proxy.size, hingeIsOpen: hingeIsOpen)
            ZStack(alignment: .topTrailing) {
                ShellSurface()
                if geometry.isOpen {
                    EntryPanel(store: store)
                        .frame(width: max(0, geometry.rightOrigin - 19), height: proxy.size.height)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    HingeSpine().frame(height: proxy.size.height)
                        .position(x: geometry.rightOrigin - 9.5, y: proxy.size.height / 2)
                }
                ScannerPanel(store: store, photo: $photo, compact: !geometry.isOpen)
                    .frame(width: geometry.panelWidth, height: proxy.size.height)
                if ProcessInfo.processInfo.environment["XCODE_RUNNING_FOR_PREVIEWS"] != "1" {
                    HingeObserver { value in
                        if hingeIsOpen != nil, value != hingeIsOpen { store.audio.play(.open) }
                        hingeIsOpen = value
                    }.frame(width: 1, height: 1).allowsHitTesting(false)
                }
            }
            .clipped()
            .onChange(of: geometry.isOpen) { _, open in
                if open && store.showingCompactEntry {
                    store.showingCompactEntry = false
                    store.showingCatalog = false
                }
            }
        }
        .ignoresSafeArea()
        .preferredColorScheme(.dark)
        .environment(\.locale, Locale(identifier: store.language.localeIdentifier))
        .statusBarHidden()
        .persistentSystemOverlays(.hidden)
        .task { store.resume() }
        .onChange(of: photo) { _, item in
            guard let item else { return }
            Task { await store.importPhoto(item); photo = nil }
        }
    }
}

struct CompactRecordView: View {
    @Bindable var store: DexStore

    var body: some View {
        GeometryReader { proxy in
            ZStack {
                ShellSurface()
                EntryPanel(store: store, onClose: {
                    store.audio.play(.button)
                    store.showingCompactEntry = false
                })
                    .frame(width: proxy.size.width, height: proxy.size.height)
            }
            .clipped()
        }
        .ignoresSafeArea()
        .environment(\.locale, Locale(identifier: store.language.localeIdentifier))
        .preferredColorScheme(.dark)
        .statusBarHidden()
        .persistentSystemOverlays(.hidden)
    }
}

private struct ScannerPanel: View {
    @Bindable var store: DexStore
    @Binding var photo: PhotosPickerItem?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let compact: Bool

    private var canRescan: Bool {
        store.capturedImage != nil || store.scannedPokemon != nil || store.message != nil
    }

    private var scanDisabled: Bool {
        store.isScanning || (!canRescan && !store.useSample && store.camera.status != .ready)
    }

    private var scanButtonTitle: String {
        if store.isScanning { return store.text("SCANNING", "扫描中", "スキャン中") }
        return canRescan ? store.text("RESCAN", "重新扫描", "再スキャン") : store.text("SCAN", "扫描", "スキャン")
    }

    private var viewfinderTitle: String {
        if store.isScanning { return store.text("SCANNING…", "扫描中…", "スキャン中…") }
        if store.scannedPokemon != nil { return store.scanStatusTitle }
        if store.useSample { return store.text("SAMPLE TARGET", "样本目标", "サンプル") }
        return store.capturedImage == nil ? store.text("LIVE VIEW", "实时取景", "ライブビュー") : store.text("PHOTO REVIEW", "照片回看", "写真の確認")
    }

    var body: some View {
        GeometryReader { proxy in
            let layout = DuoGeometry(size: proxy.size)
            let side = layout.viewfinder.width
            ZStack(alignment: .topLeading) {
                header.frame(height: 70).padding(.horizontal, 34).offset(y: 54)
                HStack {
                    pixel(store.text("OPTICAL SENSOR", "光学传感器", "光学センサー"), 7).foregroundStyle(.white.opacity(0.65))
                    Spacer()
                    pixel(store.text("KANTO / 01", "关都 / 01", "カントー / 01"), 7).foregroundStyle(.white.opacity(0.65))
                }.frame(width: proxy.size.width - 98).offset(x: 49, y: 146)
                viewfinder(side: side).frame(width: side + 34, height: side + 34)
                    .position(x: proxy.size.width / 2, y: layout.viewfinder.midY)
                HStack(spacing: 10) {
                    Button { store.chooseCamera() } label: { Image(systemName: "camera.fill").frame(width: 28) }
                        .accessibilityLabel(store.text("Use camera", "使用相机", "カメラを使う")).accessibilityIdentifier("camera-button")
                        .disabled(store.isScanning)
                    PhotosPicker(selection: $photo, matching: .images) {
                        Image(systemName: "photo.on.rectangle.angled").frame(width: 28)
                    }.accessibilityLabel(store.text("Import photo", "导入照片", "写真を読み込む")).disabled(store.isScanning)
                    Spacer(minLength: 0)
                    Button {
                        if canRescan { store.rescan() }
                        else { Task { await store.scan() } }
                    } label: {
                        HStack(spacing: 8) {
                            Image(systemName: canRescan && !store.isScanning ? "arrow.clockwise" : "viewfinder")
                            pixel(scanButtonTitle, 9)
                        }
                    }.buttonStyle(HardwareButtonStyle(color: Color(red: 0.11, green: 0.27, blue: 0.24)))
                        .disabled(scanDisabled)
                        .opacity(scanDisabled ? 0.55 : 1)
                        .accessibilityIdentifier("identify-button")
                }
                .buttonStyle(HardwareButtonStyle()).frame(width: proxy.size.width - 76).offset(x: 38, y: layout.viewfinder.maxY + 35)
                footer.frame(width: proxy.size.width - 80).position(x: proxy.size.width / 2, y: proxy.size.height - 49)
                    .disabled(store.isScanning)
            }
        }
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 13) {
            ScannerLights(isScanning: store.isScanning, isSpeaking: store.audio.isSpeaking)
            Spacer()
            VStack(alignment: .trailing, spacing: 8) {
                pixel(store.text("POKÉDEX", "宝可梦图鉴", "ポケモン図鑑"), 10)
                pixel(store.text("FIELD UNIT 001", "野外终端 001", "フィールド端末 001"), 6)
            }
            // Reserve the cover camera's expanded privacy-indicator area even
            // before capture starts, so entering live view never shifts the UI.
            .offset(y: 28)
            .foregroundStyle(DexTheme.cream.opacity(0.9))
        }
    }

    private func viewfinder(side: CGFloat) -> some View {
        ZStack {
            RoundedRectangle(cornerRadius: 15)
                .fill(LinearGradient(colors: [Color(white: 0.88), Color(white: 0.54), Color(white: 0.75)], startPoint: .topLeading, endPoint: .bottomTrailing))
                .shadow(color: .black.opacity(0.55), radius: 3, x: 1, y: 5)
            RoundedRectangle(cornerRadius: 6).fill(DexTheme.charcoal).padding(10)
            ZStack {
                DexTheme.lcd
                if let pokemon = store.scannedPokemon {
                    targetGrid
                    VStack(spacing: 10) {
                        Image(pokemon.spriteName).resizable().interpolation(.none).scaledToFit()
                            .frame(width: side * 0.58, height: side * 0.58)
                            .shadow(color: DexTheme.ink.opacity(0.2), radius: 0, x: 4, y: 6)
                            .accessibilityLabel(pokemon.name(in: store.language))
                            .accessibilityIdentifier("scan-result-sprite")
                        pixel(pokemon.name(in: store.language), 10)
                            .lineLimit(1).minimumScaleFactor(0.6)
                            .accessibilityIdentifier("scan-result-name")
                        if store.scanResult?.accepted == nil {
                            pixel(store.text("LOW CONFIDENCE · RESCAN", "置信度较低 · 请重新扫描", "確信度が低い結果 · 再スキャン"), 6)
                        }
                    }.padding(.horizontal, 24).foregroundStyle(DexTheme.ink)
                        .accessibilityElement(children: .contain).accessibilityIdentifier("scan-result")
                        .transition(reduceMotion ? .opacity : .scale(scale: 0.92).combined(with: .opacity))
                } else if let captured = store.capturedImage {
                    Image(uiImage: captured).resizable().scaledToFill()
                        .frame(width: side, height: side)
                        .accessibilityLabel(store.text("Captured scan image", "已捕获的扫描图像", "撮影したスキャン画像"))
                        .accessibilityIdentifier("scan-capture")
                } else if !store.useSample && store.camera.status == .ready {
                    CameraPreview(controller: store.camera)
                } else if store.useSample {
                    targetGrid
                    if let sample = store.sample {
                        Image(sample.spriteName).resizable().interpolation(.none).scaledToFit()
                            .frame(width: side * 0.68, height: side * 0.68)
                            .accessibilityLabel(sample.name(in: store.language))
                            .shadow(color: DexTheme.ink.opacity(0.2), radius: 0, x: 4, y: 6)
                    }
                } else {
                    cameraStatus
                }
                ScanLines().allowsHitTesting(false)
                if store.isScanning {
                    ScanSweep(reduceMotion: reduceMotion)
                        .accessibilityLabel(store.text("Scanning captured image", "正在扫描已捕获的图像", "撮影した画像をスキャン中"))
                        .accessibilityIdentifier("scan-animation")
                }
                VStack {
                    HStack(spacing: 6) {
                        Circle().fill(store.isScanning ? .orange : DexTheme.ink).frame(width: 5, height: 5)
                        pixel(viewfinderTitle, 7)
                        Spacer()
                        Image(systemName: "battery.100percent").font(.system(size: 14))
                    }
                    Spacer()
                    HStack {
                        pixel(store.scannedPokemon.map { "#\($0.number)" } ?? (store.useSample ? "#\(store.sample?.number ?? "025")" : "AF / 1×"), 8)
                        Spacer()
                        pixel(store.scannedPokemon != nil ? "\(Int((store.scanResult?.candidates.first?.confidence ?? 0) * 100))%" : store.text("OFFLINE", "离线", "オフライン"), 7)
                    }
                }.padding(14).foregroundStyle(DexTheme.ink)
                if store.scannedPokemon == nil {
                    Reticle().stroke(DexTheme.ink.opacity(0.6), lineWidth: 2).padding(42).allowsHitTesting(false)
                }
                if let message = store.message, store.scannedPokemon == nil {
                    VStack(spacing: 8) {
                        Image(systemName: "viewfinder.trianglebadge.exclamationmark").font(.title2)
                        Text(message).font(PixelFont.font(size: store.language == .en ? 8 : 14, language: store.language)).multilineTextAlignment(.center).lineSpacing(6)
                        if !store.candidates.isEmpty {
                            Text(store.text("Possible: ", "可能是：", "候補：") + store.candidates.prefix(2).compactMap { candidate in PokemonCatalog.shared.pokemon(id: candidate.dexID)?.name(in: store.language) }.joined(separator: " / "))
                                .font(.system(size: 11, design: .monospaced))
                        }
                    }.padding(15).frame(maxWidth: .infinity).foregroundStyle(DexTheme.cream)
                        .background(DexTheme.charcoal.opacity(0.95)).clipShape(RoundedRectangle(cornerRadius: 6)).padding(18)
                        .accessibilityIdentifier("scan-message")
                }
            }.frame(width: side, height: side).clipped().clipShape(RoundedRectangle(cornerRadius: 3))
                .animation(reduceMotion ? nil : .easeOut(duration: 0.2), value: store.scannedPokemon?.id)
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("viewfinder")
            VStack {
                HStack { Screw(); Spacer(); Screw() }
                Spacer()
                HStack { Screw(); Spacer(); Screw() }
            }.padding(4).allowsHitTesting(false)
        }
    }

    private var targetGrid: some View {
        Canvas { context, size in
            var dots = Path()
            for x in stride(from: 0.0, to: size.width, by: 20) {
                for y in stride(from: 0.0, to: size.height, by: 20) {
                    dots.addRect(CGRect(x: x, y: y, width: 1, height: 1))
                }
            }
            context.fill(dots, with: .color(DexTheme.ink.opacity(0.18)))
            for inset in [40.0, 75.0] {
                context.stroke(Path(ellipseIn: CGRect(x: inset, y: inset, width: size.width - inset * 2, height: size.height - inset * 2)), with: .color(DexTheme.ink.opacity(0.08)), lineWidth: 1)
            }
        }
    }

    private var cameraStatus: some View {
        VStack(spacing: 14) {
            Image(systemName: "camera.aperture").font(.system(size: 42, weight: .ultraLight))
            if store.camera.status == .requesting {
                ProgressView().tint(DexTheme.ink)
                Text(store.text("Starting camera…", "正在启动相机…", "カメラを起動中…"))
                    .font(.system(size: 15, design: .monospaced))
            } else if store.camera.status == .denied {
                Text(store.text("Camera access is off", "相机权限未开启", "カメラへのアクセスが無効です"))
                    .font(.system(size: 15, design: .monospaced))
                Button(store.text("Open Settings", "打开设置", "設定を開く")) {
                    if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
                }.font(.system(size: 13, weight: .bold)).tint(DexTheme.ink)
            } else {
                Text(store.text("Camera unavailable", "相机暂不可用", "カメラを利用できません"))
                    .font(.system(size: 15, design: .monospaced))
                Text(store.text("Import a photo", "导入照片", "写真を読み込む"))
                    .font(.system(size: 12, design: .monospaced))
            }
        }.foregroundStyle(DexTheme.ink).multilineTextAlignment(.center).padding(25)
    }

    private var footer: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 9) {
                Button {
                    store.audio.play(.button)
                    if compact { store.showingCompactEntry = true } else { store.showingCatalog = true }
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: "book.closed.fill")
                        pixel(compact ? store.text("OPEN RECORD", "打开记录", "図鑑を開く") : store.text("POKÉDEX", "宝可梦图鉴", "ポケモン図鑑"), 8)
                    }
                }.buttonStyle(.plain).accessibilityIdentifier("record-button")
                let total = PokemonCatalog.shared.entries.count
                pixel(store.text("\(store.seenIDs.count) SEEN · \(total) SPECIES", "已发现 \(store.seenIDs.count) · 共\(total)种", "発見 \(store.seenIDs.count) · 全\(total)種"), 6)
                    .foregroundStyle(.white.opacity(0.5))
            }.foregroundStyle(DexTheme.cream)
            Spacer()
            SpeakerGrille()
            Button { store.showingSettings = true; store.audio.play(.button) } label: {
                Image(systemName: "gearshape.fill").font(.system(size: 18)).frame(width: 44, height: 44)
            }.buttonStyle(.plain).foregroundStyle(.white.opacity(0.65))
                .accessibilityLabel(store.text("Settings", "设置", "設定")).accessibilityIdentifier("settings-button")
        }
    }

    private func pixel(_ text: String, _ size: CGFloat) -> some View {
        Text(text).font(PixelFont.font(size: store.language == .en ? size : size + 4, language: store.language))
    }
}

private struct ScanSweep: View {
    let reduceMotion: Bool
    @State private var started = Date()

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: reduceMotion)) { timeline in
            GeometryReader { proxy in
                let progress = reduceMotion ? 0.5 : timeline.date.timeIntervalSince(started).truncatingRemainder(dividingBy: 1.1) / 1.1
                let beamY = proxy.size.height * progress
                ZStack(alignment: .top) {
                    DexTheme.ink.opacity(0.16)
                    LinearGradient(colors: [.clear, DexTheme.lcd.opacity(0.65)], startPoint: .top, endPoint: .bottom)
                        .frame(height: 70).offset(y: beamY - 70)
                    Rectangle().fill(DexTheme.cream).frame(height: 3)
                        .shadow(color: DexTheme.lcd, radius: 8).offset(y: beamY)
                }
            }
        }.allowsHitTesting(false).accessibilityElement(children: .ignore)
    }
}

private struct Reticle: Shape {
    func path(in r: CGRect) -> Path {
        var path = Path()
        let length: CGFloat = 16
        for (x, y, dx, dy) in [(r.minX, r.minY, 1.0, 1.0), (r.maxX, r.minY, -1.0, 1.0), (r.minX, r.maxY, 1.0, -1.0), (r.maxX, r.maxY, -1.0, -1.0)] {
            path.move(to: CGPoint(x: x, y: y + dy * length))
            path.addLine(to: CGPoint(x: x, y: y))
            path.addLine(to: CGPoint(x: x + dx * length, y: y))
        }
        return path
    }
}

// Fixed-layout previews don't inherit a physical window's corner geometry.
// Supply the Duo display profiles here; the running app uses the system's
// active display container instead, including when switching between screens.
#Preview("Duo · closed", traits: .fixedLayout(width: 466, height: 678)) {
    ContentView().containerShape(UnevenRoundedRectangle(
        topLeadingRadius: 8, bottomLeadingRadius: 8,
        bottomTrailingRadius: 59, topTrailingRadius: 59
    ))
}

#Preview("Duo · open", traits: .fixedLayout(width: 951, height: 669)) {
    ContentView().containerShape(RoundedRectangle(cornerRadius: 55))
}
