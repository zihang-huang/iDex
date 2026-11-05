"""Create validation-only golden RGB/logit fixtures; optionally consume Apple RGB dumps."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image
import torch
from model import make_model,load_checkpoint,LABELS
from labels import add_labels, read_labels


def main():
    p=argparse.ArgumentParser();p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--apple-rgb-dir',type=Path);p.add_argument('--reference-checkpoint',type=Path,help='Optional same-label reference; absent uses candidate for export parity')
    p.add_argument('--manifest',type=Path,default=Path('artifacts/replacement/data/manifest.jsonl'));add_labels(p)
    a=p.parse_args();torch.set_num_threads(6)
    if a.out.exists(): raise ValueError('Use fresh fixture destination')
    a.out.mkdir(parents=True)
    candidate,state=load_checkpoint(a.checkpoint,a.labels)
    baseline=load_checkpoint(a.reference_checkpoint,a.labels)[0] if a.reference_checkpoint else (make_model('baseline') if a.labels==LABELS else candidate)
    candidate.eval();baseline.eval()
    labels=read_labels(a.labels);size=state['config']['size']
    rows=[json.loads(s) for s in a.manifest.read_text().splitlines()]
    selected=[]
    for dex in [r['id'] for r in labels]:
        eligible=[r for r in rows if r['use'] and r['split']=='val' and r['target_id']==dex]
        if eligible:selected.append(sorted(eligible,key=lambda r:r['sha256'])[0])
    selected+=sorted([r for r in rows if r['use'] and r['split']=='ood_val' and r['source']=='coco128'],key=lambda r:r['sha256'])[:20]
    fixtures=[]
    with torch.inference_mode():
        for i,row in enumerate(selected):
            im=Image.open(row['path']).convert('RGB');side=min(im.size);left=(im.width-side)//2;top=(im.height-side)//2
            im=im.crop((left,top,left+side,top+side));image_file=f'{i:03}-{row["sha256"][:12]}.png'
            # Fixed square fixture removes resize ambiguity for same-resolution models.
            im.resize((size,size),Image.Resampling.BILINEAR).save(a.out/image_file)
            fixture=dict(id=row['sha256'],image=image_file,group=row['group'],target_id=row['target_id'])
            for role,model,resolution in [('baseline',baseline,size if baseline is candidate else 224),('candidate',candidate,size)]:
                if a.apple_rgb_dir:
                    pixels=np.frombuffer((a.apple_rgb_dir/f'{role}-{i}-{resolution}x{resolution}.rgb').read_bytes(),dtype=np.uint8).reshape(resolution,resolution,3).copy()
                else:pixels=np.asarray(Image.open(a.out/image_file).resize((resolution,resolution),Image.Resampling.BILINEAR)).copy()
                x=torch.from_numpy(pixels).permute(2,0,1).unsqueeze(0).float()/255
                logits=model(x)[0].tolist();file=f'{i:03}-{role}-logits.json';(a.out/file).write_text(json.dumps(logits))
                fixture[f'{role}_reference_logits']=file
            fixtures.append(fixture)
    (a.out/'manifest.json').write_text(json.dumps(dict(fixtures=fixtures),indent=2))
    (a.out/'labels.json').write_text(json.dumps(labels,indent=2))
    (a.out/'receipt.json').write_text(json.dumps(dict(count=len(fixtures),checkpoint_sha256=hashlib.sha256(a.checkpoint.read_bytes()).hexdigest(),source='validation only',reference='CPU FP32; Apple exact RGB dumps' if a.apple_rgb_dir else 'CPU FP32; PIL final square RGB; verify against Apple dumped pixels',apple_parity='pending'),indent=2))
    print(f'{len(fixtures)} validation-only fixtures saved')


if __name__=='__main__':main()
