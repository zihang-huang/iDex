import SwiftUI

/// Grid cards or compact rows in the archive; remembered between launches.
enum CatalogLayout: String {
    case grid, list
}

struct CatalogSheet: View {
    @Bindable var store: DexStore
    @State private var query = ""
    @State private var seenOnly = false
    /// Resets to all generations on every open, so a stale filter never hides a search result.
    @State private var generation: Int? = nil
    @AppStorage("idex.catalogLayout") private var layout = CatalogLayout.grid

    var body: some View {
        NavigationStack {
            let sections = results
            VStack(spacing: 0) {
                generationFilter
                HStack(spacing: 12) {
                    Toggle(store.text("Discovered only", "仅显示已发现", "発見済みのみ"), isOn: $seenOnly)
                        .font(.system(size: 13, design: .monospaced))
                    layoutButton(.grid, systemImage: "square.grid.2x2.fill", label: store.text("Grid", "网格", "グリッド"))
                    layoutButton(.list, systemImage: "list.bullet", label: store.text("List", "列表", "リスト"))
                }.padding(.horizontal, 20).padding(.vertical, 10)
                ScrollViewReader { proxy in
                    ScrollView {
                        Color.clear.frame(height: 0).id(Self.topID)
                        // One lazy grid holds every entry, so scrollTo can reach entries that
                        // have not been created yet; a grid nested per section could not.
                        LazyVGrid(columns: columns, alignment: .leading, spacing: layout == .grid ? 12 : 8, pinnedViews: [.sectionHeaders]) {
                            ForEach(sections) { section in
                                Section {
                                    ForEach(section.entries) { pokemon in
                                        entryButton(pokemon).id(pokemon.id)
                                    }
                                } header: {
                                    sectionHeader(section)
                                }
                            }
                        }.padding(.horizontal, 20).padding(.bottom, 20)
                        if sections.isEmpty {
                            ContentUnavailableView.search(text: query)
                        }
                    }
                    .task {
                        // Reopen at the record being viewed. Lazy content needs a layout pass
                        // first, so retry once after a longer pause.
                        guard let id = store.selected?.id else { return }
                        for delay in [50, 300] {
                            try? await Task.sleep(for: .milliseconds(delay))
                            proxy.scrollTo(id, anchor: .center)
                        }
                    }
                    .onChange(of: generation) { proxy.scrollTo(Self.topID, anchor: .top) }
                    .onChange(of: layout) {
                        if let id = store.selected?.id, results.contains(where: { section in section.entries.contains { $0.id == id } }) {
                            proxy.scrollTo(id, anchor: .center)
                        }
                    }
                }
            }
            .background(DexTheme.charcoal)
            .navigationTitle(store.text("National archive", "全国图鉴", "全国図鑑"))
            .navigationBarTitleDisplayMode(.inline)
            .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: store.text("Name, number or type", "名称、编号或属性", "名前・番号・タイプ"))
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button(store.text("Done", "完成", "完了")) { store.showingCatalog = false }.accessibilityIdentifier("settings-done") } }
        }.preferredColorScheme(.dark)
            .environment(\.locale, Locale(identifier: store.language.localeIdentifier))
            .statusBarHidden()
            .persistentSystemOverlays(.hidden)
    }

    private static let topID = "catalog-top"

    private var results: [CatalogSection] {
        PokemonCatalog.shared.sections(matching: query, language: store.language, generation: generation,
                                       onlyIDs: seenOnly ? store.seenIDs : nil)
    }

    /// Cards fill the width as before; rows split into two columns on the unfolded display.
    private var columns: [GridItem] {
        [GridItem(.adaptive(minimum: layout == .grid ? 125 : 380), spacing: 12)]
    }

    private var generationFilter: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                filterButton(store.text("ALL", "全部", "すべて"), font: PixelFont.font(size: store.language == .en ? 8 : 13, language: store.language),
                             value: nil, identifier: "generation-all")
                ForEach(PokemonCatalog.shared.generations, id: \.self) { value in
                    filterButton(Pokemon.romanNumeral(value), font: DexTheme.pixel(8), value: value, identifier: "generation-\(value)")
                        .accessibilityLabel(Pokemon.generationTitle(value, in: store.language))
                }
            }.padding(.horizontal, 20).padding(.vertical, 8)
        }.padding(.top, 4)
    }

    private func filterButton(_ title: String, font: Font, value: Int?, identifier: String) -> some View {
        let selected = generation == value
        return Button { generation = value; store.audio.play(.button) } label: { Text(title).font(font) }
            .buttonStyle(HardwareButtonStyle(color: selected ? DexTheme.lcd : DexTheme.graphite, foreground: selected ? DexTheme.ink : DexTheme.cream))
            .accessibilityIdentifier(identifier)
            .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private func layoutButton(_ value: CatalogLayout, systemImage: String, label: String) -> some View {
        let selected = layout == value
        return Button { layout = value; store.audio.play(.button) } label: { Image(systemName: systemImage).frame(width: 17) }
            .buttonStyle(HardwareButtonStyle(color: selected ? DexTheme.lcd : DexTheme.graphite, foreground: selected ? DexTheme.ink : DexTheme.cream))
            .accessibilityLabel(label)
            .accessibilityIdentifier("catalog-layout-\(value.rawValue)")
            .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private func sectionHeader(_ section: CatalogSection) -> some View {
        Text("\(Pokemon.generationTitle(section.generation, in: store.language)) · \(section.entries.count)")
            .font(PixelFont.font(size: store.language == .en ? 8 : 14, language: store.language))
            .foregroundStyle(DexTheme.lcd)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, 8)
            .background(DexTheme.charcoal)
            .accessibilityAddTraits(.isHeader)
    }

    private func entryButton(_ pokemon: Pokemon) -> some View {
        Button { store.browse(pokemon) } label: {
            if layout == .grid { gridCard(pokemon) } else { listRow(pokemon) }
        }.buttonStyle(.plain).accessibilityIdentifier("pokemon-\(pokemon.id)")
    }

    private func gridCard(_ pokemon: Pokemon) -> some View {
        VStack(spacing: 8) {
            HStack {
                Text("#\(pokemon.number)").font(DexTheme.pixel(7))
                Spacer()
                if store.seenIDs.contains(pokemon.id) { Image(systemName: "checkmark.seal.fill").font(.system(size: 11)) }
            }
            Image(pokemon.spriteName).resizable().interpolation(.none).scaledToFit().frame(height: 80).accessibilityHidden(true)
            Text(pokemon.name(in: store.language))
                .font(PixelFont.font(size: store.language == .en ? 8 : 16, language: store.language))
                .lineLimit(1).minimumScaleFactor(0.5)
        }.padding(12).foregroundStyle(DexTheme.ink)
            .background(DexTheme.lcd, in: RoundedRectangle(cornerRadius: 5))
    }

    /// One line per species; the trailing ●/— matches the record panel's SEEN field.
    private func listRow(_ pokemon: Pokemon) -> some View {
        HStack(spacing: 10) {
            Text("#\(pokemon.number)").font(DexTheme.pixel(7)).frame(width: 46, alignment: .leading)
            Image(pokemon.spriteName).resizable().interpolation(.none).scaledToFit().frame(width: 40, height: 40).accessibilityHidden(true)
            // A capped name column keeps the type tags aligned from row to row.
            Text(pokemon.name(in: store.language))
                .font(PixelFont.font(size: store.language == .en ? 8 : 16, language: store.language))
                .lineLimit(1).minimumScaleFactor(0.5)
                .frame(maxWidth: 130, alignment: .leading)
            HStack(spacing: 4) {
                ForEach(pokemon.typeNames(in: store.language), id: \.self) { type in
                    TypeTag(name: type, language: store.language)
                }
            }
            Spacer(minLength: 4)
            Text(store.seenIDs.contains(pokemon.id) ? "●" : "—").font(DexTheme.pixel(8)).frame(width: 16)
                .accessibilityLabel(store.seenIDs.contains(pokemon.id) ? store.text("Discovered", "已发现", "発見済み") : "")
        }.padding(.horizontal, 12).padding(.vertical, 6).foregroundStyle(DexTheme.ink)
            .background(DexTheme.lcd, in: RoundedRectangle(cornerRadius: 5))
    }
}

