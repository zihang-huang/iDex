"""Render auditable training examples and duplicate conflict sheets (no inference)."""
import argparse
from labels import add_labels, read_labels
import collections
import json
from pathlib import Path
from PIL import Image,ImageDraw,ImageOps

parser=argparse.ArgumentParser(); add_labels(parser)
parser.add_argument('--root',type=Path,default=Path('artifacts/replacement'))
args=parser.parse_args(); labels=read_labels(args.labels)
root=args.root; out=root/'reports/audit';out.mkdir(parents=True,exist_ok=True)
rows=[json.loads(s) for s in (root/'data/manifest.jsonl').read_text().splitlines()]
labels=read_labels(args.labels)
items=[]
for label in labels:
    choices=[r for r in rows if r['target_id']==label['id'] and r['use'] and r['split']=='train']
    # One representative per source where available; no model/test-based choices.
    chosen=[]
    for source in ['sgtsaughter','keremberke','JJMack','sprites','tcg']:
        available=[r for r in choices if r['source']==source]
        if available: chosen.append(available[len(available)//2])
    for r in chosen: items.append((r,f"{label['id']} {label['name']} {r['source']}"))

def sheet(items,file,cols=6,cell=(180,160)):
    canvas=Image.new('RGB',(cols*cell[0],((len(items)+cols-1)//cols)*cell[1]),'white');d=ImageDraw.Draw(canvas)
    for i,(r,title) in enumerate(items):
        x=i%cols*cell[0];y=i//cols*cell[1]
        with Image.open(r['path']) as im:
            im=im.convert('RGB');im.thumbnail((cell[0],cell[1]-35));canvas.paste(im,(x,y))
        d.text((x,y+cell[1]-33),title[:28],fill='black');d.text((x,y+cell[1]-18),r['sha256'][:12],fill='black')
    canvas.save(file)
for i in range(0,len(items),72): sheet(items[i:i+72],out/f'train_classes_{i//72:02}.jpg')
conflicts=json.loads((root/'data/conflicts.json').read_text())
examples=[]
for c in conflicts[:36]:
    for index in c['rows'][:2]:
        r=rows[index];examples.append((r,f"conflict {r['target_id']} {r['source_label']}"))
if examples: sheet(examples,out/'quarantine_examples.jpg')
groups=collections.defaultdict(list)
for r in rows:
    if r['use'] and not r['split'].startswith('quarantine'):groups[r['group']].append(r)
assert all(len({r['split'] for r in values})==1 for values in groups.values())
summary={'groups':len(groups),'split_overlap':0,'sources':dict(collections.Counter(r['source'] for r in rows)),'class_sheets':len(items),'rights':'Source/uploader terms archived; underlying IP and individual photo attribution unresolved for redistribution'}
(out/'audit_summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
