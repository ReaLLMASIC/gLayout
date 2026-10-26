"""Software-only evidence-state tests; none of these values are EDA results."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts.e3_fidelity_point import calibration, prediction_decision


class FidelityPointTests(unittest.TestCase):
    def test_empirical_screen_is_deferred_and_never_an_actual_counterexample(self):
        decision = prediction_decision({'complete':True,'operating_point_valid':True},
            {'force_full':False,'upper_ugb_Hz':10},
            {'specifications':[{'name':'ugb','unit':'Hz','min':20}]})
        self.assertEqual(decision['action'],'screened_deferred')
        self.assertFalse(decision['prediction_establishes_S2'])
        self.assertFalse(decision['is_actual_counterexample'])
        self.assertFalse(decision['verified_source_selection_eligible'])
        self.assertNotIn('checked',decision)

    def test_out_of_support_and_incomplete_nominal_cannot_screen(self):
        contract = {'specifications':[{'name':'ugb','unit':'Hz','min':20}]}
        prediction = {'force_full':True,'reason':'nominal_input_out_of_support','upper_ugb_Hz':10}
        decision = prediction_decision({'complete':True,'operating_point_valid':True},prediction,contract)
        self.assertEqual(decision['action'],'promote_full')
        self.assertTrue(decision['force_full'])
        decision = prediction_decision({'complete':False},None,contract)
        self.assertEqual(decision['action'],'promote_full')
        self.assertTrue(decision['force_full'])

    def test_ugb_interval_pass_does_not_assert_other_specs_or_full_objective(self):
        decision = prediction_decision({'complete':True,'operating_point_valid':True},
            {'force_full':False,'upper_ugb_Hz':30},
            {'specifications':[{'name':'ugb','unit':'Hz','min':20}, {'name':'pm','unit':'deg','min':60}]})
        self.assertEqual(decision['action'],'promote_full')
        self.assertFalse(decision['prediction_establishes_S2'])

    def test_calibration_rejects_unfrozen_formal_eval_source_and_missing_provenance(self):
        # This minimal object tests acceptance metadata only; it is never used
        # to produce a circuit prediction or saved as an experiment artifact.
        artifact = {'version':'nominal_to_worst_ugb_v1',
            'coefficient_fit_split':'train_only','residual_and_support_selection_split':'train_and_validation_only',
            'S2_is_established_by_prediction':False,'formal_calibration_freeze':False,
            'train_rows':[{'split':'train','raw_evidence':'software_fixture','actual_three_corner_AC_complete':True}],
            'validation_rows':[{'split':'validation','raw_evidence':'software_fixture','actual_three_corner_AC_complete':True}],
            'train_source_lineages':['train_fixture'],'validation_source_lineages':['validation_fixture']}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'metadata.json'
            path.write_text(json.dumps(artifact))
            calibration(path,{'parent_lineage':'eval_fixture'},False)
            with self.assertRaises(ValueError):calibration(path,{'parent_lineage':'eval_fixture'},True)
            with self.assertRaises(ValueError):calibration(path,{'parent_lineage':'train_fixture'},False)
            artifact['validation_rows'][0]['actual_three_corner_AC_complete']=False
            path.write_text(json.dumps(artifact))
            with self.assertRaises(ValueError):calibration(path,{'parent_lineage':'eval_fixture'},False)


if __name__=='__main__':
    unittest.main()