struct SettingsSheet: View {
    @Bindable var store: DexStore
    var body: some View {
        @Bindable var audio = store.audio
        NavigationStack {
            Form {
                Section(store.text("Language / 语言", "语言 / Language", "言語 / Language")) {
                    ForEach(AppLanguage.allCases) { language in
                        Button {
                            store.language = language
                            store.audio.play(.button)
                        } label: {
                            HStack {
                                Text(language.title).foregroundStyle(.primary)
                                Spacer()
                                if store.language == language { Image(systemName: "checkmark").foregroundStyle(.green) }
                            }
                        }.accessibilityIdentifier("language-\(language.rawValue)")
                    }
                }
                Section(store.text("Sound", "声音", "サウンド")) {
                    Toggle(store.text("Device sounds & spoken entries", "设备音效与图鉴语音", "効果音と図鑑の読み上げ"), isOn: $audio.isSoundEnabled)
                        .accessibilityIdentifier("sound-toggle")
                    Button(store.text("Stop reading", "停止朗读", "読み上げを停止")) { audio.stopSpeaking() }
                }
                Section(store.text("Field guide", "使用指南", "使い方")) {
                    Label(store.text("Point at a Pokémon, then identify.", "将取景器对准宝可梦，轻点识别。", "ポケモンにカメラを向けて、スキャンします。"), systemImage: "viewfinder")
                    Label(store.text("Unfold to reveal the research panel.", "展开屏幕，查看内部研究面板。", "画面を開くと、リサーチパネルが表示されます。"), systemImage: "book")
                    Label(store.text("Photos and recognition stay on your iPhone.", "照片与识别过程均留在你的 iPhone 上。", "写真と識別処理は、すべて iPhone 内で完結します。"), systemImage: "lock.shield")
                    Text(store.text("The bundled model recognizes the original 151 Kanto Pokémon. Uncertain scans ask you to try again. Samples use the same model as your camera.", "内置模型可识别最初的151种关都宝可梦。匹配不确定时会提示重试。样本与相机使用相同的识别模型。", "内蔵モデルは、カントー地方の最初の151種のポケモンを識別します。結果が不確かな場合は、再スキャンをお試しください。サンプルとカメラは同じ識別モデルを使います。"))
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section(store.text("Credits", "制作信息", "クレジット")) {
                    Text("iDex · FIELD UNIT 001").font(DexTheme.pixel(8))
                    Text(store.text("An independent fan project. Pokémon and its characters belong to Nintendo, Creatures, and GAME FREAK. Not affiliated with or endorsed by them.", "独立粉丝项目。宝可梦及相关角色归任天堂、Creatures及GAME FREAK所有。本项目与其无关联，亦未获得其认可。", "個人によるファンプロジェクトです。ポケモンおよび関連キャラクターの権利は、任天堂・クリーチャーズ・ゲームフリークに帰属します。本プロジェクトは、各社との提携や公認を受けていません。"))
                        .font(.footnote).foregroundStyle(.secondary)
                    Link(store.text("Sprites · Pokémon Database", "像素图 · Pokémon Database", "スプライト · Pokémon Database"), destination: URL(string: "https://pokemondb.net/sprites")!)
                    Link(store.text("Gen 5-style sprites (No. 650+) · Pokémon Showdown", "第650号起的像素图 · Pokémon Showdown", "No.650以降のスプライト · Pokémon Showdown"), destination: URL(string: "https://play.pokemonshowdown.com/sprites/gen5/")!)
                    Link(store.text("Pokédex data · PokéAPI", "图鉴数据 · PokéAPI", "図鑑データ · PokéAPI"), destination: URL(string: "https://github.com/PokeAPI/pokeapi")!)
                    Link(store.text("Missing Chinese entries · pokemon.cn", "补充中文图鉴 · 宝可梦官方网站", "中国語の補足 · pokemon.cn"), destination: URL(string: "https://www.pokemon.cn/play/pokedex/")!)
                    Link(store.text("Missing Japanese entries · Pokémon Zukan", "补充日文图鉴 · ポケモンずかん", "日本語の補足 · ポケモンずかん"), destination: URL(string: "https://zukan.pokemon.co.jp/")!)
                    Text("Press Start 2P · Fusion Pixel · SIL OFL 1.1").font(.caption).foregroundStyle(.secondary)
                }
            }.navigationTitle(store.text("Device settings", "设备设置", "デバイス設定"))
                .navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button(store.text("Done", "完成", "完了")) { store.showingSettings = false }.accessibilityIdentifier("settings-done") } }
        }.preferredColorScheme(.dark)
            .environment(\.locale, Locale(identifier: store.language.localeIdentifier))
            .statusBarHidden()
            .persistentSystemOverlays(.hidden)
    }
}
