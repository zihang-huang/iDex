"""Download data/weights only. No dataset scripts or remote model code executes.

All downloads remain below --root, are SHA256 inventoried and atomically renamed.
Use metadata first; inspect the archived cards before choosing data.
"""
import argparse
import hashlib
import json
import time
import threading
import concurrent.futures
import urllib.error
import urllib.request
from pathlib import Path
from pathlib import PurePosixPath
from labels import add_labels, read_labels
from sources import JJMACK, JJMACK_REV, verify_jjmack, acquire_sprites, acquire_tcg

DATASETS = ['sgtsaughter/pokemon-classification-images-151', 'JJMack/pokemon-classification-gen1-9', 'keremberke/pokemon-classification']
BASELINE = 'BiernyVR/pokemon-classifier-mobilenetv3'
BASELINE_REV = '3bf528cf0f6ab8464ea3bac0f70d84886e8dab25'
BASELINE_SHA = '58e54044ed3ff747a26717313570e4c0b0f2204e7bdfcef7351d011861b2defe'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(4*1024*1024), b''): h.update(b)
    return h.hexdigest()


_local = threading.local()


def _session():
    """One keep-alive session per thread: each new TLS tunnel through a local proxy costs seconds."""
    session = getattr(_local, 'session', None)
    if session is None:
        import requests
        session = _local.session = requests.Session()
        session.headers['User-Agent'] = 'iDex-local-research/1.0'
    return session


