"""Freeze a stricter public comparison scope by provenance, before test prediction.

Exclude every positive test group touching a named incumbent training source.
Remaining sgtsaughter examples still have unknown baseline exposure, not certified
independence. Known-source test outputs remain explicitly diagnostic only.
"""
import argparse
from labels import add_labels, read_labels
import collections
import hashlib
import json
from pathlib import Path

parser=argparse.ArgumentParser(); add_labels(parser)
parser.add_argument('--root',type=Path,default=Path('artifacts/replacement'))
args=parser.parse_args(); labels=read_labels(args.labels)
root=args.root;out=root/'evaluation_scope.json'
if out.exists():raise SystemExit('Evaluation scope already frozen')
manifest=root/'data/manifest.jsonl'
rows=[json.loads(s) for s in manifest.read_text().splitlines()]
exposed={r['group'] for r in rows if r['source'] in ['keremberke','JJMack'] and r['target_id'] is not None}
eligible=[r for r in rows if r['use'] and r['split']=='test_public' and r['source']=='sgtsaughter' and r['group'] not in exposed]
support=dict(sorted(collections.Counter(r['target_id'] for r in eligible).items()))
record=dict(manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),rule='sgtsaughter positive test rows excluding every connected component touching any keremberke/JJMack Kanto row',sha256s=sorted(r['sha256'] for r in eligible),support=support,classes=len(support),images=len(eligible),groups=len({r['group'] for r in eligible}),source_known_groups_excluded=len(exposed),caveat='Baseline exposure UNKNOWN: no source-level or image-level proof these sgtsaughter assets were unseen. Grouping may miss shared artwork. This is the stricter public diagnostic, not independent camera evidence.')
out.write_text(json.dumps(record,indent=2));print(json.dumps({k:v for k,v in record.items() if k not in ['sha256s','support']},indent=2))
