"""Fixed-matrix coordination fixtures; no models, SSH or physical execution."""
import json
import contextlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.run_e3_suite import (FIDELITY_READY, INSTANCE_READY, LOCAL_READY, SEALED, collect, command,
    local_ready, plan, reserve, run, save, validate_resume)


def manifest_fixture():
    tasks = ['task_%02d' % i for i in range(24)]
    return {'status': 'FROZEN_E3', 'formal_dispatch': True, 'task_ids': tasks, 'trials': 5,
        'selection_seeds': [41, 73, 109, 167, 223], 'dispatch_order_seed': 20261019,
        'parameter_task_ids': tasks[:8], 'instance_task_ids': tasks[:8], 'instance_trials': 1,
        'signal_task_ids': tasks[:8], 'selector_ablation_weights': {'without_distance': {}, 'without_margin': {}},
        'fidelity_task_ids': tasks[-2:], 'fidelity_manifest': '/trusted/future_F3/manifest.json',
        'risk_weights': {'uncertainty': 1, 'low_margin': 1},
        'parameter_baseline': {'strategies': ['random', 'gpt_feedback']},
        'backend_manifest_path': '/trusted/freeze/manifest.json', 'source_revision': 'a'*40,
        'freeze_id': 'fixture', 'implementation_sha256': {'fixture.py': 'fixture'},
        'budget': {'maximum_context_tokens': 12288, 'maximum_output_tokens': 1024}}


