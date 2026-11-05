import Foundation
import CoreText
import SwiftUI

/// Controls both interface copy and the voice used for Pokédex readings.
enum AppLanguage: String, CaseIterable, Identifiable, Codable {
    case en
    case zhHans
    case ja

    var id: String { rawValue }
    var title: String { text("English", "简体中文", "日本語") }
    var localeIdentifier: String { text("en", "zh-Hans", "ja") }
    var speechLocale: String { text("en-US", "zh-CN", "ja-JP") }

    static var systemDefault: AppLanguage {
        preferred(in: Locale.preferredLanguages)
    }

    static func preferred(in languages: [String]) -> AppLanguage {
        for identifier in languages {
            switch Locale(identifier: identifier).language.languageCode?.identifier {
            case "en": return .en
            case "zh": return .zhHans
            case "ja": return .ja
            default: continue
            }
        }
        return .en
    }

    func text(_ english: String, _ chinese: String, _ japanese: String) -> String {
        switch self {
        case .en: return english
        case .zhHans: return chinese
        case .ja: return japanese
        }
    }
}

struct PokemonStat: Codable, Hashable, Identifiable {
    let name: String
    let value: Int
    var id: String { name }

    func title(in language: AppLanguage) -> String {
        switch name {
        case "hp": return language.text("HP", "体力", "HP")
        case "attack": return language.text("ATTACK", "攻击", "こうげき")
        case "defense": return language.text("DEFENSE", "防御", "ぼうぎょ")
        case "special-attack": return language.text("SP. ATK", "特攻", "とくこう")
        case "special-defense": return language.text("SP. DEF", "特防", "とくぼう")
        case "speed": return language.text("SPEED", "速度", "すばやさ")
        default: return name.uppercased()
        }
    }
}

struct Pokemon: Identifiable, Codable, Hashable {
    let id: Int
    /// Game generation that introduced the species, from 1 (Red/Green) upward.
    let generation: Int
    let englishName: String
    let chineseName: String
    let japaneseName: String
    /// Stable, English type identifiers, such as `grass` and `poison`.
    let types: [String]
    /// Height in metres.
    let height: Double
    /// Weight in kilograms.
    let weight: Double
    let englishDescription: String
    let chineseDescription: String
    let japaneseDescription: String
    let englishGenus: String
    let chineseGenus: String
    let japaneseGenus: String
    let stats: [PokemonStat]

    var number: String { String(format: "%03d", id) }
    var spriteName: String { "pokemon-\(number)" }
    var totalStats: Int { stats.reduce(0) { $0 + $1.value } }

    func name(in language: AppLanguage) -> String {
        language.text(englishName, chineseName, japaneseName)
    }

    func description(in language: AppLanguage) -> String {
        language.text(englishDescription, chineseDescription, japaneseDescription)
    }

    func genus(in language: AppLanguage) -> String {
        language.text(englishGenus, chineseGenus, japaneseGenus)
    }

    func typeNames(in language: AppLanguage) -> [String] {
        types.map { Self.typeName($0, in: language) }
    }

    func generationTitle(in language: AppLanguage) -> String {
        Self.generationTitle(generation, in: language)
    }

    static func generationTitle(_ generation: Int, in language: AppLanguage) -> String {
        let chinese = ["一", "二", "三", "四", "五", "六", "七", "八", "九"]
        let han = chinese.indices.contains(generation - 1) ? chinese[generation - 1] : "\(generation)"
        return language.text("GEN. \(romanNumeral(generation))", "第\(han)世代", "第\(generation)世代")
    }

    static func romanNumeral(_ generation: Int) -> String {
        let roman = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX"]
        return roman.indices.contains(generation - 1) ? roman[generation - 1] : "\(generation)"
    }

    static func typeName(_ type: String, in language: AppLanguage) -> String {
        switch language {
        case .en: return type.uppercased()
        case .zhHans: return chineseTypeNames[type] ?? type
        case .ja: return japaneseTypeNames[type] ?? type
        }
    }

    private static let chineseTypeNames = [
        "normal": "一般", "fighting": "格斗", "flying": "飞行", "poison": "毒",
        "ground": "地面", "rock": "岩石", "bug": "虫", "ghost": "幽灵",
        "steel": "钢", "fire": "火", "water": "水", "grass": "草",
        "electric": "电", "psychic": "超能力", "ice": "冰", "dragon": "龙",
        "dark": "恶", "fairy": "妖精"
    ]

    private static let japaneseTypeNames = [
        "normal": "ノーマル", "fighting": "かくとう", "flying": "ひこう", "poison": "どく",
        "ground": "じめん", "rock": "いわ", "bug": "むし", "ghost": "ゴースト",
        "steel": "はがね", "fire": "ほのお", "water": "みず", "grass": "くさ",
        "electric": "でんき", "psychic": "エスパー", "ice": "こおり", "dragon": "ドラゴン",
        "dark": "あく", "fairy": "フェアリー"
    ]

