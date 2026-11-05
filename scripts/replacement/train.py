"""Bounded, checkpointed RTX training and inference on a frozen grouped manifest."""
import argparse
import hashlib
import json
import os
import random
import shutil
import time
from pathlib import Path

import numpy as np
import PIL
from PIL import Image
import psutil
import torch
import torchvision
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler
from torchvision import transforms as T
from model import LABELS, SOURCE, make_model, load_checkpoint
from labels import add_labels, read_labels, check_labels
from synthetic import augment


def seed_everything(seed):
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed); torch.cuda.manual_seed_all(seed)


class Images(Dataset):
    def __init__(self,rows,size,training=False,labels=None,backgrounds=(),synthetic_probability=.6):
        self.rows=rows; self.labels=read_labels() if labels is None else labels
        self.targets={r['id']:i for i,r in enumerate(self.labels)}
        self.backgrounds=backgrounds; self.synthetic_probability=synthetic_probability
        # App import centers a square then scales. PIL approximates CoreGraphics;
        # Apple golden-pixel harness is the final preprocessing parity gate.
        if training:
            self.transform=T.Compose([T.RandomResizedCrop(size,scale=(.65,1),ratio=(.85,1.18)),T.RandomHorizontalFlip(),T.RandomRotation(12,fill=255),T.ColorJitter(.2,.2,.15,.025),T.ToTensor()])
        else: self.transform=T.Compose([T.CenterCrop(size=1),T.ToTensor()])
        self.size=size; self.training=training
    def __len__(self): return len(self.rows)
    def __getitem__(self,i):
        row=self.rows[i]
        with Image.open(row.get('alpha_path',row['path']) if self.training else row['path']) as src:
            rgba=src.convert('RGBA')
            im=Image.alpha_composite(Image.new('RGBA',rgba.size,'white'),rgba).convert('RGB')
            if self.training:
                if row.get('alpha_path') and random.random()<self.synthetic_probability:
                    im=augment(src,self.size,rng=random,backgrounds=self.backgrounds)
                    x=T.functional.to_tensor(im)
                else: x=self.transform(im)
            else:
                side=min(im.size); left=(im.width-side)//2; top=(im.height-side)//2
                im=im.crop((left,top,left+side,top+side)).resize((self.size,self.size),Image.Resampling.BILINEAR)
                x=T.functional.to_tensor(im)
        target=self.targets[row['target_id']] if row['target_id'] is not None else -1
        return x,target,i


def rows_from(manifest,split):
    return [r for r in (json.loads(s) for s in manifest.read_text().splitlines()) if r['use'] and r['split'] in split.split(',')]


def loader(rows,args,training=False):
    sampler=None
    if training and getattr(args,'balanced_sampling',False):
        sampler=WeightedRandomSampler(sampling_weights(rows),len(rows),replacement=True)
    dataset=Images(rows,args.size,training,read_labels(args.labels),getattr(args,'backgrounds',()),getattr(args,'synthetic_probability',.6))
    return DataLoader(dataset,batch_size=args.batch,shuffle=training and sampler is None,sampler=sampler,
                      num_workers=args.workers,pin_memory=True,persistent_workers=False)


def sampling_weights(rows):
    from collections import Counter
    counts=Counter(r['target_id'] for r in rows)
    if None in counts: raise ValueError('balanced supervised sampling requires known targets')
    return torch.tensor([counts[r['target_id']]**-.5 for r in rows],dtype=torch.double)


def training_backgrounds(manifest, negative_manifest):
    if not negative_manifest or not negative_manifest.exists(): return []
    frozen=[json.loads(s) for s in manifest.read_text(encoding='utf-8').splitlines()]
    held=[r for r in frozen if r['split']!='train']
    forbidden={r['sha256'] for r in held}; groups={r['group'] for r in held}
    rows=[r for r in (json.loads(s) for s in negative_manifest.read_text(encoding='utf-8').splitlines())
          if r['use'] and r['target_id'] is None and r['split'] in ('train','train_ood_new')]
    if any(r['sha256'] in forbidden or r['group'] in groups for r in rows):
        raise ValueError('Synthetic background overlaps frozen evaluation')
    return [r['path'] for r in rows]


