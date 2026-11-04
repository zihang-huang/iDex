# Train and export the iDex classifier

The app already includes the locally trained EfficientNet-B0 **FP32** Core ML package. A normal Git clone includes the weights; building/running iDex needs no Python, API key, separate download or model-hosting account. See [the active model contract](../../iDex/Recognition/MODEL.md), [distribution notices](../../iDex/Recognition/MODEL_NOTICE.md) and [model-manifest.json](model-manifest.json).

These first-party scripts retain the bounded data/training/export workflow. Raw datasets, tensor checkpoints, generated predictions, device reports and rollback copies stay in ignored `artifacts/replacement/`; they are not part of the model upload. Reproducing the campaign requires the pinned source data plus a CUDA training environment. Re-exporting requires a matching locally held or newly trained tensor checkpoint.

## Data and training

### National Dex (1025 classes)

Every label-aware Python entry point accepts `--labels`; its default remains
`iDex/Recognition/pokemon_labels.json` (151 classes). The file defines both count
and logit order, including reversed ID order. Checkpoints embed the full list and
loaders/continuation/resume/selection reject mismatches. `make_labels.py` uses the
local PokéAPI CSV cache or downloads the same CSV used by the catalog builder;
it refuses any difference in the shipped first 151 records. Do not replace the
app's labels before the matching model is integrated.

Run these commands from the repository root, in the existing isolated environment.
They are the full acquisition/training sequence, **not commands run by the offline
tests**. Use a fresh artifact root to preserve the original campaign. PowerShell:

```powershell
$trainPython = 'D:\project\.venvs\idex-train\Scripts\python.exe'
$labels = 'scripts/replacement/labels-national.json'
$runRoot = 'artifacts/replacement-national'
$sources = "$runRoot/sources"
$manifest = "$runRoot/data/manifest.jsonl"
$checkpoint = "$runRoot/runs/efficientnet224/best.pt"

& $trainPython scripts/replacement/make_labels.py
& $trainPython scripts/replacement/acquire.py metadata --root $sources --labels $labels
& $trainPython scripts/replacement/acquire.py pretrained --root $sources --labels $labels
& $trainPython scripts/replacement/acquire.py data --dataset JJMack/pokemon-classification-gen1-9 --root $sources --labels $labels
& $trainPython scripts/replacement/acquire.py data --dataset keremberke/pokemon-classification --root $sources --labels $labels
& $trainPython scripts/replacement/acquire.py data --dataset sgtsaughter/pokemon-classification-images-151 --root $sources --labels $labels
& $trainPython scripts/replacement/acquire.py sprites --root $sources --labels $labels --delay 0.15 --attempts 6 --workers 8
& $trainPython scripts/replacement/acquire.py tcg --root $sources --labels $labels --delay 0.15 --attempts 8 --workers 8
& $trainPython scripts/replacement/acquire.py negatives --root $sources --labels $labels
& $trainPython scripts/replacement/data.py --root $runRoot --labels $labels --min-groups 5
& $trainPython scripts/replacement/refine_groups.py --root $runRoot --labels $labels --min-groups 5
& $trainPython scripts/replacement/audit.py --root $runRoot --labels $labels
& $trainPython scripts/replacement/freeze_eval_scope.py --root $runRoot --labels $labels
# Inspect the source receipts, conflicts, sheets and insufficient_groups.json first.
& $trainPython scripts/replacement/train.py train --arch efficientnet_b0 --labels $labels --manifest $manifest --sources $sources --out "$runRoot/runs/efficientnet224" --epochs 20 --batch 128 --max-minutes 600 --balanced-sampling
& $trainPython scripts/replacement/train.py predict --arch efficientnet_b0 --labels $labels --manifest $manifest --checkpoint $checkpoint --split val,ood_val --out "$runRoot/predictions/val.jsonl"
& $trainPython scripts/replacement/choose_candidate.py --labels $labels --checkpoint $checkpoint --predictions "$runRoot/predictions/val.jsonl" --out "$runRoot/selection.json"
# Selection is immutable. Only now open the reserved test.
& $trainPython scripts/replacement/train.py predict --arch efficientnet_b0 --labels $labels --manifest $manifest --checkpoint $checkpoint --split test_public,ood_test_public --selection "$runRoot/selection.json" --final --out "$runRoot/predictions/test.jsonl"
& $trainPython scripts/replacement/metrics.py summarize --labels $labels --predictions "$runRoot/predictions/test.jsonl" --output "$runRoot/reports/test.json" --replicates 1000
& $trainPython scripts/replacement/analyze_predictions.py --labels $labels --candidate "$runRoot/predictions/test.jsonl" --manifest $manifest --selection "$runRoot/selection.json" --out "$runRoot/reports/analysis"
```

