"""Data-only ingestion, cross-source duplicate grouping and immutable split freeze.

Public test is baseline-contaminated/unknown, never a promotion benchmark.
Near-duplicate groups are conservative automated candidates, not proof all related
artworks or capture sessions were discovered. Manual group review is required.
"""
import argparse
import collections
import hashlib
import io
import json
import random
import re
import time
import warnings
import zipfile
from pathlib import Path, PurePosixPath

import numpy as np
import pyarrow.parquet as pq
from PIL import Image, ImageOps
from labels import add_labels, read_labels, generations
from splitting import split_classes
from sources import verify_jjmack
from synthetic import has_transparency

Image.MAX_IMAGE_PIXELS = 40_000_000
warnings.simplefilter('error', Image.DecompressionBombWarning)


def digest(data): return hashlib.sha256(data).hexdigest()
def normalize(s):
    s = str(s).lower().replace('♀','f').replace('♂','m').replace('female','f').replace('male','m')
    return re.sub('[^a-z0-9]', '', s)


def rgb_image(raw):
    with Image.open(io.BytesIO(raw)) as src:
        image = ImageOps.exif_transpose(src).convert('RGBA')
        return Image.alpha_composite(Image.new('RGBA', image.size, 'white'), image).convert('RGB')


N = 32
DCT = np.cos(np.pi/N * (np.arange(N)[None,:]+.5)*np.arange(8)[:,None])
def phash(image):
    # Trim nearly white margins before hashing to group alpha/white artwork copies.
    thumb = image.copy(); thumb.thumbnail((512,512))
    a = np.asarray(thumb)
    mask = np.min(a, axis=2)<240
    yy,xx = np.where(mask)
    if len(xx): thumb = thumb.crop((int(xx.min()),int(yy.min()),int(xx.max())+1,int(yy.max())+1))
    a = np.asarray(thumb.convert('L').resize((N,N), Image.Resampling.LANCZOS),dtype=np.float32)
    low = DCT @ a @ DCT.T
    bits = low.flatten()>np.median(low.flatten()[1:])
    return int.from_bytes(np.packbits(bits).tobytes(),'big')


class Groups:
    def __init__(self,n): self.p=list(range(n))
    def root(self,x):
        while self.p[x]!=x:
            self.p[x]=self.p[self.p[x]]; x=self.p[x]
        return x
    def union(self,a,b):
        a,b=self.root(a),self.root(b)
        self.p[max(a,b)]=min(a,b)


