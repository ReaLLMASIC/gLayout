"""Post-release orchestration software fixtures; no model or EDA execution."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.run_e3_evaluation import baseline, post, released_plan, save
from src.e3_dispatch import plan
from tests.test_run_e3_suite import manifest_fixture


class E3EvaluationTests(unittest.TestCase):
    def test_actual_readonly_release_must_cover_exact1730_fixed_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);manifest = manifest_fixture();manifest['hidden_release_file'] = str(root/'release.json')
            manifest['original_baseline_plan'] = str(root/'original/plan.json')
            release = {'sealed_searches': [], 'search_counts': {'gpt': 480, 'parameter': 80, 'local': 1080,
                'signals': 80, 'fidelity': 10}}
            for part in ('gpt', 'parameter', 'local', 'signals', 'fidelity'):
                for row in plan(manifest, part):
                    release['sealed_searches'].append({**row, 'episode_directory': str(root/'episodes'/str(len(release['sealed_searches']))),
                        'selected_revision': 0, 'selected_source_sha256': {'layout.py': 'software fixture'}})
            filename = root/'manifest.json';save(filename, manifest);filename.chmod(0o444);save(root/'release.json', release)
            with patch('scripts.run_e3_evaluation.verify'), patch('scripts.run_e3_evaluation.require_release', return_value=release):
                _, _, fixed = released_plan(filename)
                self.assertEqual(len(fixed['jobs']), 1730)
                self.assertEqual(fixed['declared_selected_source_points'], 43250)
                self.assertEqual(fixed['declared_original_baseline_points'], 600)
                release['sealed_searches'].pop()
                with self.assertRaisesRegex(ValueError, 'exactly1730'):released_plan(filename)

    def test_pre_release_stops_before_output_or_any_physical_callback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);filename = root/'manifest.json';manifest = manifest_fixture()
            save(filename, manifest);filename.chmod(0o444)
            with patch('scripts.run_e3_evaluation.verify'), patch('scripts.run_e3_evaluation.require_release',
                    side_effect=RuntimeError('Actual shared release absent')), patch(
                    'scripts.run_e3_evaluation.invoke', side_effect=AssertionError('No physical work before global release')):
                with self.assertRaisesRegex(RuntimeError, 'release absent'):post(filename, root/'output')
            self.assertFalse((root/'output').exists())

    def fixture(self, root):
        fixed = {'freeze_id': 'software_fixture', 'jobs': []}
        for i in range(2):
            row = copy.deepcopy(plan(manifest_fixture(), 'gpt')[i]);row.update(
                episode_directory=str(root/('episode%d' % i)), selected_revision=0, status='NOT_EVALUATED')
            fixed['jobs'].append(row)
        manifest_file = root/'freeze/manifest.json'
        save(manifest_file, {'software_fixture': True})
        states = {row['episode_directory']: {'phase': 'formal_E3', 'post_freeze_started': False} for row in fixed['jobs']}
        def context(row, manifest):return Path(row['episode_directory']), states[row['episode_directory']]
        return manifest_file, fixed, states, context

    def test_reservation_precedes_gateway_and_complete_results_never_repeat(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);filename, fixed, states, context = self.fixture(root);out = root/'output'
            def invoke(row):
                ledger = json.loads((out/'private/state.json').read_text())
                actual = next(r for r in ledger['jobs'] if r['episode_directory'] == row['episode_directory'])
                self.assertEqual(actual['status'], 'DISPATCH_RESERVED');self.assertTrue(Path(actual['reservation']).is_file())
                states[row['episode_directory']]['post_freeze_started'] = True
                save(Path(row['episode_directory'])/'public/episode.json', {'task_id': row['task_id'],
                    'post_freeze_complete': True, 'hidden_domain_size': 16, 'hidden_incomplete': 0, 'hidden_S2_verified': 12})
            def fixed_input(_):return filename, {}, copy.deepcopy(fixed)
            with patch('scripts.run_e3_evaluation.released_plan', side_effect=fixed_input), patch(
                    'scripts.run_e3_evaluation.episode_context', side_effect=context), patch(
                    'scripts.run_e3_evaluation.archive_episode', return_value={'new_physical_calls': 0}), patch(
                    'scripts.run_e3_evaluation.invoke', side_effect=invoke) as call:
                first = post(filename, out);second = post(filename, out)
            self.assertEqual(call.call_count, 2)
            self.assertEqual(first['status'], 'COMPLETE_SELECTED_SOURCE_EVALUATION')
            self.assertEqual(second['episode_status_counts'], {'EVALUATED': 2})

    def test_unknown_stops_queue_and_remains_not_a_retry_on_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);filename, fixed, states, context = self.fixture(root);out = root/'output'
            def invoke(row):
                states[row['episode_directory']]['post_freeze_started'] = True
                save(Path(row['episode_directory'])/'public/episode.json', {'task_id': row['task_id'],
                    'post_freeze_complete': False, 'hidden_domain_size': 16, 'hidden_incomplete': 16, 'hidden_S2_verified': 0})
            with patch('scripts.run_e3_evaluation.released_plan', side_effect=lambda _: (filename, {}, copy.deepcopy(fixed))), patch(
                    'scripts.run_e3_evaluation.episode_context', side_effect=context), patch(
                    'scripts.run_e3_evaluation.archive_episode', return_value={}), patch(
                    'scripts.run_e3_evaluation.invoke', side_effect=invoke) as call:
                post(filename, out);second = post(filename, out)
            self.assertEqual(call.call_count, 1)
            self.assertEqual(second['episode_status_counts'], {'PAUSED_UNKNOWN': 1, 'NOT_EVALUATED': 1})

    def test_interrupted_reserved_execution_stays_unresolved_without_dispatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);filename, fixed, states, context = self.fixture(root);out = root/'output'
            with patch('scripts.run_e3_evaluation.released_plan', side_effect=lambda _: (filename, {}, copy.deepcopy(fixed))), patch(
                    'scripts.run_e3_evaluation.episode_context', side_effect=context), patch(
                    'scripts.run_e3_evaluation.invoke', side_effect=RuntimeError('Interrupted real invocation')) as call:
                post(filename, out);second = post(filename, out)
            self.assertEqual(call.call_count, 1)
            self.assertEqual(second['episode_status_counts'], {'UNRESOLVED_PRIOR_DISPATCH': 1, 'NOT_EVALUATED': 1})

    def test_baseline_delegates_to_existing600_collector_only_after_release(self):
        with patch('scripts.run_e3_evaluation.released_plan') as release, patch(
                'scripts.run_e3_evaluation.collect_baseline', return_value={'declared_points': 600}) as collector:
            self.assertEqual(baseline(Path('/actual/manifest.json'), Path('/actual/output'), []), {'declared_points': 600})
        release.assert_called_once();collector.assert_called_once()


if __name__ == '__main__':unittest.main()
