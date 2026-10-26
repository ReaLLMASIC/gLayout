"""Finite baseline scheduler/context fixtures only; no Docker, SPICE or model."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.prepare_nf_span_baselines import packet, preflight
from scripts import run_nf_span_baselines as runner
from tests.test_train_span_proposer import TinyTokenizer


def contexts(root):
    result = []
    for cid in ('C02','C07'):
        points = [{'configuration_id':cid+'_'+str(i), 'parameters':{}, 'trusted_evaluator_files':{}, 'reference_id':'N'+str(i)} for i in range(9)]
        result.append({'collection':{'circuit_id':cid,'source_pack':str(root/'source'),'source_files':['generator.py'],
            'trusted_bundle':str(root/'trusted'),'container_image':'fixture_digest','magic_runtime':str(root/'magic'),'pdk_revision':'fixture_pdk'},
            'registry':{'configurations':points},'initial_state':{'initial_state_id':cid+'_initial','parent_lineage':'compiler','base_source':{'g.py':'x=1\n'}}})
    return result


class NFSpanBaselineTests(unittest.TestCase):
    def test_reserve_before_one_real_call_unknown_stops_all_remaining_and_resume_never_retries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); output=root/'output'; plan={'output_root':str(output)}; data=contexts(root);calls=[]
            def execute(**args):
                state=json.loads((output/'state.json').read_text());self.assertEqual(state['cells'][0]['status'],'DISPATCH_RESERVED')
                self.assertEqual(args['phase'],'formal_train');self.assertEqual(args['context']['source_role'],'formal_train')
                self.assertEqual(args['context']['evidence_roles'],['trusted_evaluator_control']);calls.append(args)
                raise RuntimeError('Software fixture unknown; no physical tool invoked')
            with patch.object(runner,'load',return_value=(plan,data)),patch.object(runner,'CandidateExecutor'):
                state=runner.run(root/'plan.json',execute=execute,gate=lambda *a:{'software_fixture':True})
                self.assertEqual(state['status'],'PAUSED_UNKNOWN_NO_RETRY');self.assertEqual(len(state['not_run']),17)
                runner.run(root/'plan.json',execute=execute,gate=lambda *a:self.fail('No second dispatch permitted'))
            self.assertEqual(len(calls),1);self.assertEqual(len(state['cells']),18)
            cost=json.loads(next(output.glob('*/points/*/actual_cost.json')).read_text())
            self.assertFalse(cost['missing_CPU_values_are_zero']);self.assertEqual(cost['stages'],{})

    def test_expired_resource_gate_keeps_the_whole_eighteen_NOT_RUN(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);plan={'output_root':str(root/'output')}
            with patch.object(runner,'load',return_value=(plan,contexts(root))),patch.object(runner,'CandidateExecutor') as forbidden:
                state=runner.run(root/'plan.json',gate=lambda *a:None);forbidden.assert_not_called()
            self.assertEqual(len(state['not_run']),18);self.assertEqual(state['new_model_calls'],0)

    def test_unresolved_durable_reservation_remains_unknown(self):
        state={'status':'RUNNING_FORMAL_FRESH18','cells':[{'status':'DISPATCH_RESERVED'},{'status':'NOT_RUN'}]}
        runner.orphaned(state);self.assertEqual(state['status'],'PAUSED_UNKNOWN_NO_RETRY')
        self.assertEqual(state['cells'][0]['status'],'UNRESOLVED_RESERVED_NO_RETRY')

    def test_complete_nine_domain_and_full_sources_survive_preview_and_actual_mapping(self):
        state={'initial_state_id':'fixture','base_source':{'layout.py':'x=1\n','enum.py':'p=[1,2]\n'}}
        circuit={'circuit_id':'C02','name':'fixture','ports':['D','G','S','B'],'devices':[{'name':'M1','kind':'nfet','nets':['D','G','S','B']}]}
        contract={'task_id':'fixture_nf','objective':{'id':'area','unit':'um2','direction':'min'},'specifications':[],
            'required_corners':['tt','ss','ff'],'analysis_contracts':{'op':{'columns':3}},'nominal_operating_point':{'VDD':1.8},
            'power_definition':'fixture','numerical_controls':{'integration_method':'trap'}}
        points=[{'configuration_id':'nf'+str(i),'domain_role':'anchor' if i==4 else 'development','contract':copy.deepcopy(contract),
            'parameters':{'circuit':circuit,'sizing':{'M1':{'w':2+i/2,'l':.6,'nf':4+i}}}} for i in range(9)]
        collection={'collection_id':'fixture_nf','documents':{'patch_format':'ordinary fixture','complete_API':'unchanged'}}
        summaries=[{'configuration_id':p['configuration_id'],'software_fixture':True} for p in points]
        original,teacher,proof=packet(collection,state,points,summaries,True)
        self.assertEqual(teacher['task_packet']['visible_sources'],state['base_source'])
        self.assertEqual(len(teacher['task_packet']['contract']['geometry_domain']['points']),9)
        self.assertEqual(teacher['visible_history'][0]['observation']['qualification_preview'],summaries)
        self.assertNotIn('actual_new_baseline',teacher['visible_history'][0]['observation'])
        self.assertTrue(preflight(TinyTokenizer(),original,teacher)['mapping']['teacher_and_original_map_to_identical_ordinary_request'])
        actual,_,_=packet(collection,state,points,summaries,False)
        self.assertEqual(actual['visible_history'][0]['observation']['actual_new_baseline'],summaries)


if __name__=='__main__':unittest.main()
