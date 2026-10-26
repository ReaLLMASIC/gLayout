"""Joint32 software controls: no models/PDK/physical labels or formal measurements."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts import evaluate_nf_joint_pool as joint
from src.train_nf_span_bundle import validate_rules_ready,with_readonly_entrypoint
from tests.test_train_span_proposer import request,TinyTokenizer


class NFJointPoolTests(unittest.TestCase):
    def test_rule_candidate_identity_is_never_reported_as_GPT(self):
        row={'candidate_id':'old','proposal_generation':{'proposer_cohort':'literal_span_GPT_eight_fresh_trials','teacher_mode':'literal_span','model':'GPT'}}
        cell={'initial_state_id':'fixture','producer':'rule','trial_id':2,'joint_trial_id':2,'rule_id':'gate_plan'}
        with patch.object(joint.span,'candidate_row',return_value=copy.deepcopy(row)):
            actual=joint.joint_candidate_row({}, {},{},cell,Path('/fixture/raw'))
        value=actual['proposal_generation']
        self.assertEqual(value['producer'],'rule');self.assertEqual(value['teacher_mode'],'train_collection_rules')
        self.assertEqual(value['proposer_cohort'],'original_eight_planning_rules_train_proposals')
        self.assertIsNone(value['model']);self.assertEqual(value['model_inferences'],0)
        self.assertEqual(value['joint_trial_id'],2);self.assertEqual(value['raw_directory'],'/fixture/raw')

    def test_rule_first_order_does_not_change_any_numeric_parent_threshold(self):
        parent={'status':'frozen','version':'software_fixture','hard_constraints_first':True,
            'quality_absolute_tolerance':1e-9,'quality_relative_tolerance':1e-3,'quality_minimum_relative_effect':.01}
        before=copy.deepcopy(parent);value=joint.joint_rule(parent)
        self.assertEqual(parent,before)
        for key in parent:
            if key!='version':self.assertEqual(value[key],parent[key])
        self.assertEqual(value['sft_selection']['actual_trial_field'],'joint_trial_id')
        self.assertEqual(value['sft_selection']['declared_trial_order'],list(range(1,17)))
        cells=joint.slots([{'initial_state_id':'a','parent_collection':'a'},{'initial_state_id':'b','parent_collection':'b'}])
        self.assertEqual(len(cells),32);self.assertEqual([c['producer'] for c in cells[:16]],['rule']*8+['GPT']*8)

    def test_no_physics_before_actual_rule_ready(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with patch.object(joint,'scan') as scan,patch.object(joint.physical,'physical_pass') as physical:
                with self.assertRaises(FileNotFoundError):joint.cycle({'proposal_collection_sha256':'x'}, {},{},[],{}, {'status':'RUNNING'},root,None,root,lambda:None)
                scan.assert_not_called();physical.assert_not_called()

    def test_rule_ready_receipt_binds_frozen_acceptance_and_exact_proposal(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'acceptance.json';value={'status':'frozen','role':joint.ROLE,'proposal_collection_sha256':'a'*64};p.write_text(json.dumps(value))
            ready={'status':'ALL16_ORIGINAL_RULE_ATTEMPTS_TERMINAL_BEFORE_GPT','attempts':16,'model_calls':0,'proposal_collection_sha256':'a'*64,
                'acceptance_path':str(p.resolve()),'acceptance_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
            validate_rules_ready(ready,'a'*64,p)
            for changed in [{**ready,'attempts':15},{**ready,'model_calls':1},{**ready,'proposal_collection_sha256':'b'*64}]:
                with self.assertRaises(ValueError):validate_rules_ready(changed,'a'*64,p)
            p.write_text(json.dumps({**value,'status':'DRAFT'}))
            with self.assertRaises(ValueError):validate_rules_ready(ready,'a'*64,p)

    def test_completion_during_physical_pass_rescans_both_pools_and_drains_late_eligible(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);raw=root/'raw';raw.mkdir();out=root/'out';out.mkdir();(out/'rules_ready.json').write_text('{}');events=[];executed=[]
            state={'status':'RUNNING','cells':[{'initial_state_id':'fixture','producer':'rule','trial_id':1,'status':'PHYSICAL_PENDING'},
                {'initial_state_id':'fixture','producer':'GPT','trial_id':1,'status':'NOT_RUN'},
                {'initial_state_id':'fixture','producer':'GPT','trial_id':2,'status':'NOT_RUN'}]}
            def scan(*args):
                events.append('scan')
                if (raw/'completion.json').exists():
                    if state['cells'][1]['status']=='NOT_RUN':state['cells'][1]['status']='PHYSICAL_PENDING'
                    state['cells'][2]['status']='STUDENT_BUDGET_REJECTED_BEFORE_PHYSICS'
            def physical(*args,**kwargs):
                events.append('physical');active=[c for c in state['cells'] if c['status']=='PHYSICAL_PENDING'];self.assertEqual(len(active),1)
                executed.append(active[0]['producer']);active[0]['status']='ADMITTED_COMPLETE_DOMAIN';(raw/'completion.json').write_text('{}')
            with patch.object(joint,'validate_rules_ready'),patch.object(joint,'scan',side_effect=scan),patch.object(joint.physical,'physical_pass',side_effect=physical),patch.object(joint,'derive'),patch.object(joint.span,'raw_matrix',return_value={}):
                joint.cycle({'proposal_collection_sha256':'fixture'},{'output_root':str(raw)},{},[],{},state,out,None,root,lambda:None)
                self.assertEqual(events,['scan','physical','scan']);self.assertEqual(state['cells'][1]['status'],'PHYSICAL_PENDING')
                self.assertEqual(state['cells'][2]['status'],'STUDENT_BUDGET_REJECTED_BEFORE_PHYSICS')
                joint.cycle({'proposal_collection_sha256':'fixture'},{'output_root':str(raw)},{},[],{},state,out,None,root,lambda:None)
            self.assertEqual(executed,['rule','GPT']);self.assertEqual(state['status'],'COMPLETE')

    def test_original_all_eight_rule_programs_materialize_twice_without_model_or_physics(self):
        code='''def device_specs(circuit, sizing):
    out=[]
    return out

def build(pdk, circuit, sizing, mode="independent"):
    nm={"independent":None}
    plan = nm.get(mode) or nm["independent"]
    row_specs=[];top="fixture"
    return assemble(pdk, row_specs, circuit.ports, name=top)
'''
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder=root/'acceptance';(folder/'interface/scripts').mkdir(parents=True);out=root/'out';out.mkdir()
            shutil.copyfile('scripts/corpus_rule_proposer.py',folder/'interface/scripts/corpus_rule_proposer.py')
            (folder/'acceptance.json').write_text(json.dumps({'proposal_collection_sha256':'f'*64}))
            contexts=[]
            for sid in ['fixture_a','fixture_b']:
                ordinary=request();ordinary['task_packet']['allowed_paths']=['textbook_sharing/layout.py','glayout/sharing/enumeration.py']
                base={'textbook_sharing/layout.py':code,'glayout/sharing/enumeration.py':'plans=[]\n'};ordinary['task_packet']['visible_sources']=base
                ordinary=with_readonly_entrypoint(ordinary,'# fixture readonly entrypoint\n')
                contexts.append({'initial_state_id':sid,'base_source':base,'original_request_value':ordinary})
            with patch.object(joint.physical,'physical_pass') as physical:
                result=joint.materialize_rules(folder,contexts,out,TinyTokenizer());physical.assert_not_called()
            self.assertEqual(result['attempts'],16);self.assertEqual(result['model_calls'],0)
            attempts=[json.loads(p.read_text()) for p in out.glob('raw_rules/*/*/attempt.json')]
            self.assertEqual(len(attempts),16);self.assertTrue(all(a['usage']['model_inferences']==0 for a in attempts))
            self.assertEqual(len(list(out.glob('raw_rules/*/*/compiled.json'))),16)


if __name__=='__main__':unittest.main()
