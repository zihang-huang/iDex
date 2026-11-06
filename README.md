[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md) | [日本語](README.ja.md)

![iDex — Gotta scan ’em all.](docs/images/banner.png)

# iDex

A pocket Pokédex for iPhone Duo. Point, scan, and pretend Professor Oak gave you a research grant.

Native SwiftUI · English / 简体中文 / 繁體中文 / 日本語 · On-device Core ML

## A little field trip

| Scan it | Read in English | 简体中文 | 日本語 |
| :---: | :---: | :---: | :---: |
| <img src="docs/screenshots/scanner-result-en.png" width="200" alt="English scanner identifying the bundled Pikachu sample"> | <img src="docs/screenshots/record-en.png" width="200" alt="Pikachu record with types, dimensions and field notes"> | <img src="docs/screenshots/record-zh.png" width="200" alt="Charizard record in Simplified Chinese"> | <img src="docs/screenshots/record-ja.png" width="200" alt="Charizard record in Japanese"> |

No wild Pokémon were inconvenienced.

[Before the scan](docs/screenshots/scanner-sample-en.png) · [Search the archive](docs/screenshots/catalog-search-en.png)

## What's in the bag?

- **151 Kanto Pokémon.** Pixel sprites, stats, field notes, and cries.
- **Scan a photo or use the camera.** Recognition runs on your iPhone; photos stay in memory.
- **Unfold for more room.** The archive sits beside the scanner on the inner display.
- **English, 简体中文, 繁體中文, and 日本語.** All 151 entries include localized names, descriptions, types, and stats. Search by name, number, or type; listen using installed system voices.
- **A local discovery log.** Your progress survives closing the app. Your research grant remains imaginary.

## Choose your language

Open **Settings → Language** and choose **English**, **简体中文**, **繁體中文**, or **日本語**. The first launch follows your preferred supported system language, and your selection is saved. Controls, accessibility labels, Pokédex entries, and narration follow the selected language. Names are searchable in all four languages; type search uses the selected language. Narration uses installed iOS voices.

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

Professor Oak has declined to comment. The model knows the original 151 species and can still mistake unrelated objects for Pokémon. Scores aren't calibrated probabilities; low-confidence guesses don't automatically become discoveries or trigger narration. Real camera accuracy and physical hinge behavior still need device testing.

## Under the hood

SwiftUI, AVFoundation, Core ML, and system speech. Everything runs locally.

[Development guide](docs/development.md) · [Model notes](iDex/Recognition/MODEL.md) · [Performance](docs/performance.md) · [Screenshots & graphics](docs/images/README.md)

## License

iDex's original app source code and supporting scripts use the [MIT License](LICENSE), copyright (c) 2026 Zihang Huang. See [NOTICE.md](NOTICE.md) for scope and exclusions.

The packaged model is excluded; contributor trained-model rights are offered under CC BY-NC-SA 4.0 as described in the [model notice](iDex/Recognition/MODEL_NOTICE.md). Pokémon content and external training datasets are also excluded. See [asset credits](iDex/Catalog/ATTRIBUTION.md); bundled fonts retain the [Press Start 2P](iDex/Resources/Fonts/PressStart2P-OFL.txt) and [Fusion Pixel](iDex/Resources/Fonts/FusionPixel-OFL.txt) OFL licenses.

## Thanks, humans

Sprites: [Pokémon Database](https://pokemondb.net/sprites). Data and cries: [PokéAPI](https://github.com/PokeAPI/pokeapi). Model: locally trained EfficientNet-B0 (FP32), built with [TorchVision](https://docs.pytorch.org/vision/stable/models/efficientnet.html). Fonts: Press Start 2P and Fusion Pixel (SIL OFL 1.1).

[Full asset credits](iDex/Catalog/ATTRIBUTION.md) · [Model provenance](iDex/Recognition/MODEL.md)

An unofficial fan project. Pokémon belongs to Nintendo, Creatures, GAME FREAK, and The Pokémon Company. iDex is not affiliated with or endorsed by them.
