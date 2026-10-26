"""Fixed-plan/resume software controls, not physical qualification results."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts.e3_remaining_ota_qualify import TASKS, fixed_plan, retained_points, returned_file, wait_upstream


class RemainingOTAQualificationTests(unittest.TestCase):
    def test_fixed_four_complete_source_bindings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for ident in TASKS:
                folder = root/'private'/ident;folder.mkdir(parents=True)
                source = folder/'layout.py';source.write_text('complete = "software fixture"\n')
                task = {'task_id': ident, 'target': 'five_t' if 'five_t' in ident else 'compact_miller',
                    'formal_admission': False, 'source_overrides': {'layout.py': str(source)}}
                (folder/'task.json').write_text(json.dumps(task))
            plan = fixed_plan(root)
            self.assertEqual(tuple(row['task_id'] for row in plan), TASKS)
            before = plan[0]['editable_source_bytes_as_text']['layout.py']
            (root/'private'/TASKS[0]/'layout.py').write_text(before+'# changed actual source\n')
            self.assertNotEqual(fixed_plan(root), plan)

    def test_returned_unknown_is_not_rerun(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);folder = root/'points'/TASKS[0];folder.mkdir(parents=True)
            (folder/'point.json').write_text(json.dumps({'task_id': TASKS[0], 'configuration_id': 'anchor',
                'fidelity': 'pex_spice', 'run_directory': '/software_fixture_not_actual_measurement',
                'checked': {'execution_integrity': 'incomplete', 'S2': False}}))
            done, missing = retained_points(root)
            self.assertIn(TASKS[0], done)
            self.assertNotIn(TASKS[0], missing)
            self.assertEqual(tuple(missing), TASKS[1:])

    def test_started_without_final_record_is_unresolved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);(root/'points'/TASKS[0]).mkdir(parents=True)
            with self.assertRaisesRegex(RuntimeError, 'UNRESOLVED'):
                retained_points(root)

    def test_waits_for_returned_basic_record_not_boolean_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);full = root/'full.json';basic = root/'basic.json'
            full.write_text(json.dumps({'status': 'COMPLETE', 'records': []}))
            basic.write_text(json.dumps({'fidelity': 'basic', 'run_directory': '/software_fixture',
                'checked': {'execution_integrity': 'incomplete', 'S2': False}}))
            result, waiting = wait_upstream(full, basic, root, .1)
            self.assertEqual(result['status'], 'COMPLETE')
            self.assertEqual(waiting['status'], 'UPSTREAM_PHYSICAL_LANES_RETURNED')
            basic.write_text('{"partial":')
            self.assertIsNone(returned_file(basic))


if __name__ == '__main__':
    unittest.main()