class E3SuiteTests(unittest.TestCase):
    def test_fixed_all_six_matrices_and_matched_T0_slots(self):
        manifest = manifest_fixture()
        self.assertEqual([len(plan(manifest, part)) for part in ('gpt', 'parameter', 'local', 'signals', 'fidelity', 'instance')],
            [480, 80, 1080, 80, 10, 8])
        self.assertEqual(plan(manifest, 'gpt'), plan(manifest, 'gpt'))
        t0 = [row for row in plan(manifest, 'local') if row['policy_variant'] == 'T0']
        self.assertEqual({row['evaluation_seed_slot'] for row in t0}, {41, 73, 109})
        self.assertEqual(len(t0), 216)
        self.assertTrue(all('training_seed' not in row for row in t0))
        self.assertEqual({row['selector_variant'] for row in plan(manifest, 'signals')}, {'without_distance', 'without_margin'})

    def test_reservation_is_durable_before_child_and_never_recreated(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary);job = plan(manifest_fixture(), 'gpt')[0];state = {'jobs': [job]}
            folder = reserve(job, 0, out, manifest_fixture(), out/'state.json', state, {'busy_cores': 1})
            self.assertEqual(json.loads((out/'state.json').read_text())['jobs'][0]['status'], 'DISPATCH_RESERVED')
            self.assertFalse(Path(job['dispatch_record']).exists())
            self.assertTrue((folder/'reservation.json').is_file())
            self.assertIsNone(reserve(job, 0, out, manifest_fixture(), out/'state.json', state, {}))
            self.assertEqual(job['status'], 'UNRESOLVED_EXISTING_RESERVATION')

    def test_resume_rejects_reordered_or_changed_seed_matrix(self):
        jobs = plan(manifest_fixture(), 'gpt')
        frozen = {'identity': {'freeze_id': 'actual'}, 'jobs': jobs}
        state = {'plan_identity': frozen['identity'], 'jobs': json.loads(json.dumps(jobs))}
        validate_resume(state, frozen)
        state['jobs'][0]['selection_seed'] += 1
        with self.assertRaises(ValueError):validate_resume(state, frozen)

    def test_local_missing_freeze_waits_without_reservation_or_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);manifest = root/'manifest.json';save(manifest, manifest_fixture())
            args = SimpleNamespace(manifest=manifest, output=root/'suite', part='local', workers=4)
            def stop_after_wait(_):
                raise KeyboardInterrupt('Fixture stops a WAITING coordinator without any child')
            with patch('scripts.run_e3_suite.verify'), patch('scripts.run_e3_suite.local_ready', return_value={
                    'ready': False, 'status': 'WAITING_FOR_FROZEN_E4_METHODS'}), patch(
                    'scripts.run_e3_suite.subprocess.Popen', side_effect=AssertionError('No local trial before real methods/READY')), patch(
                    'scripts.run_e3_suite.resources', side_effect=AssertionError('No dispatch resource allocation while blocked')), patch(
                    'scripts.run_e3_suite.time.sleep', side_effect=stop_after_wait):
                with self.assertRaises(KeyboardInterrupt):run(args)
            state = json.loads((root/'suite/state.json').read_text())
            self.assertTrue(state['status'].startswith('WAITING'))
            self.assertTrue(all(job['status'] == 'NOT_RUN' for job in state['jobs']))
            self.assertEqual(list((root/'suite').glob('*/reservation.json')), [])

    def test_missing_fidelity_freeze_waits_without_starting_any_trial(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);manifest = root/'manifest.json';save(manifest, manifest_fixture())
            args = SimpleNamespace(manifest=manifest, output=root/'suite', part='fidelity', workers=4)
            with patch('scripts.run_e3_suite.verify'), patch('scripts.run_e3_suite.fidelity_ready', return_value={
                    'ready': False, 'status': 'WAITING_FOR_FROZEN_FIDELITY_METHOD'}), patch(
                    'scripts.run_e3_suite.subprocess.Popen', side_effect=AssertionError('No trial without actual F3 freeze')), patch(
                    'scripts.run_e3_suite.resources', side_effect=AssertionError('No allocation while blocked')), patch(
                    'scripts.run_e3_suite.time.sleep', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):run(args)
            state = json.loads((root/'suite/state.json').read_text())
            self.assertEqual(state['status'], 'WAITING_FOR_FROZEN_FIDELITY_METHOD')
            self.assertTrue(all(job['status'] == 'NOT_RUN' for job in state['jobs']))

    def test_instance_without_actual_release_waits_without_reservation_or_arrival(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);manifest = manifest_fixture()
            manifest['hidden_release_file'] = str(root/'absent_release.json')
            manifest['original_baseline_plan'] = str(root/'plan.json')
            filename = root/'manifest.json';save(filename, manifest)
            def check_actual_release(code, payload):
                self.assertEqual(code, INSTANCE_READY)
                output = io.StringIO()
                with patch('sys.argv', ['backend', json.dumps(payload)]), contextlib.redirect_stdout(output):
                    exec(code, {})
                return json.loads(output.getvalue())
            with patch('scripts.run_e3_suite.verify'), patch('scripts.run_e3_suite.remote', side_effect=check_actual_release), patch(
                    'scripts.run_e3_suite.subprocess.Popen', side_effect=AssertionError('No I arrival before shared release')), patch(
                    'scripts.run_e3_suite.resources', side_effect=AssertionError('No allocation while blocked')), patch(
                    'scripts.run_e3_suite.time.sleep', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    run(SimpleNamespace(manifest=filename, output=root/'suite', part='instance', workers=4))
            state = json.loads((root/'suite/state.json').read_text())
            self.assertEqual(state['status'], 'WAITING_FOR_SHARED_EVALUATION_RELEASE')
            self.assertTrue(all(job['status'] == 'NOT_RUN' for job in state['jobs']))
            self.assertEqual(list((root/'suite').glob('*/reservation.json')), [])

    def test_interrupted_durable_reservation_is_never_relaunched(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);manifest = manifest_fixture();manifest_file = root/'manifest.json';save(manifest_file, manifest)
            jobs = plan(manifest, 'gpt')[:1];out = root/'suite';out.mkdir()
            ident = {'part': 'gpt', 'manifest': str(manifest_file.resolve()), 'freeze_id': manifest['freeze_id'],
                **{key: manifest[key] for key in ('backend_manifest_path', 'source_revision', 'implementation_sha256')}}
            save(out/'plan.json', {'identity': ident, 'jobs': jobs, 'automatic_retry': False});(out/'plan.json').chmod(0o444)
            actual = json.loads(json.dumps(jobs));actual[0]['status'] = 'DISPATCH_RESERVED'
            save(out/'state.json', {'plan_identity': ident, 'jobs': actual})
            with patch('scripts.run_e3_suite.verify'), patch('scripts.run_e3_suite.plan', return_value=jobs), patch(
                    'scripts.run_e3_suite.subprocess.Popen', side_effect=AssertionError('Never automatically relaunch')), patch(
                    'scripts.run_e3_suite.resources', side_effect=AssertionError('No new trial allowed')):
                result = run(SimpleNamespace(manifest=manifest_file, output=out, part='gpt', workers=4))
            self.assertEqual(result['status'], 'PAUSED_UNRESOLVED')
            self.assertEqual(json.loads((out/'state.json').read_text())['jobs'][0]['status'], 'UNRESOLVED_DISPATCH_RESERVATION')

    def test_fidelity_ready_reads_actual_readonly_matched_ten_plan(self):
        for code in (LOCAL_READY, FIDELITY_READY, SEALED):compile(code, '<backend protocol>', 'exec')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);manifest = manifest_fixture();manifest['fidelity_manifest'] = str(root/'F3.json')
            f3 = {'status': 'FROZEN_E3_FIDELITY_METHOD', 'formal_dispatch': True,
                'main_freeze_id': manifest['freeze_id'], 'freeze_id': 'F3_fixture',
                'budget': manifest['budget'], 'risk_weights': manifest['risk_weights'],
                'backend_manifest_path': '/backend/frozen_F3/manifest.json',
                'search_plan': [{'task_id': task, 'trial_id': str(trial)} for task in manifest['fidelity_task_ids'] for trial in range(1, 6)]}
            def check():
                output = io.StringIO()
                with patch('sys.argv', ['backend', json.dumps(manifest)]), contextlib.redirect_stdout(output):
                    exec(FIDELITY_READY, {})
                return json.loads(output.getvalue())
            save(root/'F3.json', f3);(root/'F3.json').chmod(0o444)
            self.assertTrue(check()['ready'])
            (root/'F3.json').chmod(0o644);f3['search_plan'].pop();save(root/'F3.json', f3);(root/'F3.json').chmod(0o444)
            self.assertFalse(check()['ready'])

    def test_stdout_cannot_substitute_for_real_search_and_backend_seal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);job = plan(manifest_fixture(), 'gpt')[0]
            client = {key: job[key] for key in ('task_id', 'method', 'trial_id', 'policy_variant', 'evaluation_seed_slot')}
            client.update(formal=True, episode_directory='/trusted/real/episode', local_output_directory=str(root/'policy'))
            record = root/'client.json';save(record, client);job['dispatch_record'] = str(record)
            with patch('scripts.run_e3_suite.remote', side_effect=AssertionError('No report exists')):
                collect(job)
            self.assertEqual(job['status'], 'UNRESOLVED_NO_SEARCH_RECORD')
            (root/'policy').mkdir();save(root/'policy/search.json', {'task_id': job['task_id'],
                'method': job['method'], 'trial_id': job['trial_id'], 'status': 'SEARCH_FINISHED'})
            with patch('scripts.run_e3_suite.remote', return_value={'sealed': False}):
                with self.assertRaises(ValueError):collect(job)

    def test_job_commands_preserve_part_specific_method_slots_and_no_hidden(self):
        manifest = manifest_fixture()
        local = next(row for row in plan(manifest, 'local') if row['policy_variant'] == 'T0')
        argv = command(local, manifest, Path('/local/client.json'))
        self.assertIn('--search-only', argv)
        self.assertEqual(argv[argv.index('--training-seed')+1], str(local['evaluation_seed_slot']))
        p = command(plan(manifest, 'parameter')[0], manifest, Path('/local/client.json'))
        i = command(plan(manifest, 'instance')[0], manifest, Path('/local/client.json'))
        self.assertIn('e3_parameter_episode.py', p[1]);self.assertIn('--formal', p)
        self.assertIn('e3_instance_episode.py', i[1]);self.assertNotIn('--training-seed', i)
        signal = plan(manifest, 'signals')[0];s = command(signal, manifest, Path('/local/client.json'))
        self.assertEqual(s[s.index('--selector-variant')+1], signal['selector_variant'])
        f = command(plan(manifest, 'fidelity')[0], {**manifest, 'backend_manifest_path': '/actual/F3.json'}, Path('/local/client.json'))
        self.assertIn('e3_fidelity_episode.py', f[1]);self.assertEqual(f[f.index('--manifest')+1], '/actual/F3.json')
        self.assertTrue(all('post_freeze' not in text for text in argv+p+i+s+f))


if __name__ == '__main__':
    unittest.main()
