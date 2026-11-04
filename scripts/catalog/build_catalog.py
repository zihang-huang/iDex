#!/usr/bin/env python3
"""Rebuild the offline National Pokédex catalog from cached upstream CSVs and sprites."""
import concurrent.futures
import csv
import io
import json
from pathlib import Path
import re
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / '.catalog-cache'
RESOURCES = ROOT / 'iDex' / 'Resources'
CATALOG = RESOURCES / 'pokemon-national.json'
# Official-site Chinese/Japanese text for entries PokéAPI lacks; see fetch_official_text.py.
OFFICIAL_TEXT = Path(__file__).with_name('official-text.json')
CSV_BASE = 'https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/'
FILES = ['pokemon.csv', 'pokemon_species.csv', 'pokemon_species_names.csv', 'pokemon_species_flavor_text.csv', 'pokemon_types.csv', 'types.csv', 'pokemon_stats.csv', 'stats.csv']
LAST_ID = 1025
# Last species with an official Black/White sprite; later ones use Smogon's Gen 5-style sprites.
LAST_BLACK_WHITE_ID = 649

def download(url, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path.read_bytes()
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'iDex-development-catalog/1.0'})
            data = urllib.request.urlopen(request, timeout=40).read()
            path.write_bytes(data)
            return data
        except Exception:
            if attempt == 3:
                raise
            time.sleep(1 + attempt)

def rows(file):
    return list(csv.DictReader(io.StringIO(download(CSV_BASE + file, CACHE / file).decode('utf-8'))))

