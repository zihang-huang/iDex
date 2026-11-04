"""Bounded fresh COCO training negatives; frozen evaluation remains untouched."""
import concurrent.futures
import hashlib
import json
import random
import threading
import urllib.request
import zipfile
import argparse
from pathlib import Path
from PIL import ImageDraw,Image
from data import rgb_image,phash
from acquire import fetch
from labels import add_labels,read_labels

p=argparse.ArgumentParser();add_labels(p);p.add_argument('--root',type=Path,default=Path('artifacts/replacement'));a=p.parse_args()
read_labels(a.labels)
root=a.root;folder=root/'sources/coco-oe';folder.mkdir(parents=True,exist_ok=True)
metadata=folder/'image_info_test2017.zip'
fetch('http://images.cocodataset.org/annotations/image_info_test2017.zip',metadata,5_000_000,'e52f412dd7195ac8f98d782b44c6dd30ea10241e9f42521f67610fbe055a74f8')
with zipfile.ZipFile(metadata) as archive:
    file=next(n for n in archive.namelist() if n.endswith('/image_info_test2017.json'))
    info=json.loads(archive.read(file))
licenses={x['id']:x for x in info['licenses']}
# Source metadata marks these Attribution images. Photographer attribution is
# not included in this archive: retain caveat; no redistribution is authorized.
images=sorted([x for x in info['images'] if x['license']==4],key=lambda x:x['id'])
random.Random(20261027).shuffle(images);images=images[:200]
frozen=[json.loads(s) for s in (root/'data/manifest.jsonl').read_text().splitlines()]
frozen_sha={r['sha256'] for r in frozen}
frozen_hashes=[int(r[k],16) for r in frozen for k in ['phash','phash_mirror']]
total=0;budget_lock=threading.Lock()


def download(item):
    global total
    path=folder/f"{int(item['id']):012d}.jpg"
    # Official metadata supplies this HTTP public-data route. The publisher's
    # HTTPS hostname has a certificate mismatch; no TLS verification is disabled.
    url=item['coco_url']
    if not url.startswith('http://images.cocodataset.org/test2017/'):raise ValueError('unexpected source host/path')
    if not path.exists():
        with urllib.request.urlopen(url,timeout=45) as response:
            pieces=[];count=0
            while part:=response.read(256*1024):
                count+=len(part)
                if count>2_000_000:raise ValueError('image cap')
                with budget_lock:
                    total+=len(part)
                    if total>50_000_000:raise ValueError('total transfer cap')
                pieces.append(part)
            raw=b''.join(pieces)
        if len(raw)>2_000_000:raise ValueError('image cap')
        path.write_bytes(raw)
    else:
        with budget_lock:
            total+=path.stat().st_size
            if total>50_000_000:raise ValueError('total source cap')
    raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    im=rgb_image(raw);h=phash(im)
    nearest=min((h^q).bit_count() for q in frozen_hashes)
    status='excluded_near_frozen' if nearest<=10 or sha in frozen_sha else 'proposed_train_only'
    png=folder/f'{sha}.png';im.save(png,compress_level=1)
    return dict(sha256=sha,path=png.as_posix(),source='COCO-test2017-training-negatives',source_metadata=item,license=licenses[item['license']],bytes=len(raw),url=url,phash=f'{h:016x}',nearest_frozen_phash=nearest,status=status,target_id=None,split='train_ood_new',use=status=='proposed_train_only',group=f"coco-new-{item['id']}")


with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(download,images))
if sum(r['bytes'] for r in rows)>50_000_000:raise ValueError('50MB total source cap exceeded')
# Conservative same-source near-neighbor exclusion, before any training.
kept=[]
for row in rows:
    if row['use'] and any((int(row['phash'],16)^int(x['phash'],16)).bit_count()<=10 for x in kept):row.update(use=False,status='excluded_near_new')
    if row['use']:kept.append(row)
out=root/'negative_train_manifest.jsonl'
if out.exists():raise ValueError('Negative manifest already frozen')
out.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
record=dict(selected=200,retained=len(kept),download_bytes=sum(r['bytes'] for r in rows),metadata_sha256=hashlib.sha256(metadata.read_bytes()).hexdigest(),manifest_sha256=hashlib.sha256(out.read_bytes()).hexdigest(),frozen_positive_manifest_sha256=hashlib.sha256((root/'data/manifest.jsonl').read_bytes()).hexdigest(),terms='COCO photo licenses retained by ID; source archive lacks photographer/Flickr URL, no redistribution clearance',review='Review all thumbnails before use. No frozen validation/test images are reused. Same COCO source family still limits independence.')
(folder/'receipt.json').write_text(json.dumps(record,indent=2))
canvas=Image.new('RGB',(1600,((len(rows)+9)//10)*110),'white');draw=ImageDraw.Draw(canvas)
for i,r in enumerate(rows):
    with Image.open(r['path']) as im:
        im=im.convert('RGB');im.thumbnail((156,85));x=i%10*160;y=i//10*110;canvas.paste(im,(x,y));draw.text((x,y+86),str(r['source_metadata']['id'])+(' KEEP' if r['use'] else ' EXCLUDE'),fill='black')
canvas.save(folder/'review.jpg');print(json.dumps(record,indent=2))
