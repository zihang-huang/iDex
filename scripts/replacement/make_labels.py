"""Generate national species labels, refusing any change to the shipped prefix."""
import argparse
import csv
import io
import json
from pathlib import Path
from labels import LABELS, read_labels

CSV_URL = 'https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/pokemon_species.csv'


def build_labels(text, original):
    rows = {int(r['id']): r['identifier'] for r in csv.DictReader(io.StringIO(text))}
    labels = [dict(id=i, name=rows[i]) for i in range(1, 1026)]
    for i, (old, new) in enumerate(zip(original, labels), 1):
        if old != new:
            raise ValueError(f'QUESTION: shipped label {i} differs: {old!r} != {new!r}')
    if len(original) != 151:
        raise ValueError('QUESTION: expected 151 shipped labels for prefix compatibility')
    return labels


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--csv', type=Path, default=Path('.catalog-cache/pokemon_species.csv'))
    p.add_argument('--original', type=Path, default=LABELS)
    p.add_argument('--out', type=Path, default=Path('scripts/replacement/labels-national.json'))
    a=p.parse_args()
    source=a.csv
    if not source.exists():
        from acquire import fetch
        source=Path('artifacts/replacement/sources/pokeapi/pokemon_species.csv')
        fetch(CSV_URL, source, 1_000_000)
    labels=build_labels(source.read_text(encoding='utf-8-sig'), read_labels(a.original))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(labels, indent=2)+'\n', encoding='utf-8')
    print(f'{len(labels)} labels; first 151 exactly match {a.original}; wrote {a.out}')


if __name__=='__main__': main()
