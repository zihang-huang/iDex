#!/usr/bin/env python3
"""Bundle pinned PokéAPI cries as iOS-native PCM WAV files. Requires ffmpeg."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request
import wave

ROOT = Path(__file__).resolve().parents[2]
REVISION = 'b3a9044bb839b5e3152aaa536c7b463a0fcf0140'
BASE = f'https://raw.githubusercontent.com/PokeAPI/cries/{REVISION}'
CACHE = ROOT / '.catalog-cache' / 'cries' / REVISION
OUTPUT = ROOT / 'iDex' / 'Resources' / 'Cries'


def download(relative):
    path = CACHE / relative
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(4):
            try:
                request = urllib.request.Request(f'{BASE}/{relative}', headers={'User-Agent': 'iDex-development-audio/1.0'})
                with urllib.request.urlopen(request, timeout=40) as response:
                    path.write_bytes(response.read())
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(attempt + 1)
    return path


def build(entry):
    dex_id = entry['id']
    relative = f'cries/pokemon/latest/{dex_id}.ogg'
    source = download(relative)
    # Some upstream .ogg paths (including Pikachu) contain MP3 data. Let
    # ffmpeg detect and validate the actual codec rather than the extension.
    destination = OUTPUT / f'pokemon-cry-{dex_id:03d}.wav'
    # Keep bundled cries byte-for-byte: different ffmpeg builds resample to different bytes.
    if not destination.exists():
        subprocess.run([
            'ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(source),
            '-map_metadata', '-1', '-ac', '1', '-ar', '22050',
            '-c:a', 'pcm_s16le', '-fflags', '+bitexact', '-flags:a', '+bitexact', str(destination)
        ], check=True)
    with wave.open(str(destination)) as audio:
        assert audio.getnchannels() == 1 and audio.getsampwidth() == 2
        assert audio.getframerate() == 22050 and audio.getnframes() > 0
        frames = audio.getnframes()
    return {
        'id': dex_id, 'name': entry['englishName'], 'file': destination.name,
        'source': f'{BASE}/{relative}',
        'sourceSHA256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
        'frames': frames, 'sampleRate': 22050
    }


def main():
    if not shutil.which('ffmpeg'):
        raise SystemExit('Install ffmpeg to regenerate cry assets; the app needs no external dependencies.')
    entries = json.loads((ROOT / 'iDex/Resources/pokemon-national.json').read_text(encoding='utf-8'))
    assert {entry['id'] for entry in entries} == set(range(1, len(entries) + 1))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        manifest = sorted(pool.map(build, entries), key=lambda item: item['id'])
    (OUTPUT / 'cry-sources.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (OUTPUT / 'PokeAPI-Cries-LICENSE.txt').write_bytes(download('LICENSE').read_bytes())
    print(f'Bundled {len(manifest)} cries ({sum((OUTPUT / item["file"]).stat().st_size for item in manifest):,} bytes).')


if __name__ == '__main__':
    main()
