#!/usr/bin/env python3
"""Export the README's unedited screenshots from an Xcode UI-test result."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
if len(sys.argv) != 2:
    raise SystemExit("Usage: python3 scripts/readme/export_screenshots.py PATH.xcresult")

names = {
    "scanner-sample-en": "scanner-sample-en.png",
    "pikachu-scanner-result": "scanner-result-en.png",
    "pikachu-recognition": "record-en.png",
    "record-cover-zhHans": "record-zh.png",
    "record-cover-ja": "record-ja.png",
    "record-cover-zhHant": "record-zh-TW.png",
    "catalog-english-search": "catalog-search-en.png",
}
destination = root / "docs/screenshots"
destination.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix="idex-screenshots-") as directory:
    subprocess.run([
        "xcrun", "xcresulttool", "export", "attachments", "--path", sys.argv[1],
        "--output-path", directory,
    ], check=True)
    manifest = json.loads((Path(directory) / "manifest.json").read_text())
    selected = {}
    for test in manifest:
        for attachment in test["attachments"]:
            label = attachment["suggestedHumanReadableName"].split("_0_")[0]
            if label in names and not attachment["isAssociatedWithFailure"]:
                selected[label] = Path(directory) / attachment["exportedFileName"]
    if missing := names.keys() - selected.keys():
        raise SystemExit(f"Missing successful screenshot attachments: {sorted(missing)}")
    for label, filename in names.items():
        shutil.copyfile(selected[label], destination / filename)
        print(f"Wrote docs/screenshots/{filename}")
