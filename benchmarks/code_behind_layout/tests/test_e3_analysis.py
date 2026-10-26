import unittest

from src.e3_analysis import analyze


def manifest():
    return {'tasks': [{'task_id': 't'+str(i), 'source_group': 's'+str(i//3),
        'merged_source_group': 'm'+str(min(i//3, 6))} for i in range(24)],
        'methods': ['A', 'R', 'B', 'C'], 'trials': 5}


def episode(task, method, trial, passed=8, unknown=0):
    return {**task, 'method': method, 'trial_id': str(trial), 'status': 'SEARCH_FINISHED',
        'hidden_domain_size': 16, 'hidden_S2_verified': passed, 'hidden_incomplete': unknown}


class AnalysisTests(unittest.TestCase):
    def test_NOT_RUN_keeps_all_declared_denominators_without_fake_zero_success(self):
        report = analyze(manifest(), [])
        self.assertEqual(report['methods']['C']['declared_hidden_configurations'], 1920)
        self.assertEqual(report['methods']['C']['full_matrix_coverage_identification_bounds'], [0, 1])
        self.assertIsNone(report['methods']['C']['hidden_S2_coverage'])
        self.assertEqual(report['primary_contrasts'], [])

    def test_unknown_retains_observed_success_and_cannot_trigger_paired_CI(self):
        plan = manifest()
        row = episode(plan['tasks'][0], 'C', 1, passed=4, unknown=8)
        report = analyze(plan, [row])
        bound = report['methods']['C']['full_matrix_coverage_identification_bounds']
        self.assertAlmostEqual(bound[0], 4/1920)
        self.assertAlmostEqual(bound[1], (4+8+119*16)/1920)
        self.assertFalse(report['primary_analysis_complete'])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            analyze(plan, [row, row])

    def test_full_matrix_uses_eight_and_seven_whole_groups(self):
        plan = manifest()
        rows = [episode(task, method, trial, 12 if method == 'C' else 8)
                for task in plan['tasks'] for method in plan['methods'] for trial in range(1, 6)]
        report = analyze(plan, rows, replicates=20)
        self.assertTrue(report['primary_analysis_complete'])
        self.assertEqual(report['fully_paired_tasks'], 24)
        self.assertEqual({row['source_groups'] for row in report['primary_contrasts']}, {7, 8})
        self.assertTrue(all(row['task_mean_difference'] == 0.25 for row in report['primary_contrasts']))


if __name__ == '__main__':
    unittest.main()
