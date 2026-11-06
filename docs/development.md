# iDex development guide

[← Back to the README](../README.md)

A native pocket Pokédex for iPhone Duo, available in English, Simplified Chinese, Traditional Chinese, and Japanese. Built with SwiftUI, AVFoundation, Core ML, and local speech synthesis. An unofficial fan project.

## Run

Open `iDex.xcodeproj` in Xcode 27.1, select the **iDex** scheme and **iPhone Duo** simulator, then Run. There are no packages, API keys, server, or runtime downloads to configure. The app target supports iOS 27 and newer; hinge observation uses iOS 27.1 when available.

On a physical iPhone, iDex requests camera access and starts the viewfinder. Tap **Scan** to retain the latest camera frame immediately, then run recognition on that frozen image. A sweeping beam and looping scan chime accompany inference; the result appears as soon as recognition finishes. The camera stops after capture. The viewfinder reveals the matched Pokémon's pixel sprite, name, and model score. Tap **Rescan** to clear the result and restore live framing, then **Scan** to capture the next target. Camera and Photo Library controls also switch sources; importing a photo immediately runs the same scan sequence. Photos remain in memory. The sweep respects Reduce Motion and the chime respects the sound setting.

In Simulator, iDex starts with an explicitly labelled Pikachu sample because there is no rear camera. **Scan** runs that sprite through the actual bundled Core ML model; **Rescan** restores the labelled sample so the full flow can be repeated.

Unfolding reveals the archive on the left. The viewfinder uses a fixed 466-point panel anchored to the right edge, with its own fixed 320-point square at y=179. The 951×669 expanded layout adds a 466-point left panel and 19-point hinge, preserving the scanner's right-edge inset, vertical position, and size from the 466×678 cover display. The camera controller lives above both layout states. UIKit's `UIHingeInteraction` observes hardware hinge updates, gates the interior reveal, and plays the opening sound; it never requests a rotation. The layout also requires enough width and height for both panels, so rotating the closed cover cannot reveal a cramped archive.

`DexSceneDelegate` hosts the SwiftUI interface in a controller that explicitly requests `prefersInterfaceOrientationLocked`. Duo's inner display ignores supported-orientation masks by default, so the portrait declarations alone cannot disable rotation. The scene delegate supplies the iOS 27 orientation policy, while the explicit lock prevents rotation when the app fills the display. Record, catalog, and settings use full-screen hosting controllers with the same lock; standard SwiftUI sheet controllers release it. Scene activation and deactivation resume and suspend the shared scanner state. All app screens hide the status bar and request hidden persistent system overlays; iOS can still reveal the home indicator for system gestures.

Scan results stay in the viewfinder on both displays, keeping **Rescan** accessible. **Open record** shows the entry in a dismissible full-screen record while closed and gives access to the archive. Opening the device dismisses that compact record so the inside becomes visible. Search in any supported language by name, dex number, or localized type. Browse records with the arrow buttons, switch field notes to base stats, and use Read/Stop for narration.

Settings offers English / 简体中文 / 繁體中文 / 日本語 and a sound toggle. Japanese includes names, genera, and descriptions for all 151 species, localized types and stats, and `ja-JP` narration. The catalog rebuild uses PokéAPI Japanese language ID 11 (kanji text). Traditional Chinese uses PokéAPI language ID 4 (`zh-Hant`) for names, genera, and descriptions, Taiwan-usage interface copy, and `zh-TW` narration; `zh-Hant`, `zh-TW`, `zh-HK`, and `zh-MO` system preferences select it. Names are searchable across all four languages, while type search follows the selected language. Names, types, notes, controls, camera privacy text, pixel fonts, and speech use the selected language. The first launch follows the system language. Language, sound, last-viewed species, and discovered species IDs persist locally. Photos remain in memory, are released when their scan result appears, and are never uploaded or written to an app photo archive. System speech uses installed voices; a desired voice may need to be installed in iOS Settings for offline speech.

## Recognition scope

The app includes a roughly **17 MB FP32 EfficientNet-B0 Core ML model for the original 151 Kanto species**. It computes predictions on the device and always selects the highest-ranked Pokémon. A top score of at least 25% and a logit margin of at least 0.5 allow automatic discovery and narration. Weaker results show the top Pokémon's sprite, labelled “Best match” and “Low confidence”, with its actual model score; they are not automatically marked discovered or narrated.