Stop on any nonzero exit; do not proceed with a failed acquisition. `sprites` and
`tcg` cache complete API responses/pages and individual images. Rerunning the same
command resumes from those files; an interrupted individual transfer is retried.
Downloads reuse one keep-alive connection per thread (a fresh TLS tunnel through a
local proxy measured 4–10 s, a reused one ~0.65 s). `--workers N` warms the image
cache with N parallel downloads first; receipts, identity checks and samples are
still produced by the original ordered pass, so the output matches `--workers 1`.
`--delay` applies per worker. PokeAPI directories measured to decode below 64 px
(`sources.UNDERSIZED_DIRS`: generation I–II and the generation III–VII icons) are
recorded in `excluded.json` as `known_undersized_dir` without a download. Newer-game
sprites are 34-frame 512 px WebP/GIF animations (0.5–25 MB); only frame 0 is kept.
Transient 408/429/500/502/503/504 and network failures use bounded exponential
backoff. Receipts in each source's `downloads.jsonl` retain URL, bytes and SHA-256.
`samples.jsonl` retains source identities and derivation flags. Sprites are default
forms only: artwork/HOME normal and shiny, Showdown first frames, generation front
sprites; decoded images smaller than 64 px on either axis are excluded. TCG walks
all 250-card pages, filters single-national-number Pokémon cards, fetches
`images.small`, and creates a marked `card_art_crop` at x8–92%, y11–47%. This crop
is approximate for nonstandard/full-art layouts, not a verified object annotation.
The API still lists a few cards whose image the CDN no longer serves (e.g.
`ecard2-67`); a 404/410 on a card image is recorded in `tcg/excluded.json` as
`http_404`/`http_410` and skipped, while every other HTTP error still stops the stage.

JJMack metadata is fetched at revision
`959ff557b102fc3b4f912d0ca769273be5b9ca7f`; metadata/data ingestion reject another
revision. A stale metadata cache must be replaced deliberately before acquisition.
The `test`/`test2` ClassLabel entries are excluded; species outside the selected
labels retain the original unknown-input handling. Families (`pokeapi:id:family`)
and cards (`tcg:set-number`, full card + crop together) are merged with the existing
exact-pixel, mirrored pHash and foreground duplicate groups before splitting.

`insufficient_groups.json` records classes below `--min-groups` (default 5): three
or more groups still receive at least one train/val/test group; fewer than three
are train-only, including explicit zero-support records. Other classes continue.
Training requires some validation data and every requested class in train. A
train-only class has no held-out accuracy estimate. Test selection prioritizes
groups containing non-synthetic, non-sprite examples. This grouping does not
establish independent camera accuracy or eliminate all shared-artwork exposure.

Synthetic augmentation runs online only on retained transparent foregrounds,
with probability `.6` (`--synthetic-probability`, 0 disables it). It produces a
fixed-size RGB composite with 35–90% foreground scale, random position, ±15°
rotation, mild perspective, blur/brightness/contrast/color temperature, JPEG
quality40–90 and occasional screen-like grid/moiré. Other samples use the original
augmentation. A fixed Python RNG seed makes the synthetic module deterministic.
Default backgrounds are solid colors/gradients. To use COCO backgrounds, acquire
the **separate train-only** negatives with `acquire_oe.py --root $runRoot --labels
$labels`, review the receipt/sheet, then add `--background-manifest
"$runRoot/negative_train_manifest.jsonl"` to training. Frozen OOD validation/test
images cannot be backgrounds. No review completion receipt is fabricated.

Balanced sampling weights each image by its class frequency to the power `-.5`;
enable with `--balanced-sampling`, disable with `--no-balanced-sampling` (default
off for legacy compatibility). It does not silently change the batch size or
epoch/time budget. Resume checks sampling and augmentation settings as well as
the original model/manifest contract.

Metric reports include top1/top3/top5, accepted coverage/accuracy and unknown FAR,
plus source/generation slices. Generation comes from the committed
`iDex/Resources/pokemon-national.json`; unknown targets get an `unknown` slice.
An absent slice means no evaluated examples, not zero error. Online synthetic
training samples are not independent test samples; a synthetic metric slice only
exists when explicitly supplied predictions carry that source.

For bounded multi-checkpoint selection and final reporting, `finish.py --root
$runRoot --labels $labels --candidate $checkpoint --no-handoff` is an alternative
to the individual prediction/selection/report steps. Repeat `--candidate` to
compare validation candidates. The historical DenseNet baseline is optional:
missing/incompatible labels produce `reports/baseline-comparison.json` with an
explicit skip reason; same-label baselines still get paired diagnostics. The
original `.95` accepted-known precision / `.05` per-source unknown FAR constraints
remain; infeasible validation gives explicit unconditional abstention.

On Mac, export and validate the same labels/checkpoint in a fresh output folder:

```sh
python scripts/replacement/export.py --checkpoint /path/to/best.pt \
  --labels scripts/replacement/labels-national.json \
  --out artifacts/replacement-national/export --deployment iOS18
python scripts/replacement/fixtures.py --checkpoint /path/to/best.pt \
  --labels scripts/replacement/labels-national.json \
  --reference-checkpoint /path/to/best.pt \
  --manifest artifacts/replacement-national/data/manifest.jsonl \
  --out artifacts/replacement-national/fixtures
```

