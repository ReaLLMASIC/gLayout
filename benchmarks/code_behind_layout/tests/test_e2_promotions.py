"""Software fixtures for promotion control flow, never physical measurements."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.e2_execution import Pool


class PromotionControlTests(unittest.TestCase):
    def pool(self, out, observations, existing=()):
        pool = Pool.__new__(Pool)
        pool.out = Path(out)
        pool.state = {"full_query_budget": 2, "full_evaluations": list(existing),
            "nominal_observations": {}, "promotion_decisions": []}
        pool.save = lambda: None
        def nominal(candidate):
            index = candidate["stream_index"]
            row = {"prediction": observations[index], "physical": {"run_directory": "software_fixture_only"}}
            pool.state["nominal_observations"][str(index)] = row
            return row
        pool.nominal = nominal
        def full(candidate):
            row = {"stream_index": candidate["stream_index"], "S2": False, "complete": True, "worst_ugb_Hz": None}
            pool.state["full_evaluations"].append(row)
            return row
        pool.full = full
        return pool

    @patch("scripts.e2_execution.archive", return_value={"software_fixture": True})
    def test_forced_full_is_not_pruned_by_a_verified_better_value(self, unused_archive):
        with tempfile.TemporaryDirectory() as out:
            pool = self.pool(out, {0: {"force_full": True, "upper_ugb_Hz": 1.},
                1: {"force_full": False, "upper_ugb_Hz": 100.}},
                existing=[{"stream_index": 9, "S2": True, "worst_ugb_Hz": 8.}])
            pool.calibrated_promotions([{"stream_index": 0}, {"stream_index": 1}])
            self.assertEqual(pool.state["full_evaluations"][-1]["stream_index"], 0)
            self.assertEqual(pool.state["unpromoted_due_to_budget_or_empirical_interval"], [1])
            self.assertFalse(pool.state["promotion_decisions"][0]["prediction_establishes_S2"])

    @patch("scripts.e2_execution.archive", return_value={"software_fixture": True})
    def test_missing_nominal_keeps_forced_evaluations_unresolved_at_budget(self, unused_archive):
        with tempfile.TemporaryDirectory() as out:
            pool = self.pool(out, {0: None, 1: None, 2: None})
            pool.calibrated_promotions([{"stream_index": i} for i in range(3)])
            self.assertEqual(len(pool.state["full_evaluations"]), 2)
            self.assertEqual(pool.state["forced_full_left_when_budget_exhausted"], 1)
            self.assertEqual(pool.state["unpromoted_due_to_budget_or_empirical_interval"], [2])
            self.assertTrue(all(row["S2"] is False for row in pool.state["full_evaluations"]))


if __name__ == "__main__":
    unittest.main()