@torch.inference_mode()
def validation(model, batches):
    model.eval(); total=correct=0; loss=0.
    for x,y,_ in batches:
        x=x.cuda(non_blocking=True); y=y.cuda(non_blocking=True)
        out=model(x); loss+=torch.nn.functional.cross_entropy(out,y,reduction='sum').item()
        correct+=(out.argmax(1)==y).sum().item(); total+=len(y)
    return dict(top1=correct/total if total else None,loss=loss/total if total else None,n=total)


def run_train(args):
    if args.out.exists() and not args.resume: raise ValueError('Run already exists; resume explicitly or use a fresh path')
    args.out.mkdir(parents=True,exist_ok=True)
    lock=args.manifest.parent/'split_lock.json'
    assert lock.exists(),'Freeze data first'
    manifest_sha=hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    assert json.loads(lock.read_text())['manifest_sha256']==manifest_sha
    tr=rows_from(args.manifest,'train'); va=rows_from(args.manifest,'val')
    labels=read_labels(args.labels)
    assert set(r['target_id'] for r in tr)=={r['id'] for r in labels},'Training rows must cover every supplied label'
    if not va: raise ValueError('No independent validation groups; cannot select a checkpoint')
    args.backgrounds=training_backgrounds(args.manifest,args.background_manifest)
    args.background_manifest_sha256=hashlib.sha256(args.background_manifest.read_bytes()).hexdigest() if args.background_manifest else None
    assert not {r['group'] for r in tr}&{r['group'] for r in va}
    model=make_model(args.arch,pretrained=not args.init_checkpoint and not args.resume,num_classes=len(labels),source=args.sources).cuda().to(memory_format=torch.channels_last)
    if args.init_checkpoint:
        initial=torch.load(args.init_checkpoint,map_location='cpu',weights_only=True)
        check_labels(initial,labels)
        if initial['manifest_sha256']!=manifest_sha or initial['config']['arch']!=args.arch or initial['config']['size']!=args.size:
            raise ValueError('Explicit continuation checkpoint contract mismatch')
        model.load_state_dict(initial['model'],strict=True)
    optimizer=torch.optim.AdamW(model.parameters(),lr=args.lr,weight_decay=.01)
    scheduler=torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,T_max=args.epochs)
    start=0; best=-1.
    if args.resume:
        state=torch.load(args.out/'last.pt',map_location='cpu',weights_only=True)
        check_labels(state,labels)
        if state['manifest_sha256']!=manifest_sha: raise ValueError('resume manifest mismatch')
        if state['config']['arch']!=args.arch or state['config']['size']!=args.size: raise ValueError('resume model config mismatch')
        for key in ['seed','epochs','lr','batch','workers']:
            if state['config'][key]!=getattr(args,key): raise ValueError(f'resume {key} mismatch; create a new explicit continuation run')
        for key,default in [('balanced_sampling',False),('synthetic_probability',.6),('background_manifest',None),('background_manifest_sha256',None)]:
            value=getattr(args,key);value=str(value) if isinstance(value,Path) else value
            if state['config'].get(key,default)!=value: raise ValueError(f'resume {key} mismatch')
        model.load_state_dict(state['model']); optimizer.load_state_dict(state['optimizer']); scheduler.load_state_dict(state['scheduler'])
        start=state['epoch']; best=state['best_val']
    train_loader=loader(tr,args,True); val_loader=loader(va,args)
    config={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()}
    if args.init_checkpoint: config['init_checkpoint_sha256']=hashlib.sha256(args.init_checkpoint.read_bytes()).hexdigest()
    code_hashes={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in Path('scripts/replacement').glob('*.py')}
    (args.out/'source').mkdir(exist_ok=True)
    for file in Path('scripts/replacement').glob('*.py'): shutil.copy2(file,args.out/'source'/file.name)
    env=dict(python=os.sys.version,torch=str(torch.__version__),torchvision=str(torchvision.__version__),PIL=PIL.__version__,cuda=torch.version.cuda,gpu=torch.cuda.get_device_name(0),seed=args.seed,parameters=sum(p.numel() for p in model.parameters()),config=config,manifest_sha256=manifest_sha,code_hashes=code_hashes)
    (args.out/'environment.json').write_text(json.dumps(env,indent=2))
    began=time.time(); interrupted=False; last_epoch=start
    torch.cuda.reset_peak_memory_stats()
    for epoch in range(start,args.epochs):
        if time.time()-began>args.max_minutes*60: interrupted=True; break
        # Seed per epoch makes epoch-boundary recovery reproducible (worker count fixed).
        seed_everything(args.seed+epoch); tick=time.time(); model.train(); loss_sum=0.; total=0
        for x,y,_ in train_loader:
            x=x.cuda(non_blocking=True).contiguous(memory_format=torch.channels_last); y=y.cuda(non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast('cuda',dtype=torch.bfloat16):
                logits=model(x); loss=torch.nn.functional.cross_entropy(logits,y,label_smoothing=.05)
            loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(),5.); optimizer.step()
            loss_sum+=loss.item()*len(y); total+=len(y)
        scores=validation(model,val_loader); scheduler.step()
        last_epoch=epoch+1
        improved=scores['top1']>best; best=max(best,scores['top1'])
        # State dict only: no remote class or pickled module needed to restore.
        checkpoint=dict(model={k:v.detach().cpu() for k,v in model.state_dict().items()},optimizer=optimizer.state_dict(),scheduler=scheduler.state_dict(),epoch=epoch+1,best_val=best,config=config,labels=labels,manifest_sha256=manifest_sha)
        temp=args.out/'last.partial'; torch.save(checkpoint,temp); temp.replace(args.out/'last.pt')
        if improved:
            torch.save(dict(model=checkpoint['model'],epoch=epoch+1,best_val=best,config=config,labels=labels,manifest_sha256=manifest_sha),args.out/'best.pt')
        row=dict(epoch=epoch+1,train_loss=loss_sum/total,val=scores,seconds=time.time()-tick,elapsed_seconds=time.time()-began,gpu_peak_bytes=torch.cuda.max_memory_allocated(),rss_bytes=psutil.Process().memory_info().rss)
        with (args.out/'history.jsonl').open('a') as f: f.write(json.dumps(row)+'\n')
        print(json.dumps(row),flush=True)
    (args.out/'run_status.json').write_text(json.dumps(dict(status='budget_checkpointed' if interrupted else 'completed',elapsed_seconds=time.time()-began,best_val=best,last_epoch=last_epoch),indent=2))


