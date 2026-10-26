"""Software classification fixtures; these are not physical measurements."""
import unittest
from scripts.e3_summarize_qualification import classify


class QualificationSummaryTests(unittest.TestCase):
    def test_unknown_does_not_become_failure(self):
        record = {"checked": {"execution_integrity": "incomplete", "S1": False, "S2": False}}
        self.assertFalse(classify(record, None, {"direction": "min"})["qualifies_shortfall"])

    def test_area_needs_feasible_initial_and_witness(self):
        initial = {"checked": {"execution_integrity": "valid", "S1": True, "S2": True}, "objective": 120.}
        base = {"checked": {"execution_integrity": "valid", "S2": True}, "objective": 100.}
        self.assertTrue(classify(initial, base, {"direction": "min"})["qualifies_shortfall"])
        base["checked"]["S2"] = False
        self.assertFalse(classify(initial, base, {"direction": "min"})["qualifies_shortfall"])

    def test_candidate_correctness_failure_requires_feasible_witness(self):
        initial = {"checked": {"execution_integrity": "valid", "failure_class": "candidate", "S1": False, "S2": False}}
        base = {"checked": {"execution_integrity": "valid", "S2": True}, "objective": 100.}
        self.assertTrue(classify(initial, base, {"direction": "min"})["qualifies_shortfall"])
        initial["checked"]["failure_class"] = "unknown"
        self.assertFalse(classify(initial, base, {"direction": "min"})["qualifies_shortfall"])


if __name__ == "__main__":
    unittest.main()
