# iDex trained image classifier

iDex bundles a locally trained **EfficientNet-B0 FP32 Core ML model** for all **1,025 species of the National Pokédex**. The complete package is tracked in Git at `NationalClassifier.mlpackage`; a normal clone or GitHub source ZIP includes it. The app performs inference offline and does not download weights or upload photos at runtime. It replaced the original 151-class Kanto model on 5 November 2026; that model remains in Git history.

## Artifact and contract

- Training checkpoint SHA-256: `2022deef65a694f9ce51701832c9793574dbc4c62bf6ffd6258725d22a32b5fe` (embedded as `checkpoint_sha256` metadata).
- Training manifest SHA-256: `a6ce4a0fb819b273d8a1593acc37bc90710f762949665088a63c34e06e612d82` (embedded as `manifest_sha256`).
- Packaged weights SHA-256: `d86a078716426ec852f5eac740f3a1397e08144591eaa3cfd6a49e5013a9954f`.
- Model spec SHA-256: `d0f2fe5029a60b5932c796796ed7b4d13e04bf346055428a54060798df803472`.
- Package: 21,332,447 bytes across three files. Largest file: 21,208,896 bytes. Regular Git storage is used, with binary attributes and no LFS filter.
- Implementation/initialization: TorchVision EfficientNet-B0, initialized from its ImageNet-1K weights and fine-tuned locally for 20 epochs. This is trained for iDex, not a claim that the architecture or every input asset originated here. See [model and dataset notices](MODEL_NOTICE.md).
- Input: `image`, fixed 224×224 RGB. ImageType scales by `1/255`; channelwise ImageNet normalization is embedded exactly once (mean `.485,.456,.406`, std `.229,.224,.225`).
- Output: `logits`, FP32 `[1,1025]` raw finite scores, in exact `pokemon_labels.json` order. No temperature or softmax is embedded.
- Label-file SHA-256: `8997df2be5630e1af2f5e77019dbda51170732cb5c205e94828a17cb1cb9faa1`; IDs 1…1025 in order, identical to `scripts/replacement/labels-national.json`. The first 151 records equal the Kanto model's labels.
- The export does not embed a label hash or production descriptions; the package's description still reads "experimental". `SelectedModelTests` pins the checkpoint, manifest and bundled-label hashes instead.

The machine-readable record is [model-manifest.json](../../scripts/replacement/model-manifest.json). Verify a downloaded model from the repository root:

```sh
shasum -a 256 iDex/Recognition/NationalClassifier.mlpackage/Data/com.apple.CoreML/weights/weight.bin
```

## Runtime behavior

Photo import corrects orientation, composites alpha onto white, bounds thumbnail area to approximately4.2 megapixels, and produces a centered square no larger than1200px. The classifier creates a BGRA-backed image feature with RGB model semantics and `scaleFill` at224px. Camera processing rotates the retained frame and takes a centered square. Normalization is not repeated in Swift.

`PokemonClassifier` serializes loading and inference in an actor. Physical devices use `.all`; Simulator uses `.cpuOnly`. The app offers the top three results and accepts an automatic discovery/narration only when the first softmax score and the first/second raw-logit margin both reach the threshold chosen in Settings (`RecognitionThreshold`, stored as `idex.recognitionThreshold`):

| Threshold | Softmax temperature | Minimum score | Minimum raw margin | Origin |
| --- | --- | --- | --- | --- |
| Strict mode (default, `strict`) | 0.75 | .95 | 3 | Chosen on the national model's validation split |
| Fun mode (`relaxed`) | 1 | .25 | .5 | The original iDex heuristic |

The displayed score uses the same temperature as the chosen threshold; the margin always uses raw logits. A new threshold applies from the next scan. Other results remain best guesses. Neither tier is a trained unknown detector or calibrated probability. There is no background class; unrelated objects can still be accepted, far more often in Fun mode.

## Validation and limits

Data were split by source group (shared artwork, card and photo groups never cross splits). The selected checkpoint had the best validation top-1 (0.9437, epoch 20). The strict threshold was chosen on validation data only: the highest known-class coverage with at least 95% accepted precision and at most 5% false acceptance of COCO photos (validation: 76.7% coverage, 99.8% accepted accuracy, 4.7% false acceptance).

Frozen public test split (12,449 known images, 64 COCO unknowns), evaluated once after selection:

| Measure | Result |
| --- | --- |
| Top-1 / top-3 / top-5 | 93.8% (95% CI 93.3–94.3%) / 97.1% / 97.9% |
| Macro F1 | 0.917 |
| Strict mode: coverage / accepted accuracy / unknown false acceptance | 75.8% / 99.7% / 3.1% |
| Fun mode: coverage / accepted accuracy / unknown false acceptance | 93.4% / 97.4% / 40.6% |
| Top-1 by source | game sprites 98.3%, community image datasets 95.3–96.3%, trading cards 89.6% |
| Top-1 by generation | I 96.0%, II 91.9%, III 93.3%, IV 93.9%, V 94.1%, VI 89.7%, VII 89.6%, VIII 91.2%, IX 89.5% |

Test images come from the same kinds of sources as training (game art, cards, collected photos), so they are not an independent camera test. Plush toys, figures, screen photos and real lighting have not been measured; the 64-image unknown set is small. Later generations have far fewer training images (about 19–37 per species for generations VI–IX against 164 for generation I).

The Core ML FP32 package passed 258 source-logit fixtures on a GitHub-hosted macOS 27.0.1 runner under both `.all` and `.cpuOnly` (`.github/workflows/export-model.yml`, run 41946529839): no missing or failed fixtures, no top-1 mismatches, worst absolute error 6.2e-05. Physical-iPhone parity, latency and energy have not been measured for this model.

## Build and reproduce

Xcode27.1 and the existing iDex scheme compile the model automatically. No API key, server, model-hosting service, or separate weight download is required. The model-format minimum iOS18 is compatible with the app's iOS27+ floor; no additional older-phone support is implied.

Acquisition, training, evaluation and export tools are in [scripts/replacement](../../scripts/replacement/README.md). The trained tensor checkpoint, raw training images and evaluation predictions are not distributed in Git. The Mac export runs in CI when a branch named `model-export` carries the checkpoint at `scripts/replacement/release/national-best.pt`; locally on a Mac:

```sh
python scripts/replacement/export.py --checkpoint /path/to/national-best.pt \
  --labels scripts/replacement/labels-national.json \
  --out artifacts/replacement/export --deployment iOS18
xcrun coremlc compile iDex/Recognition/NationalClassifier.mlpackage /tmp/idex-model-compiled
```

Export writes fresh FP32 and FP16 diagnostic packages and never overwrites the app package. Only the verified FP32 package is selected for the app.
