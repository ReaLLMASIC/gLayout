from pathlib import Path
import tempfile
import unittest

from src.spice_validation import validate_analysis


class AnalysisCompletenessTests(unittest.TestCase):
    def evaluate(self,data,contract,log="ngspice-44.2 done\n"):
        with tempfile.TemporaryDirectory() as tmp:
            data_path=Path(tmp)/"data.dat";data_path.write_text("axis value\n"+data)
            log_path=Path(tmp)/"ngspice.log";log_path.write_text(log)
            return validate_analysis(data_path,log_path,contract)

    def test_partial_finite_ac_is_not_complete(self):
        contract={"kind":"ac","columns":2,"start":10,"end":1000,"points":3,"scale":"log"}
        self.assertTrue(self.evaluate("10 4\n100 2\n1000 1\n",contract)["complete"])
        self.assertFalse(self.evaluate("10 4\n100 2\n",contract)["complete"])

    def test_transient_must_finish_and_cover_measurement_windows(self):
        contract={"kind":"transient","columns":2,"start":0,"end":4e-6,"required_windows":[[1.8e-6,1.99e-6]]}
        self.assertFalse(self.evaluate("0 .9\n1e-6 .91\n",contract)["complete"])
        self.assertTrue(self.evaluate("0 .9\n1.9e-6 .91\n4e-6 .9\n",contract)["complete"])

    def test_dc_missing_middle_and_op_shape_are_rejected(self):
        contract={"kind":"dc","columns":2,"expected_axis":[.6,.7,.8]}
        self.assertFalse(self.evaluate(".6 .6\n.8 .8\n",contract)["complete"])
        self.assertFalse(self.evaluate("0 .9\n0 .9\n",{"kind":"op","columns":2})["complete"])

    def test_completed_gmin_fallback_is_allowed_but_abort_is_not(self):
        contract={"kind":"op","columns":2}
        self.assertTrue(self.evaluate("0 .9\n",contract,"Warning: dynamic gmin stepping failed\nNote: True gmin stepping completed\nngspice-44.2 done\n")["complete"])
        self.assertFalse(self.evaluate("0 .9\n",contract,"doAnalyses: timestep too small\nngspice-44.2 done\n")["complete"])


if __name__=="__main__":unittest.main()
