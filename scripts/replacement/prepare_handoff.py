"""Prepare a private, hash-inventoried Mac bundle; no upload or Core ML claim."""
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
import torch
from model import load_checkpoint
import argparse
from labels import add_labels


def main():
    p=argparse.ArgumentParser();add_labels(p);p.add_argument('--root',type=Path,default=Path('artifacts/replacement'));a=p.parse_args()
    root=a.root; selection=json.loads((root/'selection.json').read_text())
    checkpoint=Path(selection['checkpoint'])
    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest()==selection['checkpoint_sha256']
    out=root/'handoff'
    if out.exists(): raise ValueError('Handoff exists; preserve it and choose a new version')
    out.mkdir();torch.set_num_threads(6)
    model,state=load_checkpoint(checkpoint,a.labels);model.eval();size=state['config']['size']
    torch.manual_seed(20261027);example=torch.rand(1,3,size,size)
    traced=torch.jit.trace(model,example,check_trace=True)
    differences=[]
    with torch.inference_mode():
        for x in [example,torch.zeros_like(example),torch.ones_like(example),torch.rand_like(example)]:
            error=float((model(x)-traced(x)).abs().max());differences.append(error)
            if error>1e-4:raise ValueError(f'Eager/trace parity failed: {error}')
    traced.save(str(out/'candidate.torchscript.pt'))
    shutil.copy2(checkpoint,out/'candidate-best.pt')
    (out/'trace_receipt.json').write_text(json.dumps(dict(max_errors=differences,torch=str(torch.__version__),size=size,coreml_status='Not exported: compatible Mac/converter and Apple runtime required'),indent=2))
    subprocess.run([sys.executable,'scripts/replacement/fixtures.py','--checkpoint',str(checkpoint),'--labels',str(a.labels),'--manifest',str(root/'data/manifest.jsonl'),'--reference-checkpoint',str(checkpoint),'--out',str(out/'fixtures')],check=True)
    shutil.copy2(root/'selection.json',out/'selection.json')
    shutil.copy2(a.labels,out/'labels.json')
    shutil.copy2('scripts/replacement/contract.json',out/'contract.json')
    bundle=out/'idex-mac-handoff.zip'
    paths=list(out.rglob('*'))+[p for p in Path('scripts/replacement').rglob('*') if '__pycache__' not in p.parts]
    paths+=[p for p in Path('iDex/Recognition/KantoClassifier.mlpackage').rglob('*')]
    paths+=[a.labels,Path('iDex/Recognition/MODEL.md'),Path('AGENTS.md'),root/'data/split_lock.json',root/'reports/inventory.json',root/'sources/BiernyVR--pokemon-classifier-mobilenetv3/pokemon_densenet121_best.pth']
    manifest=[]
    with zipfile.ZipFile(bundle,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
        for path in paths:
            if not path.is_file() or path==bundle:continue
            data=path.read_bytes();name=path.as_posix()
            archive.writestr(name,data);manifest.append(dict(path=name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
        archive.writestr('HANDOFF_MANIFEST.json',json.dumps(manifest,indent=2))
    (out/'bundle_receipt.json').write_text(json.dumps(dict(path=str(bundle),bytes=bundle.stat().st_size,sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),files=len(manifest),privacy='Local private research transfer only; no upload or publish performed'),indent=2))
    print(json.dumps(dict(bundle=str(bundle),files=len(manifest),trace_errors=differences),indent=2))


if __name__=='__main__':main()
