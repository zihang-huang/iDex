import Testing
import UIKit
import CoreText
@testable import iDex

@MainActor
struct CatalogTests {
    @Test func catalogIncludesTheWholeNationalPokedex() {
        let entries = PokemonCatalog.shared.entries
        #expect(entries.map(\.id) == Array(1...1025))
        #expect(Set(entries.map(\.englishName)).count == 1025)
        #expect(Set(entries.map(\.chineseName)).count == 1025)
        #expect(Set(entries.map(\.japaneseName)).count == 1025)
        #expect(entries.prefix(151).allSatisfy { $0.generation == 1 })
        #expect(entries.last?.generation == 9)
        #expect(zip(entries, entries.dropFirst()).allSatisfy { $0.generation <= $1.generation })
        #expect(entries.allSatisfy { !$0.englishDescription.isEmpty && !$0.chineseDescription.isEmpty })
        #expect(entries.allSatisfy { !$0.englishGenus.isEmpty && !$0.chineseGenus.isEmpty })
        #expect(entries.allSatisfy { !$0.japaneseDescription.isEmpty && !$0.japaneseGenus.isEmpty })
        #expect(entries.allSatisfy { $0.height > 0 && $0.weight > 0 })
        #expect(entries.allSatisfy { $0.stats.count == 6 && $0.stats.allSatisfy { $0.value > 0 } })
        #expect(entries.allSatisfy { (1...2).contains($0.types.count) })
    }

    @Test func spriteAssetsAreBundledForEverySpecies() {
        for pokemon in PokemonCatalog.shared.entries {
            let sprite = UIImage(named: pokemon.spriteName)
            #expect(sprite != nil, "Missing sprite for \(pokemon.englishName)")
            #expect(sprite?.size == CGSize(width: 96, height: 96))
        }
    }

    @Test func allPixelFontsRegisterFromBundledFiles() {
        PixelFont.register()
        for fontName in [PixelFont.latinName, PixelFont.chineseName, PixelFont.japaneseName] {
            let font = CTFontCreateWithName(fontName as CFString, 12, nil)
            #expect(CTFontCopyPostScriptName(font) as String == fontName)
        }
    }

