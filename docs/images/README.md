# README visuals

The banner and social preview reuse iDex's existing app icon and bundled Press Start 2P font. They are decorative graphics, not screenshots. The icon's vector source is in [scripts/icon](../../scripts/icon/README.md); font and Pokémon credits remain in [asset attribution](../../iDex/Catalog/ATTRIBUTION.md).

| Asset | Size | Use |
| --- | --- | --- |
| [banner.png](banner.png) | 1600 × 560 | README header |
| [social-preview.png](social-preview.png) | 1280 × 640 | Optional repository social preview |

Regenerate both on macOS from the repository root:

```sh
swift scripts/readme/generate_assets.swift
```

## Screenshots

The seven PNGs in [docs/screenshots](../screenshots) are unedited UI-test attachments captured using Xcode 27.1 and the iPhone Duo iOS 27.1 simulator. The original five English and Chinese captures are from 24 October 2026; the Japanese Charizard record is from 25 October 2026; the Traditional Chinese Charizard record was captured with Xcode 27.2 and the iOS 27.2 simulator on 6 November 2026. They show the cover display, with audio muted. The scanner sample is explicitly labelled in the app and passes through real bundled-model inference. The Chinese, Traditional Chinese, and Japanese Charizard records are browsed from the archive, not camera recognition results. These captures do not validate a physical camera or hinge transition.

The English [README](../../README.md), [简体中文](../../README.zh-CN.md), [繁體中文](../../README.zh-TW.md), and [日本語](../../README.ja.md) share these assets and link to each other at the top of each file.

To capture a fresh set, run from the repository root with the simulator folded. Choose a new result-bundle path if one already exists:

```sh
xcodebuild test -project iDex.xcodeproj -scheme iDex \
  -destination 'platform=iOS Simulator,name=iPhone Duo' \
  -parallel-testing-enabled NO \
  -only-testing:iDexUITests/iDexUITests/testSampleIsIdentifiedByBundledModel \
  -only-testing:iDexUITests/iDexUITests/testRecordFillsCoverDisplayAndCloses \
  -only-testing:iDexUITests/iDexUITests/testCatalogSearchAcceptsEnglishChineseAndDexNumber \
  -resultBundlePath artifacts/readme/Screenshots.xcresult

python3 scripts/readme/export_screenshots.py artifacts/readme/Screenshots.xcresult
```

All three selected tests passed for the original captures. The Japanese record comes from `testRecordFillsCoverDisplayAndCloses` in `artifacts/japanese-localization/ui-cover.xcresult`; all four selected UI tests passed in that run. The command above now also exports the Japanese and Traditional Chinese records from the cover-record test. Result bundles and build logs stay under ignored `artifacts/`; the selected screenshots live in `docs/` so GitHub can display them.
