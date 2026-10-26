import unittest
import copy

from src.e3_risk_model import DISABLED, STATUS_PREDICATES, VERSION, VisibleMarginDistanceRule, normalized_margin
from scripts.build_e3_risk_model import ranking


def artifact():
    return {'version':VERSION,'status':'TRANSPARENT_HEURISTIC_NOT_CALIBRATED_FAILURE_MODEL',
        'evaluation_outcomes_used':False,'disabled_channels':list(DISABLED),
        'continuous_margin_excluded_status_predicates':list(STATUS_PREDICATES)}


def contract():
    return {'required_corners':['tt','ss'],
        'specifications':[{'name':'gain','unit':'1','min':2}, {'name':'power','unit':'W','max':0.1}]}


def observation(gain=2.4):
    return {'corners':{corner:{'converged':True,'operating_point_valid':True,
        'metrics':{'gain':{'value':gain,'unit':'1'},'power':{'value':0.04,'unit':'W'}}}
        for corner in ['tt','ss']}}


def state():
    return {'features':{'a':{'w':1},'b':{'w':2},'c':{'w':3}},'bounds':{'w':[1,3]},
        'weights':{'failure_probability':0,'uncertainty':1,'changed_call_coverage':0,'low_margin':1},
        'revision':0,'revisions':[{'revision':0,'results':{'a':{
            'checked':{'execution_integrity':'valid','S1':True},'physical_feedback':observation()}}}],
        'contract':contract()}


class RuleTests(unittest.TestCase):
    def test_ota_boolean_predicate_is_gate_not_continuous_margin(self):
        definition={'required_corners':['tt','ss','ff'],'specifications':[
            {'name':'original_development_predicate','unit':'1','min':1,'max':1},
            {'name':'gain_dB','unit':'dB','min':30}, {'name':'UGB_Hz','unit':'Hz','min':8000000}]}
        raw={'corners':{corner:{'converged':True,'operating_point_valid':True,'metrics':{
            'original_development_predicate':{'unit':'1','value':1},
            'gain_dB':{'unit':'dB','value':36},'UGB_Hz':{'unit':'Hz','value':10000000}}} for corner in definition['required_corners']}}
        self.assertAlmostEqual(normalized_margin(definition,raw),0.2)
        only_predicate={**definition,'specifications':definition['specifications'][:1]}
        self.assertIsNone(normalized_margin(only_predicate,raw))
        value=state();value['contract']=only_predicate;value['revisions'][0]['results']['a']['physical_feedback']=raw
        self.assertTrue(all(row['low_margin']==0 for row in VisibleMarginDistanceRule(artifact()).predict({},value,value['features']).values()))
        del raw['corners']['ss']['metrics']['original_development_predicate']
        self.assertIsNone(normalized_margin(definition,raw))

    def test_only_the_explicit_status_name_is_excluded(self):
        definition={'required_corners':['tt'],'specifications':[{'name':'held_voltage','unit':'V','min':1,'max':1}]}
        raw={'corners':{'tt':{'converged':True,'operating_point_valid':True,'metrics':{'held_voltage':{'unit':'V','value':1}}}}}
        self.assertEqual(normalized_margin(definition,raw),0)
        definition['specifications'][0]={'name':'original_development_predicate','unit':'1','min':1,'max':1}
        raw['corners']['tt']['metrics']={'original_development_predicate':{'unit':'1','value':0}}
        self.assertIsNone(normalized_margin(definition,raw))

    def test_actual_limits_and_complete_corners_required(self):
        self.assertAlmostEqual(normalized_margin(contract(),observation()),0.2)
        self.assertAlmostEqual(normalized_margin(contract(),observation(1.8)),-0.1)
        raw=observation();del raw['corners']['ss']
        self.assertIsNone(normalized_margin(contract(),raw))
        raw=observation();raw['corners']['ss']['metrics']['gain']['unit']='dB'
        self.assertIsNone(normalized_margin(contract(),raw))

    def test_heuristic_signals_do_not_claim_probabilities(self):
        value=state();features={k:dict(v) for k,v in value['features'].items()}
        result=VisibleMarginDistanceRule(artifact()).predict({'layout.py':'pass\n'},value,features)
        self.assertEqual(result['a']['uncertainty'],0)
        self.assertEqual(result['c']['uncertainty'],1)
        self.assertAlmostEqual(result['b']['low_margin'],1/1.2)
        for row in result.values():
            self.assertEqual(row['failure_probability'],0)
            self.assertEqual(row['changed_call_coverage'],0)
        del value['contract']
        result=VisibleMarginDistanceRule(artifact()).predict({},value,features)
        self.assertTrue(all(row['low_margin']==0 for row in result.values()))

    def test_unavailable_channels_cannot_receive_weights(self):
        value=state();value['weights']['failure_probability']=0.5
        with self.assertRaisesRegex(ValueError,'zero weight'):
            VisibleMarginDistanceRule(artifact()).predict({},value,value['features'])

    def test_each_public_point_uses_its_own_contract(self):
        value=state();value['contracts_by_configuration']={name:copy.deepcopy(contract()) for name in value['features']}
        value['contracts_by_configuration']['a']['specifications'][0]['min']=4
        result=VisibleMarginDistanceRule(artifact()).predict({},value,value['features'])
        self.assertEqual(result['b']['low_margin'],1)
        value['contracts_by_configuration']['hidden']=contract()
        with self.assertRaisesRegex(ValueError,'exactly the public'):
            VisibleMarginDistanceRule(artifact()).predict({},value,value['features'])

    def test_hidden_feedback_rejected_and_edits_reset_novelty(self):
        value=state();value['revisions'][0]['results']['hidden']={'checked':{}}
        with self.assertRaisesRegex(ValueError,'Hidden'):
            VisibleMarginDistanceRule(artifact()).predict({},value,value['features'])
        value=state();value['revision']=1;value['revisions'].append({'revision':1,'results':{}})
        result=VisibleMarginDistanceRule(artifact()).predict({},value,value['features'])
        self.assertTrue(all(row['uncertainty']==1 for row in result.values()))

    def test_positive_ratio_comparison_is_not_failure_validation(self):
        rows=[{'nominal_ugb_Hz':1,'worst_ugb_Hz':3}, {'nominal_ugb_Hz':2,'worst_ugb_Hz':2}]
        value=ranking(rows,[-0.3,-0.1])
        self.assertEqual(value['nominal_order_reversals'],1)
        self.assertEqual(value['bootstrap_positive_ratio_ensemble_order_reversals'],1)
        self.assertIsNone(value['configuration_failure_metrics'])


if __name__=='__main__':unittest.main()
