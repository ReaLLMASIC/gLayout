import unittest
from src.fidelity_analysis import rank_diagnostics, finite_pool_selection


class FidelityAnalysisTests(unittest.TestCase):
    def test_reversals_and_ties_have_actual_pair_denominators(self):
        result = rank_diagnostics([1, 2, 3], [3, 2, 1], prediction_absolute_tolerance=0,
                                  actual_absolute_tolerance=0, relative_tolerance=0)
        self.assertEqual(result["spearman_exact_ties"], -1)
        self.assertEqual(result["kendall_tau_b_declared_ties"], -1)
        self.assertEqual(result["effective_pair_reversal_rate"], 1)
        tied = rank_diagnostics([1, 1, 1], [2, 2, 2], prediction_absolute_tolerance=0,
                                actual_absolute_tolerance=0, relative_tolerance=0)
        self.assertIsNone(tied["spearman_exact_ties"])
        self.assertIsNone(tied["effective_pair_reversal_rate"])
        self.assertEqual(tied["both_ties"], 3)

    def test_failed_delivery_stays_a_failure_without_fabricated_regret(self):
        pool = [{"candidate_id": "best", "feasible": True, "ugb": 10},
                {"candidate_id": "okay", "feasible": True, "ugb": 8},
                {"candidate_id": "unstable", "feasible": False, "ugb": 100}]
        failed = finite_pool_selection(pool, ["unstable"], objective="ugb", direction="max")
        self.assertFalse(failed["feasible_delivery"])
        self.assertIsNone(failed["absolute_regret"])
        result = finite_pool_selection(pool, ["unstable", "okay"], objective="ugb", direction="max")
        self.assertEqual(result["absolute_regret"], 2)
        self.assertEqual(result["full_evaluation_count"], 2)
