import SwiftUI

struct EntryPanel: View {
    @Bindable var store: DexStore
    var onClose: (() -> Void)? = nil
    @State private var showStats = false

    var body: some View {
        // Leave room for the footer inside the shell's inset border, even on
        // the shorter interior display and with the taller CJK pixel fonts.
        VStack(spacing: 10) {
            HStack(spacing: 12) {
                Screw()
                Text(store.text("POKÉMON RESEARCH", "宝可梦研究终端", "ポケモンリサーチ", "寶可夢研究終端"))
                    .font(PixelFont.font(size: store.language == .en ? 9 : 16, language: store.language))
                    .foregroundStyle(DexTheme.cream.opacity(0.85))
                Spacer()
                Indicator(color: .green, size: 8)
                Screw()
            }.padding(.top, 55)
            if let pokemon = store.selected {
                LCDPanel {
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            Text("No. \(pokemon.number)").font(DexTheme.pixel(10)).accessibilityIdentifier("entry-number")
                            Spacer()
                            Text(store.entryStatusTitle)
                                .font(PixelFont.font(size: store.language == .en ? 7 : 13, language: store.language))
                        }
                        Rectangle().fill(DexTheme.ink.opacity(0.25)).frame(height: 1)
                        HStack(alignment: .center, spacing: 12) {
                            ZStack {
                                Circle().stroke(DexTheme.ink.opacity(0.13), lineWidth: 1).frame(width: 120, height: 120)
                                Ellipse().fill(DexTheme.ink.opacity(0.12)).frame(width: 95, height: 15).offset(y: 49)
                                Image(pokemon.spriteName).resizable().interpolation(.none).scaledToFit().frame(width: 145, height: 145).accessibilityHidden(true)
                            }
                            VStack(alignment: .leading, spacing: 10) {
                                Text(pokemon.name(in: store.language))
                                    .font(PixelFont.font(size: store.language == .en ? 12 : 25, language: store.language)).accessibilityIdentifier("pokemon-name")
                                    .lineLimit(1).minimumScaleFactor(0.55)
                                Text(pokemon.genus(in: store.language)).font(.system(size: 12, design: .monospaced))
                                HStack(spacing: 4) {
                                    ForEach(pokemon.typeNames(in: store.language), id: \.self) { type in
                                        Text(type).font(PixelFont.font(size: store.language == .en ? 6 : 12, language: store.language))
                                            .padding(.horizontal, 7).padding(.vertical, 5)
                                            .overlay { RoundedRectangle(cornerRadius: 2).stroke(DexTheme.ink.opacity(0.6), lineWidth: 1) }
                                    }
                                }
                            }
                        }.frame(maxWidth: .infinity, alignment: .leading)
                        HStack {
                            metric(store.text("HEIGHT", "身高", "たかさ", "身高"), String(format: "%.1f m", pokemon.height))
                            Spacer()
                            metric(store.text("WEIGHT", "体重", "おもさ", "體重"), String(format: "%.1f kg", pokemon.weight))
                            Spacer()
                            metric(store.text("SEEN", "发现", "発見", "發現"), store.seenIDs.contains(pokemon.id) ? "●" : "—")
                        }
                        Rectangle().fill(DexTheme.ink.opacity(0.25)).frame(height: 1)
                        HStack {
                            Text(showStats ? store.text("BASE STATS", "基础能力", "種族値", "基礎能力") : store.text("FIELD NOTES", "观察记录", "図鑑説明", "觀察紀錄"))
                                .font(PixelFont.font(size: store.language == .en ? 8 : 14, language: store.language))
                            Spacer()
                            Button { showStats.toggle(); store.audio.play(.button) } label: {
                                Image(systemName: showStats ? "text.alignleft" : "chart.bar.xaxis").frame(width: 32, height: 28)
                            }.buttonStyle(.plain).accessibilityLabel(store.text("Toggle base stats", "切换基础能力", "種族値の表示を切り替える", "切換基礎能力"))
                        }
                        if showStats {
                            VStack(spacing: 7) {
                                ForEach(pokemon.stats) { stat in
                                    HStack(spacing: 8) {
                                        Text(stat.title(in: store.language)).font(.system(size: 10, design: .monospaced)).frame(width: 60, alignment: .leading)
                                        GeometryReader { geo in
                                            ZStack(alignment: .leading) {
                                                Rectangle().fill(DexTheme.ink.opacity(0.1))
                                                Rectangle().fill(DexTheme.ink.opacity(0.7)).frame(width: geo.size.width * CGFloat(stat.value) / 255)
                                            }
                                        }.frame(height: 5)
                                        Text("\(stat.value)").font(DexTheme.pixel(6)).frame(width: 25, alignment: .trailing)
                                    }
                                }
                            }.frame(height: 104)
                        } else {
                            ScrollView {
                                Text(pokemon.description(in: store.language))
                                    .font(PixelFont.font(size: store.language == .en ? 8 : 17, language: store.language))
                                    .lineSpacing(store.language == .en ? 7 : 5)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }.frame(minHeight: 64, idealHeight: 104, maxHeight: 104)
                        }
                    }
                }
                HStack(spacing: 12) {
                    Button { store.step(-1) } label: { Image(systemName: "arrowtriangle.left.fill").frame(width: 17) }
                        .accessibilityLabel(store.text("Previous Pokémon", "上一个宝可梦", "前のポケモン", "上一隻寶可夢"))
                    Button { store.step(1) } label: { Image(systemName: "arrowtriangle.right.fill").frame(width: 17) }
                        .accessibilityLabel(store.text("Next Pokémon", "下一个宝可梦", "次のポケモン", "下一隻寶可夢"))
                    Spacer(minLength: 0)
                    Button { store.speak() } label: {
                        HStack(spacing: 8) {
                            Image(systemName: "speaker.wave.2.fill")
                            Text(store.text("READ", "朗读", "読み上げ", "朗讀")).font(PixelFont.font(size: store.language == .en ? 8 : 14, language: store.language))
                        }
                    }.accessibilityIdentifier("read-button")
                    Button { store.audio.stopSpeaking() } label: { Image(systemName: "stop.fill") }
                        .accessibilityLabel(store.text("Stop reading", "停止朗读", "読み上げを停止", "停止朗讀"))
                }.buttonStyle(HardwareButtonStyle())
                HStack {
                    Button { store.showingCatalog = true; store.audio.play(.button) } label: {
                        HStack(spacing: 8) {
                            Image(systemName: "square.grid.2x2.fill")
                            Text(store.text("BROWSE 151", "浏览151种", "全151種を見る", "瀏覽151種")).font(PixelFont.font(size: store.language == .en ? 8 : 14, language: store.language))
                        }
                    }.buttonStyle(.plain).foregroundStyle(DexTheme.cream).accessibilityIdentifier("catalog-button")
                    Spacer()
                    Text(store.confidence.map { "\(Int($0 * 100))%" } ?? store.text("GEN. I", "第一世代", "第1世代", "第一世代"))
                        .font(DexTheme.pixel(7)).foregroundStyle(.white.opacity(0.5))
                    if let onClose {
                        Button(action: onClose) {
                            Text(store.text("CLOSE", "关闭", "閉じる", "關閉"))
                                .font(PixelFont.font(size: store.language == .en ? 8 : 14, language: store.language))
                        }
                        .buttonStyle(HardwareButtonStyle())
                        .accessibilityLabel(store.text("Close record", "关闭记录", "図鑑を閉じる", "關閉紀錄"))
                        .accessibilityIdentifier("close-record")
                    } else {
                        SpeakerGrille().scaleEffect(0.8).frame(width: 50)
                    }
                }
            }
            Spacer(minLength: 0)
            HStack {
                Screw()
                Spacer()
                Text(store.text("SILPH CO. · PERSONAL FIELD SYSTEM", "西尔佛公司 · 个人野外系统", "シルフカンパニー · 個人用フィールドシステム", "西佛公司 · 個人野外系統"))
                    .font(PixelFont.font(size: store.language == .en ? 5 : 11, language: store.language))
                    .foregroundStyle(Color.black.opacity(0.45)).shadow(color: .white.opacity(0.18), radius: 0, y: 1)
                    .accessibilityIdentifier("record-footer")
                Spacer()
                Screw()
            }.padding(.bottom, 24)
        }.padding(.horizontal, 34)
    }

    private func metric(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(title).font(PixelFont.font(size: store.language == .en ? 6 : 12, language: store.language)).opacity(0.65)
            Text(value).font(DexTheme.pixel(8))
        }
    }
}
