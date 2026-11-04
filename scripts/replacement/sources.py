"""PokeAPI/TCG parsing and resumable acquisition, without remote Python code."""
import hashlib
import json
import time
import urllib.error
from pathlib import Path
from urllib.parse import urlparse
from PIL import Image

JJMACK_REV = '959ff557b102fc3b4f912d0ca769273be5b9ca7f'
JJMACK = 'JJMack/pokemon-classification-gen1-9'
GENERATIONS = {f'generation-{roman}': f'gen{i}' for i,roman in enumerate(
    ('i','ii','iii','iv','v','vi','vii','viii','ix'),1)}


def verify_jjmack(meta):
    if meta.get('sha') != JJMACK_REV:
        raise ValueError(f'JJMack revision mismatch: require {JJMACK_REV}, got {meta.get("sha")}')


def sprite_urls(payload):
    """Only default-form front artwork; family identity survives all variants."""
    sprites=payload.get('sprites') or {}; result=[]; seen=set()
    def add(url, family, variant):
        if not url or url in seen: return
        parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.netloc!='raw.githubusercontent.com' or not parsed.path.startswith('/PokeAPI/sprites/'):
            raise ValueError(f'unexpected sprite host/path: {url}')
        seen.add(url); result.append(dict(url=url, family=family, variant=variant))
    for family in ('official-artwork','home','showdown'):
        for variant in ('front_default','front_shiny'):
            add((sprites.get('other',{}).get(family) or {}).get(variant), family, variant)
    def front(value, family, path=''):
        if not isinstance(value,dict): return
        for key,item in sorted(value.items()):
            if key=='front_default': add(item,family,path+key)
            elif isinstance(item,dict): front(item,family,path+key+'/')
    for gen,value in sorted((sprites.get('versions') or {}).items()):
        if gen in GENERATIONS: front(value,GENERATIONS[gen])
    return result


def tcg_cards(payload, allowed):
    if not isinstance(payload.get('data'),list): raise ValueError('TCG page needs data array')
    result=[]
    for card in payload['data']:
        ids=card.get('nationalPokedexNumbers')
        if card.get('supertype')!='Pokémon' or not isinstance(ids,list) or len(ids)!=1: continue
        if type(ids[0]) is not int or ids[0] not in allowed: continue
        url=(card.get('images') or {}).get('small')
        if not url: continue
        if not card.get('id') or not card.get('set',{}).get('id') or not card.get('number'):
            raise ValueError('TCG card missing group identity')
        parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.netloc!='images.pokemontcg.io':
            raise ValueError(f'unexpected TCG image host: {url}')
        result.append(dict(id=card['id'],target_id=ids[0],url=url,
                           source_group=f'tcg:{card["set"]["id"]}-{card["number"]}'))
    return result


def retry_fetch(fetch, url, path, *, limit, attempts=6, delay=1., sleep=time.sleep):
    """Existing complete files are reused; failed transfers retry exponentially."""
    if attempts<1 or delay<0: raise ValueError('invalid retry/rate settings')
    for attempt in range(attempts):
        try:
            cached=path.exists()
            record=fetch(url,path,limit)
            if not cached and delay: sleep(delay)
            return record
        except (OSError, urllib.error.URLError) as exc:
            if isinstance(exc,urllib.error.HTTPError) and exc.code not in (408,429,500,502,503,504): raise
            if attempt+1==attempts: raise
            sleep(max(delay,1.)*2**attempt)


def record_download(folder, record):
    with (folder/'downloads.jsonl').open('a',encoding='utf-8') as out:
        out.write(json.dumps(record)+'\n')


def write_samples(folder, rows):
    path=folder/'samples.jsonl'; partial=path.with_suffix('.partial')
    partial.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8'); partial.replace(path)