def main():
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        csvs = dict(zip(FILES, pool.map(rows, FILES)))
    species_names = {(int(r['pokemon_species_id']), int(r['local_language_id'])): r for r in csvs['pokemon_species_names.csv']}
    type_names = {r['id']: r['identifier'] for r in csvs['types.csv']}
    stat_names = {r['id']: r['identifier'] for r in csvs['stats.csv']}
    species_slugs = {int(r['id']): r['identifier'] for r in csvs['pokemon_species.csv']}
    generations = {int(r['id']): int(r['generation_id']) for r in csvs['pokemon_species.csv']}
    official = json.loads(OFFICIAL_TEXT.read_text(encoding='utf-8')) if OFFICIAL_TEXT.exists() else {}

    def localized(language, number, field, upstream):
        # PokéAPI text wins; official-site text only fills its gaps.
        return upstream or official.get(language, {}).get(str(number), {}).get(field, '')

    flavor = {}
    # Retain the latest available text in each language (CSV is ordered by version id).
    for r in csvs['pokemon_species_flavor_text.csv']:
        if int(r['species_id']) <= LAST_ID and r['language_id'] in ('9', '11', '12'):
            normalized = ' '.join(r['flavor_text'].replace('\f', ' ').split())
            flavor[(int(r['species_id']), int(r['language_id']))] = normalized.replace(' ', '') if r['language_id'] == '12' else normalized
    entries = []
    slug_by_id = {}
    for p in csvs['pokemon.csv']:
        number = int(p['id'])
        if not 1 <= number <= LAST_ID:
            continue
        en = species_names[(number, 9)]
        zh = species_names[(number, 12)]
        ja = species_names[(number, 11)]
        slug_by_id[number] = p['identifier']
        entry = {
            'id': number,
            'generation': generations[number],
            'englishName': en['name'],
            'chineseName': zh['name'],
            'japaneseName': ja['name'],
            'types': [type_names[t['type_id']] for t in csvs['pokemon_types.csv'] if int(t['pokemon_id']) == number],
            'height': int(p['height']) / 10,
            'weight': int(p['weight']) / 10,
            'englishDescription': flavor[(number, 9)],
            'chineseDescription': localized('zh-Hans', number, 'description', flavor.get((number, 12))),
            'japaneseDescription': localized('ja', number, 'description', flavor.get((number, 11))),
            'englishGenus': en['genus'],
            'chineseGenus': localized('zh-Hans', number, 'genus', zh['genus']),
            'japaneseGenus': localized('ja', number, 'genus', ja['genus']),
            'stats': [{'name': stat_names[s['stat_id']], 'value': int(s['base_stat'])} for s in csvs['pokemon_stats.csv'] if int(s['pokemon_id']) == number]
        }
        entries.append(entry)
    assert [p['id'] for p in entries] == list(range(1, LAST_ID + 1))
    incomplete = [p['id'] for p in entries if not (p['chineseDescription'] and p['chineseGenus'] and p['japaneseName']
                  and p['japaneseDescription'] and p['japaneseGenus'] and len(p['stats']) == 6)]
    assert not incomplete, f'Missing localized text for {incomplete}; run fetch_official_text.py'
    RESOURCES.mkdir(parents=True, exist_ok=True)
    CATALOG.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    assets = RESOURCES / 'PokemonSprites.xcassets'
    assets.mkdir(exist_ok=True)
    (assets / 'Contents.json').write_text(json.dumps({'info': {'author': 'xcode', 'version': 1}}, indent=2))
    def sprite(p):
        number = p['id']
        asset = assets / f'pokemon-{number:03d}.imageset'
        path = asset / 'sprite.png'
        if number <= LAST_BLACK_WHITE_ID:
            primary = f'https://img.pokemondb.net/sprites/black-white/normal/{slug_by_id[number]}.png'
        else:
            showdown_id = re.sub('[^a-z0-9]', '', species_slugs[number])
            primary = f'https://play.pokemonshowdown.com/sprites/gen5/{showdown_id}.png'
        urls = [primary, f'https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{number}.png']
        for source in urls:
            try:
                data = download(source, path)
                if not data.startswith(b'\x89PNG'):
                    path.unlink()
                    raise ValueError('Not a PNG')
                break
            except Exception:
                if source == urls[-1]:
                    raise
        (asset / 'Contents.json').write_text(json.dumps({'images': [{'filename': 'sprite.png', 'idiom': 'universal'}], 'info': {'author': 'xcode', 'version': 1}}, indent=2))
        return number, source
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        sources = dict(pool.map(sprite, entries))
    (RESOURCES / 'sprite-sources.json').write_text(json.dumps(sources, indent=2) + '\n')
    font_dir = RESOURCES / 'Fonts'
    font_dir.mkdir(exist_ok=True)
    for filename in ['PressStart2P-Regular.ttf', 'OFL.txt']:
        target = 'PressStart2P-OFL.txt' if filename == 'OFL.txt' else filename
        download('https://raw.githubusercontent.com/google/fonts/main/ofl/pressstart2p/' + filename, font_dir / target)
    fusion_url = 'https://github.com/TakWolf/fusion-pixel-font/releases/download/2026.10.16/fusion-pixel-font-12px-proportional-otf-v2026.10.16.zip'
    archive = download(fusion_url, CACHE / 'fusion-pixel-font.zip')
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        for name in zipped.namelist():
            if name.endswith(('zh_hans.otf', '-ja.otf', 'OFL.txt', 'LICENSE.txt')):
                output_name = 'FusionPixel-OFL.txt'
                if name.endswith('zh_hans.otf'):
                    output_name = 'FusionPixel-12px-zh-Hans.otf'
                elif name.endswith('-ja.otf'):
                    output_name = 'FusionPixel-12px-ja.otf'
                output = font_dir / output_name
                output.write_bytes(zipped.read(name))
    fallbacks = sorted(number for number, source in sources.items() if 'PokeAPI/sprites' in source)
    print(f'Built {len(entries)} English, Simplified Chinese, and Japanese entries and {len(sources)} sprites.')
    print('Sprites from the PokeAPI fallback:', fallbacks or 'none')
    print('Pikachu:', entries[24])
    print('Fonts:', [p.name for p in font_dir.iterdir()])

if __name__ == '__main__':
    main()