def fetch(url, target, limit=2_000_000_000, expected=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        partial = target.with_suffix(target.suffix + '.partial')
        count = 0
        with _session().get(url, stream=True, timeout=90) as response:
            # Same error type as urllib so retry_fetch keeps its retryable-status contract.
            if response.status_code >= 400:
                raise urllib.error.HTTPError(url, response.status_code, response.reason, response.headers, None)
            if int(response.headers.get('Content-Length', 0)) > limit: raise ValueError('download exceeds budget')
            with partial.open('wb') as output:
                for b in response.iter_content(1024*1024):
                    count += len(b)
                    if count > limit: raise ValueError('download exceeds budget')
                    output.write(b)
        partial.replace(target)
    digest = sha(target)
    if expected and digest != expected: raise ValueError(f'checksum mismatch: {target}')
    row = dict(path=str(target), url=url, bytes=target.stat().st_size, sha256=digest, retrieved_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    print(json.dumps(row), flush=True)
    return row


def ranged_fetch(url,target,total,expected=None):
    """Bounded four-way 8 MiB ranges, retries capped; never execute contents."""
    if target.exists(): return fetch(url,target,total+1,expected)
    folder=target.with_suffix(target.suffix+'.parts'); folder.mkdir(parents=True,exist_ok=True)
    chunk=8*1024*1024
    def part(start):
        end=min(total-1,start+chunk-1); file=folder/str(start)
        if file.exists() and file.stat().st_size==end-start+1: return
        last=None
        for attempt in range(3):
            try:
                req=urllib.request.Request(url+'?download=true',headers={'Range':f'bytes={start}-{end}','User-Agent':'iDex-local-research/1.0'})
                with urllib.request.urlopen(req,timeout=45) as response:
                    if response.status!=206 or response.headers.get('Content-Range')!=f'bytes {start}-{end}/{total}': raise ValueError('range contract mismatch')
                    data=response.read(chunk+1)
                if len(data)!=end-start+1: raise ValueError('range length mismatch')
                file.write_bytes(data)
                print(f'{target.name} range {start}-{end} complete',flush=True)
                return
            except Exception as e: last=e
        raise last
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(part,range(0,total,chunk)))
    partial=target.with_suffix(target.suffix+'.ranged.partial')
    with partial.open('wb') as out:
        for start in range(0,total,chunk): out.write((folder/str(start)).read_bytes())
    if expected and sha(partial)!=expected: raise ValueError('ranged checksum mismatch')
    partial.replace(target)
    return fetch(url,target,total+1,expected)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('stage', choices=['metadata','baseline','data','pretrained','negatives','sprites','tcg'])
    p.add_argument('--root', type=Path, default=Path('artifacts/replacement/sources'))
    p.add_argument('--dataset', choices=DATASETS, default=DATASETS[0])
    add_labels(p)
    p.add_argument('--delay',type=float,default=1.,help='minimum delay after each uncached new-source request')
    p.add_argument('--attempts',type=int,default=6)
    p.add_argument('--workers',type=int,default=1,help='parallel cache-warming downloads for sprites/tcg; --delay applies per worker')
    a = p.parse_args(); a.root.mkdir(parents=True, exist_ok=True)
    labels=read_labels(a.labels)
    if a.stage in ('sprites','tcg'):
        stage=acquire_sprites if a.stage=='sprites' else acquire_tcg
        stage(a.root,labels,fetch,a.delay,a.attempts,a.workers)
        return
    records = []
    if a.stage=='negatives':
        records.append(fetch('https://github.com/ultralytics/assets/releases/download/v0.0.0/coco128.zip',a.root/'coco128/coco128.zip',20_000_000))
        records.append(fetch('https://raw.githubusercontent.com/ultralytics/ultralytics/main/ultralytics/cfg/datasets/coco128.yaml',a.root/'coco128/source.yaml',100_000))
        records.append(fetch('https://raw.githubusercontent.com/cocodataset/cocodataset.github.io/master/dataset/termsofuse.htm',a.root/'coco128/terms.html',100_000))
    if a.stage == 'metadata':
        for repo in DATASETS + [BASELINE]:
            kind = 'datasets/' if repo in DATASETS else 'models/'
            folder = a.root / repo.replace('/', '--')
            endpoint=f'https://huggingface.co/api/{kind}{repo}'
            if repo==JJMACK: endpoint+=f'/revision/{JJMACK_REV}'
            records.append(fetch(endpoint, folder/'metadata.json', 10_000_000))
            meta = json.loads((folder/'metadata.json').read_text('utf-8'))
            if repo==JJMACK: verify_jjmack(meta)
            revision = BASELINE_REV if repo == BASELINE else meta['sha']
            prefix = 'datasets/' if repo in DATASETS else ''
            records.append(fetch(f'https://huggingface.co/{prefix}{repo}/resolve/{revision}/README.md', folder/'README.md', 1_000_000))
    if a.stage == 'baseline':
        folder = a.root / BASELINE.replace('/', '--')
        for name in ['pokemon_densenet121_best.pth','pokemon_labels.json']:
            records.append(fetch(f'https://huggingface.co/{BASELINE}/resolve/{BASELINE_REV}/{name}', folder/name, 100_000_000, BASELINE_SHA if name.endswith('.pth') else None))
    if a.stage == 'data':
        folder = a.root / a.dataset.replace('/', '--')
        if a.dataset == 'keremberke/pokemon-classification':
            revision = 'a0b014ffa0bf56b0a490676d298b3d73ca52b8d6'
            expected = {'train':'6359730e9a6c620313401857e79aab8ca2571f65b34d621fd33cb88365811353', 'valid':'aec4f0c7e9d318fc4e1af1a69387d0250f570177de4bf661c1a7042abf48910e', 'test':'38a98970a0b5c8cecab8be18f09cb16037a71a9819f56c5e57052deb4806239d'}
            for split, checksum in expected.items():
                records.append(fetch(f'https://huggingface.co/datasets/{a.dataset}/resolve/{revision}/data/{split}.zip',folder/f'{split}.zip',100_000_000,checksum))
            with (a.root/'downloads.jsonl').open('a', encoding='utf-8') as out:
                for record in records: out.write(json.dumps(record)+'\n')
            return
        meta = json.loads((folder/'metadata.json').read_text('utf-8'))
        if a.dataset==JJMACK: verify_jjmack(meta)
        files = [x['rfilename'] for x in meta['siblings'] if x['rfilename'].endswith(('.parquet', '.zip'))]
        if not files: raise ValueError('No parquet/zip; inspect metadata manually')
        if len(files) > 20: raise ValueError('Too many shards; inspect budget')
        total = sum(x.stat().st_size for x in a.root.rglob('*') if x.is_file())
        for name in files:
            safe=PurePosixPath(name)
            if safe.is_absolute() or '..' in safe.parts or '\\' in name or ':' in name: raise ValueError('unsafe remote dataset path')
            if total > 8_000_000_000: raise ValueError('source download total exceeds 8 GB budget')
            target = folder/name
            url=f"https://huggingface.co/datasets/{a.dataset}/resolve/{meta['sha']}/{name}"
            expected={'PokemonData.zip':'31e6852f0cdc8e7a8abc4074ac844c4be059b915f0099367eeb2aeff4cc1748f','train.parquet':'74e32dc22e51789fb46b4873c86a1a1b4dcdbe77a1f30a379fd01597784b4314','test.parquet':'4b812cf954e8e69479eaeb0f8c88d24b9d0796c898d88f76867c82fba1d74313','validation.parquet':'6d0022b9d0bd12dd10a56ecc86f519d2968cbb384c6f396014a93ba36e9c8633'}.get(name)
            # Large sources are range fetched only with authoritative length from
            # a 1-byte range response, rather than trusting approximate card sizes.
            if not target.exists():
                req=urllib.request.Request(url+'?download=true',headers={'Range':'bytes=0-0'})
                with urllib.request.urlopen(req,timeout=45) as response:
                    header=response.headers.get('Content-Range',''); response.read(1)
                    size=int(header.split('/')[-1]) if header else 0
                if size<=0 or size>2_000_000_000: raise ValueError('invalid range size')
                records.append(ranged_fetch(url,target,size,expected))
            else: records.append(fetch(url,target,expected=expected))
            total += target.stat().st_size
    if a.stage == 'pretrained':
        # Official torchvision state dictionaries, loaded later with weights_only=True.
        for name in ['mobilenet_v3_large-5c1a4163.pth','efficientnet_b0_rwightman-7f5810bc.pth']:
            expected={'mobilenet_v3_large-5c1a4163.pth':'5c1a416349c4cf298f2a6a5e2600ed0ee55e604713578f5e74e6bc8bcaef7997','efficientnet_b0_rwightman-7f5810bc.pth':'7f5810bc96def8f7552d5b7e68d53c4786f81167d28291b21c0d90e1fca14934'}[name]
            records.append(fetch(f'https://download.pytorch.org/models/{name}', a.root/'torchvision'/name, 100_000_000,expected))
    with (a.root/'downloads.jsonl').open('a', encoding='utf-8') as out:
        for record in records: out.write(json.dumps(record)+'\n')


if __name__ == '__main__': main()
