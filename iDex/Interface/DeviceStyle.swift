import SwiftUI

enum DexTheme {
    static let red = Color(red: 0.70, green: 0.075, blue: 0.105)
    static let ink = Color(red: 0.12, green: 0.17, blue: 0.13)
    static let lcd = Color(red: 0.72, green: 0.81, blue: 0.58)
    static let cream = Color(red: 0.86, green: 0.86, blue: 0.77)
    static let charcoal = Color(red: 0.12, green: 0.14, blue: 0.15)
    /// One step lighter than charcoal, so hardware buttons stay visible on charcoal sheets.
    static let graphite = Color(red: 0.19, green: 0.21, blue: 0.22)
    static func pixel(_ size: CGFloat) -> Font { .custom("PressStart2P-Regular", size: size) }
}

struct ShellSurface: View {
    var body: some View {
        ZStack {
            LinearGradient(colors: [Color(red: 0.91, green: 0.21, blue: 0.24), DexTheme.red, Color(red: 0.55, green: 0.035, blue: 0.065)], startPoint: .topLeading, endPoint: .bottomTrailing)
            Canvas { context, size in
                var brightDots = Path()
                var faintDots = Path()
                for x in stride(from: 0.0, to: size.width, by: 4) {
                    for y in stride(from: 0.0, to: size.height, by: 4) {
                        let rect = CGRect(x: x, y: y, width: 1, height: 1)
                        if Int(x * 7 + y * 13) % 9 == 0 { brightDots.addRect(rect) }
                        else { faintDots.addRect(rect) }
                    }
                }
                context.fill(brightDots, with: .color(.white.opacity(0.10)))
                context.fill(faintDots, with: .color(.white.opacity(0.025)))
            }.allowsHitTesting(false)
            // Resolve each corner independently against the active display. The
            // cover's 8pt leading corners become square at these insets, while
            // its 59pt trailing corners (and the interior's 55pt corners) stay
            // concentric with the screen instead of using a fixed decorative R.
            ConcentricRectangle().stroke(.black.opacity(0.35), lineWidth: 5).padding(9)
            ConcentricRectangle().stroke(.white.opacity(0.16), lineWidth: 1).padding(12)
        }
    }
}

struct Screw: View {
    var body: some View {
        Circle().fill(LinearGradient(colors: [.gray, .black.opacity(0.8)], startPoint: .topLeading, endPoint: .bottomTrailing))
            .overlay { Capsule().fill(.black.opacity(0.7)).frame(width: 7, height: 1.5).rotationEffect(.degrees(-35)) }
            .overlay { Circle().stroke(.white.opacity(0.3), lineWidth: 0.6) }
            .frame(width: 12, height: 12).shadow(color: .black.opacity(0.6), radius: 1, y: 1)
            .accessibilityHidden(true)
    }
}

struct Indicator: View {
    var color: Color
    var size: CGFloat = 10
    var isLit = true
    var body: some View {
        Circle().fill(RadialGradient(colors: isLit
            ? [.white.opacity(0.95), color, color.opacity(0.45)]
            : [color.opacity(0.35), color.opacity(0.18), .black.opacity(0.65)],
            center: .init(x: 0.32, y: 0.25), startRadius: 0, endRadius: size * 0.8))
            .overlay { Circle().stroke(.black.opacity(0.65), lineWidth: 2) }
            .frame(width: size, height: size)
            .shadow(color: color.opacity(isLit ? 0.7 : 0), radius: 4)
            .accessibilityHidden(true)
    }
}

struct Lens: View {
    var isLit = false

    var body: some View {
        Circle().fill(LinearGradient(colors: [.white, Color(white: 0.5), Color(white: 0.85)], startPoint: .topLeading, endPoint: .bottomTrailing))
            .overlay { Circle().fill(Color(white: 0.13)).padding(6) }
            .overlay { Circle().fill(RadialGradient(colors: isLit
                ? [Color(red: 0.78, green: 1, blue: 1), Color(red: 0.03, green: 0.83, blue: 1), Color(red: 0.02, green: 0.40, blue: 0.65)]
                : [Color(red: 0.15, green: 0.39, blue: 0.45), Color(red: 0.02, green: 0.23, blue: 0.31), Color(red: 0.01, green: 0.10, blue: 0.19)],
                center: .init(x: 0.35, y: 0.25), startRadius: 0, endRadius: 57)).padding(9) }
            .overlay(alignment: .topLeading) { Ellipse().fill(.white.opacity(isLit ? 0.85 : 0.3)).frame(width: 23, height: 12).rotationEffect(.degrees(-40)).offset(x: 15, y: 15) }
            .frame(width: 70, height: 70)
            .shadow(color: .cyan.opacity(isLit ? 0.65 : 0), radius: 12)
            .shadow(color: .black.opacity(0.55), radius: 3, x: 2, y: 5)
            .accessibilityHidden(true)
    }
}

