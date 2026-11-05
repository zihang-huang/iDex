"""One four-epoch outlier-exposure correction, no inference architecture change."""
import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path
import torch
from torch.utils.data import DataLoader
from model import load_checkpoint
from train import Images,seed_everything,validation,rows_from
from labels import add_labels,read_labels,check_labels


def main():
    p=argparse.ArgumentParser();p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--resume',action='store_true');add_labels(p)
    p.add_argument('--root',type=Path,default=Path('artifacts/replacement'));a=p.parse_args()
    root=a.root;out=root/'runs/efficientnet224-oe';labels=read_labels(a.labels)
    if out.exists() and not a.resume:raise ValueError('OE run exists; resume explicitly')
    assert (root/'negative_review_completed.json').exists(),'Visual negative audit required'
    manifest=root/'data/manifest.jsonl';negative=root/'negative_train_manifest.jsonl'
    sha=hashlib.sha256(manifest.read_bytes()).hexdigest();negsha=hashlib.sha256(negative.read_bytes()).hexdigest()
    if json.loads((root/'negative_review_completed.json').read_text())['manifest_sha256']!=negsha:raise ValueError('Negative audit manifest mismatch')
    torch.set_num_threads(6);seed_everything(20261047)
    model,state=load_checkpoint(a.checkpoint,a.labels)
    if state['manifest_sha256']!=sha:raise ValueError('Frozen positive manifest mismatch')
    model=model.cuda().to(memory_format=torch.channels_last)
    positive=rows_from(manifest,'train');val=rows_from(manifest,'val')
    negatives=[r for r in (json.loads(s) for s in negative.read_text().splitlines()) if r['use']]
    assert len(negatives)>=100
    train_loader=DataLoader(Images(positive,224,True,labels),batch_size=64,shuffle=True,num_workers=4,pin_memory=True)
    val_loader=DataLoader(Images(val,224,labels=labels),batch_size=64,num_workers=4,pin_memory=True)
    neg_loader=DataLoader(Images(negatives,224,True,labels),batch_size=16,shuffle=True,num_workers=2,pin_memory=True,persistent_workers=True)
    optimizer=torch.optim.AdamW(model.parameters(),lr=3e-5,weight_decay=.001)
    scheduler=torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,T_max=4)
    out.mkdir(parents=True,exist_ok=True);(out/'source').mkdir(exist_ok=True)
    for file in Path('scripts/replacement').glob('*.py'):shutil.copy2(file,out/'source'/file.name)
    config=dict(arch=state['config']['arch'],size=224,manifest=str(manifest),epochs=4,seed=20261047,lr=3e-5,oe_weight=.1,positive_batch=64,negative_batch=16,batch_norm='frozen running statistics',initial_checkpoint_sha256=hashlib.sha256(a.checkpoint.read_bytes()).hexdigest(),negative_manifest_sha256=negsha)
    (out/'environment.json').write_text(json.dumps(dict(config=config,torch=str(torch.__version__),gpu=torch.cuda.get_device_name(0)),indent=2))
    start=0
    if a.resume:
        last=torch.load(out/'last.pt',map_location='cpu',weights_only=True)
        check_labels(last,labels)
        if last['manifest_sha256']!=sha or last['negative_manifest_sha256']!=negsha or last['config']!=config:raise ValueError('OE resume contract mismatch')
        model.load_state_dict(last['model']);optimizer.load_state_dict(last['optimizer']);scheduler.load_state_dict(last['scheduler']);start=last['epoch']
    begin=time.time();torch.cuda.reset_peak_memory_stats()
    for epoch in range(start,4):
        seed_everything(20261047+epoch);model.train()
        for layer in model.modules():
            if isinstance(layer,torch.nn.modules.batchnorm._BatchNorm):layer.eval()
        neg_iter=iter(neg_loader);tick=time.time();loss_sum=0.;n=0
        for x,y,_ in train_loader:
            try:xo,_,_=next(neg_iter)
            except StopIteration:neg_iter=iter(neg_loader);xo,_,_=next(neg_iter)
            x=x.cuda(non_blocking=True);y=y.cuda(non_blocking=True);xo=xo.cuda(non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast('cuda',dtype=torch.bfloat16):
                logits=model(torch.cat([x,xo],0).contiguous(memory_format=torch.channels_last))
                supervised=torch.nn.functional.cross_entropy(logits[:len(x)],y,label_smoothing=.05)
                uniform=-torch.log_softmax(logits[len(x):].float(),dim=1).mean()
                loss=supervised+.1*uniform
            if not torch.isfinite(loss):raise ValueError('Non-finite corrective loss')
            loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5);optimizer.step();loss_sum+=loss.item()*len(y);n+=len(y)
        score=validation(model,val_loader);scheduler.step()
        ck=dict(model={k:v.detach().cpu() for k,v in model.state_dict().items()},epoch=epoch+1,best_val=score['top1'],config=config,labels=state['labels'],manifest_sha256=sha,negative_manifest_sha256=negsha)
        torch.save(ck,out/f'epoch-{epoch+1}.pt')
        torch.save(dict(ck,optimizer=optimizer.state_dict(),scheduler=scheduler.state_dict()),out/'last.pt')
        row=dict(epoch=epoch+1,loss=loss_sum/n,val=score,seconds=time.time()-tick,gpu_peak_bytes=torch.cuda.max_memory_allocated());(out/'history.jsonl').open('a').write(json.dumps(row)+'\n');print(json.dumps(row),flush=True)
    (out/'run_status.json').write_text(json.dumps(dict(status='completed',epochs=4,seconds=time.time()-begin),indent=2))


if __name__=='__main__':main()
