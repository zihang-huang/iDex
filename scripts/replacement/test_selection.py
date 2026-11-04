"""CPU-only selection contract checks with tiny synthetic validation artifacts.

Run: python -m unittest discover -s scripts/replacement -p test_selection.py -v
No images, model construction, accelerator calls, or real training files are used.
"""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

import choose_candidate
from labels import read_labels

CLASS_COUNT = len(read_labels())


LABELS = [dict(id=i, name=f'class-{i}') for i in range(1, CLASS_COUNT+1)]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prediction(identity, target, split, source, confident=True):
    logits = [0.] * CLASS_COUNT
    if confident:
        logits[0] = 30.
    return dict(sha256=hashlib.sha256(identity.encode()).hexdigest(), group=identity,
                target_id=target, source=source, domain='synthetic', split=split,
                label_ids=list(range(1, CLASS_COUNT+1)), logits=logits)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        # Explicit workspace temp avoids sandboxed OS temp paths on Windows.
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.labels_path = self.root / 'labels.json'
        self.labels_path.write_text(json.dumps(LABELS),encoding='utf-8')
        self.manifest = self.root / 'manifest.jsonl'
        self.predictions = self.root / 'validation.jsonl'
        self.receipt = self.predictions.with_suffix('.metadata.json')
        self.checkpoint = self.root / 'candidate.pt'
        self.output = self.root / 'selection.json'
        self.rows = [prediction('known', 1, 'val', 'public'),
                     prediction('ood-art', None, 'ood_val', 'artwork', confident=False),
                     prediction('ood-natural', None, 'ood_val', 'natural', confident=False)]
        self.truth = [dict(r, use=True) for r in self.rows]
        # Training, test and excluded validation rows must not enter the expected
        # selection population. The selector reads metadata only, not images.
        self.truth.extend([dict(prediction('train', 1, 'train', 'public'), use=True),
                           dict(prediction('test', 1, 'test_public', 'public'), use=True),
                           dict(prediction('excluded', 1, 'val', 'public'), use=False)])
        self.write_jsonl(self.manifest, self.truth)
        self.state = dict(model={'sentinel': torch.tensor([1.], device='cpu')},
                          config=dict(arch='mobilenet_v3_large', size=224, manifest=str(self.manifest)),
                          labels=copy.deepcopy(LABELS), manifest_sha256=sha(self.manifest))
        self.save_checkpoint()
        self.save_predictions()

    @staticmethod
    def write_jsonl(path, rows):
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')

    def save_checkpoint(self):
        torch.save(self.state, self.checkpoint)

    def save_receipt(self):
        self.receipt.write_text(json.dumps(dict(checkpoint_sha256=sha(self.checkpoint),
                                               manifest_sha256=sha(self.manifest),
                                               arch='mobilenet_v3_large', size=224,
                                               predictions_sha256=sha(self.predictions))), encoding='utf-8')

    def save_predictions(self):
        self.write_jsonl(self.predictions, self.rows)
        self.save_receipt()

    def select(self):
        argv = ['choose_candidate.py', '--checkpoint', str(self.checkpoint),
                '--predictions', str(self.predictions), '--out', str(self.output), '--labels', str(self.labels_path)]
        with patch('sys.argv', argv), patch('sys.stdout', io.StringIO()):
            choose_candidate.main()
        return json.loads(self.output.read_text())

    def assert_rejected(self, message):
        with self.assertRaisesRegex(ValueError, message):
            self.select()
        self.assertFalse(self.output.exists(), 'rejected inputs must not freeze a selection')

    def test_valid_population_freezes_receipted_policy_without_promoting(self):
        result = self.select()
        policy = result['policy']
        self.assertIs(policy['enabled'], True)
        self.assertIs(policy['abstain_all'], False)
        self.assertEqual(policy['validation_known_coverage'], 1)
        self.assertEqual(policy['validation_known_accuracy'], 1)
        self.assertEqual(policy['validation_unknown_far'], 0)
        self.assertEqual(policy['validation_source_fars'], {'artwork': 0, 'natural': 0})
        self.assertEqual(result['checkpoint_sha256'], sha(self.checkpoint))
        self.assertEqual(result['manifest_sha256'], sha(self.manifest))
        self.assertEqual(result['validation_predictions_sha256'], sha(self.predictions))
        self.assertIs(result['promotion'], False)
        frozen = self.output.read_bytes()
        with self.assertRaisesRegex(ValueError, 'already frozen'):
            self.select()
        self.assertEqual(self.output.read_bytes(), frozen)

    def test_infeasible_policy_is_explicit_unconditional_abstention(self):
        # An OOD image is indistinguishable from the correct known image. Every
        # policy accepting the known image also false-accepts this OOD source.
        self.rows[1]['logits'] = list(self.rows[0]['logits'])
        self.save_predictions()
        result = self.select()
        policy = result['policy']
        self.assertIs(policy['enabled'], False)
        self.assertIs(policy['abstain_all'], True)
        self.assertIn('unconditionally abstain', policy['status'])
        # A made-up huge finite cutoff could later accept extreme logits. There
        # must be no numeric acceptance thresholds masquerading as abstain-all.
        self.assertNotIn('confidence', policy)
        self.assertNotIn('margin', policy)
        self.assertNotIn('validation_known_accuracy', policy)
        self.assertIs(result['promotion'], False)
        json.dumps(result, allow_nan=False)

    def test_large_easy_ood_source_cannot_hide_natural_source_failure(self):
        # Pooled FAR is 1/21 (<5%), but natural-object FAR is 100%. A pooled-only
        # selector would accept this policy; the source-specific gate must stop it.
        self.rows = [prediction('known', 1, 'val', 'public'),
                     prediction('hard-natural', None, 'ood_val', 'natural')]
        self.rows.extend(prediction(f'easy-{i}', None, 'ood_val', 'artwork', confident=False)
                         for i in range(20))
        self.truth = [dict(r, use=True) for r in self.rows]
        self.write_jsonl(self.manifest, self.truth)
        self.state['manifest_sha256'] = sha(self.manifest)
        self.save_checkpoint()
        self.save_predictions()
        policy = self.select()['policy']
        self.assertIs(policy['enabled'], False)
        self.assertIs(policy['abstain_all'], True)

    def test_v1_manifest_receipt_cannot_select_v2_manifest(self):
        stale = json.loads(self.receipt.read_text())
        stale['manifest_sha256'] = hashlib.sha256(b'prior v1 split manifest').hexdigest()
        self.receipt.write_text(json.dumps(stale))
        self.assert_rejected('prediction receipt mismatch: manifest_sha256')

    def test_legacy_receipt_missing_prediction_digest_is_rejected(self):
        stale = json.loads(self.receipt.read_text())
        stale.pop('predictions_sha256')
        self.receipt.write_text(json.dumps(stale))
        self.assert_rejected('prediction receipt mismatch: predictions_sha256')

    def test_replaced_checkpoint_invalidates_existing_prediction_receipt(self):
        self.state['model']['sentinel'] = torch.tensor([2.], device='cpu')
        self.save_checkpoint()
        self.assert_rejected('prediction receipt mismatch: checkpoint_sha256')

    def test_current_receipt_cannot_hide_checkpoint_old_manifest(self):
        self.state['manifest_sha256'] = hashlib.sha256(b'old v1 manifest').hexdigest()
        self.save_checkpoint()
        self.save_receipt()
        self.assert_rejected('manifest mismatch')

    def test_changed_prediction_bytes_invalidate_receipt(self):
        self.rows[0]['logits'][0] = 29.
        self.write_jsonl(self.predictions, self.rows)
        self.assert_rejected('prediction receipt mismatch: predictions_sha256')

    def test_missing_validation_row_is_not_silently_evaluated_as_subset(self):
        self.rows.pop()
        self.save_predictions()
        self.assert_rejected('validation population mismatch')

    def test_duplicate_prediction_identity_cannot_replace_required_row(self):
        self.rows[-1] = copy.deepcopy(self.rows[0])
        self.save_predictions()
        self.assert_rejected('validation population mismatch')

    def test_extra_duplicate_prediction_is_rejected(self):
        self.rows.append(copy.deepcopy(self.rows[0]))
        self.save_predictions()
        self.assert_rejected('validation population mismatch')

    def test_metadata_must_match_frozen_manifest(self):
        original = copy.deepcopy(self.rows)
        for field, changed in [('group', 'another-session'), ('target_id', 2),
                               ('source', 'different'), ('domain', 'different')]:
            with self.subTest(field=field):
                self.rows = copy.deepcopy(original)
                self.rows[0][field] = changed
                self.save_predictions()
                self.assert_rejected(f'prediction metadata mismatch: {field}')

    def test_missing_or_mixed_prediction_label_order_is_rejected(self):
        original = copy.deepcopy(self.rows)
        for mode in ('missing', 'reversed'):
            with self.subTest(mode=mode):
                self.rows = copy.deepcopy(original)
                if mode == 'missing':
                    self.rows[1].pop('label_ids')
                else:
                    self.rows[1]['label_ids'].reverse()
                self.save_predictions()
                self.assert_rejected('explicit label order required')

    def test_checkpoint_label_order_must_match_prediction_columns(self):
        self.state['labels'].reverse()
        self.save_checkpoint()
        self.save_receipt()
        self.assert_rejected('checkpoint labels mismatch')

    def test_strict_metrics_gate_rejects_wrong_logit_count_and_nonfinite(self):
        original = copy.deepcopy(self.rows)
        for bad in ([0.] * (CLASS_COUNT-1), [float('nan')] + [0.] * (CLASS_COUNT-1)):
            with self.subTest(length=len(bad)):
                self.rows = copy.deepcopy(original)
                self.rows[0]['logits'] = bad
                self.save_predictions()
                self.assert_rejected(f'{CLASS_COUNT} logits|logits must be finite')

    def test_test_split_cannot_influence_selection(self):
        self.rows[0]['split'] = 'test_public'
        self.save_predictions()
        self.assert_rejected('Only validation inputs')

    def test_validation_requires_both_known_and_unknown_examples(self):
        original = copy.deepcopy(self.rows)
        for target in (None, 1):
            with self.subTest(target=target):
                self.rows = copy.deepcopy(original)
                for record in self.rows:
                    record['target_id'] = target
                self.truth = [dict(r, use=True) for r in self.rows]
                self.write_jsonl(self.manifest, self.truth)
                self.state['manifest_sha256'] = sha(self.manifest)
                self.save_checkpoint()
                self.save_predictions()
                self.assert_rejected('Need positive and negative validation data')


if __name__ == '__main__':
    unittest.main()
