"""Package unchanged baseline tensors for identical validation calibration tooling."""
import argparse
from labels import add_labels, read_labels
import hashlib
import json
from pathlib import Path
import torch
from model import make_model,LABELS

parser=argparse.ArgumentParser(); add_labels(parser)
parser.add_argument('--root',type=Path,default=Path('artifacts/replacement'))
args=parser.parse_args(); labels=read_labels(args.labels)
root=args.root;file=root/'baseline-reference.pt'
if file.exists():raise ValueError('Preserve the existing baseline reference')
if labels!=read_labels(): raise ValueError('Historical baseline labels mismatch')
torch.set_num_threads(6);model=make_model('baseline',num_classes=len(labels)).eval()
manifest=root/'data/manifest.jsonl'
state=dict(model=model.state_dict(),config=dict(arch='baseline',size=224,manifest=str(manifest)),labels=labels,manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),source_checkpoint_sha256='58e54044ed3ff747a26717313570e4c0b0f2204e7bdfcef7351d011861b2defe')
torch.save(state,file)
(root/'baseline-reference.json').write_text(json.dumps(dict(sha256=hashlib.sha256(file.read_bytes()).hexdigest(),parameters=sum(p.numel() for p in model.parameters()),source_sha256=state['source_checkpoint_sha256'],purpose='Unchanged source tensors; same calibration search as candidate; never modifies app model'),indent=2))
print('Unchanged baseline tensor reference packaged')
