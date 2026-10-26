"""Original-baseline orchestration software controls; no physical measurements."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.e3_original_baseline import (adopt_anchor, check_methods_freeze, collect,
    join, load_plan, prepare, retained, save, validate_task)


def software_task(ident):
    names = ['anchor']+['dev%02d' % i for i in range(8)]+['hidden%02d' % i for i in range(16)]
    points = [{'configuration_id': name, 'role': 'anchor' if i == 0 else 'development' if i < 9 else 'hidden',
        'parameters': {'width': i+1}, 'reference_id': ident+'_'+name,
        'reference_file': '/software_fixture/reference.spice',
        'contract': {'task_id': ident, 'configuration_id': name,
            'objective': {'metric': 'area', 'unit': 'um2', 'direction': 'min'}}}
        for i, name in enumerate(names)]
    return {'task_id': ident, 'status': 'FROZEN_E3_TASK', 'formal_admission': True,
        'parent_lineage': ident+'_lineage', 'entrypoint': 'generator.py', 'source_files': ['generator.py', 'layout.py'],
        'configurations': points}


class E3OriginalBaselineTests(unittest.TestCase):
    def test_prepare_materializes_exact600_sources_and_trusted_inputs_without_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);preparation = root/'packets'
            for i in range(24):
                task = software_task('task%02d' % i)
                save(preparation/'private'/task['task_id']/'task.json', task)

            def capsule_fixture(task_path, source):
                source.mkdir(parents=True)
                (source/'generator.py').write_text('# complete transport fixture\n')
                (source/'layout.py').write_text('# complete editable module fixture\n')
                task = json.loads(task_path.read_text())
                return {'source_files': task['source_files'], 'entrypoint': task['entrypoint']}

            def trusted_fixture(task, point, destination):
                destination.mkdir(parents=True)
                (destination/'reference.spice').write_text('* exact software reference '+point['reference_id'])
                save(destination/'contract.json', point['contract'])
                return ['contract.json', 'reference.spice']

            with patch('scripts.e3_original_baseline.capsule', side_effect=capsule_fixture), patch(
                    'scripts.e3_original_baseline.trusted', side_effect=trusted_fixture) as evaluator, patch(
                    'scripts.e3_original_baseline.CandidateExecutor.execute', side_effect=AssertionError('No physical experiment')):
                plan = prepare(preparation, root/'original_baseline')
            self.assertEqual(evaluator.call_count, 600)
            self.assertEqual(sum(len(row['points']) for row in plan['tasks']), 600)
            self.assertEqual(plan['preparation_cost']['physical_calls'], 0)
            loaded_root, loaded = load_plan(root/'original_baseline/plan.json')
            self.assertEqual(loaded['declared_tasks'], 24)
            self.assertEqual((loaded_root/loaded['tasks'][0]['source_directory']/'layout.py').read_text(),
                '# complete editable module fixture\n')
            self.assertFalse(Path(loaded['tasks'][0]['points'][0]['trusted_directory']).is_absolute())
            with self.assertRaises(ValueError):
                prepare(preparation, root/'original_baseline')

    def test_pre_freeze_hidden_collection_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'manifest.json';save(path, {'status': 'DRAFT_E3', 'formal_dispatch': False})
            with patch('scripts.e3_original_baseline.CandidateExecutor.execute', side_effect=AssertionError('No physical dispatch')):
                with self.assertRaises(ValueError):
                    check_methods_freeze(path, Path(temporary), {})

    def test_retained_unknown_is_not_a_new_slot_and_partial_is_unresolved(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            plan = {'tasks': [{'task_id': 'task', 'points': [{'configuration_id': 'anchor', 'role': 'anchor'},
                {'configuration_id': 'dev', 'role': 'development'}]}]}
            point = output/'private/points/task/anchor/point.json'
            save(point, {'task_id': 'task', 'configuration_id': 'anchor', 'role': 'anchor', 'fidelity': 'pex_spice',
                'checked': {'execution_integrity': 'incomplete', 'S2': False}})
            done, missing = retained(plan, output)
            self.assertEqual(len(done), 1);self.assertEqual(len(missing), 1)
            (output/'private/points/task/dev').mkdir()
            with self.assertRaisesRegex(RuntimeError, 'UNRESOLVED'):
                retained(plan, output)

    def test_exact_old_unknown_is_retained_but_E1_contract_mismatch_is_miss(self):
        evidence = {'run_directory': '/software_fixture/prior', 'task_id': 'task'}
        point = {'parameters': {}, 'contract': {'objective': {'metric': 'area', 'unit': 'um2', 'direction': 'min'}}}
        with patch('scripts.e3_original_baseline.source_contents', return_value={'layout.py': b'complete\n'}), patch(
                'scripts.e3_original_baseline.exact_bindings', return_value=False), patch(
                'scripts.e3_original_baseline.verify_cached', side_effect=AssertionError('No mismatched cache adoption')):
            row, event = adopt_anchor(evidence, point, Path('/software_fixture'), ['layout.py'], Path('/software_fixture'))
        self.assertIsNone(row);self.assertIn('old E1', event['reason'])
        with patch('scripts.e3_original_baseline.source_contents', return_value={}), patch(
                'scripts.e3_original_baseline.exact_bindings', return_value=True), patch(
                'scripts.e3_original_baseline.verify_cached', return_value=None), patch(
                'scripts.e3_original_baseline.checked_raw', return_value=({'execution_integrity': 'incomplete', 'S2': False}, None)), patch(
                'scripts.e3_original_baseline.read', return_value={'phase': 'development_E3_fixture'}), patch(
                'scripts.e3_original_baseline.physical_costs', return_value={'physical_calls': 1}):
            row, event = adopt_anchor(evidence, point, Path('/software_fixture'), [], Path('/software_fixture'))
        self.assertEqual(row['new_physical_calls'], 0)
        self.assertEqual(event['status'], 'EXACT_PRIOR_UNKNOWN_RETAINED')

    def test_unknown_pauses_collection_and_resume_cannot_dispatch_again(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);manifest = root/'freeze/manifest.json';output = root/'runs/baseline'
            save(manifest, {'original_baseline_plan': str(root/'freeze/original_baseline'), 'task_ids': ['task']})
            task = {'task_id': 'task', 'points': [{'configuration_id': 'anchor', 'role': 'anchor'},
                {'configuration_id': 'dev', 'role': 'development'}]}
            plan = {'tasks': [task], 'preparation_cost': {'physical_calls': 0}, 'maximum_new_physical_calls': 600}
            fake_task = {'source_files': ['layout.py']}

            def execute_fixture(plan_root, plan, task_row, point_row, folder):
                row = {'task_id': 'task', 'configuration_id': point_row['configuration_id'], 'role': point_row['role'],
                    'fidelity': 'pex_spice', 'new_physical_calls': 1, 'run_directory': str(folder/'software_fixture'),
                    'checked': {'execution_integrity': 'incomplete', 'S2': False},
                    'physical_costs': {name: 0 for name in ('stage_wall_seconds', 'waited_child_CPU_seconds', 'missing_CPU_records', 'missing_wall_records')}}
                save(folder/'point.json', row)
                return row

            with patch('scripts.e3_original_baseline.load_plan', return_value=(root/'freeze/original_baseline', plan)), patch(
                    'scripts.e3_original_baseline.check_methods_freeze', return_value={}), patch(
                    'scripts.e3_original_baseline.point_inputs', return_value=(fake_task, {}, root, root)), patch(
                    'scripts.e3_original_baseline.gate', return_value={}), patch(
                    'scripts.e3_original_baseline.archive_point', return_value={}), patch(
                    'scripts.e3_original_baseline.execute_point', side_effect=execute_fixture) as execute:
                first = collect(manifest, output)
                second = collect(manifest, output)
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(first['new_physical_calls'], 1)
            self.assertEqual(second['status'], 'PAUSED_PRIOR_UNKNOWN_NO_AUTOMATIC_NEW_DISPATCH')

    def test_domain_roles_exact(self):
        task = software_task('task');task['configurations'][-1]['role'] = 'development'
        with self.assertRaises(ValueError):
            validate_task(task)

    def test_join_exports_only_aggregate_and_keeps_unknown_denominator(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve();plan_root = root/'freeze/original_baseline'
            baseline = root/'baseline';episode = root/'episode';task = software_task('task')
            save(plan_root/'tasks/task/task.json', task)
            manifest = {'status': 'FROZEN_E3', 'original_baseline_plan': str(plan_root)}
            save(root/'freeze/manifest.json', manifest)
            save(baseline/'private/binding.json', {'original_baseline_plan': str(plan_root),
                'manifest': str(root/'freeze/manifest.json')})
            save(episode/'private/task.json', task)
            save(episode/'private/manifest.json', manifest)
            save(episode/'private/state.json', {'sealed': True, 'in_flight': None, 'method': 'C',
                'formal_trial': True, 'phase': 'formal_E3', 'trial_id': '1', 'selection': {'revision': 2}})
            save(episode/'public/episode.json', {'post_freeze_complete': False})
            save(episode/'public/search.json', {'method': 'C'})
            original = [{'task_id': 'task', 'configuration_id': point['configuration_id'],
                'role': point['role'], 'fidelity': 'pex_spice', 'checked': {'execution_integrity': 'valid', 'S2': True}}
                for point in task['configurations']]
            for row in original:
                save(baseline/'private/points/task'/row['configuration_id']/'point.json', row)
            selected = [{'configuration_id': 'anchor', 'checked': {'execution_integrity': 'valid', 'S2': False}}]
            save(episode/'private/post_freeze_points.json', selected)
            plan = {'tasks': [{'task_id': 'task', 'task_file': 'tasks/task/task.json', 'points': task['configurations']}]}
            with patch('scripts.e3_original_baseline.load_plan', return_value=(plan_root, plan)), patch(
                    'scripts.e3_original_baseline.verify'), patch('scripts.e3_episode.require_release'):
                report = join(baseline, episode, root/'public/regression.json')
            self.assertEqual(report['groups']['all']['original_verified_S2'], 25)
            self.assertEqual(report['groups']['all']['verified_regressions'], 1)
            self.assertEqual(report['groups']['hidden']['selected_unknown_on_original_passes'], 16)
            self.assertIsNone(report['groups']['all']['regression_rate'])
            self.assertNotIn('hidden00', json.dumps(report))
            self.assertEqual(report['status'], 'INCOMPLETE_UNKNOWN')

    def test_in_flight_without_a_record_cannot_be_repeated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);manifest = root/'freeze/manifest.json';output = root/'runs/baseline'
            save(manifest, {'original_baseline_plan': str(root/'freeze/original_baseline'), 'task_ids': ['task']})
            save(output/'private/in_flight.json', {'point_directory': str(output/'private/points/task/anchor')})
            plan = {'tasks': [], 'preparation_cost': {'physical_calls': 0}}
            with patch('scripts.e3_original_baseline.load_plan', return_value=(root/'freeze/original_baseline', plan)), patch(
                    'scripts.e3_original_baseline.check_methods_freeze', return_value={}), patch(
                    'scripts.e3_original_baseline.execute_point', side_effect=AssertionError('Never repeat unknown dispatch')):
                with self.assertRaisesRegex(RuntimeError, 'UNRESOLVED'):
                    collect(manifest, output)

    def test_fidelity_join_requires_the_actual_same_main_freeze_and_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve();plan_root = root/'freeze/original_baseline';baseline = root/'baseline';episode = root/'episode'
            task = software_task('task');main_path = root/'freeze/manifest.json'
            main = {'status': 'FROZEN_E3', 'freeze_id': 'main', 'original_baseline_plan': str(plan_root),
                'hidden_release_file': str(root/'actual_release.json')}
            save(main_path, main);save(plan_root/'tasks/task/task.json', task)
            save(baseline/'private/binding.json', {'manifest': str(main_path), 'original_baseline_plan': str(plan_root)})
            fidelity = {**main, 'status': 'FROZEN_E3_FIDELITY_METHOD', 'freeze_id': 'F3', 'main_freeze_id': 'main',
                'main_protocol_manifest': str(main_path), 'fidelity_policy': 'F3_actual_nominal_promote_shared_PEX'}
            save(episode/'private/manifest.json', fidelity);save(episode/'private/task.json', task)
            save(episode/'private/state.json', {'formal_trial': True, 'sealed': True, 'in_flight': None,
                'phase': 'formal_E3', 'method': 'C', 'trial_id': '1', 'selection': {'revision': 0}})
            save(episode/'public/episode.json', {'post_freeze_complete': True});save(episode/'public/search.json', {'method': 'C'})
            rows = []
            for point in task['configurations']:
                row = {**point, 'fidelity': 'pex_spice', 'task_id': 'task', 'checked': {'execution_integrity': 'valid', 'S2': True}}
                save(baseline/'private/points/task'/point['configuration_id']/'point.json', row);rows.append(row)
            save(episode/'private/post_freeze_points.json', rows)
            plan = {'tasks': [{'task_id': 'task', 'task_file': 'tasks/task/task.json', 'points': task['configurations']}]}
            with patch('scripts.e3_original_baseline.load_plan', return_value=(plan_root, plan)), patch(
                    'scripts.e3_original_baseline.verify'), patch('scripts.e3_episode.require_release'):
                result = join(baseline, episode, root/'public/regression.json')
                self.assertEqual(result['groups']['all']['regression_rate'], 0)
                self.assertEqual(result['fidelity_policy'], fidelity['fidelity_policy'])
                fidelity['main_freeze_id'] = 'another_freeze';save(episode/'private/manifest.json', fidelity)
                with self.assertRaisesRegex(ValueError, 'same formal method freeze'):
                    join(baseline, episode, root/'public/rejected.json')


if __name__ == '__main__':
    unittest.main()