def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,default=Path('artifacts/replacement'))
    p.add_argument('--seed',type=int,default=20261027); p.add_argument('--ood-limit',type=int,default=1200)
    add_labels(p); p.add_argument('--min-groups',type=int,default=5)
    a=p.parse_args(); started=time.time()
    dest=a.root/'data'; dest.mkdir(parents=True,exist_ok=True)
    if (dest/'split_lock.json').exists(): raise SystemExit('Split already frozen. Use a new root to change it.')
    images=dest/'images'; images.mkdir(exist_ok=True)
    labels=read_labels(a.labels); allowed={r['id'] for r in labels}; generation=generations()
    mapping={normalize(x['name']):x['id'] for x in labels}
    mapping.update({k:v for k,v in {'nidoranf':29,'nidoranm':32,'mrmime':122,'farfetchd':83}.items() if v in allowed})
    rows=[]; bad=[]; cache={}

    def add(raw,source,member,label,upstream_split,extra=None):
        try:
            sh=digest(raw)
            if sh in cache:
                base=cache[sh]; im=None
            else:
                im=rgb_image(raw)
                if im.width<8 or im.height<8: raise ValueError('too small')
                pixel=digest(f'{im.width}x{im.height}:'.encode()+im.tobytes())
                h=phash(im); hf=phash(ImageOps.mirror(im))
                path=images/(sh+'.png')
                # Persist lossless decoded pixels, not arbitrary archive paths.
                valid=False
                if path.exists():
                    try:
                        with Image.open(path) as saved: saved.verify()
                        valid=True
                    except Exception: pass
                if not valid: im.save(path,optimize=False,compress_level=1)
                base=dict(sha256=sh,pixel_sha256=pixel,path=path.as_posix(),width=im.width,height=im.height,phash=f'{h:016x}',phash_mirror=f'{hf:016x}')
                # Keep a separate RGBA training asset. Hash/group against the
                # original white-composited RGB so alpha cannot bypass grouping.
                with Image.open(io.BytesIO(raw)) as src:
                    if has_transparency(src):
                        alpha=images/(sh+'-alpha.png')
                        ImageOps.exif_transpose(src).convert('RGBA').save(alpha)
                        base['alpha_path']=alpha.as_posix()
                cache[sh]=base
            name=normalize(label); target=mapping.get(name); form='unspecified'
            for prefix in ['alolan','galarian','hisuian','paldean','mega']:
                if name.startswith(prefix) and name[len(prefix):] in mapping:
                    target=mapping[name[len(prefix):]]; form=prefix
            row=dict(base,source=source,member=member,source_label=str(label),target_id=target,form=form,upstream_split=upstream_split,domain='public_mixed_unverified',baseline_exposure='known-source' if source in ['JJMack','keremberke'] else 'unknown-possible-overlap')
            if extra: row.update(extra)
            if row['target_id'] is not None: row['generation']=generation.get(row['target_id'])
            rows.append(row)
        except Exception as e:
            bad.append(dict(source=source,member=member,error=str(e)))

    archives=sorted((a.root/'sources'/'sgtsaughter--pokemon-classification-images-151').glob('*.zip'))+sorted((a.root/'sources'/'keremberke--pokemon-classification').glob('*.zip'))+sorted((a.root/'sources'/'coco128').glob('*.zip'))
    for archive in archives:
        source='coco128' if 'coco128' in str(archive) else 'keremberke' if 'keremberke' in str(archive) else 'sgtsaughter'
        with zipfile.ZipFile(archive) as z:
            infos=z.infolist()
            if sum(x.file_size for x in infos)>15_000_000_000: raise ValueError('archive expansion budget')
            for info in infos:
                member=PurePosixPath(info.filename)
                if member.is_absolute() or '..' in member.parts: raise ValueError('unsafe archive path')
                if member.suffix.lower() not in ['.jpg','.jpeg','.png','.webp','.bmp']: continue
                if info.file_size>30_000_000: continue
                original=re.split(r'_(?:jpg|png|jpeg)\.rf\.', member.name)[0]
                extra=dict(source_group=f'{source}:{member.parent.name}:{original}')
                if source=='coco128': extra.update(target_id=None,domain='public_natural_object_negative',baseline_exposure='unknown-pretraining-possible')
                add(z.read(info),source,info.filename,member.parent.name,archive.stem,extra)
                if len(rows)%1000==0: print(f'ingested {len(rows)}',flush=True)
    jjfolder=a.root/'sources'/'JJMack--pokemon-classification-gen1-9'
    jjfiles=sorted(jjfolder.rglob('*.parquet'))
    if jjfiles: verify_jjmack(json.loads((jjfolder/'metadata.json').read_text(encoding='utf-8')))
    for file in jjfiles:
        pf=pq.ParquetFile(file)
        metadata=pf.schema_arrow.metadata or {}
        hf=json.loads(metadata.get(b'huggingface',b'{}'))
        names=hf.get('info',{}).get('features',{}).get('label',{}).get('names',[])
        for batch in pf.iter_batches(batch_size=64):
            for item in batch.to_pylist():
                label=item.get('label',item.get('labels'))
                if names and isinstance(label,int) and names[label].lower() in ('test','test2'): continue
                label=names[label] if names and isinstance(label,int) else label
                image=item.get('image',item.get('image_data'))
                raw=image if isinstance(image,bytes) else image.get('bytes')
                if not raw: raise ValueError('external image paths not followed')
                label=item.get('name',label)
                filename=item.get('file_name','')
                dex=int(item['label'])
                if not names and dex in (0,1026): continue
                target=dex if dex in allowed else None
                # National Dex ID is authoritative where names are truncated or
                # Nidoran sex characters are lost in the publisher's name column.
                pose=re.sub(r'-s(?=\.[a-z]+$)','',filename)
                source_group=f'JJMack:{pose}' if target else f'JJMack:ood-species-{dex}'
                add(raw,'JJMack',f'{file.name}:{len(rows)}:{filename}',label,file.stem,dict(target_id=target,national_dex_id=dex,generation=item.get('generation'),shiny=item.get('shiny'),source_group=source_group))
            if len(rows)%1000<64: print(f'ingested {len(rows)}',flush=True)
    for source in ('sprites','tcg'):
        receipt=a.root/'sources'/source/'samples.jsonl'
        if not receipt.exists(): continue
        for line in receipt.read_text(encoding='utf-8').splitlines():
            sample=json.loads(line)
            if sample['target_id'] not in allowed: continue
            raw=Path(sample['path']).read_bytes()
            if sample.get('derived_sha256') and digest(raw)!=sample['derived_sha256']:
                raise ValueError(f'derived image checksum mismatch: {sample["path"]}')
            add(raw,source,sample['path'],sample['target_id'],'acquired',
                {k:v for k,v in sample.items() if k not in ('path','source')})
    if not rows: raise ValueError('No image inputs')
    (dest/'ingest_errors.json').write_text(json.dumps(bad,indent=2))
    print(f'grouping {len(rows)} source rows, {len(cache)} unique byte images',flush=True)
    groups=Groups(len(rows)); pixels={}; originals={}; hashes=collections.defaultdict(list); edges=[]
    # 8 disjoint hash bytes: distance <= 6 has >=2 exact byte matches.
    # Include mirror fingerprints, exact bytes/pixels and cross-label groups.
    for i,r in enumerate(rows):
        original=r.get('source_group')
        if original in originals: groups.union(i,originals[original])
        elif original: originals[original]=i
        if r['pixel_sha256'] in pixels: groups.union(i,pixels[r['pixel_sha256']])
        else: pixels[r['pixel_sha256']]=i
        for key in ['phash','phash_mirror']:
            h=int(r[key],16); candidates=set()
            for block in range(8): candidates.update(hashes[(block,(h>>(8*block))&255)])
            for j in candidates:
                d=min((h^int(rows[j][k],16)).bit_count() for k in ['phash','phash_mirror'])
                if d<=6:
                    if groups.root(i)!=groups.root(j): edges.append(dict(a=i,b=j,hamming=d))
                    groups.union(i,j)
            for block in range(8): hashes[(block,(h>>(8*block))&255)].append(i)
    grouped=collections.defaultdict(list)
    for i,r in enumerate(rows): grouped[groups.root(i)].append(i)
    conflicts=[]; byclass=collections.defaultdict(list); unknown=[]
    for root,indices in grouped.items():
        targets={rows[i]['target_id'] for i in indices}
        # Unknown sources are kept as one OOD group; they may mix multiple OOD species.
        conflict=len(targets)>1
        group_id=digest('|'.join(sorted({rows[i]['sha256'] for i in indices})).encode())[:24]
        for i in indices: rows[i]['group']=group_id
        if conflict:
            conflicts.append(dict(group=group_id,targets=list(targets),rows=indices))
            for i in indices: rows[i]['split']='quarantine_label_conflict'
        elif next(iter(targets)) is None: unknown.append(root)
        else: byclass[next(iter(targets))].append(root)
    rng=random.Random(a.seed)
    counts,insufficient=split_classes(rows,grouped,byclass,[l['id'] for l in labels],a.seed,a.min_groups,rng)
    (dest/'insufficient_groups.json').write_text(json.dumps(insufficient,indent=2),encoding='utf-8')
    bysource=collections.defaultdict(list)
    for root in unknown: bysource[rows[root]['source']].append(root)
    for source,roots in sorted(bysource.items()):
        rng.shuffle(roots)
        for j,root in enumerate(roots):
            split=('ood_val' if j%2 else 'ood_test_public') if j<a.ood_limit else 'unused_ood'
            for i in grouped[root]: rows[i]['split']=split
    # Exact duplicates remain in provenance but are excluded from effective samples.
    seen=set()
    for r in rows:
        key=(r['pixel_sha256'],r['target_id'])
        r['use']=key not in seen and not r['split'].startswith('quarantine')
        seen.add(key)
    manifest=dest/'manifest.jsonl'
    manifest.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
    (dest/'near_duplicate_edges.json').write_text(json.dumps(edges,indent=2))
    (dest/'conflicts.json').write_text(json.dumps(conflicts,indent=2))
    summary=dict(rows=len(rows),byte_unique=len(cache),groups=len(grouped),conflicts=len(conflicts),errors=len(bad),class_groups=counts,
                 min_groups=a.min_groups,insufficient_groups=insufficient,labels=labels,
                 effective_splits=dict(collections.Counter(r['split'] for r in rows if r['use'])),
                 seconds=time.time()-started,seed=a.seed,manifest_sha256=digest(manifest.read_bytes()),
                 caveat='Public baseline contamination known/unknown. Automated near-duplicate grouping incomplete. No independent camera test exists. No promotion evidence.')
    (dest/'split_lock.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__': main()
