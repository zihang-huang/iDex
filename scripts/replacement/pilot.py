"""Bounded synthetic GPU viability check; never an accuracy benchmark."""
import argparse
from labels import add_labels, read_labels
import json
import time
from pathlib import Path
import torch
from model import make_model

parser=argparse.ArgumentParser(); add_labels(parser)
parser.add_argument('--root',type=Path,default=Path('artifacts/replacement'))
args=parser.parse_args(); labels=read_labels(args.labels)
torch.set_num_threads(6);torch.manual_seed(20261027)
results=[]
for arch in ['mobilenet_v3_large','efficientnet_b0']:
    model=make_model(arch,pretrained=True,num_classes=len(labels)).cuda().to(memory_format=torch.channels_last).train()
    opt=torch.optim.AdamW(model.parameters(),lr=.0003)
    x=torch.rand(64,3,224,224,device='cuda').contiguous(memory_format=torch.channels_last)
    y=torch.arange(64,device='cuda')%len(labels)
    torch.cuda.reset_peak_memory_stats();torch.cuda.synchronize();start=time.time()
    for _ in range(4):
        opt.zero_grad(set_to_none=True)
        with torch.autocast('cuda',dtype=torch.bfloat16):
            loss=torch.nn.functional.cross_entropy(model(x),y)
        assert torch.isfinite(loss);loss.backward();opt.step()
    torch.cuda.synchronize()
    row=dict(arch=arch,batch=64,size=224,steps=4,seconds=time.time()-start,loss=float(loss.detach()),parameters=sum(p.numel() for p in model.parameters()),peak_bytes=torch.cuda.max_memory_allocated(),purpose='synthetic viability only; no generalization claim')
    print(json.dumps(row),flush=True);results.append(row)
    del model,opt,x,y;torch.cuda.empty_cache()
(args.root/'reports/gpu_pilot.json').write_text(json.dumps(results,indent=2))
