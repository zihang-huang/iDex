"""CPU-only paired prediction analysis; no inference and no training-set scores.

Example: python scripts/replacement/analyze_predictions.py --baseline BASE.jsonl
  --candidate CANDIDATE.jsonl --manifest MANIFEST.jsonl --labels LABELS.json
  --out artifacts/replacement/reports/analysis [--selection SELECTION.json]

The caller controls test access after candidate selection. This script refuses
training/unused/quarantine rows; it never chooses thresholds or a checkpoint.
"""
import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from metrics import CAVEAT, PAIRED_FIELDS, SCALARS, load_rows, metrics
from labels import add_labels,read_labels,generations


ORIGINAL = dict(confidence=.25, margin=.5, temperature=1.)
ALLOWED_SPLITS = {'val', 'ood_val', 'test_public', 'ood_test_public',
                  'test_camera', 'ood_test_camera'}
EXAMPLE_RULE = (
    'Known mistakes: candidate top1 incorrect, sorted by descending candidate '
    'T=1 confidence then ascending sha256, first image per group, maximum 36. '
    'Unknown accepts: union of baseline/candidate original-policy accepts, '
    'sorted by descending maximum T=1 confidence then ascending sha256, first '
    'image per group, maximum 36. If any accepted unknown has a COCO source, '
    'reserve one slot for the highest-ranked COCO example before filling the '
    'remaining slots. Sort the final selection by the same ranking. These '
    'deterministic diagnostic extremes are not representative samples; all '
    'cases and all accepted unknowns are retained in JSONL.'
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def write_jsonl(path, rows):
    with Path(path).open('w', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row, allow_nan=False) + '\n')


def compact(summary):
    return {key: summary[key] for key in (*SCALARS, 'counts')}


def paired_rows(baseline, candidate, manifest, labels):
    for row in (*baseline, *candidate):
        if not isinstance(row, dict) or row.get('split') not in ALLOWED_SPLITS:
            raise ValueError(f'no scores permitted for split {row.get("split") if isinstance(row, dict) else None}')
    # Public metric validation rejects duplicate identities, nonfinite/count
    # errors and explicit column-order mismatches before any pairing map is made.
    metrics(baseline, labels, **ORIGINAL)
    metrics(candidate, labels, **ORIGINAL)
    other = {row['sha256']: row for row in candidate}
    if set(other) != {row['sha256'] for row in baseline}:
        raise ValueError('paired analysis requires identical prediction sha256 sets')
    candidate = [other[row['sha256']] for row in baseline]
    usable = collections.defaultdict(list)
    for row in manifest:
        if row.get('use'):
            usable[row['sha256']].append(row)
    matched = {}
    for base, new in zip(baseline, candidate):
        for field in PAIRED_FIELDS:
            if base[field] != new[field]:
                raise ValueError(f'paired prediction metadata mismatch: {field}')
        options = usable[base['sha256']]
        if len(options) != 1:
            raise ValueError('each prediction requires exactly one usable manifest row')
        truth = options[0]
        for field in PAIRED_FIELDS:
            if base[field] != truth[field]:
                raise ValueError(f'prediction/manifest metadata mismatch: {field}')
        matched[base['sha256']] = truth
    return baseline, candidate, matched


def frozen_policy(selection_path, candidate_path, manifest_path):
    if selection_path is None:
        return None
    selection = json.loads(Path(selection_path).read_text(encoding='utf-8-sig'))
    if selection.get('manifest_sha256') != digest(manifest_path):
        raise ValueError('frozen selection manifest digest mismatch')
    receipt_path = Path(candidate_path).with_suffix('.metadata.json')
    receipt = json.loads(receipt_path.read_text(encoding='utf-8-sig'))
    if (not selection.get('checkpoint_sha256')
            or receipt.get('checkpoint_sha256') != selection['checkpoint_sha256']):
        raise ValueError('frozen selection candidate checkpoint digest mismatch')
    if receipt.get('manifest_sha256') != selection['manifest_sha256']:
        raise ValueError('candidate receipt manifest digest mismatch')
    if receipt.get('predictions_sha256') != digest(candidate_path):
        raise ValueError('candidate receipt prediction digest mismatch')
    policy = selection['policy']
    enabled, abstain_all = policy.get('enabled'), policy.get('abstain_all')
    if not ((enabled is True and abstain_all is False)
            or (enabled is False and abstain_all is True)):
        raise ValueError('frozen policy must explicitly enable acceptance or abstain_all')
    temperature = policy.get('temperature')
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not np.isfinite(temperature) or temperature <= 0:
        raise ValueError('frozen temperature must be positive and finite')
    if abstain_all:
        if 'confidence' in policy or 'margin' in policy:
            raise ValueError('abstain_all must not use finite pseudo-abstention thresholds')
    elif 'confidence' not in policy or 'margin' not in policy:
        raise ValueError('enabled frozen policy requires confidence and raw margin thresholds')
    return policy