    func spokenEntry(in language: AppLanguage) -> String {
        if language == .zhHans {
            return "\(chineseName)。全国图鉴编号\(id)。\(chineseGenus)。属性，\(typeNames(in: language).joined(separator: "，"))。\(chineseDescription)"
        }
        if language == .ja {
            return "\(japaneseName)。全国図鑑番号\(id)。\(japaneseGenus)。\(typeNames(in: language).joined(separator: "、"))タイプ。\(japaneseDescription)"
        }
        return "\(englishName). Pokédex number \(id). \(englishGenus). \(typeNames(in: language).joined(separator: " and ")) type. \(englishDescription)"
    }
}

/// One generation's slice of the archive browser.
struct CatalogSection: Identifiable, Equatable {
    let generation: Int
    let entries: [Pokemon]
    var id: Int { generation }
}

struct PokemonCatalog {
    static let shared = PokemonCatalog()
    let entries: [Pokemon]
    /// Generations present in the catalog, in order.
    let generations: [Int]
    private let entriesByID: [Int: Pokemon]
    private let searchIndex: [SearchEntry]

    private struct SearchEntry {
        let pokemon: Pokemon
        let number: String
        let englishTypes: [String]
        let chineseTypes: [String]
        let japaneseTypes: [String]

        func types(in language: AppLanguage) -> [String] {
            switch language {
            case .en: return englishTypes
            case .zhHans: return chineseTypes
            case .ja: return japaneseTypes
            }
        }
    }

    private init(bundle: Bundle = .main) {
        guard let url = bundle.url(forResource: "pokemon-national", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let decoded = try? JSONDecoder().decode([Pokemon].self, from: data) else {
            assertionFailure("The bundled National Pokédex catalog is missing or invalid.")
            entries = []
            generations = []
            entriesByID = [:]
            searchIndex = []
            return
        }
        entries = decoded.sorted { $0.id < $1.id }
        generations = Array(Set(entries.map(\.generation))).sorted()
        entriesByID = Dictionary(uniqueKeysWithValues: entries.map { ($0.id, $0) })
        searchIndex = entries.map {
            SearchEntry(pokemon: $0, number: $0.number,
                        englishTypes: $0.typeNames(in: .en), chineseTypes: $0.typeNames(in: .zhHans),
                        japaneseTypes: $0.typeNames(in: .ja))
        }
    }

    func pokemon(id: Int) -> Pokemon? {
        entriesByID[id]
    }

    func search(_ query: String, language: AppLanguage) -> [Pokemon] {
        let value = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return entries }
        let numberQuery = value.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
        return searchIndex.compactMap { entry in
            let matches = entry.pokemon.englishName.localizedCaseInsensitiveContains(value)
                || entry.pokemon.chineseName.contains(value)
                || entry.pokemon.japaneseName.contains(value)
                || entry.number.contains(numberQuery)
                || entry.types(in: language).contains { $0.localizedCaseInsensitiveContains(value) }
            return matches ? entry.pokemon : nil
        }
    }

    /// Search results narrowed to one generation and/or a set of IDs, grouped by generation in dex order.
    func sections(matching query: String, language: AppLanguage, generation: Int? = nil, onlyIDs: Set<Int>? = nil) -> [CatalogSection] {
        let matches = search(query, language: language).filter {
            (generation == nil || $0.generation == generation) && (onlyIDs?.contains($0.id) ?? true)
        }
        return Dictionary(grouping: matches, by: \.generation)
            .sorted { $0.key < $1.key }
            .map { CatalogSection(generation: $0.key, entries: $0.value) }
    }
}

/// Font registration stays entirely local; no network request is required at launch.
enum PixelFont {
    private static var didRegister = false
    static let latinName = "PressStart2P-Regular"
    // Determined from the upstream OTF's PostScript name.
    static let chineseName = "Fusion-Pixel-12px-Prop-zh-Hans-Regular"
    static let japaneseName = "Fusion-Pixel-12px-Prop-ja-Regular"

    static func register() {
        guard !didRegister else { return }
        didRegister = true
        for (name, ext) in [("PressStart2P-Regular", "ttf"), ("FusionPixel-12px-zh-Hans", "otf"), ("FusionPixel-12px-ja", "otf")] {
            if let url = Bundle.main.url(forResource: name, withExtension: ext) {
                CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
            }
        }
    }

    static func font(size: CGFloat, language: AppLanguage = .en) -> Font {
        .custom(language.text(latinName, chineseName, japaneseName), size: size)
    }
}