@torch.inference_mode()
def predict(args):
    labels=read_labels(args.labels)
    if args.arch!='baseline' and not args.checkpoint: raise ValueError('prediction requires --checkpoint')
    if args.arch=='baseline' and labels!=read_labels(): raise ValueError('Historical baseline labels mismatch')
    if args.arch=='baseline' and args.size!=224: raise ValueError('Shipped baseline contract requires 224px input')
    manifest_sha=hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    lock=json.loads((args.manifest.parent/'split_lock.json').read_text())
    if lock['manifest_sha256']!=manifest_sha: raise ValueError('evaluation split lock mismatch')
    if args.split.find('test')>=0 and not args.final:
        raise ValueError('Test is locked: select on validation first and pass --final with selection record')
    if args.final:
        selection=json.loads(args.selection.read_text())
        if selection['manifest_sha256']!=manifest_sha: raise ValueError('selection manifest mismatch')
        if 'labels' in selection: check_labels(selection,labels)
        if args.arch!='baseline':
            if selection['checkpoint_sha256']!=hashlib.sha256(args.checkpoint.read_bytes()).hexdigest() or selection['size']!=args.size or selection['arch']!=args.arch:
                raise ValueError('final checkpoint does not match frozen selection')
    rows=rows_from(args.manifest,args.split)
    model=load_checkpoint(args.checkpoint,args.labels)[0] if args.checkpoint else make_model('baseline',num_classes=len(labels),source=args.sources)
    if args.checkpoint:
        state=torch.load(args.checkpoint,map_location='cpu',weights_only=True)
        if state['config']['size']!=args.size: raise ValueError('checkpoint resolution mismatch')
        if state['config']['arch']!=args.arch: raise ValueError('checkpoint architecture mismatch')
        if state['manifest_sha256']!=manifest_sha: raise ValueError('checkpoint evaluation manifest mismatch')
    model=model.eval().cuda(); args.out.parent.mkdir(parents=True,exist_ok=True)
    began=time.time()
    with args.out.open('w',encoding='utf-8') as f:
        for x,_,ix in loader(rows,args):
            out=model(x.cuda()).float().cpu().tolist()
            for i,logits in zip(ix.tolist(),out):
                r=rows[i]
                output={k:r[k] for k in ['sha256','group','target_id','source','domain','split']}
                output.update({k:r[k] for k in ['form','shiny','generation','national_dex_id','baseline_exposure','family','card_art_crop','synthetic'] if k in r})
                output.update(logits=logits,label_ids=[l['id'] for l in labels]); f.write(json.dumps(output)+'\n')
    metadata=dict(rows=len(rows),seconds=time.time()-began,arch=args.arch,checkpoint=str(args.checkpoint),checkpoint_sha256=hashlib.sha256(args.checkpoint.read_bytes()).hexdigest() if args.checkpoint else None,predictions_sha256=hashlib.sha256(args.out.read_bytes()).hexdigest(),size=args.size,manifest_sha256=manifest_sha,preprocess='PIL EXIF decoded in ingest, white alpha, center square, RGB bilinear resize; approximation of app CoreGraphics pending Apple pixel parity')
    args.out.with_suffix('.metadata.json').write_text(json.dumps(metadata,indent=2)); print(json.dumps(metadata),flush=True)


