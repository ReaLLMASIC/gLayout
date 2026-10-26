"""Maintenance software controls; no process is signalled or model loaded."""
import subprocess
import unittest
from unittest.mock import Mock, call
from scripts.ordinary_inference_memory_operation import OLD_PID, idle, no_future_dispatch, wait_calibration


class OrdinaryMemoryOperationTests(unittest.TestCase):
    def test_historical_pause_cannot_hide_a_later_dispatch(self):
        terminal = {'status': 'COMPLETED_PROPOSAL_MATRIX', 'planned_proposals': 96, 'returned_attempts': 96, 'remaining_not_run': 0}
        queue = {'pid': 1728183, 'events': [{'lane': 'T0', 'event': 'LANE_PAUSED'}]}
        self.assertEqual(no_future_dispatch(queue, terminal)['queue_pid'], 1728183)
        queue['events'].append({'lane': 'T0', 'event': 'COLLECTION_PROCESS_STARTED'})
        with self.assertRaises(ValueError): no_future_dispatch(queue, terminal)

    def test_incomplete_original_sampler_cannot_release_window(self):
        queue = {'pid': 1728183, 'events': [{'lane': 'T0', 'event': 'LANE_PAUSED_UNKNOWN'}]}
        terminal = {'status': 'COMPLETED_PROPOSAL_MATRIX', 'planned_proposals': 96, 'returned_attempts': 88, 'remaining_not_run': 8}
        with self.assertRaises(ValueError): no_future_dispatch(queue, terminal)

    def test_received_request_client_or_socket_prevents_maintenance(self):
        inspection = {'service_pid': OLD_PID, 'service_exact_argv_matches': True, 'actual_T0_clients': [], 'pending_received_requests': []}
        idle(inspection, [])
        with self.assertRaises(ValueError): idle(inspection, ['ESTAB 0 0 127.0.0.1:8114 peer'])
        for key in ['actual_T0_clients', 'pending_received_requests']:
            with self.assertRaises(ValueError): idle({**inspection, key: ['one actual active item']}, [])

    def test_timeout_only_terminates_exact_child_and_waits_for_exit(self):
        child = Mock(); child.wait.side_effect = [subprocess.TimeoutExpired('calibration', 900), -15]
        callback = Mock()
        self.assertEqual(wait_calibration(child, callback), (-15, True))
        self.assertEqual(child.wait.call_args_list, [call(timeout=900), call(timeout=260)])
        child.terminate.assert_called_once_with(); callback.assert_called_once_with()
        child.kill.assert_not_called()


if __name__ == '__main__': unittest.main()
