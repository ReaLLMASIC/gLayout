"""Ratio-only software fixtures; no model/physical measurements or training rows."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.freeze_ratio_span_teacher import collector_source, freeze
from scripts import evaluate_ratio_span_proposals as ratio
from src.train_ratio_span_bundle import BUNDLE_VERSION, SID, LINEAGE, EDITABLE, ORDER, load_bundle
from src.train_span_proposer import MODE, ROLE, VERSION


def fixture(root):
    request = {'task_packet': {'allowed_paths': [EDITABLE], 'visible_sources': {EDITABLE: 'complete_source=1\n'},
        'documents': {'frozen_generator_entrypoint_source': 'actual_complete_caller\n'}}}
    values = {'original_request': request, 'teacher_request': request, 'student_request': request,
        'initial_state': {'origin': 'natural', 'parent_lineage': LINEAGE, 'base_source': request['task_packet']['visible_sources']},
        'effective_registry': {'lineages': [{'lineage_id': LINEAGE, 'split': 'train'}],
            'configurations': [{'configuration_id': identifier} for identifier in ORDER]},
        'mapping_proof': {'teacher_and_original_map_to_identical_ordinary_request': True}}
    entry = {'initial_state_id': SID, 'parent_lineage': LINEAGE, 'readonly_entrypoint': 'readonly_generator.py'}
    (root / entry['readonly_entrypoint']).write_text('actual_complete_caller\n')
    for key, value in values.items():
        entry[key] = key + '.json'; (root / entry[key]).write_text(json.dumps(value))
    audit = {'phase': 'formal_train', 'all_nine_points_complete': True,
        'records': [{'S2': True, 'full_RC_device_graph_clean': True} for _ in range(9)]}
    (root / 'baseline_audit.json').write_text(json.dumps(audit))
    (root / 'teacher_context_preflight.json').write_text(json.dumps({'actual_fresh_formal_feedback': True,
        'source_or_contract_truncated': False, 'token_counts': {'teacher': {'fits_with_full_output_reserve': True},
            'student': {'fits_with_full_output_reserve': True}}}))
    (root / 'tokenizer_inventory.json').write_text('{}')
    manifest = {'status': 'DRAFT_NO_MODEL_CALLS', 'role': 'train_proposal_collection', 'source_role': ROLE,
        'ratio_bundle_version': BUNDLE_VERSION, 'teacher_interface_version': VERSION, 'contexts': [entry],
        'planned_proposals': 8, 'maximum_dispatch_hours': 8, 'shared_global_inference_slots': 2,
        'endpoint': 'http://127.0.0.1:8116/spans/decision',
        'sampling': {'backend': 'isolated_gpt_cli', 'model': 'gpt-6.1-sol', 'reasoning_effort': 'high',
            'mode': MODE, 'trials': list(range(1, 9)), 'seed': None, 'proposal_workers': 2,
            'max_new_tokens': 3072, 'max_context_tokens': 16384, 'timeout_seconds': 240},
        'student_preselection': {'interface_version': 'ordinary_policy_action_context_v2',
            'max_new_tokens': 1024, 'max_context_tokens': 16384, 'stage': 'before_physics'}}
    (root / 'collection.json').write_text(json.dumps(manifest)); return manifest


def writable(root):
    for p in [root, *root.rglob('*')]: p.chmod(0o755 if p.is_dir() else 0o644)


class RatioProposalTests(unittest.TestCase):
    def test_subprocess_frozen_collector_loads_ratio8_without_health_or_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture(root); target = root / 'interface'; (target / 'src').mkdir(parents=True)
            (target / 'src/__init__.py').write_text('')
            for name in ['train_span_proposer', 'student_interface', 'local_model_adapter', 'model_adapter',
                         'policy_state', 'training', 'measurement', 'report_parsers', 'spice_validation']:
                shutil.copyfile(Path('src') / (name + '.py'), target / 'src' / (name + '.py'))
            shutil.copyfile('src/train_ratio_span_bundle.py', target / 'src/train_span_bundle.py')
            (target / 'collector.py').write_text(collector_source(Path('scripts/collect_train_span_proposals.py').read_text()))
            try:
                freeze(root / 'collection.json')
                result = subprocess.run([sys.executable, str(target / 'collector.py'), '--collection', str(root / 'collection.json'),
                    '--validate-only'], cwd=tmp, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout)
                self.assertEqual(output['planned_proposals'], 8)
                self.assertEqual(output['new_model_calls'], 0)
            finally: writable(root)

    def test_no_development_subset_caller_mismatch_or_wrong_lineage_is_admitted(self):
        for change in ('development', 'subset', 'caller', 'lineage', 'overflow'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); manifest = fixture(root)
                if change == 'development':
                    p = root / 'baseline_audit.json'; value = json.loads(p.read_text()); value['phase'] = 'development'
                elif change == 'subset':
                    p = root / 'effective_registry.json'; value = json.loads(p.read_text()); value['configurations'].pop()
                elif change == 'caller':
                    p = root / 'student_request.json'; value = json.loads(p.read_text())
                    value['task_packet']['documents']['frozen_generator_entrypoint_source'] = 'different_caller'
                elif change == 'lineage':
                    p = root / 'collection.json'; value = manifest; value['contexts'][0]['parent_lineage'] = 'evaluation_source'
                else:
                    p = root / 'teacher_context_preflight.json'; value = json.loads(p.read_text())
                    value['token_counts']['student']['fits_with_full_output_reserve'] = False
                p.write_text(json.dumps(value))
                with self.assertRaises(ValueError): load_bundle(root / 'collection.json', require_frozen=False)

    def test_readonly_freeze_blocks_changed_caller_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture(root)
            try:
                freeze(root / 'collection.json'); self.assertEqual(load_bundle(root / 'collection.json')['planned_proposals'], 8)
                (root / 'readonly_generator.py').chmod(0o644)
                with self.assertRaisesRegex(ValueError, 'readonly'): load_bundle(root / 'collection.json')
            finally: writable(root)


class RatioPhysicalTests(unittest.TestCase):
    def test_late_return_and_rejection_are_rescanned_then_eligible_candidate_drains(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); raw = root / 'raw'; raw.mkdir(); output = root / 'output'; output.mkdir()
            state = {'status': 'RUNNING', 'cells': [
                {'initial_state_id': SID, 'trial_id': 1, 'status': 'PHYSICAL_PENDING'},
                {'initial_state_id': SID, 'trial_id': 2, 'status': 'NOT_RUN'},
                {'initial_state_id': SID, 'trial_id': 3, 'status': 'NOT_RUN'}]}; done = []
            def scan(*args):
                if (raw / 'completion.json').exists():
                    if state['cells'][1]['status'] == 'NOT_RUN': state['cells'][1]['status'] = 'PHYSICAL_PENDING'
                    state['cells'][2]['status'] = 'STUDENT_BUDGET_REJECTED_BEFORE_PHYSICS'
            def physics(*args):
                row, = [c for c in state['cells'] if c['status'] == 'PHYSICAL_PENDING']
                done.append(row['trial_id']); row['status'] = 'ADMITTED_COMPLETE_DOMAIN'
                (raw / 'completion.json').write_text('{}')
            with patch.object(ratio.span, 'scan_returned', side_effect=scan), patch.object(ratio, 'serial_physical_pass', side_effect=physics), \
                    patch.object(ratio, 'derive'), patch.object(ratio.span, 'raw_matrix', return_value={}):
                ratio.cycle({}, {'output_root': str(raw)}, {}, [], {}, state, output, None, root, lambda: None)
                self.assertEqual(state['status'], 'RUNNING')
                self.assertEqual(state['cells'][1]['status'], 'PHYSICAL_PENDING')
                ratio.cycle({}, {'output_root': str(raw)}, {}, [], {}, state, output, None, root, lambda: None)
            self.assertEqual(done, [1, 2]); self.assertEqual(state['status'], 'COMPLETE')
            self.assertEqual(state['cells'][2]['status'], 'STUDENT_BUDGET_REJECTED_BEFORE_PHYSICS')

    def test_incomplete_return_stops_serial_worker_and_preserves_other_unrun_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); run = root / 'run'; run.mkdir(); output = root / 'output'; (output / 'candidate').mkdir(parents=True)
            row = {'candidate_id': 'fixture', 'candidate_source': {}, 'outcomes': []}
            (output / 'candidate/candidate.json').write_text(json.dumps(row))
            (output / 'baseline.json').write_text(json.dumps({'p0': {'evidence_path': 'baseline', 'baseline_candidate_id': 'initial'}}))
            state = {'status': 'RUNNING', 'deadline_utc': (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat(),
                'resource_samples': [], 'cells': [{'status': 'PHYSICAL_PENDING', 'parent_collection': 'parent',
                    'candidate_file': 'candidate/candidate.json', 'baseline_adoption': 'baseline.json',
                    'points': [{'configuration_id': 'p' + str(i), 'status': 'NOT_RUN'} for i in range(3)]}]}
            def execute(*args):
                args[4].mkdir(parents=True); return {'run_directory': str(run)}
            resource = {'available_disk_GiB': 8, 'actual_busy_cores': 4, 'RAM_used_GiB': 100}
            with patch.object(ratio, 'TrustedPhysicalStore') as store, patch.object(ratio, 'audit_full_rc', return_value={'is_clean': True}):
                store.return_value._configuration.return_value = {'domain_role': 'anchor'}
                store.return_value._read_run.return_value = {'point_evaluation_complete': False}
                with patch.object(ratio, 'ROOT', root):
                    ratio.serial_physical_pass({}, {'parent': {}}, {}, state, output, lambda: None,
                        sample=lambda: resource, execute_point=execute)
            self.assertEqual(state['status'], 'PAUSED_UNKNOWN')
            self.assertEqual([p['status'] for p in state['cells'][0]['points']], ['UNKNOWN_NO_RETRY', 'NOT_RUN', 'NOT_RUN'])
            self.assertEqual(state['cells'][0]['physical_point_reservations'], 1)

    def test_unknown_never_derives_a_final_training_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); state = {'status': 'RUNNING', 'cells': []}
            def unknown(*args): state['status'] = 'PAUSED_UNKNOWN'
            with patch.object(ratio.span, 'scan_returned'), patch.object(ratio, 'serial_physical_pass', side_effect=unknown), \
                    patch.object(ratio, 'derive') as derive:
                ratio.cycle({}, {}, {}, [], {}, state, root, None, root, lambda: None)
            derive.assert_not_called()

    def test_s1_missing_rc_retains_audit_error_and_cost_then_stops_other_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); run = root / 'run'; (run / 'evidence').mkdir(parents=True)
            validation = {'assessment': {'S1': True}, 'artifacts': {'pex': {
                'ports': ['IN', 'OUT'], 'netlist': 'missing.spice', 'top_cell': 'fixture'}}}
            (run / 'evidence/validation.json').write_text(json.dumps(validation))
            output = root / 'output'; (output / 'candidate').mkdir(parents=True)
            row = {'candidate_id': 'fixture', 'candidate_source': {}, 'outcomes': []}
            (output / 'candidate/candidate.json').write_text(json.dumps(row))
            state = {'status': 'RUNNING', 'deadline_utc': (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat(),
                'resource_samples': [], 'cells': [{'status': 'PHYSICAL_PENDING', 'parent_collection': 'parent',
                    'candidate_file': 'candidate/candidate.json', 'baseline_adoption': 'never_reached',
                    'points': [{'configuration_id': 'p' + str(i), 'status': 'NOT_RUN'} for i in range(2)]}]}
            folders = []
            def execute(*args):
                args[4].mkdir(parents=True); folders.append(args[4]); return {'run_directory': str(run)}
            resource = {'available_disk_GiB': 8, 'actual_busy_cores': 4, 'RAM_used_GiB': 100}
            with patch.object(ratio, 'TrustedPhysicalStore') as store, patch.object(ratio, 'ROOT', root):
                store.return_value._configuration.return_value = {'contract': {'ports': ['IN', 'OUT']}}
                ratio.serial_physical_pass({}, {'parent': {}}, {}, state, output, lambda: None,
                    sample=lambda: resource, execute_point=execute)
                store.return_value._read_run.assert_not_called()
            audit = json.loads((folders[0] / 'full_RC_device_graph_audit.json').read_text())
            self.assertEqual(audit['audit']['status'], 'UNKNOWN_RC_GRAPH_QUARANTINE')
            self.assertIn('missing.spice', audit['audit']['error'])
            self.assertGreaterEqual(audit['wall_seconds'], 0)
            self.assertGreaterEqual(audit['CPU_seconds'], 0)
            self.assertFalse(audit['simulation_netlist_simplified'])
            self.assertEqual(state['status'], 'PAUSED_UNKNOWN')
            self.assertEqual([p['status'] for p in state['cells'][0]['points']], ['UNKNOWN_NO_RETRY', 'NOT_RUN'])
            self.assertEqual(row['outcomes'], [])


if __name__ == '__main__': unittest.main()