This is a 151-class model without a trained unknown/background class. Unrelated objects and non-Kanto Pokémon can still produce false matches. Camera accuracy across toys, cards, lighting, and viewpoints needs physical-device evaluation. The model score is not a calibrated probability. See [model provenance and reproduction](../iDex/Recognition/MODEL.md).

The app target uses Swift `-O` optimization with whole-module compilation and C/Objective-C optimization level 2 in both Debug and Release. Optimized builds can make debugger stepping and local-variable inspection less precise. Xcode’s SwiftUI previews require temporarily selecting `-Onone` and `singlefile` compilation.

Photo preparation runs outside the main actor and requests a thumbnail of approximately four megapixels or less before making the centered, upright 1200px square. Camera capture prefers native YUV frames, converting only the retained scan frame to RGB. Static texture drawing batches dots and lines, while catalog searches reuse prepared numbers and localized types. See [performance measurements and reproduction](performance.md).

Confirmed scans play the matched Pokémon's cry, then narrate its entry after the cry finishes. All 151 species have a bundled cry; low-confidence matches do not automatically play one or narrate. Cry playback follows the existing sound toggle. Audio session configuration, player preparation, waveform generation, cry decoding, and speech setup run on a dedicated serial queue. The audio player and voices are reused, and stopping a scan does not initialize an unused speech service. Audio never holds up capture or the completed result. Mute, backgrounding, and newer requests cancel pending playback even while native audio setup is in progress.

## Tests and visual checks

Run Product → Test, or:

```sh
xcodebuild test -project iDex.xcodeproj -scheme iDex \
  -destination 'platform=iOS Simulator,name=iPhone Duo'
```

The tests exercise real bundled-model inference, the selected FP32 model contract and known-image rankings, and blank-image best guesses without automatic discovery, catalog completeness, every sprite, all four font faces, English, Simplified Chinese, Traditional Chinese, and Japanese search and prompts, layout continuity, language persistence, discovery display, and archive selection. The UI tests explicitly mute audio to keep automated runs quiet.

`ContentView.swift` contains named SwiftUI previews at the Duo cover and expanded dimensions. The physical camera and an actual fold transition still require device testing; rendered expanded previews and geometry tests do not prove physical continuity.

Home-indicator hiding is an iOS preference, not a guarantee. The simulator still displays the indicator in the catalog after idle despite the hosting controller returning `true` for `prefersHomeIndicatorAutoHidden`; scanner and record snapshots show it hidden. Physical-device confirmation is still required.

Duo exposes two integrated displays. To capture its folded cover screen, specify `--display=1`; the default screenshot may select the inactive interior display and return black.

```sh
xcrun simctl io booted screenshot --display=1 /tmp/idex-cover.png
```

## Assets and attribution

- [Pokémon Database sprites](https://pokemondb.net/sprites): all 151 Black/White pixel sprites bundled offline.
- [PokéAPI](https://github.com/PokeAPI/pokeapi): species names, localized flavor text, dimensions, types, and stats.
- [PokéAPI cries](https://github.com/PokeAPI/cries): all 151 species' latest cries, pinned and converted to mono PCM WAV for offline playback. Regenerate with `python3 scripts/audio/build_cries.py` (development requires `ffmpeg`).
- Press Start 2P and Fusion Pixel: bundled Latin, Simplified Chinese, Traditional Chinese, and Japanese pixel fonts under SIL OFL 1.1, with license files.
- Locally trained EfficientNet-B0 FP32 is the user-selected default. Its exact checkpoint, parity results, public-data limits and rollback are in [MODEL.md](../iDex/Recognition/MODEL.md).
- Physical-device inspiration: [Stuff's DIY Pokédex article](https://stuff.co.za/2026/04/15/the-pokedex-is-real-and-fully-functional-but-youd-have-to-build-your-own/) and [Pokebattler's Pokédex reference](https://articles.pokebattler.com/2018/08/30/pogo-pokedex-by-the-numbers/).

See [catalog attribution](../iDex/Catalog/ATTRIBUTION.md), [model notes](../iDex/Recognition/MODEL.md), and `scripts/` for reproducible catalog, model, and app-icon generation. Pokémon and related characters belong to Nintendo, Creatures, GAME FREAK, and The Pokémon Company. iDex is not affiliated with or endorsed by them.
