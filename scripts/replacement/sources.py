"""PokeAPI/TCG parsing and resumable acquisition, without remote Python code."""
import contextlib
import hashlib
import json
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
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


# Measured on dex 1-89 (2026-11-04): every image in these PokeAPI directories decodes below
# 64 px, so they are recorded as excluded without a download. Newer-game icons are larger
# and are not listed. Some Let's Go animations exceed 25 MB, hence the per-file budget.
UNDERSIZED_DIRS = tuple(f'/sprites/pokemon/versions/{d}/' for d in (
    'generation-i', 'generation-ii', 'generation-iii/icons', 'generation-iv/icons',
    'generation-v/icons', 'generation-vi/icons', 'generation-vii/icons',
    'generation-vii/lets-go-pikachu-lets-go-eevee/icons'))
SPRITE_LIMIT = 40_000_000


def known_undersized(url):
    return any(d in urlparse(url).path for d in UNDERSIZED_DIRS)


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


def worker_pool(workers):
    """Thread pool for cache warming; one worker keeps the original strictly sequential path."""
    if type(workers) is not int or workers<1: raise ValueError('workers must be a positive integer')
    return ThreadPoolExecutor(workers) if workers>1 else contextlib.nullcontext()


def prefetch(pool, fetch, jobs, *, delay, attempts):
    """Download (url, path, limit) jobs in parallel; the ordered pass then reuses complete files.

    Only the cache is filled here: receipts, identity checks and samples stay in the ordered pass.
    """
    if pool is None: return
    futures=[pool.submit(retry_fetch,fetch,url,path,limit=limit,delay=delay,attempts=attempts)
             for url,path,limit in jobs if not path.exists()]
    try:
        for future in as_completed(futures): future.result()
    except BaseException:
        for future in futures: future.cancel()
        raise


def sprite_raw_path(folder, dex, url):
    key=f'{dex}-'+hashlib.sha256(url.encode()).hexdigest()[:20]
    return folder/'raw'/(key+Path(urlparse(url).path).suffix)


def tcg_image_path(folder, card_id):
    return folder/'images'/(hashlib.sha256(card_id.encode()).hexdigest()[:24]+'.jpg')


def record_download(folder, record):
    with (folder/'downloads.jsonl').open('a',encoding='utf-8') as out:
        out.write(json.dumps(record)+'\n')


def write_samples(folder, rows):
    path=folder/'samples.jsonl'; partial=path.with_suffix('.partial')
    partial.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8'); partial.replace(path)


def acquire_sprites(root, labels, fetch, delay=1., attempts=6, workers=1):
    folder=root/'sprites'; folder.mkdir(parents=True,exist_ok=True); rows=[]; excluded=[]
    api_url=lambda dex: f'https://pokeapi.co/api/v2/pokemon/{dex}'
    api_path=lambda dex: folder/'api'/f'{dex}.json'
    with worker_pool(workers) as pool:
        prefetch(pool,fetch,[(api_url(x['id']),api_path(x['id']),2_000_000) for x in labels],delay=delay,attempts=attempts)
        if pool is not None:
            prefetch(pool,fetch,[(spec['url'],sprite_raw_path(folder,x['id'],spec['url']),SPRITE_LIMIT)
                                 for x in labels
                                 for spec in sprite_urls(json.loads(api_path(x['id']).read_text(encoding='utf-8')))
                                 if not known_undersized(spec['url'])],
                     delay=delay,attempts=attempts)
    for label in labels:
        dex=label['id']; meta=api_path(dex)
        record_download(folder,retry_fetch(fetch,api_url(dex),meta,limit=2_000_000,delay=delay,attempts=attempts))
        payload=json.loads(meta.read_text(encoding='utf-8'))
        if payload.get('id')!=dex or payload.get('is_default') is not True:
            raise ValueError(f'PokeAPI default-form identity mismatch: {dex}')
        for spec in sprite_urls(payload):
            if known_undersized(spec['url']):
                excluded.append(dict(target_id=dex,url=spec['url'],reason='known_undersized_dir')); continue
            raw=sprite_raw_path(folder,dex,spec['url']); image=folder/'images'/(raw.stem+'.png')
            receipt=retry_fetch(fetch,spec['url'],raw,limit=SPRITE_LIMIT,delay=delay,attempts=attempts)
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


def acquire_tcg(root, labels, fetch, delay=1., attempts=6, workers=1):
    with worker_pool(workers) as pool:
        _acquire_tcg(root, labels, fetch, delay, attempts, pool)


def _acquire_tcg(root, labels, fetch, delay, attempts, pool):
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
        prefetch(pool,fetch,[(c['url'],tcg_image_path(folder,c['id']),5_000_000) for c in cards],delay=delay,attempts=attempts)
        for card in cards:
            image=tcg_image_path(folder,card['id']); crop=image.with_name(image.stem+'-art.png')
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
