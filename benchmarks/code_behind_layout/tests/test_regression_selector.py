import unittest
from src.regression_selector import RegressionSelector


class VisibleSelectionTests(unittest.TestCase):
    features={"low":{"width":1},"middle":{"width":2},"high":{"width":3}}
    bounds={"width":(1,3)}

    def test_anchor_only_does_not_spend_regression_budget(self):
        self.assertIsNone(RegressionSelector("A",self.features,self.bounds,41).choose([]))

    def test_random_is_seeded_and_cannot_request_a_tested_point(self):
        a=RegressionSelector("R",self.features,self.bounds,41)
        b=RegressionSelector("R",self.features,self.bounds,41)
        self.assertEqual(a.choose([]),b.choose([]))
        self.assertEqual(a.choose(["low","middle"]),"high")

    def test_boundary_coverage_selects_opposite_edge_before_interior(self):
        selector=RegressionSelector("B",self.features,self.bounds,41)
        first=selector.choose([])
        self.assertIn(first,["low","high"])
        second=selector.choose([first])
        self.assertEqual({first,second},{"low","high"})

    def test_contract_risk_requires_predictions_and_frozen_weights(self):
        weights={"failure_probability":1,"uncertainty":.2,"changed_call_coverage":.2,"low_margin":.2}
        selector=RegressionSelector("C",self.features,self.bounds,41,weights)
        with self.assertRaises(ValueError):selector.choose([])
        predictions={name:{key:0.1 for key in weights} for name in self.features}
        predictions["middle"]["failure_probability"]=.9
        self.assertEqual(selector.choose([],predictions),"middle")
        with self.assertRaises(ValueError):selector.choose(["hidden"],predictions)


if __name__=="__main__":unittest.main()
