"""Mac export handoff. Never overwrite the production model or its labels.

Run with a separately installed compatible PyTorch/torchvision/coremltools stack.
PyTorch CPU and trace parity are checked here; Core ML image parity is verified
by apple/ harness on the exact Apple-prepared final pixels.
"""
import argparse
import hashlib
import json
import platform
from pathlib import Path
import numpy as np
import torch
from model import load_checkpoint
from labels import add_labels, LABELS


def main():
    p=argparse.ArgumentParser();p.add_argument('--checkpoint',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--golden',type=Path)
    p.add_argument('--deployment',choices=['iOS18','iOS26','iOS27'],default='iOS18')
    add_labels(p)
    a=p.parse_args()
    import coremltools as ct
    if not hasattr(ct.target,a.deployment): raise SystemExit(f'{a.deployment} absent in coremltools {ct.__version__}; use validated target supported by the SDK, record it explicitly')
    if a.out.exists(): raise ValueError('Use a new export folder; no overwrite')
    a.out.mkdir(parents=True)
    model,state=load_checkpoint(a.checkpoint,a.labels); model.eval();size=state['config']['size']
    torch.manual_seed(20261027);example=torch.rand(1,3,size,size)
    traced=torch.jit.trace(model,example,check_trace=True)
    capture=[]
    with torch.inference_mode():
        for x in [example,torch.zeros_like(example),torch.ones_like(example),torch.rand_like(example)]:
            delta=float((model(x)-traced(x)).abs().max());capture.append(delta)
            if delta>1e-4: raise ValueError(f'trace drift {delta}')
    results=[]
    for name,precision in [('fp32',ct.precision.FLOAT32),('fp16',ct.precision.FLOAT16)]:
        converted=ct.convert(traced,convert_to='mlprogram',minimum_deployment_target=getattr(ct.target,a.deployment),compute_precision=precision,
            inputs=[ct.ImageType(name='image',shape=example.shape,scale=1/255,color_layout=ct.colorlayout.RGB)],outputs=[ct.TensorType(name='logits')])
        converted.short_description=f'iDex experimental {state["config"]["arch"]}; not approved for production'
        converted.author='iDex local replacement experiment'
        converted.license='Research candidate: source dataset and Pokémon rights caveats apply; see report'
        converted.user_defined_metadata['checkpoint_sha256']=hashlib.sha256(a.checkpoint.read_bytes()).hexdigest()
        converted.user_defined_metadata['manifest_sha256']=state['manifest_sha256']
        prefix='KantoCandidate' if a.labels==LABELS else 'NationalCandidate'
        path=a.out/f'{prefix}-{name}.mlpackage';converted.save(str(path))
        results.append(dict(precision=name,path=str(path)))
    (a.out/'labels.json').write_text(json.dumps(state['labels'],indent=2))
    record=dict(platform=platform.platform(),torch=torch.__version__,coremltools=ct.__version__,deployment=a.deployment,size=size,trace_max_errors=capture,models=results,
                parity='PENDING: execute apple/ on Mac + physical iPhone; conversion is not inference evidence')
    (a.out/'export_receipt.json').write_text(json.dumps(record,indent=2));print(json.dumps(record,indent=2))


if __name__=='__main__': main()
