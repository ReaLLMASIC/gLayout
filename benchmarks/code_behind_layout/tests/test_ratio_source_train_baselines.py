"""Software controls for the new finite baseline consumer, not physical results."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.prepare_ratio_source_train_baselines import EDITABLE, packet, validate_assembly
from scripts.prepare_ratio_train_context import add_caller
from scripts.prepare_ratio_training_draft import validate_completion, with_exact_configuration_constraints
from src.train_generators.ratio_source_intent import K_VALUES, R_VALUES, point
import scripts.run_ratio_source_train_baselines as runner


class RatioTrainTaskTests(unittest.TestCase):
    def test_preview_retains_complete_module_all_nine_and_unchanged_contracts(self):
        source = Path(EDITABLE).read_text()
        points = [point(k, r) for k in K_VALUES for r in R_VALUES]
        initial = {'base_source': {EDITABLE: source}, 'frozen_terminal_access_source': 'FULL_FROZEN_HELPER'}
        request = packet(initial, points, [{'preview': True}], preview=True)
        task = request['task_packet']
        self.assertEqual(task['visible_sources'], {EDITABLE: source})
        self.assertEqual(task['allowed_paths'], [EDITABLE])
        self.assertEqual(task['documents']['frozen_terminal_access_source'], 'FULL_FROZEN_HELPER')
        self.assertEqual(len(task['contract']['geometry_domain']), 9)
        self.assertEqual(task['contract']['analysis_contracts'], points[0]['contract']['analysis_contracts'])
        self.assertEqual(task['contract']['target_current_rule_A']['branch2'], '5e-6*R')
        self.assertNotIn('actual_new_baseline', request['visible_history'][0]['observation'])

    def test_source_scope_rejects_eval_assembly_or_compiler_import(self):
        source = Path(EDITABLE).read_text()
        self.assertIn('glayout.primitives.fet', validate_assembly(source))
        for extra in ('from src.generators.five_t import build', 'import glayout.sharing',
                      'from glayout.cells.elementary.current_mirror import current_mirror'):
            with self.assertRaises(ValueError): validate_assembly(source + '\n' + extra + '\n')

    def test_full_actual_caller_is_shared_documentation_without_expanding_edit_scope(self):
        request = {'task_packet': {'allowed_paths': [EDITABLE], 'documents': {'unchanged': 'original'}}}
        caller = 'complete actual wrapper\nwrite_gds(configuration, output)\n'
        result = add_caller(request, caller)
        self.assertEqual(result['task_packet']['documents']['frozen_generator_entrypoint_source'], caller)
        self.assertEqual(result['task_packet']['allowed_paths'], [EDITABLE])
        self.assertEqual(request['task_packet']['documents'], {'unchanged': 'original'})
        request['task_packet']['allowed_paths'].append('generator.py')
        with self.assertRaises(ValueError): add_caller(request, caller)

    def test_future_visible_task_exposes_the_exact_original_ratio_dependent_limits(self):
        points = [point(k, r) for k in K_VALUES for r in R_VALUES]
        request = {'task_packet': {'contract': {'constraints': points[0]['contract']['specifications']}}}
        updated = with_exact_configuration_constraints(request, points)['task_packet']['contract']
        self.assertEqual(len(updated['constraints']), 6)
        self.assertEqual(len(updated['configuration_constraints']), 9)
        for row, original in zip(updated['configuration_constraints'], points):
            self.assertEqual(row['specifications'][0]['min'], 300000 / original['parameters']['R'])
        self.assertEqual(len(request['task_packet']['contract']['constraints']), 7)


class RatioFreshBaselineTests(unittest.TestCase):
    def test_future_collection_rejects_development_partial_or_unknown_controls(self):
        order = [point(k, r)['configuration_id'] for k in K_VALUES for r in R_VALUES]
        terminal = {'status': 'COMPLETED_FORMAL_RATIO_FRESH9_ALL_QUALIFIED_NO_MODELS',
            'qualified_points': 9, 'not_run': [], 'cells': [
                {'configuration_id': identifier, 'status': 'COMPLETE_QUALIFIED_FORMAL_BASELINE'} for identifier in order]}
        validate_completion(terminal, order)
        for change in ({'status': 'COMPLETED_FIXED_NINE_PHYSICAL_ATTEMPTS'},
                       {'qualified_points': 8}, {'not_run': [order[-1]]}, {'cells': terminal['cells'][:-1]}):
            bad = copy.deepcopy(terminal); bad.update(change)
            with self.assertRaises(ValueError): validate_completion(bad, order)
        bad = copy.deepcopy(terminal); bad['cells'][0]['status'] = 'UNKNOWN_OR_UNQUALIFIED_NO_RETRY'
        with self.assertRaises(ValueError): validate_completion(bad, order)

    def fixture(self, root):
        points = [point(k, r) for k in K_VALUES for r in R_VALUES]
        plan = {'output_root': str(root / 'output'), 'fixed_order': [p['configuration_id'] for p in points],
            'magic_runtime': str(root / 'magic'), 'container_image': 'fixture',
            'lineage_id': 'fixture_train', 'PDK_revision': 'fixture',
            'source_pack': str(root / 'source'), 'source_files': ['generator.py', EDITABLE],
            'trusted_bundle': str(root / 'trusted'), 'trusted_files': ['evaluate.py'],
            'generation_timeout_seconds': 240, 'evaluator_timeout_seconds': 900}
        initial = {'initial_state_id': 'natural_v3', 'task_id': 'fixture', 'base_source': {EDITABLE: 'fullsource'}}
        return plan, {'configurations': points}, initial

    def test_first_unknown_stops_and_keeps_other_eight_unrun(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); data = self.fixture(root)
            def unknown(**kwargs): raise RuntimeError('Actual infrastructure unknown software fixture')
            with patch.object(runner, 'load', return_value=data):
                result = runner.run(root / 'plan.json', execute=unknown, gate=lambda *_: {'fixture': True})
            self.assertEqual(result['status'], 'PAUSED_UNKNOWN_OR_UNQUALIFIED_NO_RETRY')
            self.assertEqual(result['qualified_points'], 0)
            self.assertEqual(len(result['not_run']), 8)
            self.assertEqual(sum(c['status'] != 'NOT_RUN' for c in result['cells']), 1)
            self.assertEqual(result['new_model_calls'], 0)

    def test_unresolved_existing_reservation_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); data = self.fixture(root); output = root / 'output'; output.mkdir()
            state = {'status': 'RUNNING_FORMAL_RATIO_FRESH9', 'cells': [
                {'configuration_id': identifier, 'status': 'DISPATCH_RESERVED' if index == 0 else 'NOT_RUN'}
                for index, identifier in enumerate(data[0]['fixed_order'])]}
            (output / 'state.json').write_text(json.dumps(state))
            with patch.object(runner, 'load', return_value=data), patch.object(runner, 'CandidateExecutor') as executor:
                result = runner.run(root / 'plan.json')
            executor.assert_not_called()
            self.assertEqual(result['status'], 'PAUSED_UNKNOWN_NO_RETRY')
            self.assertEqual(result['cells'][0]['status'], 'UNRESOLVED_RESERVED_NO_RETRY')


if __name__ == '__main__': unittest.main()
