"""Changed two-state source/context and no-retry scheduling paths; zero tools."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import prepare_natural_terminal_baselines as prep
from scripts import run_natural_terminal_baselines as runner
from tests.test_train_span_proposer import TinyTokenizer


def contexts(root):
    data=[]
    for spec in prep.FIXED:
        points=[{'configuration_id':spec['circuit_id']+'_'+str(i),'parameters':{},
            'trusted_evaluator_files':{},'reference_id':'N'+str(i)} for i in range(9)]
        data.append({'collection':{'circuit_id':spec['circuit_id'],'source_pack':str(root/'source'),
            'source_files':['generator.py'],'trusted_bundle':str(root/'trusted'),
            'container_image':'fixture_digest','magic_runtime':str(root/'magic'),'pdk_revision':'fixture_pdk'},
            'registry':{'configurations':points},'initial_state':{'initial_state_id':spec['initial_state_id'],
            'parent_lineage':'compiler','base_source':{'g.py':'x=1\n'}}})
    return data


class NaturalTerminalBaselineTests(unittest.TestCase):
    def test_historical_completion_order_does_not_replace_frozen_domain_order(self):
        points=[{'configuration_id':'z'+str(i),'contract':{'task_id':'c01'},
            'parameters':{'circuit':{'circuit_id':'C01'}}} for i in range(9)]
        candidate={'visible_contract':{'task_id':'c01'},'outcomes':[
            {'configuration_id':'z'+str(i)} for i in [0,8,1,2,3,4,5,6,7]]}
        self.assertEqual(prep.ordered_domain({'configurations':points},candidate,'C01'),points)
        candidate['outcomes'][-1]['configuration_id']='z0'
        with self.assertRaises(ValueError):prep.ordered_domain({'configurations':points},candidate,'C01')

    def test_full_two_module_AST_duplicate_rejected_without_numeric_normalization(self):
        source={prep.SOURCES[0]:'x=1\n',prep.SOURCES[1]:'p=[1,2]\n'}
        existing={prep.program(source,source)}
        with self.assertRaisesRegex(ValueError,'distinct full AST'):prep.distinct_initials([source],existing)
        other={**source,prep.SOURCES[1]:'p=[1,3]\n'}
        prep.distinct_initials([other],existing)
        with self.assertRaises(ValueError):prep.distinct_initials([other,copy.deepcopy(other)],existing)

    def test_complete_readonly_caller_and_nine_points_identical_for_teacher_and_ordinary(self):
        source={prep.SOURCES[0]:'x=1\n',prep.SOURCES[1]:'p=[1,2]\n'}
        caller='result=build(pdk,circuit,sizing,mode="independent",name=name)\n'
        state={'initial_state_id':prep.FIXED[0]['initial_state_id'],'base_source':source}
        circuit={'devices':[{'name':'M1','kind':'nfet','nets':['D','G','S','B']}],'ports':['D','G','S','B']}
        contract={'task_id':'original_task','required_corners':['tt','ss','ff'],
            'objective':{'id':'area_min','direction':'min','unit':'um2'},'specifications':[],
            'nominal_operating_point':{'VDD':1.8},'analysis_contracts':{'op':{'kind':'op','columns':3}}}
        points=[{'configuration_id':'z'+str(i),'domain_role':'anchor' if i==0 else 'development',
            'contract':contract,'parameters':{'circuit':circuit,'sizing':{'M1':{'w':1+i/10,'l':.6,'nf':4}}}} for i in range(9)]
        collection={'documents':{'readonly_generator_py':caller}}
        ordinary,teacher,proof=prep.packet(collection,state,points,[{'actual_old_terminal_preview':True}],True)
        self.assertEqual(ordinary['task_packet']['allowed_paths'],prep.SOURCES)
        self.assertNotIn('generator.py',ordinary['task_packet']['allowed_paths'])
        self.assertEqual(teacher['task_packet']['documents']['readonly_generator_py'],caller)
        self.assertEqual(teacher['task_packet']['visible_sources'],source)
        self.assertEqual(len(teacher['task_packet']['contract']['geometry_domain']['points']),9)
        self.assertNotIn('actual_new_baseline',teacher['visible_history'][0]['observation'])
        self.assertTrue(prep.preflight(TinyTokenizer(),ordinary,teacher)['mapping']['teacher_and_original_map_to_identical_ordinary_request'])
        actual,_,_=prep.packet(collection,state,points,[],False)
        self.assertIn('actual_new_baseline',actual['visible_history'][0]['observation'])

    def test_reserve_before_first_fresh_call_new_context_unknown_stops_seventeen(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); output=root/'output'; plan={'output_root':str(output)}; calls=[]
            def execute(**args):
                state=json.loads((output/'state.json').read_text())
                self.assertEqual(state['cells'][0]['status'],'DISPATCH_RESERVED')
                self.assertEqual(args['context']['initial_state_id'],prep.FIXED[0]['initial_state_id'])
                self.assertEqual(args['context']['evidence_roles'],['trusted_evaluator_control'])
                self.assertEqual(args['phase'],'formal_train');calls.append(args)
                raise RuntimeError('Software fixture unknown; no model or EDA invoked')
            with patch.object(runner,'load',return_value=(plan,contexts(root))),patch.object(runner,'CandidateExecutor'):
                state=runner.run(root/'plan.json',execute=execute,gate=lambda *a:{'fixture':True})
                self.assertEqual(state['status'],'PAUSED_UNKNOWN_NO_RETRY');self.assertEqual(len(state['not_run']),17)
                runner.run(root/'plan.json',execute=execute,gate=lambda *a:self.fail('Unknown cannot dispatch again'))
            self.assertEqual(len(calls),1)
            cost=json.loads(next(output.glob('*/points/*/actual_cost.json')).read_text())
            self.assertEqual(cost['physical_point_calls'],1);self.assertFalse(cost['missing_CPU_values_are_zero'])

    def test_gate_deadline_and_orphan_keep_original_denominator_no_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);plan={'output_root':str(root/'output')}
            with patch.object(runner,'load',return_value=(plan,contexts(root))),patch.object(runner,'CandidateExecutor') as forbidden:
                state=runner.run(root/'plan.json',gate=lambda *a:None);forbidden.assert_not_called()
            self.assertEqual(len(state['not_run']),18);self.assertEqual(state['new_model_calls'],0)
        state={'status':'RUNNING_FORMAL_FRESH18','cells':[{'status':'DISPATCH_RESERVED'},{'status':'NOT_RUN'}]}
        runner.orphaned(state)
        self.assertEqual(state['status'],'PAUSED_UNKNOWN_NO_RETRY')
        self.assertEqual(state['cells'][0]['status'],'UNRESOLVED_RESERVED_NO_RETRY')

    def test_frozen_plan_load_rejects_old_context_identity_and_source_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); data=contexts(root);items=[]
            for d in data:
                folder=root/d['collection']['circuit_id'];folder.mkdir()
                for name,key in [('collection.json','collection'),('registry.json','registry'),('initial_state.json','initial_state')]:
                    prep.save(folder/name,d[key])
                items.append({'circuit_id':d['collection']['circuit_id'],'initial_state_id':d['initial_state']['initial_state_id'],
                    'folder':str(folder),'configuration_ids':[p['configuration_id'] for p in d['registry']['configurations']]})
            plan={'status':'FROZEN_TWO_NATURAL_TERMINAL_FRESH18_BASELINE_ONLY','workers':1,
                'maximum_new_full_points':18,'dispatch_horizon_seconds':14400,'phase':'formal_train',
                'new_model_calls':0,'automatic_retry':False,'CODE':[],'collections':items}
            prep.save(root/'plan.json',plan);prep.save(root/'freeze_identity.json',{})
            runner.load(root/'plan.json')
            changed=prep.read(root/'C01/initial_state.json');changed['initial_state_id']='borrowed_old_id'
            prep.save(root/'C01/initial_state.json',changed)
            with self.assertRaisesRegex(ValueError,'borrow an old context'):runner.load(root/'plan.json')


if __name__=='__main__':unittest.main()
