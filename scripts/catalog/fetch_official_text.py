#!/usr/bin/env python3
"""Fill the Chinese/Japanese Pokédex text PokéAPI lacks from the official Pokémon sites.

Only species/fields missing upstream are fetched, one page at a time with a delay.
Raw pages are cached under .catalog-cache/official/; the extracted text is written to
official-text.json, which build_catalog.py merges behind the PokéAPI text.
"""
import html
import json
import re
import time
import urllib.request

from build_catalog import CACHE, LAST_ID, OFFICIAL_TEXT, rows

SOURCES = {
    'zh-Hans': 'https://www.pokemon.cn/play/pokedex/{:04d}',
    'ja': 'https://zukan.pokemon.co.jp/detail/{:04d}',
}
LANGUAGE_IDS = {'zh-Hans': '12', 'ja': '11'}
DELAY_SECONDS = 1.2


def missing_fields():
    names = {(int(r['pokemon_species_id']), r['local_language_id']): r for r in rows('pokemon_species_names.csv')}
    flavored = {(int(r['species_id']), r['language_id']) for r in rows('pokemon_species_flavor_text.csv')}
    needed = {}
    for language, language_id in LANGUAGE_IDS.items():
        for number in range(1, LAST_ID + 1):
            fields = [field for field, present in (
                ('genus', (names.get((number, language_id)) or {}).get('genus')),
                ('description', (number, language_id) in flavored),
            ) if not present]
            if fields:
                needed.setdefault(language, {})[number] = fields
    return needed


def fetch(language, number):
    path = CACHE / 'official' / language / f'{number:04d}.html'
    if path.exists():
        return path.read_text(encoding='utf-8')
    request = urllib.request.Request(SOURCES[language].format(number), headers={'User-Agent': 'Mozilla/5.0 (iDex catalog builder)'})
    for attempt in range(3):
        try:
            page = urllib.request.urlopen(request, timeout=40).read().decode('utf-8')
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding='utf-8')
    time.sleep(DELAY_SECONDS)
    return page


def text(match):
    return html.unescape(re.sub(r'<[^>]+>', '', match.group(1))).strip() if match else ''


def parse_chinese(page):
    genus = re.search(r'pokemon-info__category">.*?pokemon-info__value[^>]*>(.*?)</span></div>', page, re.S)
    # The first story is the one the site shows by default.
    story = (re.search(r'pokemon-story__body[^"]*" v-if="storyNumber === 1">(.*?)</p>', page, re.S)
             or re.search(r'pokemon-story__body[^"]*"[^>]*>(.*?)</p>', page, re.S))
    # Match PokéAPI's Simplified Chinese normalization: no spaces.
    return {'genus': ''.join(text(genus).split()), 'description': ''.join(text(story).split())}


def parse_japanese(page):
    genus = re.search(r'js-classification">(.*?)</dd>', page, re.S)
    story = re.search(r'<div class="wrap__texts">.*?<div class="0"><p>(.*?)</p>', page, re.S)
    # Drop the "（『game』より）" credit and any "※ where to meet it" note after it;
    # match PokéAPI's single-space word breaks.
    description = re.sub(r'\s*（『[^』]*』より）.*$', '', text(story), flags=re.S)
    return {'genus': text(genus), 'description': ' '.join(description.split())}


PARSERS = {'zh-Hans': parse_chinese, 'ja': parse_japanese}


def main():
    needed = missing_fields()
    result = {'sources': SOURCES}
    failures = []
    for language, species in needed.items():
        print(f'{language}: {len(species)} species need official text')
        extracted = {}
        for number, fields in sorted(species.items()):
            parsed = PARSERS[language](fetch(language, number))
            for field in fields:
                if not parsed[field]:
                    failures.append((language, number, field))
            extracted[str(number)] = {field: parsed[field] for field in fields}
        result[language] = extracted
    if failures:
        raise SystemExit(f'Could not extract {len(failures)} fields, e.g. {failures[:10]}')
    OFFICIAL_TEXT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Wrote {OFFICIAL_TEXT.name}:', {language: len(result[language]) for language in needed})


if __name__ == '__main__':
    main()