def acquire_sprites(root, labels, fetch, delay=1., attempts=6):
    folder=root/'sprites'; folder.mkdir(parents=True,exist_ok=True); rows=[]; excluded=[]
    for label in labels:
        dex=label['id']; meta=folder/'api'/f'{dex}.json'
        record_download(folder,retry_fetch(fetch,f'https://pokeapi.co/api/v2/pokemon/{dex}',meta,limit=2_000_000,delay=delay,attempts=attempts))
        payload=json.loads(meta.read_text(encoding='utf-8'))
        if payload.get('id')!=dex or payload.get('is_default') is not True:
            raise ValueError(f'PokeAPI default-form identity mismatch: {dex}')
        for spec in sprite_urls(payload):
            key=f'{dex}-'+hashlib.sha256(spec['url'].encode()).hexdigest()[:20]
            suffix=Path(urlparse(spec['url']).path).suffix
            raw=folder/'raw'/(key+suffix); image=folder/'images'/(key+'.png')
            receipt=retry_fetch(fetch,spec['url'],raw,limit=20_000_000,delay=delay,attempts=attempts)
            record_download(folder,receipt)
            with Image.open(raw) as src:
                src.seek(0)
                if min(src.size)<64:
                    excluded.append(dict(target_id=dex,url=spec['url'],size=src.size,reason='under_64px')); continue
                im=src.convert('RGBA')
            image.parent.mkdir(parents=True,exist_ok=True); im.save(image)
            rows.append(dict(path=image.as_posix(),source='sprites',target_id=dex,
                             source_group=f'pokeapi:{dex}:{spec["family"]}',family=spec['family'],
                             variant=spec['variant'],url=spec['url'],original_sha256=receipt['sha256'],
                             derived_sha256=hashlib.sha256(image.read_bytes()).hexdigest()))
        write_samples(folder,rows)
    (folder/'excluded.json').write_text(json.dumps(excluded,indent=2),encoding='utf-8')


def acquire_tcg(root, labels, fetch, delay=1., attempts=6):
    folder=root/'tcg'; folder.mkdir(parents=True,exist_ok=True)
    allowed={x['id'] for x in labels}; page=1; rows=[]
    while True:
        meta=folder/'pages'/f'{page:05}.json'
        record_download(folder,retry_fetch(fetch,
            f'https://api.pokemontcg.io/v2/cards?page={page}&pageSize=250',meta,
            limit=20_000_000,delay=delay,attempts=attempts))
        payload=json.loads(meta.read_text(encoding='utf-8'))
        if payload.get('page')!=page or payload.get('pageSize')!=250:
            raise ValueError('TCG pagination contract mismatch')
        cards=tcg_cards(payload,allowed); count=len(payload['data']); total=payload.get('totalCount')
        if type(total) is not int or total<0 or payload.get('count')!=count or count>250:
            raise ValueError('TCG pagination count mismatch')
        for card in cards:
            key=hashlib.sha256(card['id'].encode()).hexdigest()[:24]
            image=folder/'images'/(key+'.jpg'); crop=folder/'images'/(key+'-art.png')
            receipt=retry_fetch(fetch,card['url'],image,limit=5_000_000,delay=delay,attempts=attempts)
            record_download(folder,receipt)
            with Image.open(image) as src:
                im=src.convert('RGB'); w,h=im.size
                im.crop((round(w*.08),round(h*.11),round(w*.92),round(h*.47))).save(crop)
            common=dict(source='tcg',target_id=card['target_id'],source_group=card['source_group'],
                        card_id=card['id'],url=card['url'],original_sha256=receipt['sha256'])
            rows.extend([dict(common,path=image.as_posix(),card_art_crop=False,derived_sha256=receipt['sha256']),
                         dict(common,path=crop.as_posix(),card_art_crop=True,derived_sha256=hashlib.sha256(crop.read_bytes()).hexdigest())])
        write_samples(folder,rows)
        if (page-1)*250+count>=total: break
        if count==0: raise ValueError('TCG empty page before totalCount; retry in a new request')
        page+=1
