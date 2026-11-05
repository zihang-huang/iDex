[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md)

![iDex — Gotta scan ’em all.](docs/images/banner.png)

# iDex

A pocket Pokédex for iPhone Duo. Point, scan, and pretend Professor Oak gave you a research grant.

Native SwiftUI · English / 简体中文 / 日本語 · On-device Core ML

## About this edition

This is rom0718's upgraded edition of [iDex by Zihang Huang](https://github.com/zihang-huang/iDex). The original app, its design and its code are Zihang Huang's work; this fork builds on them and keeps the original MIT license and notices. What this edition adds:

- **The full National Pokédex.** From the original 151 Kanto species to all 1,025 (generations I–IX). Data comes from PokéAPI; Chinese and Japanese entries missing there come from the official Pokémon sites. No. 650 onward use Pokémon Showdown's Gen 5-style sprites.
- **A searchable archive.** Search by name, number or type, filter by generation, keep generation headers in view, switch between grid and list, and reopen at the entry you were viewing.
- **A cry button.** Play a Pokémon's cry from its record, next to Read aloud.
- **A 1,025-species recognition model.** EfficientNet-B0 retrained on game sprites and artwork, trading card images and three public datasets. On the held-out test images it names the right Pokémon 93.8% of the time (cards 89.6%); real camera accuracy may be lower and has not been measured yet. See [model notes](iDex/Recognition/MODEL.md).
- **Strict mode and Fun mode.** Settings → Recognition mode; see “Is it Professor Oak accurate?” below.
- **Updated credits.** Settings → Credits and the documentation list every new data, sprite, audio and training source.
- **Cloud builds.** GitHub Actions workflows build and test the app and export the model on a macOS runner.

## A little field trip

| Scan it | Read in English | 简体中文 | 日本語 |
| :---: | :---: | :---: | :---: |
| <img src="docs/screenshots/scanner-result-en.png" width="200" alt="English scanner identifying the bundled Pikachu sample"> | <img src="docs/screenshots/record-en.png" width="200" alt="Pikachu record with types, dimensions and field notes"> | <img src="docs/screenshots/record-zh.png" width="200" alt="Charizard record in Simplified Chinese"> | <img src="docs/screenshots/record-ja.png" width="200" alt="Charizard record in Japanese"> |

No wild Pokémon were inconvenienced.

[Before the scan](docs/screenshots/scanner-sample-en.png) · [Search the archive](docs/screenshots/catalog-search-en.png)

## What's in the bag?

- **All 1,025 Pokémon of the National Pokédex.** Pixel sprites, stats, field notes, and cries, with a searchable archive by generation.
- **Scan a photo or use the camera.** Recognition runs on your iPhone; photos stay in memory.
- **Unfold for more room.** The archive sits beside the scanner on the inner display.
- **English, 简体中文, and 日本語.** All 1,025 entries include localized names, descriptions, types, and stats. Search by name, number, or type; listen using installed system voices.
- **A local discovery log.** Your progress survives closing the app. Your research grant remains imaginary.

## Choose your language

Open **Settings → Language** and choose **English**, **简体中文**, or **日本語**. The first launch follows your preferred supported system language, and your selection is saved. Controls, accessibility labels, Pokédex entries, and narration follow the selected language. Names are searchable in all three languages; type search uses the selected language. Narration uses installed iOS voices.

## Take it for a spin

You'll need **Xcode 27.1** and **iOS 27+**. Hinge observation uses iOS 27.1 APIs.

```sh
open iDex.xcodeproj
```

Select **iDex → iPhone Duo**, then Run. The trained FP32 model is included in this Git repository; clone normally, with no LFS or separate model download. No packages, API keys, servers, or runtime downloads to configure. In Simulator, tap **Scan** to identify the sample Pikachu. On a device, allow camera access or import a photo.

Run the tests:

```sh
xcodebuild test -project iDex.xcodeproj -scheme iDex \
  -destination 'platform=iOS Simulator,name=iPhone Duo'
```

## Is it Professor Oak accurate?

Professor Oak has declined to comment. The model knows all 1,025 species and can still mistake unrelated objects for Pokémon. Scores aren't calibrated probabilities; low-confidence guesses don't automatically become discoveries or trigger narration. Real camera accuracy and physical hinge behavior still need device testing.

**Strict mode or Fun mode?** There is one trained model. The two modes in Settings → Recognition mode differ only in how sure it must be before a scan counts as identified (recorded as discovered and read aloud). Every scan still shows its best match.

| | Strict mode (default) | Fun mode (original iDex setting) |
| --- | --- | --- |
| Rule | Score ≥ 95% at softmax temperature 0.75 and top-two logit margin ≥ 3, chosen on validation data | Score ≥ 25% and logit margin ≥ 0.5 |
| Test images identified automatically | 75.8% | 93.4% |
| …of which correct | 99.7% | 97.4% |
| Everyday photos mistaken for a Pokémon | 3.1% | 40.6% |

Strict mode keeps your discovery log clean but asks for rescans more often. Fun mode identifies almost anything you point it at, including things that are not Pokémon. The figures come from held-out test images (12,449 Pokémon images and 64 COCO everyday photos), not from real camera use.

## Under the hood

SwiftUI, AVFoundation, Core ML, and system speech. Everything runs locally.

[Development guide](docs/development.md) · [Model notes](iDex/Recognition/MODEL.md) · [Performance](docs/performance.md) · [Screenshots & graphics](docs/images/README.md)

## License

iDex's original app source code and supporting scripts use the [MIT License](LICENSE), copyright (c) 2026 Zihang Huang. See [NOTICE.md](NOTICE.md) for scope and exclusions.

The packaged model is excluded; contributor trained-model rights are offered under CC BY-NC-SA 4.0 as described in the [model notice](iDex/Recognition/MODEL_NOTICE.md). Pokémon content and external training datasets are also excluded. See [asset credits](iDex/Catalog/ATTRIBUTION.md); bundled fonts retain the [Press Start 2P](iDex/Resources/Fonts/PressStart2P-OFL.txt) and [Fusion Pixel](iDex/Resources/Fonts/FusionPixel-OFL.txt) OFL licenses.

## Thanks, humans

Original app: [Zihang Huang](https://github.com/zihang-huang/iDex). Sprites: [Pokémon Database](https://pokemondb.net/sprites) and, from No. 650, [Pokémon Showdown](https://play.pokemonshowdown.com/sprites/gen5/). Data and cries: [PokéAPI](https://github.com/PokeAPI/pokeapi); missing Chinese and Japanese entries: [pokemon.cn](https://www.pokemon.cn/play/pokedex/) and [ポケモンずかん](https://zukan.pokemon.co.jp/). Training images: [PokeAPI sprites](https://github.com/PokeAPI/sprites), [Pokémon TCG API](https://pokemontcg.io/), three Hugging Face datasets and COCO backgrounds ([model notice](iDex/Recognition/MODEL_NOTICE.md)). Model: locally trained EfficientNet-B0 (FP32), built with [TorchVision](https://docs.pytorch.org/vision/stable/models/efficientnet.html). Fonts: Press Start 2P and Fusion Pixel (SIL OFL 1.1).

[Full asset credits](iDex/Catalog/ATTRIBUTION.md) · [Model provenance](iDex/Recognition/MODEL.md)

An unofficial fan project. Pokémon belongs to Nintendo, Creatures, GAME FREAK, and The Pokémon Company. iDex is not affiliated with or endorsed by them.
