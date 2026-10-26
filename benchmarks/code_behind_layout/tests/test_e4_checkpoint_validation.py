"""Software-only prospective-plan/ledger fixtures; no model or SPICE calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.e4_validation import prepare, prepare_joint_registry, freeze, validate_plan, validate_budget, validate_editing_ledger, selection, run_checkpoint
from src.e4_methods import file_digest, SELECTION_RULE, REVISION
from src.model_adapter import PACKET_FIELDS
from src.policy_state import current_state_request
from scripts.e4_validation_mirror_domain import reference, adapter, retained_deck_assignment, injected_source, WIDTHS, LENGTHS


def budget():
    return {'decisions': 4, 'patches': 2, 'physical_evaluations': 2, 'wall_seconds': 1200,
        'maximum_context_tokens': 16384, 'maximum_output_tokens': 1024,
        'generation_timeout_seconds': 240, 'evaluator_timeout_seconds': 720}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value)); return path


class ValidationControlTests(unittest.TestCase):
    def fixture(self, root, updates=1):
        source = root/'pack'; source.mkdir(exist_ok=True); (source/'layout.py').write_text('value = 1\n')
        packet = {'task_id': 'valtask', 'goal': 'Repair the independently frozen circuit.', 'contract': {},
            'allowed_paths': ['layout.py'], 'visible_sources': {'layout.py': 'value = 1\n'},
            'documents': {'action_gateway': {'read_source_paths': ['layout.py']}},
            'visible_configurations': ['v0', 'v1'], 'budget': budget()}
        self.assertEqual(set(packet), PACKET_FIELDS)
        packet_path = save(root/'packet.json', packet)
        task_path = save(root/'task.json', {'task_id': 'valtask', 'source_pack': str(source), 'packet': str(packet_path), 'editable_paths': ['layout.py']})
        registry = {'status': 'frozen', 'lineages': [{'lineage_id': 'val', 'split': 'validation', 'topology_family': 'independent'}],
            'configurations': [{'configuration_id': name, 'split': 'validation', 'parent_lineage': 'val', 'role': 'development',
                'contract': {'task_id': 'valtask'}} for name in ['v0', 'v1']]}
        registry_path = save(root/'registry.json', registry); backend = root/'backend.py'; backend.write_text('# software fixture only\n')
        plan = {'status': 'FROZEN_E4_VALIDATION_PLAN', 'selection_rule': SELECTION_RULE, 'budget': budget(),
            'split_registry': str(registry_path), 'split_registry_sha256': file_digest(registry_path),
            'checkpoint_backend': {'path': str(backend), 'sha256': file_digest(backend)},
            'implementation_sha256': {str(backend): file_digest(backend)},
            'frozen_at_utc': '2026-10-19T00:00:00+00:00',
            'tasks': [{'task_id': 'valtask', 'task_file': str(task_path)}],
            'points': [{'task_id': 'valtask', 'configuration_id': name} for name in ['v0', 'v1']]}
        plan_path = save(root/'plan.json', plan); plan_path.chmod(0o444)
        cp = root/('checkpoint-%07d'%updates); (cp/'adapter/policy').mkdir(parents=True)
        weights = cp/'adapter/policy/adapter_model.safetensors'; weights.write_bytes(b'fixture-not-a-model')
        session_dir = root/('session%d'%updates); decision = session_dir/'decision_000'; decision.mkdir(parents=True)
        action = {'action': 'finish', 'path': '', 'patch': '', 'configuration_ids': [], 'fidelity': '', 'summary': 'done'}
        history = [{'observation': {'status': 'initial'}, 'action': action}]
        request = current_state_request(packet, [{'observation': {'status': 'initial'}}], packet['visible_sources'])
        save(decision/'request.json', {'variant': 'T1', 'request': request})
        save(decision/'invocation.json', {'pid': 12345, 'status': 'COMPLETED', 'started_at_utc': '2026-10-19T01:00:00+00:00'})
        save(decision/'response.json', {'native_tools': [], 'model': {'adapter_sha256': file_digest(weights),
                'variant': 'T1', 'training_seed': 41, 'checkpoint': str(cp), 'base_revision': REVISION, 'source_role': 'E4_checkpoint_validation_not_selected'},
            'action': action, 'usage': {'maximum_context_tokens': 16384, 'max_new_tokens': 1024,
                'input_tokens': 100, 'output_tokens': 40, 'eos_terminated': True}})
        session_path = save(session_dir/'session.json', {'closed': True, 'output': str(session_dir), 'packet': packet, 'history': history})
        ledger = {'status': 'SEALED_E4_VALIDATION_EDITING', 'method': 'T1', 'seed': 41, 'checkpoint': str(cp),
            'adapter_sha256': file_digest(weights), 'hidden_calls': 0,
            'validation_plan_sha256': file_digest(plan_path),
            'tasks': {'valtask': {'session_json': str(session_path), 'gateway_events': [{'status': 'APPLIED'}],
                'final_sources': packet['visible_sources']}},
            'points': [{'task_id': 'valtask', 'configuration_id': name, 'run_directory': str(root/(str(updates)+name))} for name in ['v0', 'v1']]}
        ledger_path = save(root/('ledger%d.json'%updates), ledger)
        return plan, plan_path, registry, cp, ledger_path

    def test_current_actual_registry_zero_points_is_DRAFT_with_concrete_blockers(self):
        result = prepare(Path(__file__).resolve().parents[1]/'data/splits/registry.json', None, budget())
        self.assertEqual(result['status'], 'DRAFT_E4_VALIDATION_PLAN')
        self.assertEqual(result['points'], [])
        self.assertTrue(any('zero validation' in item for item in result['freeze_blockers']))
        self.assertTrue(any('backend' in item for item in result['freeze_blockers']))
        self.assertEqual(result['new_model_or_EDA_calls'], 0)

    def test_common_context_and_blocked_freeze_do_not_create_ready_artifact(self):
        wrong = budget(); wrong['maximum_context_tokens'] = 8192
        with self.assertRaisesRegex(ValueError, '16384/1024'): validate_budget(wrong)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); draft = save(root/'draft.json', {'status': 'DRAFT_E4_VALIDATION_PLAN', 'freeze_blockers': ['no qualified validation source']})
            with self.assertRaisesRegex(ValueError, 'DRAFT/blocked'): freeze(draft, root/'frozen.json')
            self.assertFalse((root/'frozen.json').exists())

    def test_changed_registry_or_backend_cannot_silently_keep_frozen_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan, path, _, _, _ = self.fixture(Path(tmp))
            validate_plan(plan, path)
            Path(plan['checkpoint_backend']['path']).write_text('# changed\n')
            with self.assertRaisesRegex(ValueError, 'backend code'): validate_plan(plan, path)

    def test_joint_registry_is_separate_DRAFT_preserving_all_source_assignments(self):
        from src.training import frozen_train_registry
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, _, _, _, _ = self.fixture(root)
            registry_path = root/'registry.json'; registry = json.loads(registry_path.read_text())
            registry['lineages'][0]['source'] = 'independent_original.py'
            registry['lineages'].append({'lineage_id': 'train', 'split': 'train', 'topology_family': 'other'})
            registry['configurations'] = []; save(registry_path, registry); original = registry_path.read_bytes()
            task_path = save(root/'qualified.json', {'status': 'FROZEN_E4_VALIDATION_TASK', 'formal_admission': True,
                'parent_lineage': 'val', 'editable_paths': ['layout.py'],
                'points': [{'configuration_id': 'val%d'%i, 'split': 'validation', 'parent_lineage': 'val'} for i in range(9)]})
            task_path.chmod(0o444)
            result = prepare_joint_registry(registry_path, task_path, root/'joint')
            self.assertEqual(registry_path.read_bytes(), original)
            draft = json.loads((root/'joint/registry.json').read_text())
            self.assertEqual(result['new_validation_configurations'], 9)
            self.assertEqual({r['lineage_id']:r['split'] for r in draft['lineages']}, {'val': 'validation', 'train': 'train'})
            with self.assertRaisesRegex(ValueError, 'frozen split registry'): frozen_train_registry(draft)

    def test_clearing_blocker_text_does_not_freeze_a_joint_DRAFT_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, path, _, _, _ = self.fixture(root)
            registry_path = root/'registry.json'; registry = json.loads(registry_path.read_text())
            registry['status'] = 'DRAFT_E4_JOINT_REGISTRY'; save(registry_path, registry)
            plan.update(status='DRAFT_E4_VALIDATION_PLAN', freeze_blockers=[], split_registry_sha256=file_digest(registry_path))
            path.chmod(0o644); save(path, plan)
            with self.assertRaisesRegex(ValueError, 'canonical joint registry is actually frozen'):
                freeze(path, root/'never_frozen.json')
            self.assertFalse((root/'never_frozen.json').exists())

    def test_actual_ledger_identity_and_complete_source_request_are_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, _, _, cp, ledger = self.fixture(root)
            validate_editing_ledger(ledger, plan, cp, 'T1', 41)
            response = root/'session1/decision_000/response.json'; data = json.loads(response.read_text()); data['model']['adapter_sha256'] = 'another'
            save(response, data)
            with self.assertRaisesRegex(ValueError, 'different weights'): validate_editing_ledger(ledger, plan, cp, 'T1', 41)

    def test_source_truncation_and_zero_model_fallback_are_not_actual_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, _, _, cp, ledger = self.fixture(root)
            request = root/'session1/decision_000/request.json'; data = json.loads(request.read_text()); data['request']['task_packet']['visible_sources']['layout.py'] = '# truncated'
            save(request, data)
            with self.assertRaisesRegex(ValueError, 'complete source/history'): validate_editing_ledger(ledger, plan, cp, 'T1', 41)
            session = root/'session1/session.json'; data = json.loads(session.read_text()); data['history'] = []; save(session, data)
            with self.assertRaisesRegex(ValueError, 'No actual checkpoint decision'): validate_editing_ledger(ledger, plan, cp, 'T1', 41)

    def test_unknown_physical_run_prevents_any_completed_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, path, registry, cp, ledger = self.fixture(root)
            save(cp/'complete.json', {'optimizer_boundary': True, 'updates': 1})
            output = root/'selection.json'
            with patch('src.e4_validation.checkpoint_files', return_value={'updates': 1}), patch(
                    'src.e4_validation.TrustedPhysicalStore._inspect_execution_run', side_effect=ValueError('actual physical unknown')):
                with self.assertRaisesRegex(ValueError, 'physical unknown'):
                    selection({'method': 'T1', 'seed': 41}, {'checkpoints': [cp]}, root, registry, path, [ledger], output)
            self.assertFalse(output.exists())

    def test_missing_saved_checkpoint_cannot_be_dropped_from_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, path, registry, cp, ledger = self.fixture(root)
            with patch('src.e4_validation.checkpoint_files', return_value={'updates': 1}), patch(
                    'src.e4_validation.TrustedPhysicalStore._inspect_execution_run', return_value={'S1': True, 'S2': True}):
                with self.assertRaisesRegex(ValueError, 'Missing/unknown checkpoint'):
                    selection({'method': 'T1', 'seed': 41}, {'checkpoints': [cp, root/'checkpoint-0000002']}, root, registry, path, [ledger], root/'selection.json')

    def test_selection_calls_original_gate_and_reports_equal_score_ties(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, path, registry, cp, ledger = self.fixture(root)
            with patch('src.e4_validation.checkpoint_files', return_value={'updates': 1}), patch(
                    'src.e4_validation.TrustedPhysicalStore._inspect_execution_run', return_value={'S1': True, 'S2': True}), patch(
                    'src.e4_validation.validate_selection', return_value={}) as original:
                result = selection({'method': 'T1', 'seed': 41}, {'checkpoints': [cp]}, root, registry, path, [ledger], root/'selection.json')
            original.assert_called_once()
            self.assertEqual(result['selected_checkpoint'], str(cp.resolve()))
            self.assertTrue(result['uninformative_equal_scores'])

    def test_measured_output_failure_remains_a_terminal_actual_model_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, _, _, cp, ledger = self.fixture(root)
            response_path = root/'session1/decision_000/response.json'; response = json.loads(response_path.read_text())
            response.pop('action'); response.update(error='ValueError: missing EOS',
                failure_class='policy_output_or_budget', generation_started=True)
            response['usage'].update(output_tokens=1024, eos_terminated=False); save(response_path, response)
            session_path = root/'session1/session.json'; session = json.loads(session_path.read_text())
            session['history'][-1].pop('action'); save(session_path, session)
            data = json.loads(ledger.read_text()); data['tasks']['valtask']['gateway_events'] = [{'status': 'MODEL_RESPONSE_FAILURE'}]; save(ledger, data)
            validate_editing_ledger(ledger, plan, cp, 'T1', 41)
            response.pop('usage'); save(response_path, response)
            with self.assertRaisesRegex(ValueError, '16384/1024'):
                validate_editing_ledger(ledger, plan, cp, 'T1', 41)

    def test_raw_malformed_patch_is_retained_without_source_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, _, _, cp, ledger = self.fixture(root)
            response_path = root/'session1/decision_000/response.json'; response = json.loads(response_path.read_text())
            action = {**response['action'], 'action': 'propose_patch',
                'patch': '--- a/layout.py\n+++ b/layout.py\n@@ -1,2 +1,2 @@\n-value = 1\n+value = 2\n'}
            response['action'] = action; save(response_path, response)
            session_path = root/'session1/session.json'; session = json.loads(session_path.read_text()); session['history'][-1]['action'] = action; save(session_path, session)
            data = json.loads(ledger.read_text()); data['tasks']['valtask']['gateway_events'] = [{'status': 'ACTION_REJECTED'}]; save(ledger, data)
            actual = validate_editing_ledger(ledger, plan, cp, 'T1', 41)
            self.assertEqual(actual['tasks']['valtask']['final_sources'], {'layout.py': 'value = 1\n'})

    def test_valid_late_action_is_not_applied_or_scored_as_within_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, _, _, cp, ledger = self.fixture(root)
            folder = root/'session1/decision_000'; response = json.loads((folder/'response.json').read_text())
            response['action'].update(action='propose_patch', patch='--- a/layout.py\n+++ b/layout.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n'); save(folder/'response.json', response)
            session_path = root/'session1/session.json'; session = json.loads(session_path.read_text())
            session['packet']['budget']['deadline_utc'] = '2026-10-19T01:01:00+00:00'
            session['history'][-1].pop('action'); save(session_path, session)
            request = current_state_request(session['packet'], session['history'], session['packet']['visible_sources'])
            save(folder/'request.json', {'variant': 'T1', 'request': request})
            invocation = json.loads((folder/'invocation.json').read_text()); invocation.update(utc_deadline_exceeded=True, ended_at_utc='2026-10-19T01:01:01+00:00'); save(folder/'invocation.json', invocation)
            data = json.loads(ledger.read_text()); data['tasks']['valtask']['gateway_events'] = [{'status': 'BUDGET_REJECTED'}]; save(ledger, data)
            validate_editing_ledger(ledger, plan, cp, 'T1', 41)
            invocation['utc_deadline_exceeded'] = False; save(folder/'invocation.json', invocation)
            with self.assertRaisesRegex(ValueError, 'actual elapsed UTC'):
                validate_editing_ledger(ledger, plan, cp, 'T1', 41)

    def test_actual_unknown_stops_before_second_final_point_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan, path, _, cp, _ = self.fixture(root)
            task_path = root/'task.json'; task = json.loads(task_path.read_text())
            task.update(source_files=['layout.py'], entrypoint='layout.py', configuration_ids=['v0', 'v1']); save(task_path, task)
            registry_path = root/'registry.json'; registry = json.loads(registry_path.read_text())
            for point in registry['configurations']:
                point.update(parameters={}, trusted_evaluator_files={'evaluate.py': '# fixture'},
                    contract={'task_id': 'valtask', 'reference_id': 'fixed-N'}, pdk_revision='fixture-PDK')
            save(registry_path, registry); plan['split_registry_sha256'] = file_digest(registry_path)
            path.chmod(0o644); save(path, plan); path.chmod(0o444)
            action = {'action': 'finish', 'path': '', 'patch': '', 'configuration_ids': [], 'fidelity': '', 'summary': 'done'}
            def finish(session): session['closed'] = True
            with patch('src.e4_validation.inspect_formal_run', return_value={'checkpoints': [cp]}), patch(
                    'src.e4_validation.checkpoint_files', return_value={}), patch(
                    'src.local_model_adapter.LocalDecisionAdapter') as adapter, patch(
                    'scripts.e1_schematic_parallel.resources', return_value={'busy_cores': 0, 'RAM_used_GiB': 1}), patch(
                    'src.candidate_executor.CandidateExecutor') as executor, patch(
                    'src.e4_validation.TrustedPhysicalStore._inspect_execution_run', side_effect=ValueError('actual incomplete trace')):
                adapter.return_value.start.return_value = {'output': str(root/'session1'), 'history': [{}]}
                adapter.return_value.step.return_value = action; adapter.return_value.finish.side_effect = finish
                executor.return_value.execute.return_value = {'run_directory': str(root/'actual_run'), 'status': 'EVALUATED'}
                with self.assertRaisesRegex(RuntimeError, 'physical evidence is unknown'):
                    run_checkpoint(path, {'method': 'T1', 'seed': 41}, cp, root/'run', root)
                self.assertEqual(executor.return_value.execute.call_count, 1)
            self.assertFalse((root/'run/editing_ledger.json').exists())
            raw = json.loads((root/'run/valtask/final_unknown.json').read_text())
            self.assertEqual(raw['completed_points'], 0)
            self.assertEqual(raw['status'], 'PAUSED_UNKNOWN_NO_AUTOMATIC_RETRY')


class MirrorDomainSoftwareTests(unittest.TestCase):
    def test_fixed_whole_cartesian_and_independent_per_finger_reference(self):
        references = [reference(w, length) for w in WIDTHS for length in LENGTHS]
        self.assertEqual(len(references), 9); self.assertEqual(len(set(references)), 9)
        self.assertTrue(all(text.count('sky130_fd_pr__nfet_01v8') == 4 for text in references))
        self.assertNotIn('m=2', references[0])

    def test_new_raw_fields_adapter_preserves_original_deck_assignment(self):
        root = Path(__file__).resolve().parents[1]; original = (root/'scripts/validation_task_evaluator.py').read_text()
        revised = adapter(original)
        self.assertEqual(retained_deck_assignment(original), retained_deck_assignment(revised))
        self.assertIn("'netlist':'extracted_lvs.spice','reference':'reference.spice'", revised)
        self.assertIn('compare_device_intent', revised)
        self.assertIn("'area':{'value':area_um2,'unit':'um2'}", revised)

    def test_prospective_initial_only_opens_one_active_source_path(self):
        root = Path(__file__).resolve().parents[1]; original = (root/'src/generators/validation_mirror.py').read_text()
        revised = injected_source(original)
        self.assertEqual(revised.replace('"GND":([("reference","S"),("reference","B"),("output","B")],low)',
            '"GND":([("reference","S"),("reference","B"),("output","S"),("output","B")],low)'), original)
        self.assertIn('with_dummy=False,with_tie=True,with_dnwell=False', revised)


if __name__ == '__main__': unittest.main()