struct ScannerLights: View {
    var isScanning: Bool
    var isSpeaking: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var activeLight = 0

    private var isChasing: Bool { isScanning && !isSpeaking && !reduceMotion }

    var body: some View {
        HStack(spacing: 13) {
            Lens(isLit: isSpeaking)
            VStack(alignment: .leading, spacing: 16) {
                HStack(spacing: 9) {
                    ForEach(0..<3) { index in
                        Indicator(color: [.red, .yellow, .green][index],
                                  isLit: isScanning && !isSpeaking && (reduceMotion || index == activeLight))
                    }
                }
                Text("iDEX").font(.system(size: 28, weight: .black, design: .rounded)).italic()
                    .foregroundStyle(Color(red: 0.35, green: 0.02, blue: 0.035))
                    .shadow(color: .white.opacity(0.3), radius: 0, y: 1)
            }
        }
        .accessibilityHidden(true)
        .task(id: isChasing) {
            activeLight = 0
            guard isChasing else { return }
            do {
                while !Task.isCancelled {
                    try await Task.sleep(for: .milliseconds(220))
                    activeLight = (activeLight + 1) % 3
                }
            } catch { /* A finished scan or speech cancels the chase. */ }
        }
    }
}

struct HardwareButtonStyle: ButtonStyle {
    var color: Color = DexTheme.charcoal
    var foreground: Color = DexTheme.cream
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(foreground)
            .padding(.horizontal, 16).frame(minHeight: 44)
            .background(LinearGradient(colors: [color.opacity(0.85), color], startPoint: .top, endPoint: .bottom), in: RoundedRectangle(cornerRadius: 8))
            .overlay { RoundedRectangle(cornerRadius: 8).stroke(.white.opacity(0.17), lineWidth: 1).padding(1) }
            .overlay { RoundedRectangle(cornerRadius: 8).stroke(.black.opacity(0.6), lineWidth: 2) }
            .shadow(color: .black.opacity(0.6), radius: configuration.isPressed ? 0 : 1, x: 0, y: configuration.isPressed ? 1 : 4)
            .offset(y: configuration.isPressed ? 3 : 0)
    }
}

/// The outlined type label used on LCD surfaces (record panel and archive list).
struct TypeTag: View {
    let name: String
    let language: AppLanguage
    var body: some View {
        Text(name).font(PixelFont.font(size: language == .en ? 6 : 12, language: language))
            .padding(.horizontal, 7).padding(.vertical, 5)
            .overlay { RoundedRectangle(cornerRadius: 2).stroke(DexTheme.ink.opacity(0.6), lineWidth: 1) }
    }
}

struct LCDPanel<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        content.padding(15).foregroundStyle(DexTheme.ink)
            .background(DexTheme.lcd.gradient)
            .overlay(alignment: .top) { Rectangle().fill(.black.opacity(0.18)).frame(height: 3) }
            .overlay { ScanLines().allowsHitTesting(false) }
            .clipShape(RoundedRectangle(cornerRadius: 5))
            .padding(7).background(DexTheme.charcoal, in: RoundedRectangle(cornerRadius: 10))
            .overlay { RoundedRectangle(cornerRadius: 10).stroke(.black.opacity(0.65), lineWidth: 2) }
            .shadow(color: .white.opacity(0.15), radius: 0, y: 1)
    }
}

struct ScanLines: View {
    var body: some View {
        Canvas { context, size in
            var lines = Path()
            for y in stride(from: 0.0, to: size.height, by: 3) {
                lines.addRect(CGRect(x: 0, y: y, width: size.width, height: 0.5))
            }
            context.fill(lines, with: .color(.black.opacity(0.075)))
        }
    }
}

struct SpeakerGrille: View {
    var body: some View {
        HStack(spacing: 5) {
            ForEach(0..<6) { _ in
                Capsule().fill(.black.opacity(0.65)).frame(width: 4, height: 29)
                    .shadow(color: .white.opacity(0.16), radius: 0, x: 1, y: 1)
            }
        }.rotationEffect(.degrees(-15)).accessibilityHidden(true)
    }
}

struct HingeSpine: View {
    var body: some View {
        ZStack {
            LinearGradient(colors: [Color(red: 0.29, green: 0.02, blue: 0.035), DexTheme.red, Color(red: 0.9, green: 0.23, blue: 0.23), DexTheme.red, .black.opacity(0.7)], startPoint: .leading, endPoint: .trailing)
            VStack {
                ForEach(0..<4) { _ in
                    Spacer()
                    Rectangle().fill(.black.opacity(0.55)).frame(height: 3).overlay(alignment: .bottom) { Rectangle().fill(.white.opacity(0.2)).frame(height: 1) }
                }
                Spacer()
            }
        }.frame(width: 19).accessibilityHidden(true)
    }
}
