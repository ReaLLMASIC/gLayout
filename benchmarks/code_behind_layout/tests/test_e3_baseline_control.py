"""Bounded development-control software fixtures, not physical evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.e3_baseline_control import run


class BaselineControlTests(unittest.TestCase):
    def test_fixed_three_call_plan_and_second_invocation_does_not_repeat(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);manifest = root/'draft.json';output = root/'control'
            manifest.write_text(json.dumps({'status': 'DRAFT_E3', 'preparation': '/software_fixture'}))
            with patch('scripts.e3_baseline_control.parameter_control', return_value={'status': 'SEARCH_FINISHED', 'new_physical_calls': 2}) as p, patch(
                    'scripts.e3_baseline_control.instance_control', return_value={'new_physical_calls': 1}) as i:
                first = run(manifest, output)
                again = run(manifest, output)
            self.assertEqual(first, again)
            self.assertEqual(p.call_count, 1);self.assertEqual(i.call_count, 1)
            plan = json.loads((output/'plan.json').read_text())
            self.assertEqual(plan['maximum_new_physical_calls'], 3)
            self.assertEqual(plan['I_arrivals'], ['anchor', 'anchor'])
            self.assertEqual(first['new_physical_calls'], 3)
            self.assertEqual(first['model_calls'], 0);self.assertEqual(first['hidden_calls'], 0)

    def test_unknown_stops_and_incomplete_existing_output_cannot_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);manifest = root/'draft.json';output = root/'control'
            manifest.write_text(json.dumps({'status': 'DRAFT_E3'}))
            with patch('scripts.e3_baseline_control.parameter_control', return_value={'status': 'INCOMPLETE_UNKNOWN', 'new_physical_calls': 1}), patch(
                    'scripts.e3_baseline_control.instance_control', side_effect=AssertionError('No I dispatch after unknown')):
                report = run(manifest, output)
            self.assertEqual(report['status'], 'PAUSED_UNKNOWN')
            self.assertEqual(report['I']['status'], 'NOT_RUN')
            (output/'summary.json').unlink()
            with self.assertRaisesRegex(RuntimeError, 'incomplete engineering control'):
                run(manifest, output)

    def test_formal_manifest_cannot_be_changed_into_control(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);manifest = root/'formal.json'
            manifest.write_text(json.dumps({'status': 'FROZEN_E3'}))
            with self.assertRaises(ValueError):
                run(manifest, root/'control')
            self.assertFalse((root/'control').exists())


if __name__ == '__main__':
    unittest.main()
