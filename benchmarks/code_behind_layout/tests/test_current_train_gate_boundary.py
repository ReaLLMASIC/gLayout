"""Software-only maintenance tests: no actual processes or experiments."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import scripts.quiesce_train_gate_current_boundary as maintenance


class CurrentGateBoundaryTests(unittest.TestCase):
    def test_unrelated_physical_container_never_requires_cwd_inspection(self):
        class ContainerCommand:
            def stat(self):
                return type('Info', (), {'st_uid': maintenance.os.getuid()})()
            def read_bytes(self):
                return b'python\0/trusted/evaluate.py\0'
        actual_path = Path
        proc = type('Proc', (), {'glob': lambda self, pattern: [ContainerCommand()]})()
        with patch.object(maintenance, 'Path', side_effect=lambda value: proc if value == '/proc' else actual_path(value)), \
                patch.object(maintenance, 'process', side_effect=PermissionError('unrelated container cwd')) as inspect:
            self.assertEqual(maintenance.inspect_collectors(), [])
            inspect.assert_not_called()

    def fixture(self):
        result = {maintenance.QUEUE: {'pid': maintenance.QUEUE, 'argv': ['python3',
            'scripts/train_collection_queue.py', '--execute'], 'cwd': str(maintenance.ROOT),
            'start_ticks': maintenance.EXPECTED_START_TICKS[maintenance.QUEUE], 'state': 'S'}}
        for pid, circuit in maintenance.COLLECTORS.items():
            result[pid] = {'pid': pid, 'argv': ['python3', 'scripts/collect_training.py', '--manifest',
                '/fixture/' + circuit + '/collection.json', '--execute'], 'cwd': str(maintenance.ROOT),
                'start_ticks': maintenance.EXPECTED_START_TICKS[pid], 'state': 'S', 'manifest': '/fixture/' + circuit + '/collection.json',
                'output': '/fixture/' + circuit, 'backend': 'isolated_gpt_cli', 'sampling_mode': 'fixture'}
        return result

    def test_unready_boundary_restores_queue_without_signalling_collectors(self):
        processes = self.fixture(); signals = []
        def signal(pid, kind):
            signals.append((pid, kind)); processes[pid]['state'] = 'T' if kind == maintenance.signal.SIGSTOP else 'S'
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(maintenance, 'process', side_effect=lambda pid: dict(processes[pid])), \
                patch.object(maintenance, 'inspect_collectors', side_effect=lambda: [dict(processes[p]) for p in maintenance.COLLECTORS]), \
                patch.object(maintenance, 'boundary', return_value={'safe_eight_trial_boundary': False}), \
                patch.object(maintenance.os, 'kill', side_effect=signal), \
                patch.object(maintenance.time, 'monotonic', side_effect=[0, 0, 61, 61]), \
                patch.object(maintenance.time, 'sleep'):
            result = maintenance.prepare(Path(tmp) / 'recovery.json')
            self.assertEqual(result['status'], 'ABORTED_RESTORED')
            self.assertEqual(signals, [(maintenance.QUEUE, maintenance.signal.SIGSTOP),
                                      (maintenance.QUEUE, maintenance.signal.SIGCONT)])
            self.assertEqual((Path(tmp) / 'recovery.json').stat().st_mode & 0o777, 0o600)

    def test_restore_refuses_reused_pid_without_signalling(self):
        before = self.fixture()[maintenance.QUEUE]; after = {**before, 'start_ticks': 'changed', 'state': 'T'}
        record = {'status': 'PARENTS_QUIESCED', 'processes': [{**before,
            'changed_by_this_operation': True, 'stopped_epoch_s': 1}]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(maintenance, 'process', return_value=after), \
                patch.object(maintenance.os, 'kill') as signal:
            path = Path(tmp) / 'recovery.json'; path.write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                maintenance.restore(path, 'fixture', require_health=False)
            signal.assert_not_called()

    def test_readonly_status_does_not_claim_drain_with_new_collector(self):
        processes = self.fixture()
        for row in processes.values(): row['state'] = 'T'
        collectors = [processes[p] for p in maintenance.COLLECTORS]
        for row in collectors: row['boundary'] = {'safe_eight_trial_boundary': True}
        unexpected = {**collectors[0], 'pid': 99999}
        record = {'processes': list(processes.values()), 'initial_collectors': collectors}
        healthy = [{'status': 'READY', 'global_teacher_slots': 2,
                    'context16384_route_enabled': True, 'active_forwards': 0}] * 2
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(maintenance, 'process', side_effect=lambda pid: dict(processes[pid])), \
                patch.object(maintenance, 'inspect_collectors', return_value=collectors + [unexpected]), \
                patch.object(maintenance, 'tcp_requests', return_value=[]), \
                patch.object(maintenance, 'health', return_value=healthy), \
                patch.object(maintenance.os, 'kill') as signal:
            path = Path(tmp) / 'recovery.json'; path.write_text(json.dumps(record))
            result = maintenance.status(path)
            self.assertFalse(result['ready_for_root_local_paired_drain'])
            signal.assert_not_called()


if __name__ == '__main__':
    unittest.main()
