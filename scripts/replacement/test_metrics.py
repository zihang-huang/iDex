"""Synthetic, deterministic evaluation checks; no model/data/network required.

Run: python -m unittest discover -s scripts/replacement -p test_metrics.py
"""
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import metrics as evaluation
from labels import read_labels

CLASS_COUNT = len(read_labels())


LABELS = [dict(id=i, name=f'class-{i}') for i in range(1, CLASS_COUNT+1)]


def row(identity, target, winner=1, group=None, logits=None):
    if logits is None:
        logits = [-20.] * CLASS_COUNT
        logits[winner - 1] = 20.
    return dict(sha256=hashlib.sha256(str(identity).encode()).hexdigest(),
                group=str(identity) if group is None else group, target_id=target,
                source='synthetic', domain='unit', split='test_public',
                label_ids=list(range(1, CLASS_COUNT+1)), logits=logits)


class MetricTests(unittest.TestCase):
    def test_known_class_and_open_set_denominators(self):
        rows = [row('a', 1), row('b', 1, 2), row('c', 2, 2), row('d', None)]
        result = evaluation.metrics(rows, LABELS)
        self.assertAlmostEqual(result['top1'], 2 / 3)
        self.assertAlmostEqual(result['macro_recall'], .75)
        self.assertAlmostEqual(result['macro_f1'], 2 / 3)
        self.assertEqual(result['counts']['supported_classes'], 2)
        self.assertEqual(result['accepted_coverage'], 1)
        self.assertEqual(result['accepted_accuracy'], .5)
        self.assertAlmostEqual(result['accepted_known_accuracy'], 2 / 3)
        self.assertEqual(result['unknown_far'], 1)
        self.assertEqual(result['per_class'][0]['support'], 2)
        self.assertEqual(result['per_class'][0]['precision'], 1)
        self.assertEqual(result['per_class'][1]['precision'], .5)
        self.assertIsNone(result['per_class'][2]['recall'])
        self.assertEqual(result['top_confusion_pairs'], [dict(target_id=1, predicted_id=2, count=1)])
        self.assertIn('not independent promotion evidence', result['baseline_contamination_caveat'])
        json.dumps(result, allow_nan=False)

    def test_uniform_predictions_have_analytic_calibration(self):
        # Uniform predictions have probability 1/151 and deterministic class-1 ties.
        result = evaluation.metrics([row('u', 2, logits=[0.] * CLASS_COUNT)], LABELS)
        self.assertEqual(result['top1'], 0)
        self.assertEqual(result['top3'], 1)
        self.assertEqual(result['top5'], 1)
        self.assertAlmostEqual(result['nll'], math.log(CLASS_COUNT))
        self.assertAlmostEqual(result['brier'], (CLASS_COUNT-1) / CLASS_COUNT)
        self.assertAlmostEqual(result['ece'], 1 / CLASS_COUNT)
        self.assertEqual(result['accepted_coverage'], 0)
        self.assertIsNone(result['accepted_accuracy'])
        self.assertIsNone(result['unknown_far'])

    def test_rank_three_and_five_boundaries(self):
        logits = list(range(CLASS_COUNT, 0, -1))
        result = evaluation.metrics([row('three', 3, logits=logits), row('five', 5, logits=logits),
                                     row('six', 6, logits=logits)], LABELS)
        self.assertEqual(result['top1'], 0)
        self.assertAlmostEqual(result['top3'], 1 / 3)
        self.assertAlmostEqual(result['top5'], 2 / 3)

    def test_temperature_changes_confidence_but_not_raw_margin(self):
        logits = [-100.] * CLASS_COUNT
        logits[0:2] = [1., 0.]
        rows = [row('temperature', 1, logits=logits)]
        # At T=2 confidence is about .622, while raw margin remains 1.
        warm = evaluation.metrics(rows, LABELS, confidence=.6, margin=.75, temperature=2)
        self.assertEqual(warm['accepted_coverage'], 1)
        self.assertEqual(evaluation.metrics(rows, LABELS, confidence=.7, temperature=2)['accepted_coverage'], 0)
        self.assertEqual(evaluation.metrics(rows, LABELS, margin=1.01, temperature=.5)['accepted_coverage'], 0)
        shifted = copy.deepcopy(rows)
        shifted[0]['logits'] = [x + 1000 for x in logits]
        self.assertAlmostEqual(evaluation.metrics(shifted, LABELS)['nll'],
                               evaluation.metrics(rows, LABELS)['nll'])

    def test_ood_only_reports_null_closed_set_metrics(self):
        result = evaluation.metrics([row('ood', None)], LABELS, bootstrap_replicates=8)
        for key in ('top1', 'top3', 'top5', 'macro_recall', 'macro_f1', 'nll', 'brier', 'ece'):
            self.assertIsNone(result[key])
            self.assertEqual(result['confidence_intervals'][key]['valid_replicates'], 0)
        self.assertEqual(result['unknown_far'], 1)
        self.assertEqual(result['accepted_accuracy'], 0)
        json.dumps(result, allow_nan=False)

    def test_explicit_non_numeric_label_order_is_respected(self):
        labels = LABELS[::-1]
        sample = row('reverse', CLASS_COUNT)
        sample['label_ids'] = list(range(CLASS_COUNT, 0, -1))
        result = evaluation.metrics([sample], labels)
        self.assertEqual(result['top1'], 1)
        self.assertEqual(result['per_class'][0]['id'], CLASS_COUNT)

    def test_schema_rejects_bad_counts_nonfinite_and_mixed_orders(self):
        mutations = [lambda x: x.pop('target_id'), lambda x: x.update(target_id=True),
                     lambda x: x.update(target_id=CLASS_COUNT+1), lambda x: x.update(group=''),
                     lambda x: x.update(logits=[1.] * (CLASS_COUNT-1)), lambda x: x['logits'].__setitem__(0, float('nan')),
                     lambda x: x['logits'].__setitem__(0, '1'), lambda x: x.update(sha256='abc'),
                     lambda x: x['label_ids'].reverse()]
        for mutate in mutations:
            sample = row('bad', 1)
            mutate(sample)
            with self.subTest(sample=sample), self.assertRaises(ValueError):
                evaluation.metrics([sample], LABELS)
        with self.assertRaises(ValueError):
            evaluation.metrics([row('same', 1), row('same', 1)], LABELS)
        with self.assertRaises(ValueError):
            evaluation.metrics([row('valid', 1)], LABELS[:-1])
        with self.assertRaises(ValueError):
            evaluation.metrics([row('valid', 1)], LABELS[:-1] + [LABELS[0]])
        for options in (dict(confidence=1.1), dict(margin=-1), dict(temperature=0),
                        dict(ece_bins=0), dict(confidence='invalid')):
            with self.subTest(options=options), self.assertRaises(ValueError):
                evaluation.metrics([row('valid', 1)], LABELS, **options)

    def test_paired_bootstrap_uses_groups_and_aligns_permuted_rows(self):
        # Cluster 1 has nine images; cluster 2 has one. Sampling two clusters
        # gives differences 0, .9, or 1, unlike an image bootstrap.
        baseline = [row(i, 1, 2, group='large') for i in range(9)] + [row(9, 1, group='small')]
        candidate = [row(i, 1, group='large') for i in range(9)] + [row(9, 1, group='small')]
        result = evaluation.compare_models(baseline, candidate[::-1], LABELS, replicates=1000, seed=7)
        interval = result['delta_candidate_minus_baseline']['top1']
        self.assertAlmostEqual(interval['estimate'], .9)
        self.assertEqual(interval['lower'], 0)
        self.assertEqual(interval['upper'], 1)
        self.assertEqual(interval['valid_replicates'], 1000)
        self.assertEqual(result['bootstrap']['groups'], 2)
        same = evaluation.compare_models(baseline, baseline[::-1], LABELS, replicates=30)
        for key in evaluation.SCALARS:
            interval = same['delta_candidate_minus_baseline'][key]
            if interval['estimate'] is not None:
                self.assertEqual((interval['lower'], interval['upper']), (0, 0))

    def test_comparison_refuses_partial_or_changed_pairing(self):
        original = [row('a', 1), row('b', 2)]
        with self.assertRaises(ValueError):
            evaluation.compare_models(original, original[:1], LABELS, replicates=3)
        for field, value in [('group', 'different'), ('target_id', 2), ('split', 'val'),
                             ('source', 'changed'), ('domain', 'changed')]:
            changed = copy.deepcopy(original)
            changed[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                evaluation.compare_models(original, changed, LABELS, replicates=3)

    def test_separately_frozen_policies_have_paired_action_coverage_delta(self):
        # Identical predictions and class accuracy, but confidence ~.731. The
        # baseline accepts every image at .7; the candidate abstains at .8.
        logits = [1., 0.] + [-100.] * (CLASS_COUNT-2)
        rows = [row('known', 1, logits=logits), row('unknown', None, logits=logits)]
        result = evaluation.compare_models(rows, rows[::-1], LABELS, confidence=.8, margin=.5,
                                            baseline_confidence=.7, baseline_margin=.5, replicates=40)
        self.assertEqual(result['baseline']['accepted_coverage'], 1)
        self.assertEqual(result['candidate']['accepted_coverage'], 0)
        interval = result['delta_candidate_minus_baseline']['accepted_coverage']
        self.assertEqual((interval['estimate'], interval['lower'], interval['upper']), (-1, -1, -1))
        self.assertEqual(interval['valid_replicates'], 40)
        self.assertEqual(result['delta_candidate_minus_baseline']['top1']['estimate'], 0)
        self.assertEqual(result['baseline']['settings']['confidence_threshold'], .7)
        # Margin overrides must independently use the original, unscaled logits.
        margin_result = evaluation.compare_models(rows, rows, LABELS, confidence=.6, margin=1.1,
                                                   baseline_margin=.5, replicates=10)
        self.assertEqual(margin_result['delta_candidate_minus_baseline']['accepted_coverage']['estimate'], -1)
        # Omitting overrides continues comparing both models at one fixed policy.
        default = evaluation.compare_models(rows, rows, LABELS, replicates=10)
        self.assertEqual(default['delta_candidate_minus_baseline']['accepted_coverage']['estimate'], 0)

    def test_file_comparison_and_reproducible_aggregate_intervals(self):
        rows = [row('a', 1), row('b', 1, 2), row('c', None)]
        summary = evaluation.metrics(rows, LABELS, bootstrap_replicates=40, seed=10)
        self.assertEqual(summary, evaluation.metrics(rows, LABELS, bootstrap_replicates=40, seed=10))
        self.assertEqual(summary['confidence_intervals']['top1']['estimate'], .5)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory) / 'predictions.jsonl'
            path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
            report = evaluation.compare_models(path, path, LABELS, replicates=10)
            self.assertEqual(report['delta_candidate_minus_baseline']['top1']['estimate'], 0)
            path.write_text('{bad json}\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, ':1: invalid JSON'):
                evaluation.load_rows(path)

    def test_cli_emits_json_for_summary_and_comparison(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            directory = Path(directory)
            labels = directory / 'labels.json'
            predictions = directory / 'predictions.jsonl'
            labels.write_text(json.dumps(LABELS), encoding='utf-8')
            predictions.write_text(json.dumps(row('a', 1)) + '\n', encoding='utf-8')
            for command, arguments in [('summarize', ['--predictions', str(predictions)]),
                                       ('compare', ['--baseline', str(predictions), '--candidate', str(predictions)])]:
                output = io.StringIO()
                argv = ['metrics.py', command, '--labels', str(labels), '--replicates', '5'] + arguments
                with patch('sys.argv', argv), patch('sys.stdout', output):
                    evaluation.main()
                report = json.loads(output.getvalue())
                self.assertIn('provenance', report)
                if command == 'summarize':
                    self.assertEqual(report['top1'], 1)
                else:
                    self.assertEqual(report['delta_candidate_minus_baseline']['top1']['estimate'], 0)
            predictions.write_text(json.dumps(row('policy', 1, logits=[1., 0.] + [-100.] * (CLASS_COUNT-2))) + '\n', encoding='utf-8')
            output = io.StringIO()
            argv = ['metrics.py', 'compare', '--labels', str(labels), '--baseline', str(predictions),
                    '--candidate', str(predictions), '--replicates', '5', '--confidence', '.8',
                    '--baseline-confidence', '.7', '--baseline-margin', '.5']
            with patch('sys.argv', argv), patch('sys.stdout', output):
                evaluation.main()
            report = json.loads(output.getvalue())
            self.assertEqual(report['delta_candidate_minus_baseline']['accepted_coverage']['estimate'], -1)


if __name__ == '__main__':
    unittest.main()
