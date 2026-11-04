"""Offline national/legacy contracts. No downloads, training or model exports."""
import argparse
import collections
import copy
import hashlib
import io
import json
import random
import runpy
import sys
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import torch
from PIL import Image, ImageDraw

import acquire
import analyze_predictions
import choose_candidate
import data
import finish
import make_labels
import metrics
import model
import sources
import synthetic
import train
from labels import LABELS, add_labels, read_labels, label_ids
from splitting import split_classes

HERE=Path(__file__).resolve().parent
NATIONAL=HERE/'labels-national.json'


@pytest.fixture
def tmp_path():
    with tempfile.TemporaryDirectory(dir=HERE) as folder: yield Path(folder)


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def fixture(name): return json.loads((HERE/'testdata'/name).read_text(encoding='utf-8'))
def jsonl(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')


def prediction(index,target,labels,split='val',source='JJMack',winner=None):
    ids=label_ids(labels); logits=[0.]*len(ids)
    if winner is not None: logits[ids.index(winner)]=30.
    return dict(sha256=hashlib.sha256(str(index).encode()).hexdigest(),group=str(index),
                target_id=target,split=split,source=source,domain='offline_fixture',
                label_ids=ids,logits=logits)


def image_bytes(size=(96,96),alpha=False,seed=4):
    rng=np.random.default_rng(seed)
    im=Image.fromarray(rng.integers(0,256,(*size[::-1],3),dtype=np.uint8))
    if alpha:
        im=im.convert('RGBA'); im.putalpha(0);ImageDraw.Draw(im).ellipse((15,15,65,80),fill=(210,50,80,255))
    buf=io.BytesIO();im.save(buf,format='PNG');return buf.getvalue()


@pytest.mark.parametrize('path,count',[(LABELS,151),(NATIONAL,1025)])
def test_labels_infer_count_and_default(path,count):
    labels=read_labels(path);assert len(labels)==count
    parser=argparse.ArgumentParser();add_labels(parser)
    assert parser.parse_args([]).labels==LABELS
    assert len(read_labels(parser.parse_args(['--labels',str(path)]).labels))==count


def test_national_csv_prefix_and_generated_file_match():
    original=read_labels()
    csv='id,identifier\n'+''.join(f'{r["id"]},{r["name"]}\n' for r in read_labels(NATIONAL))
    result=make_labels.build_labels(csv,original)
    assert result==read_labels(NATIONAL) and result[:151]==original
    assert result[-1]==dict(id=1025,name='pecharunt')
    bad=copy.deepcopy(original);bad[0]['name']='wrong'
    with pytest.raises(ValueError,match='QUESTION: shipped label 1 differs'):
        make_labels.build_labels(csv,bad)


@pytest.mark.parametrize('labels',[[],[dict(id=1,name='a')],[dict(id=1,name='a'),dict(id=1,name='b')],
                                   [dict(id=True,name='a'),dict(id=2,name='b')]])
def test_invalid_labels_fail_early(labels):
    with pytest.raises(ValueError): label_ids(labels)


@pytest.mark.parametrize('path',[LABELS,NATIONAL])
def test_metrics_and_slices_use_label_count_and_catalog_generations(path):
    labels=read_labels(path);last=len(labels)
    rows=[prediction(1,1,labels,winner=1),prediction(2,last,labels,source='tcg',winner=1),
          prediction(3,None,labels,source='coco128')]
    report=metrics.metrics(rows,labels,bootstrap_replicates=4)
    assert report['top1']==.5 and report['top3']==.5
    assert len(report['per_class'])==last
    assert report['top_confusion_pairs']==[dict(target_id=last,predicted_id=1,count=1)]
    assert report['slices']['source']['tcg']['counts']['known']==1
    assert report['slices']['generation']['9' if last==1025 else '1']['counts']['known']>=1
    uniform=metrics.metrics([prediction('uniform',1,labels)],labels)
    assert uniform['nll']==pytest.approx(np.log(last))
    assert uniform['brier']==pytest.approx((last-1)/last)
    paired=metrics.compare_models(rows,rows[::-1],labels,replicates=4)
    assert paired['delta_candidate_minus_baseline']['top1']['estimate']==0


@pytest.mark.parametrize('arch',['mobilenet_v3_large','efficientnet_b0'])
@pytest.mark.parametrize('count',[151,1025])
def test_model_heads_and_tensor_checkpoint_contract(tmp_path,arch,count):
    labels=read_labels(NATIONAL if count==1025 else LABELS)
    built=model.make_model(arch,num_classes=count)
    assert built.backbone.classifier[-1].out_features==count
    checkpoint=tmp_path/'weights.pt'
    torch.save(dict(model=built.state_dict(),config=dict(arch=arch,size=224),labels=labels),checkpoint)
    restored,state=model.load_checkpoint(checkpoint,NATIONAL if count==1025 else LABELS)
    assert restored.backbone.classifier[-1].out_features==count
    if count==1025:
        with pytest.raises(ValueError,match='checkpoint labels mismatch'): model.load_checkpoint(checkpoint)


def test_sprite_response_front_families_and_host_validation():
    payload=fixture('sprites.json'); specs=sources.sprite_urls(payload)
    assert len(specs)==7
    assert {r['family'] for r in specs}=={'official-artwork','home','showdown','gen1','gen5','gen8'}
    assert not any('/back/' in r['url'] for r in specs)
    payload['sprites']['other']['home']['front_default']='https://example.invalid/1.png'
    with pytest.raises(ValueError,match='host/path'): sources.sprite_urls(payload)


def test_tcg_response_filter_and_identity():
    payload=fixture('tcg.json')
    assert [r['target_id'] for r in sources.tcg_cards(payload,{1,1025})]==[1025,1]
    assert sources.tcg_cards(payload,{1025})[0]['source_group']=='tcg:test-1'
    payload['data'][0]['nationalPokedexNumbers']=[1025,1025]
    assert not sources.tcg_cards(payload,{1025})


def test_new_source_retry_backoff_and_cached_resume(tmp_path):
    calls=[];sleeps=[];path=tmp_path/'page.json'
    def fetch(url,path,limit):
        calls.append(url)
        if len(calls)<3: raise urllib.error.HTTPError(url,503,'fixture',{},None)
        path.write_text('{}');return dict(path=str(path),sha256=sha(path))
    sources.retry_fetch(fetch,'https://fixture.invalid',path,limit=100,delay=1,sleep=sleeps.append)
    assert sleeps==[1,2,1] and len(calls)==3
    sleeps.clear()
    sources.retry_fetch(fetch,'https://fixture.invalid',path,limit=100,delay=1,sleep=sleeps.append)
    assert not sleeps
    with pytest.raises(urllib.error.HTTPError):
        sources.retry_fetch(lambda *args: (_ for _ in ()).throw(urllib.error.HTTPError('x',404,'no',{},None)),
                            'https://fixture.invalid',path,limit=100,sleep=sleeps.append)


def test_fetch_maps_http_status_to_urllib_error(tmp_path, monkeypatch):
    class Response:
        status_code=404; reason='Not Found'; headers={}
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def iter_content(self,size): return iter([b'not an image'])
    class Session:
        def get(self,url,**kwargs): return Response()
    monkeypatch.setattr(acquire,'_session',Session)
    with pytest.raises(urllib.error.HTTPError) as error:
        acquire.fetch('https://fixture.invalid/x.png',tmp_path/'x.png',100)
    assert error.value.code==404 and not list(tmp_path.iterdir())


@pytest.mark.parametrize('workers',[1,3])
def test_sprite_acquisition_gif_first_frame_size_exclusion_and_receipts(tmp_path, workers):
    payload=fixture('sprites.json');calls=[]
    def fetch(url,target,limit):
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():
            calls.append(url)
            if '/api/v2/' in url: target.write_text(json.dumps(payload))
            elif url.endswith('.gif'):
                a=Image.new('RGB',(96,96),'red');b=Image.new('RGB',(96,96),'blue')
                a.save(target,format='GIF',save_all=True,append_images=[b])
            else: target.write_bytes(image_bytes((32,32) if '/icons/' in url else (96,96),True))
        return dict(url=url,path=str(target),bytes=target.stat().st_size,sha256=sha(target))
    sources.acquire_sprites(tmp_path,[dict(id=1025,name='pecharunt')],fetch,0,workers=workers)
    rows=metrics.load_rows(tmp_path/'sprites/samples.jsonl')
    assert len(rows)==5 and all(r['source_group'].startswith('pokeapi:1025:') for r in rows)
    assert not any('/generation-i/' in url for url in calls)
    gif=next(r for r in rows if r['family']=='showdown')
    with Image.open(gif['path']) as im: assert im.getpixel((0,0))[:3]==(255,0,0) and not getattr(im,'is_animated',False)
    receipts=metrics.load_rows(tmp_path/'sprites/downloads.jsonl')
    assert all({'url','bytes','sha256'}<=r.keys() for r in receipts)
    previous=len(calls);sources.acquire_sprites(tmp_path,[dict(id=1025,name='pecharunt')],fetch,0)
    assert len(calls)==previous
    excluded=json.loads((tmp_path/'sprites/excluded.json').read_text())
    assert sorted(x['reason'] for x in excluded)==['known_undersized_dir','under_64px']


@pytest.mark.parametrize('workers',[1,3])
def test_tcg_acquisition_all_pages_and_crops_share_group(tmp_path, workers):
    calls=[];valid=fixture('tcg.json')['data'][0]
    def fetch(url,target,limit):
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():
            calls.append(url)
            if 'page=1&' in url:
                target.write_text(json.dumps(dict(page=1,pageSize=250,count=250,totalCount=251,
                    data=[valid]+[dict(supertype='Trainer') for _ in range(249)])))
            elif 'page=2&' in url:
                second=copy.deepcopy(valid);second.update(id='test-2',number='2')
                target.write_text(json.dumps(dict(page=2,pageSize=250,count=1,totalCount=251,data=[second])))
            else: target.write_bytes(image_bytes((245,342)))
        return dict(url=url,path=str(target),bytes=target.stat().st_size,sha256=sha(target))
    labels=[dict(id=1025,name='pecharunt')]
    sources.acquire_tcg(tmp_path,labels,fetch,0,workers=workers)
    rows=metrics.load_rows(tmp_path/'tcg/samples.jsonl')
    assert len(rows)==4 and rows[0]['source_group']==rows[1]['source_group']=='tcg:test-1'
    assert [r['card_art_crop'] for r in rows]==[False,True,False,True]
    with Image.open(rows[1]['path']) as im: assert im.size==(205,123)
    previous=len(calls);sources.acquire_tcg(tmp_path,labels,fetch,0);assert len(calls)==previous


@pytest.mark.parametrize('workers',[1,3])
def test_tcg_removed_card_image_is_excluded_other_errors_raise(tmp_path, workers):
    valid=fixture('tcg.json')['data'][0];gone=copy.deepcopy(valid);gone_url='https://images.pokemontcg.io/test/9.png'
    gone.update(id='test-9',number='9',images=dict(small=gone_url))
    def make_fetch(code):
        def fetch(url,target,limit):
            target.parent.mkdir(parents=True,exist_ok=True)
            if url==gone_url: raise urllib.error.HTTPError(url,code,'fixture',{},None)
            if not target.exists():
                if 'page=1&' in url:
                    target.write_text(json.dumps(dict(page=1,pageSize=250,count=2,totalCount=2,data=[gone,valid])))
                else: target.write_bytes(image_bytes((245,342)))
            return dict(url=url,path=str(target),bytes=target.stat().st_size,sha256=sha(target))
        return fetch
    labels=[dict(id=1025,name='pecharunt')]
    sources.acquire_tcg(tmp_path,labels,make_fetch(404),0,workers=workers)
    assert [r['card_id'] for r in metrics.load_rows(tmp_path/'tcg/samples.jsonl')]==['test-1','test-1']
    assert json.loads((tmp_path/'tcg/excluded.json').read_text())==[
        dict(card_id='test-9',target_id=1025,url=gone_url,reason='http_404')]
    with pytest.raises(urllib.error.HTTPError) as error:
        sources.acquire_tcg(tmp_path,labels,make_fetch(403),0,workers=workers)
    assert error.value.code==403


def test_jjmack_revision_is_required():
    sources.verify_jjmack(dict(sha=sources.JJMACK_REV))
    with pytest.raises(ValueError,match='revision mismatch'): sources.verify_jjmack(dict(sha='moving-head'))


@pytest.mark.parametrize('size',[64,224,320])
def test_synthetic_deterministic_size_and_transparency_only(size,tmp_path):
    with Image.open(io.BytesIO(image_bytes(alpha=True))) as im:
        a=synthetic.augment(im,size,rng=random.Random(17))
        b=synthetic.augment(im,size,rng=random.Random(17))
        c=synthetic.augment(im,size,rng=random.Random(18))
    assert a.size==(size,size) and a.mode=='RGB'
    assert a.tobytes()==b.tobytes() and a.tobytes()!=c.tobytes()
    with pytest.raises(ValueError,match='transparency'): synthetic.augment(Image.new('RGBA',(100,100),'red'))
    bg=tmp_path/'background.png';bg.write_bytes(image_bytes())
    with Image.open(io.BytesIO(image_bytes(alpha=True))) as im:
        assert synthetic.augment(im,size,rng=random.Random(0),backgrounds=[bg]).size==(size,size)


def test_split_degradation_missing_classes_and_photo_priority():
    rows=[];components={};byclass=collections.defaultdict(list)
    for target,count in enumerate((0,1,2,3,4,5,20),1):
        for j in range(count):
            i=len(rows);rows.append(dict(target_id=target,source='tcg' if j==count-1 else 'sprites'))
            components[i]=[i];byclass[target].append(i)
    counts,insufficient=split_classes(rows,components,byclass,range(1,8))
    assert counts==dict(enumerate((0,1,2,3,4,5,20),1))
    assert len(insufficient)==5
    for target in (2,3): assert {r['split'] for r in rows if r['target_id']==target}=={'train'}
    for target in (4,5,6,7):
        selected=[r for r in rows if r['target_id']==target]
        assert {r['split'] for r in selected}=={'train','val','test_public'}
        assert next(r for r in selected if r['source']=='tcg')['split']=='test_public'


def test_legacy_split_exact_seeded_assignments():
    rows=[dict(source='JJMack') for _ in range(17)];components={i:[i] for i in range(17)}
    split_classes(rows,components,{1:list(range(17))},[1])
    order=list(range(17));random.Random(20261027).shuffle(order)
    for j,index in enumerate(order): assert rows[index]['split']==('test_public' if j<3 else 'val' if j<6 else 'train')


def test_ingestion_national_jjmack_excludes_sentinels_and_keeps_alpha(tmp_path):
    root=tmp_path;source=root/'sources'/sources.JJMACK.replace('/','--');source.mkdir(parents=True)
    (source/'metadata.json').write_text(json.dumps(dict(sha=sources.JJMACK_REV)))
    names=['test']+[r['name'] for r in read_labels(NATIONAL)]+['test2']
    items=[dict(label=dex,image=dict(bytes=image_bytes(seed=dex)),file_name=f'{dex}.png') for dex in (0,1,1025,1026)]
    table=pa.Table.from_pylist(items).replace_schema_metadata({b'huggingface':json.dumps(dict(info=dict(features=dict(label=dict(names=names))))).encode()})
    pq.write_table(table,source/'train.parquet')
    image=root/'sprite.png';image.write_bytes(image_bytes(alpha=True,seed=90))
    jsonl(root/'sources/sprites/samples.jsonl',[dict(path=str(image),source='sprites',target_id=1025,
            source_group='pokeapi:1025:home',family='home')])
    argv=['data.py','--root',str(root),'--labels',str(NATIONAL)]
    with patch.object(sys,'argv',argv),patch('sys.stdout',io.StringIO()): data.main()
    rows=metrics.load_rows(root/'data/manifest.jsonl')
    assert len(rows)==3 and {r['target_id'] for r in rows}=={1,1025}
    sprite=next(r for r in rows if r['source']=='sprites')
    assert 'alpha_path' in sprite and sprite['generation']==9
    with Image.open(sprite['alpha_path']) as im: assert synthetic.has_transparency(im)
    lock=json.loads((root/'data/split_lock.json').read_text());assert len(lock['class_groups'])==1025
    assert lock['labels']==read_labels(NATIONAL) and len(lock['insufficient_groups'])==1025
    for script in ('refine_groups.py','audit.py','freeze_eval_scope.py'):
        with patch.object(sys,'argv',[script,'--root',str(root),'--labels',str(NATIONAL)]),patch('sys.stdout',io.StringIO()):
            runpy.run_path(str(HERE/script),run_name='__main__')
    refined=json.loads((root/'data/split_lock.json').read_text())
    assert len(refined['class_groups'])==1025 and refined['labels']==read_labels(NATIONAL)
    assert (root/'reports/audit/audit_summary.json').exists()


def test_inverse_sqrt_sampling_and_non_numeric_label_order(tmp_path):
    rows=[dict(target_id=1)]*4+[dict(target_id=2)]
    assert train.sampling_weights(rows).tolist()==[.5,.5,.5,.5,1.]
    im=tmp_path/'image.png';im.write_bytes(image_bytes())
    labels=read_labels(NATIONAL)[::-1]
    dataset=train.Images([dict(path=str(im),target_id=1025)],64,labels=labels)
    x,y,index=dataset[0];assert x.shape==(3,64,64) and y==0 and index==0
    legacy=train.Images([dict(path=str(im),target_id=151)],64)
    assert legacy[0][1]==150
    alpha=tmp_path/'alpha.png';alpha.write_bytes(image_bytes(alpha=True))
    augmented=train.Images([dict(path=str(im),alpha_path=str(alpha),target_id=1)],96,True,synthetic_probability=0)
    augmented.transform=lambda im: np.asarray(im).copy()
    assert tuple(augmented[0][0][0,0])==(255,255,255)
    args=argparse.Namespace(size=64,labels=NATIONAL,batch=2,workers=0,balanced_sampling=True)
    batches=train.loader([dict(path=str(im),target_id=1),dict(path=str(im),target_id=1025)],args,True)
    assert isinstance(batches.sampler,torch.utils.data.WeightedRandomSampler)
    args.balanced_sampling=False
    assert isinstance(train.loader(batches.dataset.rows,args,True).sampler,torch.utils.data.RandomSampler)
    assert isinstance(train.loader(batches.dataset.rows,args).sampler,torch.utils.data.SequentialSampler)


def test_synthetic_backgrounds_cannot_reuse_heldout_images(tmp_path):
    frozen=tmp_path/'manifest.jsonl';neg=tmp_path/'negative.jsonl'
    r=dict(sha256='held',group='held',target_id=None,split='ood_val',use=True,path='unused')
    jsonl(frozen,[r]);jsonl(neg,[dict(r,split='train_ood_new')])
    with pytest.raises(ValueError,match='overlaps frozen'): train.training_backgrounds(frozen,neg)
    jsonl(neg,[dict(r,sha256='new',group='new',split='train_ood_new')])
    assert train.training_backgrounds(frozen,neg)==['unused']


@pytest.mark.parametrize('path',[LABELS,NATIONAL])
def test_selection_cli_and_candidate_only_analysis(tmp_path,path):
    labels=read_labels(path);manifest=tmp_path/'manifest.jsonl';pred=tmp_path/'val.jsonl';ck=tmp_path/'candidate.pt'
    rows=[prediction('positive',len(labels),labels,winner=len(labels)),prediction('negative',None,labels,split='ood_val',source='coco128')]
    jsonl(manifest,[dict(r,use=True) for r in rows]);jsonl(pred,rows)
    torch.save(dict(model={},config=dict(arch='efficientnet_b0',size=224,manifest=str(manifest)),
                    labels=labels,manifest_sha256=sha(manifest)),ck)
    pred.with_suffix('.metadata.json').write_text(json.dumps(dict(checkpoint_sha256=sha(ck),manifest_sha256=sha(manifest),
        arch='efficientnet_b0',size=224,predictions_sha256=sha(pred))))
    selected=tmp_path/'selection.json'
    argv=['choose_candidate.py','--checkpoint',str(ck),'--predictions',str(pred),'--out',str(selected)]
    if path!=LABELS: argv+=['--labels',str(path)]
    with patch.object(sys,'argv',argv),patch('sys.stdout',io.StringIO()): choose_candidate.main()
    selection=json.loads(selected.read_text());assert selection['policy']['validation_known_accuracy']==1
    assert 'generation' in selection['validation_metrics']['slices']
    out=tmp_path/'analysis'
    argv=['analyze_predictions.py','--candidate',str(pred),'--manifest',str(manifest),'--out',str(out),'--selection',str(selected)]
    if path!=LABELS: argv+=['--labels',str(path)]
    with patch.object(sys,'argv',argv),patch('sys.stdout',io.StringIO()): analyze_predictions.main()
    report=json.loads((out/'report.json').read_text());assert report['paired_comparison']['status']=='skipped'
    assert report['candidate_original']['top1']==1
    assert finish.compatible_baseline(tmp_path/'absent.pt',labels)[0] is False
    wrong=tmp_path/'wrong.pt';torch.save(dict(labels=labels[::-1]),wrong)
    assert finish.compatible_baseline(wrong,labels)[0] is False


@pytest.mark.parametrize('path',[LABELS,NATIONAL])
def test_finish_without_baseline_uses_frozen_selection_and_writes_skip_report(tmp_path,path):
    labels=read_labels(path);root=tmp_path;manifest=root/'data/manifest.jsonl';ck=root/'candidate.pt'
    rows=[prediction('val',len(labels),labels,winner=len(labels)),
          prediction('ood-val',None,labels,split='ood_val',source='coco128'),
          prediction('test',1,labels,split='test_public',winner=1),
          prediction('ood-test',None,labels,split='ood_test_public',source='coco128')]
    jsonl(manifest,[dict(r,use=True) for r in rows])
    torch.save(dict(model={},config=dict(arch='efficientnet_b0',size=224,manifest=str(manifest)),
                    labels=labels,manifest_sha256=sha(manifest)),ck)
    calls=[]
    def run(command,check):
        calls.append(command)
        script=Path(command[1]).name;arguments=command[2:]
        if script=='train.py':
            split=arguments[arguments.index('--split')+1].split(',')
            out=Path(arguments[arguments.index('--out')+1]);subset=[r for r in rows if r['split'] in split]
            jsonl(out,subset)
            out.with_suffix('.metadata.json').write_text(json.dumps(dict(checkpoint_sha256=sha(ck),
                manifest_sha256=sha(manifest),arch='efficientnet_b0',size=224,predictions_sha256=sha(out))))
        else:
            with patch.object(sys,'argv',[script,*arguments]):
                (choose_candidate.main if script=='choose_candidate.py' else analyze_predictions.main)()
    argv=['finish.py','--root',str(root),'--candidate',str(ck),'--no-handoff']
    if path!=LABELS: argv+=['--labels',str(path)]
    with patch.object(sys,'argv',argv),patch('subprocess.run',run),patch('sys.stdout',io.StringIO()): finish.main()
    assert json.loads((root/'reports/baseline-comparison.json').read_text())['status']=='skipped'
    assert json.loads((root/'reports/selected-public.json').read_text())['top1']==1
    selection=(root/'selection.json').read_bytes();previous=len(calls)
    with patch.object(sys,'argv',argv),patch('subprocess.run',run),patch('sys.stdout',io.StringIO()): finish.main()
    assert (root/'selection.json').read_bytes()==selection
    assert len(calls)==previous+1  # Re-analysis only: no repeat predictions/selection.


@pytest.mark.parametrize('script',['acquire.py','acquire_oe.py','data.py','refine_groups.py','audit.py',
    'freeze_eval_scope.py','train.py','train_oe.py','pilot.py','prepare_baseline_reference.py',
    'prepare_handoff.py','export.py','fixtures.py','finish.py','analyze_predictions.py','choose_candidate.py'])
def test_cli_help_exits_before_download_training_or_export(script):
    with patch.object(sys,'argv',[script,'--help']),patch('sys.stdout',io.StringIO()),pytest.raises(SystemExit) as exc:
        runpy.run_path(str(HERE/script),run_name='__main__')
    assert exc.value.code==0