    @Test func japaneseFontCoversCatalogText() {
        PixelFont.register()
        let font = CTFontCreateWithName(PixelFont.japaneseName as CFString, 17, nil)
        for pokemon in PokemonCatalog.shared.entries {
            let text = pokemon.japaneseName + pokemon.japaneseGenus + pokemon.japaneseDescription
            let characters = Array(text.utf16)
            var glyphs = [CGGlyph](repeating: 0, count: characters.count)
            #expect(CTFontGetGlyphsForCharacters(font, characters, &glyphs, characters.count),
                    "Missing Japanese glyph for \(pokemon.englishName)")
        }
    }

    @Test func languageSelectionResolvesSupportedSystemPreferences() {
        #expect(AppLanguage.preferred(in: ["ja-JP", "en-US"]) == .ja)
        #expect(AppLanguage.preferred(in: ["ja"]) == .ja)
        #expect(AppLanguage.preferred(in: ["zh-Hans-CN", "ja-JP"]) == .zhHans)
        #expect(AppLanguage.preferred(in: ["en-GB", "ja-JP"]) == .en)
        #expect(AppLanguage.preferred(in: ["fr-FR", "ja-JP"]) == .ja)
        #expect(AppLanguage.preferred(in: ["fr-FR"]) == .en)
        #expect(AppLanguage.preferred(in: []) == .en)
        #expect(AppLanguage.ja.title == "日本語")
        #expect(AppLanguage.ja.localeIdentifier == "ja")
        #expect(AppLanguage.ja.speechLocale == "ja-JP")
        #expect(AppLanguage.ja.text("Scan", "扫描", "スキャン") == "スキャン")
    }

    @Test func japaneseEntriesTypesStatsAndNarrationUseJapanese() throws {
        let catalog = PokemonCatalog.shared
        let pikachu = try #require(catalog.pokemon(id: 25))
        #expect(pikachu.name(in: .ja) == "ピカチュウ")
        #expect(pikachu.genus(in: .ja) == "ねずみポケモン")
        #expect(pikachu.description(in: .ja) == pikachu.japaneseDescription)
        #expect(pikachu.typeNames(in: .ja) == ["でんき"])
        #expect(pikachu.stats.map { $0.title(in: .ja) } == ["HP", "こうげき", "ぼうぎょ", "とくこう", "とくぼう", "すばやさ"])
        #expect(pikachu.spokenEntry(in: .ja).hasPrefix("ピカチュウ。全国図鑑番号25。ねずみポケモン。でんきタイプ。"))
        #expect(pikachu.spokenEntry(in: .ja).hasSuffix(pikachu.japaneseDescription))
        #expect(try #require(catalog.pokemon(id: 6)).typeNames(in: .ja) == ["ほのお", "ひこう"])
        let fire = catalog.search("ほのお", language: .ja)
        #expect(!fire.isEmpty)
        #expect(fire.allSatisfy { $0.types.contains("fire") })
        for type in Set(catalog.entries.flatMap(\.types)) {
            #expect(Pokemon.typeName(type, in: .ja) != type)
        }
    }

    @Test func catalogSearchSupportsBothLanguagesAndNumbers() {
        let catalog = PokemonCatalog.shared
        #expect(catalog.search("pIkAcHu", language: .en).map(\.id) == [25])
        #expect(catalog.search("皮卡丘", language: .zhHans).map(\.id) == [25])
        #expect(catalog.search("皮卡丘", language: .en).map(\.id) == [25])
        // Number search matches substrings, so "025" also finds No. 1025.
        #expect(catalog.search("#025", language: .en).map(\.id) == [25, 1025])
        #expect(catalog.search("  025 \n", language: .zhHans).map(\.id) == [25, 1025])
        #expect(catalog.search("", language: .en).count == 1025)
        #expect(catalog.search("not a pokemon", language: .en).isEmpty)
    }

    @Test func typeSearchAndSpokenEntriesUseSelectedLanguage() throws {
        let catalog = PokemonCatalog.shared
        let englishFire = catalog.search("fire", language: .en)
        let chineseFire = catalog.search("火", language: .zhHans)
        #expect(!englishFire.isEmpty)
        #expect(englishFire.allSatisfy { $0.types.contains("fire") })
        // Chinese 火 also occurs in 火爆猴 (Primeape), so broad name/type
        // search intentionally includes more than the Fire-type entries.
        #expect(Set(englishFire.map(\.id)).isSubset(of: Set(chineseFire.map(\.id))))
        #expect(chineseFire.contains { $0.id == 57 })
        let pikachu = try #require(catalog.pokemon(id: 25))
        #expect(pikachu.typeNames(in: .en) == ["ELECTRIC"])
        #expect(pikachu.typeNames(in: .zhHans) == ["电"])
        #expect(pikachu.spokenEntry(in: .en).contains("Pikachu"))
        #expect(pikachu.spokenEntry(in: .zhHans).contains("皮卡丘"))
        #expect(pikachu.height == 0.4)
        #expect(pikachu.weight == 6.0)
        #expect(catalog.pokemon(id: 0) == nil)
        #expect(catalog.pokemon(id: 1026) == nil)
    }

    @Test func generationTitlesFollowEachSpecies() throws {
        let catalog = PokemonCatalog.shared
        let pikachu = try #require(catalog.pokemon(id: 25))
        #expect(pikachu.generationTitle(in: .en) == "GEN. I")
        #expect(pikachu.generationTitle(in: .zhHans) == "第一世代")
        #expect(pikachu.generationTitle(in: .ja) == "第1世代")
        let sprigatito = try #require(catalog.pokemon(id: 906))
        #expect(sprigatito.generationTitle(in: .en) == "GEN. IX")
        #expect(sprigatito.generationTitle(in: .zhHans) == "第九世代")
        #expect(sprigatito.generationTitle(in: .ja) == "第9世代")
    }

    @Test func officialSiteTextFillsUpstreamGaps() throws {
        // PokéAPI has no Japanese genus for Sprigatito; it comes from zukan.pokemon.co.jp.
        let sprigatito = try #require(PokemonCatalog.shared.pokemon(id: 906))
        #expect(sprigatito.japaneseGenus == "くさねこポケモン")
        #expect(!sprigatito.japaneseDescription.contains("より）"))
    }

    @Test func searchFindsEverySpeciesByAnyLanguageNameOrNumberInDexOrder() {
        let catalog = PokemonCatalog.shared
        for language in AppLanguage.allCases {
            for pokemon in catalog.entries {
                for query in [pokemon.englishName, pokemon.chineseName, pokemon.japaneseName, pokemon.number] {
                    let ids = catalog.search(query, language: language).map(\.id)
                    #expect(ids.contains(pokemon.id))
                    #expect(ids == ids.sorted())
                }
            }
            #expect(catalog.search("saur", language: language).map(\.id) == [1, 2, 3])
            #expect(catalog.search("Nidoran", language: language).map(\.id) == [29, 32])
            let numbered = catalog.entries.filter { $0.number.contains("25") }.map(\.id)
            #expect(Array(numbered.prefix(2)) == [25, 125])
            #expect(catalog.search("25", language: language).map(\.id) == numbered)
        }
    }

    @Test func systemCameraPromptHasAllTranslations() throws {
        for (locale, expectedWord) in [("en", "camera"), ("zh-Hans", "相机"), ("ja", "カメラ")] {
            let path = try #require(Bundle.main.path(forResource: locale, ofType: "lproj"))
            let localizedBundle = try #require(Bundle(path: path))
            let text = localizedBundle.localizedString(forKey: "NSCameraUsageDescription", value: nil, table: "InfoPlist")
            #expect(text.contains(expectedWord))
        }
    }
}
