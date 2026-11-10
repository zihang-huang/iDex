# Repository Guidelines

## Project Structure & Module Organization

iDex is a native, bilingual SwiftUI Pokédex for iPhone Duo. The app supports iOS 27+; hinge observation uses iOS 27.1 APIs.

- `iDex/iDexApp.swift` and `ContentView.swift`: app entry and scanner composition.
- `iDex/Interface/`: views, device styling, Duo geometry, and `DexStore` state.
- `iDex/Services/`: camera capture, sound, and speech.
- `iDex/Catalog/` and `Recognition/`: catalog types, classifier actor, model, labels, and provenance.
- `iDex/Resources/` and `Assets.xcassets/`: bilingual catalog, sprites, fonts, privacy strings, and app icons.
- `iDexTests/`: unit and inference tests; `iDexUITests/`: interaction tests.
- `scripts/`: catalog, model, and icon regeneration tools.

## Build, Test, and Development Commands

Use Xcode 27.1. No external packages, API keys, or server are required to run the app.

```sh
open iDex.xcodeproj
xcodebuild build -project iDex.xcodeproj -scheme iDex \
  -destination 'platform=iOS Simulator,name=iPhone Duo'
xcodebuild test -project iDex.xcodeproj -scheme iDex \
  -destination 'platform=iOS Simulator,name=iPhone Duo'
```

In Xcode, select the **iDex** scheme and **iPhone Duo**, then Run or Product → Test. Simulator starts with a labelled sample that uses real model inference.

Run `python3 scripts/catalog/build_catalog.py` to regenerate catalog resources and `swift scripts/icon/generate_icon.swift` to redraw the icon. For model conversion dependencies and verification, follow `iDex/Recognition/MODEL.md`.

## Coding Style & Naming Conventions

Match existing Swift style: four-space indentation, `UpperCamelCase` types, `lowerCamelCase` members, and filenames matching their primary type. Keep UI state on `@MainActor` and inference inside `PokemonClassifier`. Use the existing `AppLanguage.text` helpers for English, Simplified Chinese, Japanese, and Traditional Chinese (Taiwan usage) copy. No formatter or linter configuration is checked in; use Xcode formatting and `git diff --check`.

## Testing Guidelines

Use Swift Testing (`@Test`, `#expect`) for unit tests and XCTest (`test…` methods) for UI tests. Name tests after observable behavior. No numeric coverage threshold is configured. Cover affected catalog, language, recognition, persistence, or layout behavior; retain blank-image abstention checks. Keep UI automation audio muted. Validate both cover and expanded layouts for UI changes, and report physical-camera or hinge behavior separately from simulator evidence.

## Commit & Pull Request Guidelines

Follow the history's short, imperative subjects, such as `Align scanner layout with display geometry`. Keep commits focused. PRs should explain the change, link related issues when applicable, report validation and device limitations, and include screenshots for UI changes.

## Privacy & Asset Integrity

Keep recognition offline and photos in memory. Never automatically discover or narrate uncertain matches. Preserve asset attribution, font licenses, and model-label ordering. Exclude caches, `DerivedData/`, `artifacts/`, and `.xcresult` bundles from commits.
