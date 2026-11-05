"""Pre-training audit correction: trim black/white borders, group same-class poses.

Preserves first-pass manifest/lock. Refuses to alter data after training begins.
This is source/label review, not model-driven tuning of a test set.
"""
import argparse
from labels import add_labels, read_labels
import collections
import concurrent.futures
import hashlib
import json
import random
import shutil
import time
from pathlib import Path
import numpy as np
from PIL import Image,ImageOps
from data import Groups,DCT
from splitting import split_classes

parser=argparse.ArgumentParser(); add_labels(parser)
parser.add_argument('--root',type=Path,default=Path('artifacts/replacement'))
parser.add_argument('--min-groups',type=int,default=5); parser.add_argument('--seed',type=int,default=20261027)
args=parser.parse_args(); labels=read_labels(args.labels)
root=args.root; dest=root/'data'
if any((root/'runs').rglob('*.pt')): raise SystemExit('Training exists: do not revise the split')
if (dest/'manifest-v1.jsonl').exists(): raise SystemExit('Refinement already performed')
rows=[json.loads(s) for s in (dest/'manifest.jsonl').read_text().splitlines()]
started=time.time()


def fingerprint(row):
    if row['target_id'] is None or not row['use']: return None
    with Image.open(row['path']) as src:
        im=src.convert('RGB');im.thumbnail((512,512))
    for _ in range(2):
        a=np.asarray(im)
        # Remove black fit-padding and then white canvas; this also catches
        # black/white backgrounds around the exact same illustration.
        for mask in [(np.max(a,axis=2)>18),(np.min(a,axis=2)<238)]:
            yy,xx=np.where(mask)
            if len(xx):
                box=(int(xx.min()),int(yy.min()),int(xx.max())+1,int(yy.max())+1)
                im=im.crop(box);a=np.asarray(im)
                break
    # More stable explicit sequential trims than background-color inference.
    for black in [True,False]:
        a=np.asarray(im); mask=(a.max(2)>18) if black else (a.min(2)<238)
        yy,xx=np.where(mask)
        if len(xx):im=im.crop((int(xx.min()),int(yy.min()),int(xx.max())+1,int(yy.max())+1))
    values=[]
    for image in [im,ImageOps.mirror(im)]:
        a=np.asarray(image.convert('L').resize((32,32),Image.Resampling.LANCZOS),dtype=np.float32)
        low=(DCT@a@DCT.T).flatten();values.append(int.from_bytes(np.packbits(low>np.median(low[1:])).tobytes(),'big'))
    return values


groups=Groups(len(rows)); original={}
for i,row in enumerate(rows):
    old=row['group']
    if old in original:groups.union(i,original[old])
    else:original[old]=i
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    fingerprints=list(pool.map(fingerprint,rows))
lookup=collections.defaultdict(list);edges=[]
for i,values in enumerate(fingerprints):
    if values is None:continue
    target=rows[i]['target_id']
    for h in values:
        candidates=set()
        # Eleven disjoint blocks ensure a Hamming<=10 neighbor shares a block.
        for b in range(11):candidates.update(lookup[(target,b,(h>>(b*6))&63)])
        for j in candidates:
            distance=min((h^v).bit_count() for v in fingerprints[j])
            if distance<=10 and groups.root(i)!=groups.root(j):
                edges.append(dict(a=i,b=j,hamming=distance));groups.union(i,j)
        for b in range(11):lookup[(target,b,(h>>(b*6))&63)].append(i)
components=collections.defaultdict(list)
for i,row in enumerate(rows):components[groups.root(i)].append(i)
byclass=collections.defaultdict(list)
for key,indices in components.items():
    if rows[key]['split'].startswith('quarantine'):continue
    gid=hashlib.sha256('|'.join(sorted({rows[i]['sha256'] for i in indices})).encode()).hexdigest()[:24]
    for i in indices:rows[i]['group']=gid
    target=rows[key]['target_id']
    if target:byclass[target].append(key)
counts,insufficient=split_classes(rows,components,byclass,[l['id'] for l in labels],args.seed,args.min_groups)
(dest/'insufficient_groups.json').write_text(json.dumps(insufficient,indent=2),encoding='utf-8')
shutil.copy2(dest/'manifest.jsonl',dest/'manifest-v1.jsonl');shutil.copy2(dest/'split_lock.json',dest/'split_lock-v1.json')
manifest=dest/'manifest.jsonl';manifest.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
summary=json.loads((dest/'split_lock-v1.json').read_text())
summary.update(min_groups=args.min_groups,insufficient_groups=insufficient,labels=labels,groups=len(components),class_groups=counts,effective_splits=dict(collections.Counter(r['split'] for r in rows if r['use'])),manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),refinement_seconds=time.time()-started,extra_group_merges=len(edges),revision=2,reason='Pre-training visual audit found black-padding/white-background and resize copies; added same-class foreground/mirror Hamming<=10 groups. No model predictions or tests informed revision.')
(dest/'foreground_edges.json').write_text(json.dumps(edges,indent=2));(dest/'split_lock.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2),flush=True)
