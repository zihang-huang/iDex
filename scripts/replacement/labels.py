"""Single label contract shared by acquisition, training and evaluation."""
import json
from pathlib import Path

# The historical 151-class campaign contract, frozen byte-for-byte when the app moved to the
# National Pokédex; the app's own iDex/Recognition/pokemon_labels.json now matches its model.
LABELS = Path('scripts/replacement/labels-kanto.json')
CATALOG = Path('iDex/Resources/pokemon-national.json')


def label_ids(labels):
    if not isinstance(labels, list) or len(labels) < 2:
        raise ValueError('labels must be a list of at least two {id, name} records')
    for label in labels:
        if (not isinstance(label, dict) or type(label.get('id')) is not int
                or not isinstance(label.get('name'), str) or not label['name'].strip()):
            raise ValueError('every label requires an integer id and nonempty name')
    ids = [x['id'] for x in labels]
    if set(ids) != set(range(1, len(labels) + 1)):
        raise ValueError('labels must contain each ID 1..class_count exactly once')
    return ids


def read_labels(path=LABELS):
    labels = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    label_ids(labels)
    return labels


def add_labels(parser):
    parser.add_argument('--labels', type=Path, default=LABELS)


def check_labels(state, labels):
    label_ids(labels)
    if state.get('labels') != labels:
        raise ValueError('checkpoint labels mismatch')


def generations(path=CATALOG):
    return {r['id']: r['generation'] for r in json.loads(Path(path).read_text(encoding='utf-8-sig'))}
