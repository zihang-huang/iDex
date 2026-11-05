"""Freeze candidate and diagnostic uncertainty policy using validation only."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import torch
from metrics import load_rows,metrics
from labels import add_labels, read_labels, check_labels


def main():
    p=argparse.ArgumentParser();p.add_argument('--checkpoint',type=Path,required=True)
    p.add_argument('--predictions',type=Path,required=True);p.add_argument('--out',type=Path,default=Path('artifacts/replacement/selection.json'))
    add_labels(p)
    a=p.parse_args()
    if a.out.exists(): raise ValueError('Selection already frozen; no overwrite')
    rows=load_rows(a.predictions)
    if any(r['split'] not in ['val','ood_val'] for r in rows): raise ValueError('Only validation inputs may choose thresholds')
    state=torch.load(a.checkpoint,map_location='cpu',weights_only=True)
    check_labels(state,read_labels(a.labels))
    receipt=json.loads(a.predictions.with_suffix('.metadata.json').read_text())
    actual_checkpoint_sha=hashlib.sha256(a.checkpoint.read_bytes()).hexdigest()
    manifest=Path(state['config']['manifest']);sha=hashlib.sha256(manifest.read_bytes()).hexdigest()
    expected_receipt=dict(checkpoint_sha256=actual_checkpoint_sha,manifest_sha256=sha,arch=state['config']['arch'],size=state['config']['size'],predictions_sha256=hashlib.sha256(a.predictions.read_bytes()).hexdigest())
    for key,value in expected_receipt.items():
        if receipt.get(key)!=value: raise ValueError(f'prediction receipt mismatch: {key}')
    expected={r['sha256']:r for r in (json.loads(s) for s in manifest.read_text().splitlines()) if r['use'] and r['split'] in ['val','ood_val']}
    if len(rows)!=len(expected) or {r['sha256'] for r in rows}!=set(expected): raise ValueError('Prediction validation population mismatch')
    for row in rows:
        truth=expected[row['sha256']]
        for key in ['group','target_id','source','domain','split']:
            if row[key]!=truth[key]: raise ValueError(f'prediction metadata mismatch: {key}')
        if row.get('label_ids')!=[x['id'] for x in state['labels']]: raise ValueError('explicit label order required')
    metrics(rows,state['labels'])  # strict finite/logit/count/identity validation
    ids=[x['id'] for x in state['labels']];mapping={x:i for i,x in enumerate(ids)}
    x=np.asarray([r['logits'] for r in rows],dtype=np.float64); y=np.asarray([mapping[r['target_id']] if r['target_id'] else -1 for r in rows])
    known=y>=0
    if not known.any() or known.all(): raise ValueError('Need positive and negative validation data')
    losses=[]
    for t in [.5,.75,1,1.25,1.5,2,3,4,5]:
        z=x[known]/t; z-=z.max(1,keepdims=True); loss=float((np.log(np.exp(z).sum(1))-z[np.arange(known.sum()),y[known]]).mean());losses.append((loss,t))
    temperature=min(losses)[1]
    z=x/temperature;z-=z.max(1,keepdims=True);pval=np.exp(z);pval/=pval.sum(1,keepdims=True)
    confidence=pval.max(1);rank=np.argsort(x,axis=1);margin=x[np.arange(len(x)),rank[:,-1]]-x[np.arange(len(x)),rank[:,-2]]
    correct=rank[:,-1]==y
    choices=[]
    for c in [.25,.4,.5,.6,.7,.8,.85,.9,.95,.975,.99,.995]:
        for m in [.5,1,2,3,4,6,8,12]:
            accepted=(confidence>=c)&(margin>=m);positive=accepted&known
            far=float(accepted[~known].mean()); coverage=float(positive.sum()/known.sum());accuracy=float(correct[positive].mean()) if positive.any() else None
            # Separate-source diagnostic constraints prevent a large OOD pool
            # from hiding failure on the small natural-object validation set.
            source_fars={source:float(accepted[[r['source']==source and r['target_id'] is None for r in rows]].mean()) for source in sorted({r['source'] for r in rows if r['target_id'] is None})}
            if accuracy is not None and accuracy>=.95 and all(v<=.05 for v in source_fars.values()):
                choices.append((coverage,-c,-m,dict(confidence=c,margin=m,temperature=temperature,validation_known_coverage=coverage,validation_known_accuracy=accuracy,validation_unknown_far=far,validation_source_fars=source_fars)))
    policy=max(choices,key=lambda a:a[:3])[3] if choices else dict(enabled=False,abstain_all=True,temperature=temperature,status='No nonempty policy satisfies the predeclared diagnostic constraints; consumer must unconditionally abstain')
    if choices: policy.update(enabled=True,abstain_all=False)
    if sha!=state['manifest_sha256']: raise ValueError('manifest mismatch')
    record=dict(checkpoint=str(a.checkpoint),checkpoint_sha256=hashlib.sha256(a.checkpoint.read_bytes()).hexdigest(),arch=state['config']['arch'],size=state['config']['size'],manifest_sha256=sha,validation_predictions_sha256=hashlib.sha256(a.predictions.read_bytes()).hexdigest(),selection_rule='Validation top1 among bounded candidates; diagnostic temperature min known NLL, threshold max known coverage with >=95% accepted known precision and <=5% FAR per negative source',policy=policy,promotion=False,reason='Independent camera test, dataset rights and Apple validation pending')
    record.update(labels=state['labels'],validation_metrics=metrics(rows,state['labels']))
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(record,indent=2));print(json.dumps(record,indent=2))


if __name__=='__main__':main()
