"""Validation-only selection and frozen final reporting; reference is optional."""
import os
os.environ['OPENBLAS_NUM_THREADS']='1'
os.environ['OMP_NUM_THREADS']='1'
os.environ['MKL_NUM_THREADS']='1'
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
import torch
from labels import add_labels, read_labels
from metrics import load_rows, metrics, compare_models


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2,allow_nan=False),encoding='utf-8')


def compatible_baseline(path,labels):
    if not path.exists(): return False,'Baseline checkpoint missing'
    state=torch.load(path,map_location='cpu',weights_only=True)
    if state.get('labels')!=labels: return False,'Baseline has different labels; paired comparison skipped'
    return True,None


def main():
    p=argparse.ArgumentParser(description=__doc__);add_labels(p)
    p.add_argument('--root',type=Path,default=Path('artifacts/replacement'))
    p.add_argument('--candidate',type=Path,action='append',help='repeat for bounded candidate checkpoints')
    p.add_argument('--baseline',type=Path,help='optional same-label checkpoint')
    p.add_argument('--handoff',action=argparse.BooleanOptionalAction,default=True)
    a=p.parse_args();root=a.root;labels=read_labels(a.labels)
    manifest=root/'data/manifest.jsonl';manifest_sha=sha(manifest); selection_path=root/'selection.json'
    root.joinpath('policies').mkdir(parents=True,exist_ok=True)
    base_checkpoint=a.baseline or root/'baseline-reference.pt'
    has_baseline,skip_reason=compatible_baseline(base_checkpoint,labels)
    write(root/'reports/baseline-comparison.json',dict(status='available' if has_baseline else 'skipped',reason=skip_reason))

    def run(script,*args):
        subprocess.run([sys.executable,f'scripts/replacement/{script}',*map(str,args),'--labels',str(a.labels)],check=True)

    def predict(name,checkpoint,split,final=False):
        state=torch.load(checkpoint,map_location='cpu',weights_only=True)
        if state['labels']!=labels: raise ValueError('checkpoint labels mismatch')
        if state['manifest_sha256']!=manifest_sha: raise ValueError('checkpoint evaluation manifest mismatch')
        path=root/'predictions'/f'{name}.jsonl'; receipt=path.with_suffix('.metadata.json')
        expected=dict(checkpoint_sha256=sha(checkpoint),manifest_sha256=manifest_sha,
                      arch=state['config']['arch'],size=state['config']['size'])
        if path.exists() and receipt.exists():
            meta=json.loads(receipt.read_text())
            if any(meta.get(k)!=v for k,v in expected.items()) or meta.get('predictions_sha256')!=sha(path):
                raise ValueError(f'Existing prediction provenance mismatch: {path}')
            return path
        frozen=root/'policies/baseline.json' if name=='baseline-test' else selection_path
        args=['predict','--arch',state['config']['arch'],'--size',state['config']['size'],
              '--manifest',manifest,'--checkpoint',checkpoint,'--split',split,'--out',path,'--selection',frozen]
        if final: args+=['--final']
        run('train.py',*args);return path

    def calibrate(name,checkpoint,pred):
        out=root/'policies'/f'{name}.json'
        if not out.exists(): run('choose_candidate.py','--checkpoint',checkpoint,'--predictions',pred,'--out',out)
        record=json.loads(out.read_text())
        if record['checkpoint_sha256']!=sha(checkpoint) or record['manifest_sha256']!=manifest_sha or record['validation_predictions_sha256']!=sha(pred):
            raise ValueError('policy provenance mismatch')
        return record

    baseline_top1=None
    if has_baseline:
        pred=predict('baseline-policy-val',base_checkpoint,'val,ood_val')
        calibrate('baseline',base_checkpoint,pred)
        baseline_top1=metrics(load_rows(pred),labels)['top1']
    if not selection_path.exists():
        candidates=a.candidate
        if candidates is None:
            candidates=[root/f'runs/{name}/best.pt' for name in
                ('mobilenet224','efficientnet224','efficientnet224-continued')]
            candidates=[x for x in candidates if x.exists()]+sorted(root.glob('runs/efficientnet224-oe/epoch-*.pt'))
        if not candidates: raise ValueError('No candidate checkpoints; supply --candidate')
        choices=[]
        for i,checkpoint in enumerate(candidates):
            name=f'candidate-{i}';pred=predict(name+'-val',checkpoint,'val,ood_val')
            record=calibrate(name,checkpoint,pred);summary=metrics(load_rows(pred),labels)
            policy=record['policy'];utility=0 if policy.get('abstain_all') else policy['validation_known_coverage']*policy['validation_known_accuracy']
            choices.append(dict(name=name,record=record,top1=summary['top1'],utility=utility,checkpoint=str(checkpoint)))
        floor=max(x['top1'] for x in choices)-.005
        if baseline_top1 is not None: floor=max(floor,baseline_top1)
        eligible=[x for x in choices if x['top1']>=floor]
        if not eligible: raise ValueError('No candidate reaches the validation accuracy floor')
        winner=max(eligible,key=lambda x:(x['utility'],x['top1'],-Path(x['checkpoint']).stat().st_size))
        selection=winner['record'];selection.update(research_selection=True,promotion=False,
            selected_variant=winner['name'],validation_accuracy_floor=floor,baseline_val_top1=baseline_top1,
            baseline_comparison_reason=skip_reason,
            selection_rule='Validation only: within 0.5pp of best top1 (and >=same-label baseline if supplied), maximize correctly accepted known coverage; frozen per-source FAR/precision constraints',
            alternatives=[{k:v for k,v in x.items() if k!='record'} for x in choices])
        write(selection_path,selection)
    selection=json.loads(selection_path.read_text())
    selected_labels=selection.get('labels')
    if selected_labels is None:
        selected_labels=torch.load(selection['checkpoint'],map_location='cpu',weights_only=True)['labels']
    if selection['manifest_sha256']!=manifest_sha or selected_labels!=labels:
        raise ValueError('Frozen selection manifest/labels mismatch')
    cand_test=predict('selected-test',Path(selection['checkpoint']),'test_public,ood_test_public',True)
    rows=load_rows(cand_test)
    write(root/'reports/selected-public.json',metrics(rows,labels))
    arguments=['--candidate',cand_test,'--manifest',manifest,'--out',root/'reports/final-analysis','--selection',selection_path]
    if has_baseline:
        base_test=predict('baseline-test',base_checkpoint,'test_public,ood_test_public',True)
        base_rows=load_rows(base_test)
        write(root/'reports/comparison-all-public.json',compare_models(base_rows,rows,labels))
        arguments+=['--baseline',base_test]
        scope_path=root/'evaluation_scope.json'
        if scope_path.exists():
            scope=json.loads(scope_path.read_text())
            if scope['manifest_sha256']!=manifest_sha: raise ValueError('evaluation scope manifest mismatch')
            ids=set(scope['sha256s']);pa=[r for r in base_rows if r['sha256'] in ids];pb=[r for r in rows if r['sha256'] in ids]
            if len(pa)!=len(ids) or len(pb)!=len(ids): raise ValueError('evaluation scope population mismatch')
            if ids: write(root/'reports/comparison-public-unknown-exposure.json',compare_models(pa,pb,labels))
        basepolicy=json.loads((root/'policies/baseline.json').read_text())['policy'];policy=selection['policy']
        if not basepolicy.get('abstain_all') and not policy.get('abstain_all'):
            write(root/'reports/comparison-frozen-policies.json',compare_models(base_rows,rows,labels,
                confidence=policy['confidence'],margin=policy['margin'],temperature=policy['temperature'],
                baseline_confidence=basepolicy['confidence'],baseline_margin=basepolicy['margin'],baseline_temperature=basepolicy['temperature']))
    run('analyze_predictions.py',*arguments)
    if a.handoff and not (root/'handoff/bundle_receipt.json').exists(): run('prepare_handoff.py','--root',root)
    write(root/'finish_state.json',dict(stage='completed-windows-pending-independent-camera-and-apple',selection_frozen=True,baseline_comparison=skip_reason or 'available'))


if __name__=='__main__':main()