def main():
    p=argparse.ArgumentParser(); p.add_argument('action',choices=['train','predict'])
    p.add_argument('--arch',choices=['baseline','mobilenet_v3_large','efficientnet_b0'],default='mobilenet_v3_large')
    p.add_argument('--manifest',type=Path,default=Path('artifacts/replacement/data/manifest.jsonl'))
    p.add_argument('--sources',type=Path,default=SOURCE,help='cached ImageNet weights root')
    p.add_argument('--checkpoint',type=Path); p.add_argument('--init-checkpoint',type=Path); p.add_argument('--out',type=Path,required=True)
    p.add_argument('--size',type=int,default=224); p.add_argument('--epochs',type=int,default=8)
    p.add_argument('--batch',type=int,default=64); p.add_argument('--workers',type=int,default=4)
    p.add_argument('--seed',type=int,default=20261027); p.add_argument('--lr',type=float,default=.0003)
    p.add_argument('--max-minutes',type=float,default=35); p.add_argument('--resume',action='store_true')
    add_labels(p)
    p.add_argument('--balanced-sampling',action=argparse.BooleanOptionalAction,default=False)
    p.add_argument('--synthetic-probability',type=float,default=.6)
    p.add_argument('--background-manifest',type=Path,help='train-only COCO negative manifest; absent uses color/gradient backgrounds')
    p.add_argument('--selection',type=Path,default=Path('artifacts/replacement/selection.json'))
    p.add_argument('--split',default='val'); p.add_argument('--final',action='store_true')
    a=p.parse_args()
    if not 0<=a.synthetic_probability<=1 or a.max_minutes<=0 or a.batch<1 or a.epochs<1: p.error('invalid training budget/augmentation settings')
    assert torch.cuda.is_available(),'CUDA GPU required'
    torch.set_num_threads(6); seed_everything(a.seed)
    # No torch.compile or downloads; GPU benchmark determinism depends on platform.
    torch.backends.cudnn.benchmark=False
    if a.action=='train': run_train(a)
    else: predict(a)


if __name__=='__main__': main()
