import copy
import unittest
from src.promotion_calibration import fit_nominal_worst,NominalWorstCalibration


def row(i,split,nominal,worst):
    return {'parent_lineage':split+'_source','split':split,'measurement_id':str(i),
        'nominal_ugb_Hz':nominal,'worst_ugb_Hz':worst,'actual_three_corner_AC_complete':True,
        'raw_evidence':['fixture_not_research_measurement']}


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.registry={'lineages':[{'lineage_id':s+'_source','split':s} for s in ['train','validation']]}
        self.train=[row(i,'train',10+i,(10+i)*.8) for i in range(9)]
        self.validation=[row(i,'validation',11+i,(11+i)*.9) for i in range(9)]

    def test_validation_does_not_fit_coefficient(self):
        first=fit_nominal_worst(self.train,self.validation,self.registry)
        changed=copy.deepcopy(self.validation)
        for r in changed:r['worst_ugb_Hz']=r['nominal_ugb_Hz']*.5
        second=fit_nominal_worst(self.train,changed,self.registry)
        self.assertEqual(first['log_ratio_offset'],second['log_ratio_offset'])
        self.assertNotEqual(first['validation_radius_log'],second['validation_radius_log'])
        prediction=NominalWorstCalibration(first).predict(15)
        self.assertFalse(prediction['force_full'])
        self.assertLessEqual(prediction['lower_ugb_Hz'],13.5)
        self.assertGreaterEqual(prediction['upper_ugb_Hz'],13.5)

    def test_insufficient_validation_and_ood_force_real_full_evaluation(self):
        small=NominalWorstCalibration(fit_nominal_worst(self.train,self.validation[:1],self.registry)).predict(15)
        self.assertTrue(small['force_full']);self.assertEqual(small['lower_ugb_Hz'],0)
        complete=NominalWorstCalibration(fit_nominal_worst(self.train,self.validation,self.registry))
        ood=complete.predict(25)
        self.assertTrue(ood['force_full']);self.assertEqual(ood['upper_ugb_Hz'],25)

    def test_eval_lineage_cannot_be_used_even_with_forged_train_split(self):
        registry=copy.deepcopy(self.registry);registry['lineages'][0]['split']='test'
        with self.assertRaises(ValueError):fit_nominal_worst(self.train,self.validation,registry)

    def test_missing_actual_corner_evidence_and_duplicate_rejected(self):
        bad=copy.deepcopy(self.train);bad[0]['actual_three_corner_AC_complete']=False
        with self.assertRaises(ValueError):fit_nominal_worst(bad,self.validation,self.registry)
        with self.assertRaises(ValueError):fit_nominal_worst(self.train+[self.train[0]],self.validation,self.registry)