def policy_summary(rows, labels, policy):
    if policy is None:
        return None
    if not policy['abstain_all']:
        return metrics(rows, labels, confidence=policy['confidence'], margin=policy['margin'],
                       temperature=policy['temperature'])
    result = metrics(rows, labels, temperature=policy['temperature'])
    result.update(accepted_coverage=0., accepted_accuracy=None,
                  accepted_known_coverage=0. if result['counts']['known'] else None,
                  accepted_known_accuracy=None,
                  unknown_far=0. if result['counts']['unknown'] else None)
    result['counts']['accepted'] = 0
    for buckets in result['slices'].values():
        for value in buckets.values():
            value.update(accepted_coverage=0.,accepted_accuracy=None,
                         accepted_known_coverage=0. if value['counts']['known'] else None,
                         accepted_known_accuracy=None,unknown_far=0. if value['counts']['unknown'] else None)
            value['counts']['accepted']=0
    settings = result['settings']
    settings.pop('confidence_threshold')
    settings.pop('raw_logit_margin_threshold')
    settings.update(acceptance_rule='unconditional abstention', enabled=False, abstain_all=True)
    return result


def describe(row, labels, temperature=1., policy=None):
    logits = np.asarray(row['logits'], dtype=np.float64)
    ranking = np.argsort(-logits, kind='stable')
    probabilities = np.exp((logits - logits.max()) / temperature)
    probabilities /= probabilities.sum()
    top = int(ranking[0])
    confidence = float(probabilities[top])
    margin = float(logits[top] - logits[ranking[1]])
    threshold = ORIGINAL if policy is None else policy
    accept = (False if threshold.get('abstain_all') else
              confidence >= threshold['confidence'] and margin >= threshold['margin'])
    return dict(predicted_id=labels[top]['id'], predicted_name=labels[top]['name'],
                confidence=confidence, raw_margin=margin, accepted=bool(accept),
                correct=row['target_id'] is not None and labels[top]['id'] == row['target_id'],
                temperature=temperature,
                top3=[dict(id=labels[i]['id'], name=labels[i]['name'], probability=float(probabilities[i]))
                      for i in ranking[:3]])


def case_record(base, candidate, truth, labels, policy):
    record = {key: base[key] for key in ('sha256', *PAIRED_FIELDS)}
    for field in ('path', 'form', 'shiny', 'source_label', 'member', 'baseline_exposure'):
        if field in truth:
            record[field] = truth[field]
    record.update(baseline=describe(base, labels), candidate=describe(candidate, labels))
    if policy is not None:
        record['candidate_frozen'] = describe(candidate, labels, policy['temperature'], policy)
    return record


def slices(baseline, candidate, truth, labels, policy):
    report = {}
    generation=generations()
    for field in ('source', 'form', 'shiny','generation'):
        populations = collections.defaultdict(list)
        present = nonnull = 0
        for i, row in enumerate(baseline):
            record = truth[row['sha256']]
            if field=='generation': record=dict(record,generation=generation.get(record['target_id']))
            present += field in record
            nonnull += field in record and record[field] is not None
            # Typed JSON keys preserve true/false, null, and absent distinctly;
            # never infer forms or shiny labels from names or image appearance.
            key = ('present', json.dumps(record[field], sort_keys=True)) if field in record else ('missing', '')
            populations[key].append(i)
        items = []
        for (status, encoded), indices in sorted(populations.items()):
            a = [baseline[i] for i in indices]
            b = [candidate[i] for i in indices]
            item = dict(field_present=status == 'present', value=json.loads(encoded) if encoded else None,
                        baseline=compact(metrics(a, labels, **ORIGINAL)),
                        candidate=compact(metrics(b, labels, **ORIGINAL)))
            if policy is not None:
                item['candidate_frozen'] = compact(policy_summary(b, labels, policy))
            items.append(item)
        report[field] = dict(field_present_images=present, nonnull_annotation_images=nonnull,
                             missing_annotation_images=len(baseline) - present, slices=items)
    return report


def choose_examples(cases, unknown=False):
    def order(row):
        score = max(row['baseline']['confidence'], row['candidate']['confidence']) if unknown else row['candidate']['confidence']
        return -score, row['sha256']
    ranked = sorted(cases, key=order)
    chosen, groups = [], set()
    if unknown:
        coco = next((row for row in ranked if 'coco' in row['source'].lower()), None)
        if coco:
            chosen.append(coco)
            groups.add(coco['group'])
    for row in ranked:
        if row['group'] not in groups:
            chosen.append(row)
            groups.add(row['group'])
            if len(chosen) == 36:
                break
    return sorted(chosen, key=order)


