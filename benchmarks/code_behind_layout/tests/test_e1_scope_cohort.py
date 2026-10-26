"""Independent scope-cohort software controls; no policy or physical calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import shutil
import subprocess
import hashlib
from unittest.mock import patch
from types import SimpleNamespace

from scripts.e1_scope_runner import Backend, CandidateActionError, backend, initialize
from scripts.analyze_e1_scope import scoped
from scripts.run_e1_scope_suite import plan, run
from scripts.e1_matched_runner import BackendInfrastructureError
from scripts.freeze_e1_scope_cohort import runtime_bindings, unchanged_physical_inputs
from scripts.prepare_e1_scope_cohort import BUDGET, COHORT, packet, prepare, save


def proposal_fixture():
    return {'action_gateway': {'read_source_paths': ['generator.py'], 'read_source_scope': 'Runtime is not read_source'},
        'candidate_runtime_configuration': {'graph': 'complete schema fixture'},
        'candidate_runtime_primitive_library_G1_G2': {'cells': 'list with complete field schema fixture'},
        'graph_runtime_replacements': {'G0': 'No library mount', 'G1_G2': 'Candidate runtime only'}}


def packet_fixture():
    return {'task_id': 'task', 'goal': 'software fixture', 'contract': {'immutable': True},
        'allowed_paths': ['generator.py'], 'visible_sources': {'generator.py': '# complete fixture\n'},
        'documents': {'history_policy': {'limits': 'old8192'}, 'intended_anchor_graph': {'runtime': 'old runtime'},
            'PDK': {'complete_rules': 'unchanged fixture'}}, 'visible_configurations': ['anchor'],
        'budget': {**BUDGET, 'maximum_context_tokens': 8192}}


class E1ScopeTests(unittest.TestCase):
    def test_actual_bad_hunks_are_candidate_invalid_with_zero_physical_dispatch(self):
        fixtures = json.loads((Path(__file__).parent/'fixtures/e1_scope_actual_bad_patches.json').read_text())
        for raw in fixtures:
            with tempfile.TemporaryDirectory() as temporary:
                gateway = Backend.__new__(Backend);gateway.private = Path(temporary)
                source = gateway.private/'current_source';source.mkdir();(source/'generator.py').write_text(raw['source_text'])
                gateway.state = {'sealed': False, 'decisions': 0};gateway.write = lambda: None
                gateway.packet = {'allowed_paths': ['generator.py'], 'visible_sources': {'generator.py': raw['source_text']},
                    'visible_configurations': ['anchor'], 'budget': {'decisions': 2}}
                with patch('scripts.e1_matched_runner.Backend.evaluate') as physical:
                    with self.assertRaisesRegex(CandidateActionError, 'candidate_bad_patch: error: corrupt patch at line '+str(raw['expected_corrupt_line'])):
                        gateway.action(raw['action'])
                    physical.assert_not_called()
                self.assertEqual((source/'generator.py').read_text(), raw['source_text'])
                self.assertEqual(gateway.state['decisions'], 1)

    def test_only_exact_committed_classification_amendment_can_change_pilot_code(self):
        actual_root = Path(__file__).resolve().parents[1];name = 'scripts/e1_scope_runner.py'
        patch_name = 'configs/development/e1_scope_candidate_error_classification.patch'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);out = root/'episode';snapshot = out/'private/execution_implementation'
            (snapshot/'scripts').mkdir(parents=True);shutil.copyfile(actual_root/name, snapshot/name)
            amended = (actual_root/patch_name).read_text()
            subprocess.run(['git', 'apply', '--reverse', '--whitespace=nowarn', '-'], input=amended,
                text=True, cwd=snapshot, check=True, capture_output=True)
            (root/'scripts').mkdir();shutil.copyfile(actual_root/name, root/name)
            (root/'configs/development').mkdir(parents=True);(root/patch_name).write_text(amended)
            state = {'execution_implementation_sha256': {name: hashlib.sha256((snapshot/name).read_bytes()).hexdigest()}}
            with patch('scripts.freeze_e1_scope_cohort.ROOT', root):
                changes = runtime_bindings(out, state, {name})
                self.assertEqual(len(changes), 1);self.assertFalse(changes[0]['raw_pilot_status_rewritten'])
                with (root/name).open('a') as stream:stream.write('\n# unrelated source change\n')
                with self.assertRaisesRegex(ValueError, 'outside the exact committed'):
                    runtime_bindings(out, state, {name})

    def test_readonly72_packet_copy_preserves_original_binary_and_reference_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve();old = root/'prior';packets = old/'packets';tasks = []
            for i in range(24):
                ident = 'task%02d' % i;tasks.append({'task_id': ident})
                save(packets/'private'/ident/'task.json', {'task_id': ident, 'status': 'FROZEN_E1_TASK',
                    'formal_admission': True, 'reference_file': str(packets/'private'/ident/'reference.spice')})
                (packets/'private'/ident/'reference.spice').write_bytes(b'* exact independent reference fixture\n')
                (packets/'private'/ident/'primitive.gds').write_bytes(b'\xff\x00binary fixture')
                for method in ('G0', 'G1', 'G2'):
                    value = packet_fixture();value['task_id'] = ident;save(packets/'public'/ident/(method+'.json'), value)
            save(packets/'public/catalog.json', {'tasks': tasks})
            save(old/'model.json', {'status': 'frozen', 'model': 'actual_model_fixture', 'max_context_tokens': 8192, 'max_new_tokens': 1024})
            save(old/'manifest.json', {'status': 'FROZEN_E1', 'formal_dispatch': True, 'budget': {**BUDGET, 'maximum_context_tokens': 8192},
                'packet_root': str(packets), 'model_config': str(old/'model.json'), 'freeze_id': 'prior_fixture'})
            save(root/'proposal.json', proposal_fixture())
            original = {str(p.relative_to(old)): p.read_bytes() for p in old.rglob('*') if p.is_file()}
            for path in sorted(old.rglob('*'), reverse=True):path.chmod(0o555 if path.is_dir() else 0o444)
            old.chmod(0o555)
            try:
                result = prepare(old/'manifest.json', root/'proposal.json', root/'new')
                self.assertEqual(result['packet_count'], 72)
                self.assertTrue(all((old/name).read_bytes() == value for name, value in original.items()))
                self.assertEqual(old.stat().st_mode & 0o777, 0o555)
                self.assertEqual((root/'new/packets/private/task00/primitive.gds').read_bytes(), b'\xff\x00binary fixture')
                task = json.loads((root/'new/packets/private/task00/task.json').read_text())
                self.assertTrue(task['reference_file'].startswith(str(root/'new/packets')))
                self.assertFalse(task['formal_admission'])
                declared = {'task_ids': [t['task_id'] for t in tasks], 'methods': ['G0', 'G1', 'G2']}
                unchanged_physical_inputs(root/'new/packets', packets, declared, proposal_fixture())
                reference = root/'new/packets/private/task23/reference.spice';reference.chmod(0o644)
                reference.write_text('* changed independent N fixture\n')
                with self.assertRaisesRegex(ValueError, 'Immutable physical/source bytes changed'):
                    unchanged_physical_inputs(root/'new/packets', packets, declared, proposal_fixture())
            finally:
                old.chmod(0o755)
                for path in old.rglob('*'):
                    if path.is_dir():path.chmod(0o755)

    def test_packet_changes_only_documentation_and_explicit_common_context(self):
        original = packet_fixture();before = copy.deepcopy(original)
        for method in ('G0', 'G1', 'G2'):
            result = packet(original, method, proposal_fixture())
            self.assertEqual(result['visible_sources'], original['visible_sources'])
            self.assertEqual(result['contract'], original['contract'])
            self.assertEqual(result['documents']['PDK'], original['documents']['PDK'])
            self.assertEqual(result['documents']['cohort_id'], COHORT)
            self.assertEqual(result['budget']['maximum_context_tokens'], 16384)
            self.assertEqual('candidate_runtime_primitive_library' in result['documents'], method != 'G0')
        self.assertEqual(original, before)

    def test_new16k_initializer_never_mutates_original_and_pilot_has_no_hidden(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);manifest = {'status': 'DRAFT_E1_RUNNER', 'formal_dispatch': False,
                'cohort_id': COHORT, 'interface_version': COHORT, 'budget': BUDGET,
                'visible_history_policy': 'current_source_and_feedback_v1', 'task_ids': ['task'],
                'packet_root': str(root/'packets'), 'model_config': str(root/'model.json')}
            save(root/'manifest.json', manifest);save(root/'model.json', {'max_context_tokens': 16384, 'max_new_tokens': 1024})
            save(root/'packets/private/task/task.json', {'task_id': 'task', 'cohort_id': COHORT, 'stratum': 'reuse',
                'logical_group': 'fixture', 'merge_sensitivity_group': 'fixture', 'configurations': [{'configuration_id': 'anchor'}]})
            save(root/'packets/public/task/G1.json', packet(packet_fixture(), 'G1', proposal_fixture()))
            actual_root = Path(__file__).resolve().parents[1]
            for name in ('scripts/e1_scope_runner.py', 'scripts/prepare_e1_scope_cohort.py', 'scripts/e1_scope_proposal_preflight.py'):
                target = root/name;target.parent.mkdir(parents=True, exist_ok=True);shutil.copyfile(actual_root/name, target)
            before = (root/'manifest.json').read_bytes()
            with patch('scripts.e1_scope_runner.ROOT', root), patch('scripts.e1_matched_runner.ROOT', root):
                result = initialize({'manifest': str(root/'manifest.json'), 'task_id': 'task', 'method': 'G1',
                    'trial_id': 'development', 'formal': False, 'interface_pilot': True})
                out = Path(result['episode_directory']);self.assertEqual(result['packet']['budget']['decisions'], 2)
                self.assertEqual(result['packet']['budget']['physical_evaluations'], 1)
                with self.assertRaisesRegex(ValueError, 'never opens a hidden'):
                    backend({'op': 'post_freeze', 'episode_directory': str(out)})
                self.assertEqual(json.loads((out/'private/state.json').read_text())['cohort_id'], COHORT)
                (root/'scripts/e1_scope_proposal_preflight.py').write_text('# changed after actual start\n')
                with self.assertRaisesRegex(BackendInfrastructureError, 'implementation differs'):
                    backend({'op': 'current', 'episode_directory': str(out)})
            self.assertEqual((root/'manifest.json').read_bytes(), before)

    def test_old_cohort_cannot_enter_new_initializer(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'manifest.json';save(path, {'cohort_id': 'old_scope', 'interface_version': 'old'})
            with self.assertRaisesRegex(ValueError, 'separately declared'):
                initialize({'manifest': str(path)})

    def test_fresh360_matrix_and_analysis_rejects_old_trials(self):
        manifest = {'cohort_id': COHORT, 'budget': BUDGET, 'status': 'FROZEN_E1', 'formal_dispatch': True,
            'tasks': [{'task_id': 'task%02d' % i} for i in range(24)], 'task_ids': ['task%02d' % i for i in range(24)],
            'methods': ['G0', 'G1', 'G2'], 'trials': 5, 'runtime': {'candidate_CPUs': 2},
            'backend_manifest_path': '/actual/new/manifest.json', 'dispatch_order_seed': 20261018, 'freeze_id': 'new_fixture'}
        rows = plan(manifest);self.assertEqual(len(rows), 360)
        self.assertTrue(all(row['cohort_id'] == COHORT and row['status'] == 'NOT_RUN' for row in rows))
        with tempfile.TemporaryDirectory() as temporary:
            old = Path(temporary)/'old.json';old.write_text('{"cohort_id":"old_scope","freeze_id":"old"}')
            with self.assertRaisesRegex(ValueError, 'Old/different'):
                scoped(manifest, [{'cohort_id': COHORT, 'episode_json': str(old)}])

    def test_reserved_dispatch_is_retained_and_never_automatically_launched(self):
        manifest = {'cohort_id': COHORT, 'budget': BUDGET, 'status': 'FROZEN_E1', 'formal_dispatch': True,
            'tasks': [{'task_id': 'task%02d' % i} for i in range(24)], 'task_ids': ['task%02d' % i for i in range(24)],
            'methods': ['G0', 'G1', 'G2'], 'trials': 5, 'runtime': {'candidate_CPUs': 2},
            'backend_manifest_path': '/actual/new/manifest.json', 'dispatch_order_seed': 20261018, 'freeze_id': 'new_fixture'}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);manifest_path = root/'manifest.json';save(manifest_path, manifest)
            output = root/'suite';output.mkdir();jobs = plan(manifest);jobs[0]['status'] = 'DISPATCH_RESERVED'
            save(output/'state.json', {'cohort_id': COHORT, 'freeze_id': manifest['freeze_id'],
                'manifest': str(manifest_path.resolve()), 'jobs': jobs})
            with patch('scripts.run_e1_scope_suite.subprocess.Popen') as launch, patch('scripts.run_e1_scope_suite.resources') as resources:
                result = run(SimpleNamespace(manifest=manifest_path, output=output, workers=1))
                launch.assert_not_called();resources.assert_not_called()
            self.assertEqual(result['status'], 'PAUSED_UNRESOLVED_OR_UNKNOWN')
            saved = json.loads((output/'complete_matrix_index.json').read_text())
            self.assertEqual(len(saved), 360)
            self.assertEqual(saved[0]['status'], 'UNRESOLVED_RESERVATION')
            self.assertEqual(sum(row['status'] == 'NOT_RUN' for row in saved), 359)


if __name__ == '__main__':unittest.main()
