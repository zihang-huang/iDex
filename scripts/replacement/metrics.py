"""Offline metrics for a label-defined replacement experiment (NumPy only).

Scores are fractions, not percentages. Labels define the logit column order.
An optional row ``label_ids`` must match that order exactly. Absent this field,
column order is a producer assertion and cannot be discovered from numbers.
Unknown targets are excluded from closed-set metrics and calibration scores.
Groups, rather than images, are sampled with replacement for uncertainty.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from labels import LABELS, label_ids, read_labels, generations


CAVEAT = (
    'Public baseline contamination is known or unknown; public-source results '
    'are not independent promotion evidence. Automated duplicate grouping may '
    'miss related artwork or capture sessions. Independent camera evaluation '
    'is required before promotion.'
)
SCALARS = ('top1', 'top3', 'top5', 'macro_recall', 'macro_f1', 'nll', 'brier',
           'ece', 'accepted_coverage', 'accepted_accuracy',
           'accepted_known_coverage', 'accepted_known_accuracy', 'unknown_far')
PAIRED_FIELDS = ('group', 'target_id', 'source', 'domain', 'split')


def load_rows(path):
    """Read nonempty JSONL records; malformed lines fail rather than disappear."""
    rows = []
    with Path(path).open(encoding='utf-8-sig') as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f'{path}:{line_number}: invalid JSON') from exc
    return rows


def _label_order(labels):
    return label_ids(labels)


def _prepare(rows, labels, confidence, margin, temperature, ece_bins):
    ids = _label_order(labels)
    for name, value in (('confidence', confidence), ('margin', margin),
                        ('temperature', temperature)):
        if (isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating))
                or not np.isfinite(value)):
            raise ValueError(f'{name} must be finite')
    if not 0 <= confidence <= 1 or margin < 0 or temperature <= 0:
        raise ValueError('require confidence in [0,1], margin >= 0, temperature > 0')
    if type(ece_bins) is not int or ece_bins < 1:
        raise ValueError('ece_bins must be a positive integer')
    rows = list(rows)
    if not rows:
        raise ValueError('at least one prediction row is required')
    seen = set()
    arrays = []
    target = []
    index = {value: i for i, value in enumerate(ids)}
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f'row {i}: expected an object')
        for key in ('sha256', 'group', 'source', 'domain', 'split'):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f'row {i}: {key} must be a nonempty string')
        sha = row['sha256']
        if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError(f'row {i}: sha256 must be lowercase hexadecimal')
        if sha in seen:
            raise ValueError(f'row {i}: duplicate sha256; deduplicate before evaluation')
        seen.add(sha)
        if 'target_id' not in row or (row['target_id'] is not None and
                (type(row['target_id']) is not int or row['target_id'] not in index)):
            raise ValueError(f'row {i}: target_id must occur in labels or be null')
        if 'label_ids' in row:
            declared = row['label_ids']
            if (not isinstance(declared, list) or any(type(x) is not int for x in declared)
                    or declared != ids):
                raise ValueError(f'row {i}: label_ids column order differs from supplied labels')
        if 'labels' in row and row['labels'] != labels:
            raise ValueError(f'row {i}: embedded labels differ from supplied labels')
        raw = row.get('logits')
        if not isinstance(raw, (list, tuple)) or len(raw) != len(ids):
            raise ValueError(f'row {i}: expected exactly {len(ids)} logits')
        if any(isinstance(x, (str, bool)) or not isinstance(x, (int, float)) for x in raw):
            raise ValueError(f'row {i}: logits must be real numbers')
        values = np.asarray(raw, dtype=np.float64)
        if not np.all(np.isfinite(values)):
            raise ValueError(f'row {i}: logits must be finite')
        arrays.append(values)
        target.append(-1 if row['target_id'] is None else index[row['target_id']])
    logits = np.stack(arrays)
    # Stable sort gives deterministic ties in the explicitly supplied label order.
    rank = np.argsort(-logits, axis=1, kind='stable')
    shifted = (logits - logits.max(axis=1, keepdims=True)) / temperature
    if not np.all(np.isfinite(shifted)):
        raise ValueError('logits/temperature exceed safe numeric range')
    log_normalizer = np.log(np.exp(shifted).sum(axis=1))
    probabilities = np.exp(shifted - log_normalizer[:, None])
    y = np.asarray(target, dtype=np.int64)
    known = y >= 0
    prediction = rank[:, 0]
    top_confidence = probabilities[np.arange(len(rows)), prediction]
    raw_margin = logits[np.arange(len(rows)), rank[:, 0]] - logits[np.arange(len(rows)), rank[:, 1]]
    accepted = (top_confidence >= confidence) & (raw_margin >= margin)
    correct = known & (prediction == y)
    nll = np.zeros(len(rows))
    brier = np.zeros(len(rows))
    selected = np.flatnonzero(known)
    nll[selected] = log_normalizer[selected] - shifted[selected, y[selected]]
    brier[selected] = (probabilities[selected] ** 2).sum(axis=1) - 2 * probabilities[selected, y[selected]] + 1
    return dict(rows=rows, ids=ids, y=y, known=known, prediction=prediction,
                correct=correct, accepted=accepted, confidence=top_confidence,
                nll=nll, brier=brier, ece_bins=ece_bins,
                bin=np.minimum((top_confidence * ece_bins).astype(int), ece_bins - 1),
                hits={k: known & (rank[:, :k] == y[:, None]).any(axis=1) for k in (1, 3, 5)})


def _ratio(numerator, denominator):
    return float(numerator / denominator) if denominator else None


def _calculate(data, weights=None, detailed=False):
    n = len(data['y']); classes = len(data['ids'])
    w = np.ones(n) if weights is None else weights
    known, accepted, correct = data['known'], data['accepted'], data['correct']
    kw = w * known
    total, nk, no = float(w.sum()), float(kw.sum()), float(w[~known].sum())
    support = np.bincount(data['y'][known], weights=w[known], minlength=classes)
    predicted = np.bincount(data['prediction'][known], weights=w[known], minlength=classes)
    tp = np.bincount(data['y'][correct], weights=w[correct], minlength=classes)
    recall = np.divide(tp, support, out=np.zeros(classes), where=support > 0)
    precision = np.divide(tp, predicted, out=np.zeros(classes), where=predicted > 0)
    f1 = np.divide(2 * tp, support + predicted, out=np.zeros(classes), where=(support + predicted) > 0)
    supported = support > 0
    result = {f'top{k}': _ratio(float(w[data['hits'][k]].sum()), nk) for k in (1, 3, 5)}
    result.update(macro_recall=float(recall[supported].mean()) if supported.any() else None,
                  macro_f1=float(f1[supported].mean()) if supported.any() else None,
                  nll=_ratio(float(np.dot(kw, data['nll'])), nk),
                  brier=_ratio(float(np.dot(kw, data['brier'])), nk),
                  accepted_coverage=_ratio(float(w[accepted].sum()), total),
                  accepted_accuracy=_ratio(float(w[accepted & correct].sum()), float(w[accepted].sum())),
                  accepted_known_coverage=_ratio(float(w[accepted & known].sum()), nk),
                  accepted_known_accuracy=_ratio(float(w[accepted & correct].sum()), float(w[accepted & known].sum())),
                  unknown_far=_ratio(float(w[accepted & ~known].sum()), no))
    bin_count = np.bincount(data['bin'], weights=kw, minlength=data['ece_bins'])
    bin_conf = np.bincount(data['bin'], weights=kw * data['confidence'], minlength=data['ece_bins'])
    bin_correct = np.bincount(data['bin'], weights=w * correct, minlength=data['ece_bins'])
    result['ece'] = _ratio(float(np.abs(bin_correct - bin_conf).sum()), nk)
    if detailed:
        result['counts'] = dict(images=n, known=int(nk), unknown=int(no),
                                groups=len({r['group'] for r in data['rows']}),
                                supported_classes=int(supported.sum()), accepted=int(w[accepted].sum()))
        result['per_class'] = [dict(id=value, support=int(support[i]), predicted=int(predicted[i]),
                                    true_positive=int(tp[i]), recall=float(recall[i]) if support[i] else None,
                                    precision=float(precision[i]) if predicted[i] else None,
                                    f1=float(f1[i]) if support[i] + predicted[i] else None)
                               for i, value in enumerate(data['ids'])]
        wrong = known & ~correct
        pairs = np.bincount(data['y'][wrong] * classes + data['prediction'][wrong], minlength=classes**2)
        nonzero = np.flatnonzero(pairs)
        order = sorted(nonzero, key=lambda x: (-pairs[x], x))[:20]
        result['top_confusion_pairs'] = [dict(target_id=data['ids'][i // classes], predicted_id=data['ids'][i % classes],
                                             count=int(pairs[i])) for i in order]
        result['calibration_bins'] = [dict(lower=i / data['ece_bins'], upper=(i + 1) / data['ece_bins'],
                                           count=int(bin_count[i]), confidence=_ratio(bin_conf[i], bin_count[i]),
                                           accuracy=_ratio(bin_correct[i], bin_count[i])) for i in range(data['ece_bins'])]
    return result


def _settings(labels, confidence, margin, temperature, ece_bins):
    return dict(confidence_threshold=confidence, raw_logit_margin_threshold=margin,
                temperature=temperature, ece_bins=ece_bins,
                acceptance_rule='softmax(logits / temperature).max >= confidence AND raw top1-top2 logits >= margin',
                tie_break='first column in supplied label order',
                label_ids=_label_order(labels),
                label_order_sha256=hashlib.sha256(json.dumps(labels, sort_keys=True).encode()).hexdigest(),
                label_order_assumption='Producer must emit logits in supplied label order; optional per-row label_ids are checked.',
                metric_definitions='Closed-set and calibration metrics use known targets only; macro scores average supported true classes. Precision uses known-target predictions. Brier is summed over all supplied classes. ECE uses equal-width confidence bins. Accepted accuracy includes accepted unknown images as errors; unknown_far uses unknown images only.')


def _bootstrap(prepared, replicates, seed):
    if type(replicates) is not int or replicates < 1:
        raise ValueError('replicates must be a positive integer')
    rows = prepared[0]['rows']
    groups, inverse = np.unique([r['group'] for r in rows], return_inverse=True)
    rng = np.random.default_rng(seed)
    samples = [{key: [] for key in SCALARS} for _ in prepared]
    for _ in range(replicates):
        # Sample G groups; every image in a sampled group receives its multiplicity.
        counts = np.bincount(rng.integers(len(groups), size=len(groups)), minlength=len(groups))
        weights = counts[inverse]
        for output, data in zip(samples, prepared):
            values = _calculate(data, weights)
            for key in SCALARS:
                output[key].append(values[key])
    return samples, len(groups)


def _interval(values, point):
    array = np.asarray([np.nan if x is None else x for x in values], dtype=float)
    valid = array[np.isfinite(array)]
    lo, hi = np.percentile(valid, [2.5, 97.5]) if len(valid) else (None, None)
    return dict(estimate=point, lower=None if lo is None else float(lo), upper=None if hi is None else float(hi),
                valid_replicates=len(valid), total_replicates=len(values))


def metrics(rows, labels, confidence=.25, margin=.5, temperature=1., *, ece_bins=15,
            bootstrap_replicates=0, seed=20261027, _slices=True):
    """Summarize predictions, optionally adding 95% percentile group-bootstrap CIs.

    Undefined denominators produce None (JSON null). Thresholds and temperature
    must be selected on validation data and frozen before test evaluation.
    """
    data = _prepare(rows, labels, confidence, margin, temperature, ece_bins)
    result = _calculate(data, detailed=True)
    for record, label in zip(result['per_class'], labels):
        record['name'] = label['name']
    result['settings'] = _settings(labels, confidence, margin, temperature, ece_bins)
    result['baseline_contamination_caveat'] = CAVEAT
    if _slices: result['slices'] = slice_metrics(data['rows'], labels, confidence, margin, temperature, ece_bins)
    if type(bootstrap_replicates) is not int or bootstrap_replicates < 0:
        raise ValueError('bootstrap_replicates must be a nonnegative integer')
    if bootstrap_replicates:
        samples, group_count = _bootstrap([data], bootstrap_replicates, seed)
        result['confidence_intervals'] = {key: _interval(samples[0][key], result[key]) for key in SCALARS}
        result['bootstrap'] = dict(method='95% percentile group bootstrap', seed=seed,
                                   replicates=bootstrap_replicates, groups=group_count,
                                   caveat='Intervals condition on observed groups and class support; one group cannot estimate population uncertainty. Undefined replicates are omitted and counted.')
    return result


def slice_metrics(rows, labels, confidence=.25, margin=.5, temperature=1., ece_bins=15):
    """Catalog generation is authoritative; unknown targets get a null slice."""
    rows=list(rows);generation=generations(); result={}
    for key in ('source','generation'):
        buckets={}
        for row in rows:
            value=row['source'] if key=='source' else generation.get(row['target_id'])
            buckets.setdefault(str(value) if value is not None else 'unknown',[]).append(row)
        result[key]={}
        for value,items in sorted(buckets.items()):
            summary=metrics(items,labels,confidence,margin,temperature,ece_bins=ece_bins,_slices=False)
            result[key][value]={k:summary[k] for k in (*SCALARS,'counts')}
    return result


def compare_models(baseline_rows, candidate_rows, labels, confidence=.25, margin=.5,
                   temperature=1., *, baseline_temperature=None, ece_bins=15,
                   replicates=1000, seed=20261027, baseline_confidence=None,
                   baseline_margin=None):
    """Paired CIs of candidate minus baseline, resampling identical image groups.

    Inputs may be JSONL paths or iterables. Pairing is exact, never an intersection.
    Confidence, margin and temperature describe the candidate policy. Each
    baseline override defaults to the corresponding candidate value, preserving
    the original .25 confidence/.5 raw margin/T=1 comparison. Overrides support
    separately validation-frozen operating points. Thresholds are fixed for all
    bootstrap draws, never retuned on test samples. An abstain_all policy must be
    handled explicitly by a consumer, never encoded as a large finite threshold.
    """
    def read(value):
        return load_rows(value) if isinstance(value, (str, Path)) else list(value)
    first, second = read(baseline_rows), read(candidate_rows)
    bt = temperature if baseline_temperature is None else baseline_temperature
    bc = confidence if baseline_confidence is None else baseline_confidence
    bm = margin if baseline_margin is None else baseline_margin
    baseline = _prepare(first, labels, bc, bm, bt, ece_bins)
    candidate = _prepare(second, labels, confidence, margin, temperature, ece_bins)
    candidates = {row['sha256']: row for row in second}
    if set(candidates) != {row['sha256'] for row in first}:
        raise ValueError('paired comparison requires identical sha256 sets')
    aligned = [candidates[row['sha256']] for row in first]
    for row, other in zip(first, aligned):
        for field in PAIRED_FIELDS:
            if row[field] != other[field]:
                raise ValueError(f'paired metadata differs for {row["sha256"]}: {field}')
    candidate = _prepare(aligned, labels, confidence, margin, temperature, ece_bins)
    a, b = _calculate(baseline), _calculate(candidate)
    samples, groups = _bootstrap([baseline, candidate], replicates, seed)
    deltas = {}
    for key in SCALARS:
        point = None if a[key] is None or b[key] is None else b[key] - a[key]
        values = [None if x is None or y is None else y - x
                  for x, y in zip(samples[0][key], samples[1][key])]
        deltas[key] = _interval(values, point)
    return dict(baseline=metrics(first, labels, bc, bm, bt, ece_bins=ece_bins),
                candidate=metrics(aligned, labels, confidence, margin, temperature, ece_bins=ece_bins),
                delta_candidate_minus_baseline=deltas,
                bootstrap=dict(method='95% paired percentile group bootstrap', seed=seed,
                               replicates=replicates, groups=groups,
                               caveat='Intervals condition on observed groups and support. Undefined paired draws are omitted and counted; one group cannot estimate population uncertainty.'),
                direction='Higher is better except nll, brier, ece, and unknown_far. Coverage alone is not quality.',
                baseline_contamination_caveat=CAVEAT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest='command', required=True)
    for name in ('summarize', 'compare'):
        command = subcommands.add_parser(name)
        command.add_argument('--labels', type=Path, default=LABELS)
        command.add_argument('--confidence', type=float, default=.25)
        command.add_argument('--margin', type=float, default=.5, help='raw, unscaled logit margin')
        command.add_argument('--temperature', type=float, default=1.)
        command.add_argument('--ece-bins', type=int, default=15)
        command.add_argument('--replicates', type=int, default=1000)
        command.add_argument('--seed', type=int, default=20261027)
        command.add_argument('--output', type=Path)
        command.add_argument('--split', action='append', help='explicit split filter; repeat for known and OOD splits')
        if name == 'summarize':
            command.add_argument('--predictions', type=Path, required=True)
        else:
            command.add_argument('--baseline', type=Path, required=True)
            command.add_argument('--candidate', type=Path, required=True)
            command.add_argument('--baseline-temperature', type=float)
            command.add_argument('--baseline-confidence', type=float,
                                 help='validation-frozen baseline confidence; defaults to --confidence')
            command.add_argument('--baseline-margin', type=float,
                                 help='validation-frozen baseline raw logit margin; defaults to --margin')
    args = parser.parse_args()
    labels = read_labels(args.labels)
    def selected(path):
        rows = load_rows(path)
        return [row for row in rows if not args.split or row.get('split') in args.split]
    common = dict(confidence=args.confidence, margin=args.margin, temperature=args.temperature,
                  ece_bins=args.ece_bins, seed=args.seed)
    if args.command == 'summarize':
        report = metrics(selected(args.predictions), labels, bootstrap_replicates=args.replicates, **common)
    else:
        report = compare_models(selected(args.baseline), selected(args.candidate), labels,
                                baseline_temperature=args.baseline_temperature,
                                baseline_confidence=args.baseline_confidence,
                                baseline_margin=args.baseline_margin,
                                replicates=args.replicates, **common)
    report['provenance'] = dict(labels=str(args.labels), selected_splits=args.split,
                               prediction_files=[str(args.predictions)] if args.command == 'summarize'
                               else [str(args.baseline), str(args.candidate)])
    rendered = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + '\n', encoding='utf-8')
    else:
        print(rendered)


if __name__ == '__main__':
    main()