Without a Mac, `.github/workflows/export-model.yml` does the same on a GitHub Mac
runner: commit the checkpoint as `scripts/replacement/release/national-best.pt` on a
throwaway `model-export` branch and push it. The job converts FP32/FP16, builds
fixtures from the app's own bundled sprites (`ci_fixture_manifest.py`, so no training
photos are uploaded), runs the Swift parity checker with the FP32 package in both
roles against the checkpoint's PyTorch logits (CPU only, required; all compute units,
informational), writes the outcome as job annotations, and uploads
`national-classifier-export`. The regular build workflow ignores that branch.

The Apple harness derives fixed output count from the supplied labels and rejects
a shape/count mismatch; compare a national export against the same-label source
references, not the historical Kanto model. New exports use `NationalCandidate-*`
names; default-label exports retain `KantoCandidate-*`. No training, export,
physical-camera accuracy or hinge behavior is established by offline tests.

```powershell
& $trainPython -m pytest scripts/replacement -q -p no:cacheprovider
```

### Original 151-class campaign

Use a fresh artifact root. `acquire.py` fetches pinned data files/metadata without running dataset-provided code. Review [dataset provenance](references/dataset_research.md) and the source terms before use. The original campaign used TorchVision's ImageNet initialization, grouped the source images before splitting, quarantined conflicting labels, and mapped targets to the exact151 Kanto IDs. Public split scores do not certify independent camera performance.

```powershell
# Set this to your existing isolated CUDA environment; no machine-specific path is assumed.
$env:IDEX_TRAIN_PYTHON = 'C:\path\to\venv\Scripts\python.exe'
& $env:IDEX_TRAIN_PYTHON scripts/replacement/acquire.py metadata
& $env:IDEX_TRAIN_PYTHON scripts/replacement/acquire.py pretrained
& $env:IDEX_TRAIN_PYTHON scripts/replacement/acquire.py data --dataset sgtsaughter/pokemon-classification-images-151
& $env:IDEX_TRAIN_PYTHON scripts/replacement/acquire.py data --dataset keremberke/pokemon-classification
& $env:IDEX_TRAIN_PYTHON scripts/replacement/acquire.py data --dataset JJMack/pokemon-classification-gen1-9
& $env:IDEX_TRAIN_PYTHON scripts/replacement/acquire.py negatives
& $env:IDEX_TRAIN_PYTHON scripts/replacement/data.py
& $env:IDEX_TRAIN_PYTHON scripts/replacement/refine_groups.py
& $env:IDEX_TRAIN_PYTHON scripts/replacement/audit.py
& $env:IDEX_TRAIN_PYTHON scripts/replacement/freeze_eval_scope.py
& $env:IDEX_TRAIN_PYTHON scripts/replacement/train.py train --arch efficientnet_b0 --epochs 8 --max-minutes 35 --out artifacts/replacement/runs/efficientnet224
```

Inspect the acquisition and grouping receipts before training. The historical comparison helpers can use optional reference artifacts, but those artifacts are not app dependencies or part of the upload. Training/selection choices must use validation only; reserve the final group-partitioned test before opening predictions. Use [CAMERA_TEST_PROTOCOL.md](CAMERA_TEST_PROTOCOL.md) for an independent capture study. `run_candidates.ps1`/`followup.ps1` are optional recorded multi-model experiment wrappers, not an unbounded sweep or required app-build step.

The selected checkpoint came from an EfficientNet-B0 continuation of at most12 additional epochs at learning rate.0001, after the initial8-epoch run. Its exact checkpoint and frozen-manifest digests are recorded in `model-manifest.json`. The separate outlier-exposure branch was diagnostic and was not selected. The original observed Windows package versions are in `requirements-windows.txt`; install only into a separate compatible environment, not over another experiment.

## Export on Mac

Use an isolated Python3.11 environment with `requirements-mac.txt`. The recorded tested stack uses coremltools9.0 and torch2.14.1; the converter warns that torch is newer than its tested versions, so numerical parity remains mandatory for a new checkpoint.

```sh
python scripts/replacement/export.py --checkpoint /path/to/your/checkpoint.pt \
  --out artifacts/replacement/new-export --deployment iOS18
```

The loader uses installed TorchVision, `torch.load(weights_only=True)`, strict state-dict keys and semantic label-order equality. It does not load an arbitrary serialized model class or fetch remote implementation code. Normalization is embedded once. Export produces separate FP32 and FP16 diagnostic packages in a fresh folder; it never modifies the bundled default. The published package is the verified FP32 result. Do not choose another precision based only on file size.

## Numerical/device validation

Follow [apple/README.md](apple/README.md). Generate your own authorized validation fixtures, keep images out of the Git commit, and compare source logits on exact Apple-prepared RGB. This checks conversion separately from held-out recognition and unknown-input evaluation. Core ML compute-unit options are permissions, not evidence of actual ANE placement.

The app's unit tests cover the bundled checkpoint identity/FP32 output, known sample recognition, label coverage, and blank-image abstention. Keep model/labels/preprocessing together when replacing a trained artifact. Use a disposable checkout and new export folder for experiments; the active package should change only after a deliberate selection and validation.
