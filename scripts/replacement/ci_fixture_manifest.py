"""Build a conversion-parity fixture manifest from the app's own bundled sprites.

CI parity only needs deterministic images with known pixels; reusing sprites that are
already in the repository avoids uploading any training photos to a public branch.
"""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image

SPRITES = Path('iDex/Resources/PokemonSprites.xcassets')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--step', type=int, default=8, help='take every Nth dex number')
    a = p.parse_args()
    if a.out.exists(): raise ValueError('Use a fresh fixture source folder')
    a.out.mkdir(parents=True)
    rows = []
    for folder in sorted(SPRITES.glob('pokemon-*.imageset')):
        dex = int(folder.name.split('-')[1].split('.')[0])
        if (dex - 1) % a.step: continue
        with Image.open(folder / 'sprite.png') as src:
            rgba = src.convert('RGBA')
        flat = Image.new('RGBA', rgba.size, (255, 255, 255, 255))
        flat.alpha_composite(rgba)
        path = a.out / f'{dex:04}.png'
        flat.convert('RGB').save(path)
        rows.append(dict(path=path.as_posix(), use=True, split='val', source='app-sprite',
                         target_id=dex, group=f'app-sprite:{dex}',
                         sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    if not rows: raise ValueError('no bundled sprites found')
    (a.out / 'manifest.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
    print(f'{len(rows)} sprite fixtures written')


if __name__ == '__main__': main()