def resolve_image(path, manifest_path):
    original = Path(path)
    for choice in (original, Path(__file__).resolve().parents[2] / original,
                   Path(manifest_path).resolve().parent / original):
        if choice.is_file():
            return choice
    raise FileNotFoundError(str(path))


def contact_sheet(cases, path, manifest_path, title):
    width, height, columns = 240, 244, 6
    canvas = Image.new('RGB', (columns * width, 48 + max(1, (len(cases) + columns - 1) // columns) * height), 'white')
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 8), title, fill='black')
    draw.text((8, 25), 'Deterministic extremes, distinct groups. Full selection rule and all cases in report/JSONL.', fill='black')
    missing = []
    if not cases:
        draw.text((12, 65), 'No eligible examples.', fill='black')
    for i, record in enumerate(cases):
        x, y = (i % columns) * width, 48 + (i // columns) * height
        try:
            source = resolve_image(record.get('path', ''), manifest_path)
            with Image.open(source) as image:
                image = ImageOps.exif_transpose(image).convert('RGBA')
                background = Image.new('RGBA', image.size, 'white')
                image = Image.alpha_composite(background, image).convert('RGB')
                image.thumbnail((width - 8, 170))
                canvas.paste(image, (x + (width - image.width) // 2, y))
        except (OSError, ValueError) as exc:
            missing.append(dict(sha256=record['sha256'], path=record.get('path'), error=str(exc)))
            draw.text((x + 5, y + 55), 'Image unavailable; see JSONL', fill='red')
        base, new = record['baseline'], record['candidate']
        target = record['target_id'] if record['target_id'] is not None else 'UNKNOWN'
        lines = [f"True {target} | {record['source']}",
                 f"B {base['predicted_id']} p={base['confidence']:.3f} accept={base['accepted']}",
                 f"C {new['predicted_id']} p={new['confidence']:.3f} margin={new['raw_margin']:.2f}",
                 record['sha256'][:20]]
        for line, text in enumerate(lines):
            draw.text((x + 4, y + 176 + line * 15), text[:38], fill='black')
    canvas.save(path)
    return dict(file=Path(path).name, selected_images=len(cases),
                sha256s=[row['sha256'] for row in cases], image_errors=missing)


def per_class_csv(path, baseline, candidate):
    fields = ['id', 'name', 'support', 'baseline_predicted', 'candidate_predicted',
              'baseline_recall', 'candidate_recall', 'delta_recall',
              'baseline_precision', 'candidate_precision', 'baseline_f1', 'candidate_f1', 'delta_f1']
    with Path(path).open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for base, new in zip(baseline['per_class'], candidate['per_class']):
            if base['id'] != new['id'] or base['support'] != new['support']:
                raise ValueError('paired per-class supports differ')
            row = dict(id=base['id'], name=base['name'], support=base['support'])
            for key in ('predicted', 'recall', 'precision', 'f1'):
                row['baseline_' + key], row['candidate_' + key] = base[key], new[key]
            for key in ('recall', 'f1'):
                row['delta_' + key] = None if base[key] is None or new[key] is None else new[key] - base[key]
            writer.writerow(row)


def candidate_only(args,labels):
    rows=load_rows(args.candidate)
    # Reuse exact manifest/population validation, without claiming a comparison.
    _,rows,truth=paired_rows(rows,rows,load_rows(args.manifest),labels)
    policy=frozen_policy(args.selection,args.candidate,args.manifest)
    summary=metrics(rows,labels,**ORIGINAL)
    args.out.mkdir(parents=True,exist_ok=True)
    write_json(args.out/'report.json',dict(candidate_original=summary,
        candidate_frozen=policy_summary(rows,labels,policy),frozen_policy=policy,
        paired_comparison=dict(status='skipped',reason='No same-label baseline supplied'),
        provenance={key:dict(path=str(getattr(args,key)),sha256=digest(getattr(args,key)))
                    for key in ('candidate','manifest','labels')}))
    write_json(args.out/'slices.json',summary['slices'])
    with (args.out/'per_class.csv').open('w',newline='',encoding='utf-8') as out:
        writer=csv.DictWriter(out,fieldnames=list(summary['per_class'][0]));writer.writeheader();writer.writerows(summary['per_class'])
    write_jsonl(args.out/'cases.jsonl',[dict(sha256=r['sha256'],target_id=r['target_id'],
        source=r['source'],candidate=describe(r,labels),path=truth[r['sha256']].get('path')) for r in rows])
    print(json.dumps(dict(out=str(args.out),images=len(rows),paired_comparison='skipped')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ('candidate', 'manifest', 'out'):
        parser.add_argument('--' + argument, type=Path, required=True)
    parser.add_argument('--baseline',type=Path);add_labels(parser)
    parser.add_argument('--selection', type=Path, help='frozen candidate policy and provenance')
    args = parser.parse_args()
    labels = read_labels(args.labels)
    if not args.baseline:
        candidate_only(args,labels)
        return
    baseline, candidate, truth = paired_rows(load_rows(args.baseline), load_rows(args.candidate),
                                            load_rows(args.manifest), labels)
    policy = frozen_policy(args.selection, args.candidate, args.manifest)
    original_base = metrics(baseline, labels, **ORIGINAL)
    original_candidate = metrics(candidate, labels, **ORIGINAL)
    frozen = policy_summary(candidate, labels, policy)
    cases = sorted([case_record(a, b, truth[a['sha256']], labels, policy)
                    for a, b in zip(baseline, candidate)], key=lambda row: row['sha256'])
    known = [row for row in cases if row['target_id'] is not None]
    unknown = [row for row in cases if row['target_id'] is None]
    regression = [row for row in known if row['baseline']['correct'] and not row['candidate']['correct']]
    improvement = [row for row in known if not row['baseline']['correct'] and row['candidate']['correct']]
    errors = [row for row in known if not row['baseline']['correct'] or not row['candidate']['correct']]
    accepted_unknown = [row for row in unknown if row['baseline']['accepted'] or row['candidate']['accepted']]
    files = dict(known_cases=known, known_regressions=regression, known_improvements=improvement,
                 known_errors=errors, unknown_cases=unknown, unknown_accepted_union_original=accepted_unknown,
                 unknown_accepted_baseline_original=[row for row in unknown if row['baseline']['accepted']],
                 unknown_accepted_candidate_original=[row for row in unknown if row['candidate']['accepted']])
    if policy is not None:
        files['unknown_accepted_candidate_frozen'] = [row for row in unknown if row['candidate_frozen']['accepted']]
    slice_report = slices(baseline, candidate, truth, labels, policy)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, records in files.items():
        write_jsonl(args.out / (name + '.jsonl'), records)
    per_class_csv(args.out / 'per_class.csv', original_base, original_candidate)
    write_json(args.out / 'slices.json', slice_report)
    sheets = dict(candidate_known_mistakes=contact_sheet(
        choose_examples([row for row in known if not row['candidate']['correct']]),
        args.out / 'candidate_known_mistakes.png', args.manifest, 'Candidate known mistakes: descending T=1 confidence'),
        unknown_accepted=contact_sheet(choose_examples(accepted_unknown, unknown=True),
        args.out / 'unknown_accepted_original.png', args.manifest, 'Unknown accepted by either original .25 confidence / .5 raw-margin policy'))
    report = dict(baseline_original=original_base, candidate_original=original_candidate,
                  original_policy=ORIGINAL, candidate_frozen=frozen, frozen_policy=policy,
                  counts={key: len(value) for key, value in files.items()},
                  slice_annotation_support={key: {name: value[name] for name in
                      ('field_present_images', 'nonnull_annotation_images', 'missing_annotation_images')}
                      for key, value in slice_report.items()},
                  sheets=sheets, example_selection_rule=EXAMPLE_RULE,
                  provenance={name: dict(path=str(getattr(args, name)), sha256=digest(getattr(args, name)))
                              for name in ('baseline', 'candidate', 'manifest', 'labels')},
                  splits=dict(collections.Counter(row['split'] for row in baseline)),
                  baseline_contamination_caveat=CAVEAT,
                  notes=['No bootstrap or inference performed; use metrics.compare_models for paired group confidence intervals.',
                         'No training examples are scored. Test access is controlled by the caller after freezing selection.',
                         'Forms and shiny slices use actual manifest annotations only, including explicit missing/null/unspecified categories.',
                         'Original-policy acceptance uses T=1 confidence >= .25 AND raw top1-top2 logit margin >= .5.',
                         'Frozen abstain_all means zero acceptance without artificial finite thresholds.'])
    if args.selection:
        report['provenance']['selection'] = dict(path=str(args.selection), sha256=digest(args.selection))
    write_json(args.out / 'report.json', report)
    print(json.dumps(dict(out=str(args.out), counts=report['counts'], sheets=sheets), indent=2))


if __name__ == '__main__':
    main()
