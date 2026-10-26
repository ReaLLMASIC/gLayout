"""Qualification-to-DRAFT gate fixtures; these are not experiment results."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.prepare_train_pair_nf_collection import prepare


class NFCollectionPreparationTests(unittest.TestCase):
    def fixture(self, root, complete):
        prep = root / 'prep'; prep.mkdir(); trusted = prep / 'trusted'; trusted.mkdir()
        (trusted / 'evaluate.py').write_text('software fixture')
        points = [{'configuration_id': str(i)} for i in range(9)]
        (prep / 'plan.json').write_text(json.dumps({'configurations': points, 'trusted_bundle': str(trusted)}))
        raw = root / 'raw'; raw.mkdir()
        state = {'status': 'COMPLETED_FIXED_NINE_PHYSICAL_ATTEMPTS' if complete else 'RUNNING_FIXED_FRESH_NINE',
            'preparation': str(prep), 'records': [{'configuration_id': str(i), 'result': {}} for i in range(9 if complete else 3)],
            'not_started': [] if complete else [str(i) for i in range(3, 9)]}
        (raw / 'state.json').write_text(json.dumps(state))
        return raw

    def test_running_partial_grid_cannot_create_a_collection_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); raw = self.fixture(root, False)
            with patch('scripts.prepare_train_pair_nf_collection.inspect_result') as inspect:
                with self.assertRaisesRegex(ValueError, 'full original nine-point'):
                    prepare(raw, root / 'output')
                inspect.assert_not_called()
            self.assertFalse((root / 'output').exists())

    def test_completed_summary_cannot_override_a_failed_current_raw_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); raw = self.fixture(root, True)
            with patch('scripts.prepare_train_pair_nf_collection.inspect_result', return_value={'S2': False}) as inspect:
                with self.assertRaisesRegex(ValueError, 'Every predeclared point'):
                    prepare(raw, root / 'output')
                self.assertEqual(inspect.call_count, 1)
            self.assertFalse((root / 'output').exists())

    def test_original_s2_does_not_bypass_full_rc_device_and_port_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); raw = self.fixture(root, True)
            with patch('scripts.prepare_train_pair_nf_collection.inspect_result',
                       return_value={'S2': True, 'point_evaluation_complete': True}), \
                 patch('scripts.prepare_train_pair_nf_collection.audit_full_rc',
                       return_value={'matching_points': 8, 'quarantined_points': 1}):
                with self.assertRaisesRegex(ValueError, 'RC models'):
                    prepare(raw, root / 'output')
            self.assertFalse((root / 'output').exists())


if __name__ == '__main__':
    unittest.main()
