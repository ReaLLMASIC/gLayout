"""Software tests for the paused-cohort denominator consumer, not physical evidence."""
import tempfile
import unittest
from pathlib import Path
from scripts.analyze_e1_partial_interface import analyze, cohort_group, endpoints, rate


def row(status='MODEL_FAILURE', verified=150, complete=True, known=16, passed=16):
    return {'task_id': 'source', 'method': 'G2', 'trial_id': '1', 'search_status': status,
        'first_verified_times_seconds': {'S2': verified}, 'search_budget_seconds': 1200,
        'final_anchor': {'S2': True, 'complete': complete},
        'hidden': {'declared': 16, 'known': known, 'S2_passed': passed},
        'physical_stages': {'search': {'physical_calls': 3}}, 'failure_mode': 'context_budget_rejection'}


class PartialInterfaceAnalysisTests(unittest.TestCase):
    def test_later_model_failure_preserves_already_verified_s2(self):
        value = endpoints([row()], 120)
        self.assertEqual(value['within_budget_search_S2']['verified_positive'], 1)
        self.assertEqual(value['within_budget_search_S2']['known_outcomes'], 1)
        self.assertEqual(value['within_budget_search_S2']['identification_bounds'], [1/120, 1])

    def test_missing_hidden_and_unrun_are_not_zero_outcomes(self):
        value = endpoints([row(verified=None, complete=False, known=0, passed=0)], 120)
        self.assertEqual(value['within_budget_search_S2']['known_outcomes'], 1)
        self.assertEqual(value['final_frozen_source_anchor_S2']['known_outcomes'], 0)
        self.assertEqual(value['hidden_configuration_S2']['unknown_outcomes'], 1920)
        self.assertIsNone(value['hidden_configuration_S2_among_dispatched']['conditional_known_rate'])

    def test_legacy_and_manifest_groups_are_disjoint(self):
        value = row();value['failure_mode'] = 'source_read_outside_packet'
        self.assertEqual(cohort_group(value, {('source', 'G2', '1')}), 'retained_original_three')
        self.assertEqual(cohort_group(value, set()), 'later_manifest_read_failures')
        value['failure_mode'] = 'context_budget_rejection'
        self.assertEqual(cohort_group(value, set()), 'real_construction_trajectories')

    def test_active_snapshot_is_not_called_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'suite.json'
            path.write_text('{"status":"RUNNING","coordinator_pid":123,"jobs":[]}')
            with self.assertRaisesRegex(ValueError, 'paused, drained'):
                analyze(path)

    def test_inconsistent_outcome_counts_rejected(self):
        with self.assertRaises(ValueError):rate(2, 1, 120)


if __name__ == '__main__':unittest.main()
