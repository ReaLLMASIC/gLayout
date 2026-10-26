"""Student targets match the ordinary policy protocol without changing physics."""
import copy
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest

from src.candidate_executor import apply_source_patch
from src.local_model_adapter import decision_prompt
from src.model_adapter import PACKET_FIELDS
from src.student_interface import (canonical_action,derive_matched_samples,encode_policy_action,
                                   mapped_record,student_request,validate_mapped_record,
                                   CONTEXT_VERSION,VERSION,interface_definition)
from scripts.train_policy import validate_matched_data
from scripts.collect_training import preselect_student_action


class CharacterTokenizer:
    eos_token_id=1000

    def __call__(self,text,**unused):return {'input_ids':list(text.encode())}

    def apply_chat_template(self,messages,**kwargs):
        self.messages=copy.deepcopy(messages);self.template_kwargs=kwargs
        return {'input_ids':[1001]+list(messages[0]['content'].encode())+[1002]}


class StudentInterfaceTests(unittest.TestCase):
    path='textbook_sharing/layout.py'
    patch='--- a/textbook_sharing/layout.py\n+++ b/textbook_sharing/layout.py\n@@ -1 +1 @@\n-value=1\n+value=2\n'

    def context(self):
        return {'base_source':{self.path:'value=1\n'},'visible_contract':{
            'task_id':'train_collection_c08','goal':'Return source_text for the entire module.',
            'contract':{'objective':{'id':'c08_area_min','metric':'area','unit':'um2','direction':'min'},
                'constraints':[{'name':'gain','unit':'dB','min':25}],
                'geometry_domain':{'M1':{'w':4.0,'l':.3,'nf':8}},'required_corners':['tt','ss','ff']},
            'allowed_paths':[self.path],'documents':{'patch_format':'Return complete source_text','frozen_api':'build remains complete'},
            'visible_configurations':['anchor','dev1'],'budget':{'decisions':1,'maximum_output_tokens':3072},
            'editable_paths':[self.path]},'visible_feedback':[{'observation':{'S2':True,'area':88.12,'console_excerpt':'actual feedback'}}]}

    def row(self,method='T1'):
        return {'sample_id':method+':state','initial_state_id':'state','parent_lineage':'train_compiler',
                'context':json.dumps(self.context()),'patch':self.patch,'trusted_evidence_ids':['actual_raw_id_fixture']}

    def test_prompt_and_mask_equal_ordinary_single_user_serving(self):
        tokenizer=CharacterTokenizer();request=student_request(json.dumps(self.context()))
        encoded=encode_policy_action(tokenizer,request,self.patch)
        self.assertEqual(tokenizer.messages,[{'role':'user','content':decision_prompt(request)}])
        self.assertEqual(tokenizer.template_kwargs,{'tokenize':True,'add_generation_prompt':True})
        self.assertEqual(encoded.labels[:encoded.prompt_tokens],[-100]*encoded.prompt_tokens)
        self.assertEqual(encoded.labels[encoded.prompt_tokens:],encoded.input_ids[encoded.prompt_tokens:])
        self.assertEqual(encoded.input_ids[-1],tokenizer.eos_token_id)
        text=bytes(encoded.input_ids[encoded.prompt_tokens:-1]).decode()
        self.assertEqual(json.loads(text)['patch'],self.patch)

    def test_mapping_keeps_complete_source_physical_contract_and_feedback(self):
        original=self.context();saved=copy.deepcopy(original);request=student_request(original)
        self.assertEqual(set(request['task_packet']),PACKET_FIELDS)
        self.assertEqual(request['task_packet']['visible_sources'],original['base_source'])
        self.assertEqual(json.dumps(request['task_packet']['contract']),json.dumps(original['visible_contract']['contract']))
        self.assertEqual(request['visible_history'],original['visible_feedback'])
        self.assertEqual(request['task_packet']['documents']['frozen_api'],original['visible_contract']['documents']['frozen_api'])
        self.assertEqual(original,saved)
        self.assertEqual(request['task_packet']['budget']['maximum_output_tokens'],1024)

    def test_canonical_action_keeps_real_diff_and_irrelevant_fields_empty(self):
        request=student_request(self.context());action=json.loads(canonical_action(self.patch,request))
        self.assertEqual(action,{'action':'propose_patch','path':'','patch':self.patch,'configuration_ids':[],'fidelity':'','summary':''})
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/self.path;target.parent.mkdir();target.write_text('value=1\n')
            apply_source_patch(root,action['patch'],[self.path]);self.assertEqual(target.read_text(),'value=2\n')

    def test_point_family_ordinary_inputs_are_identical_and_raw_stays_intact(self):
        groups={'T1':[self.row('T1')],'T2':[self.row('T2')],'T3':[],'T4':[]};before=copy.deepcopy(groups)
        derived,report=derive_matched_samples(groups,CharacterTokenizer())
        self.assertEqual(derived['T1'][0]['student_request'],derived['T2'][0]['student_request'])
        self.assertEqual(groups,before);self.assertEqual(validate_mapped_record(derived['T1'][0]),groups['T1'][0])
        self.assertEqual(report['usable_samples_by_method'],{'T1':1,'T2':1,'T3':0,'T4':0})

    def test_one_oversize_sft_target_excludes_the_whole_matched_state(self):
        first=self.row('T1');second=self.row('T2');second['patch']=self.patch+'+'+'x'*1200+'\n'
        derived,report=derive_matched_samples({'T1':[first],'T2':[second],'T3':[],'T4':[]},CharacterTokenizer())
        self.assertEqual(len(derived['T1']),0);self.assertEqual(len(derived['T2']),0)
        self.assertEqual(report['paired_exclusions'][0]['failures'][0]['method'],'T2')
        self.assertEqual(report['paired_exclusions'][0]['failures'][0]['reason'],'ordinary_action_output_budget')

    def test_oversize_dpo_action_excludes_both_labelings(self):
        long=self.patch+'+'+'x'*1200+'\n';first=self.row('T3');first.pop('patch');first.update(pair_id='pair',chosen=self.patch,rejected=long)
        second={**first,'sample_id':'T4:state','chosen':long,'rejected':self.patch}
        derived,report=derive_matched_samples({'T1':[],'T2':[],'T3':[first],'T4':[second]},CharacterTokenizer())
        self.assertEqual(len(derived['T3']),0);self.assertEqual(len(derived['T4']),0)
        self.assertEqual(report['paired_exclusions'][0]['pair_id'],'pair')

    def test_derived_target_cannot_change_the_admitted_raw_patch(self):
        record=mapped_record(self.row(),CharacterTokenizer())
        record['target_actions']['patch']=record['target_actions']['patch'].replace('value=2','value=3')
        with self.assertRaisesRegex(ValueError,'admitted raw patch'):validate_mapped_record(record)

    def test_training_reader_consumes_matched_derived_action_records(self):
        first=self.row('T3');first.pop('patch');first.update(pair_id='pair',chosen=self.patch,rejected=self.patch.replace('value=2','value=3'))
        second={**first,'sample_id':'T4:state','chosen':first['rejected'],'rejected':first['chosen']}
        groups={'T1':[self.row('T1')],'T2':[self.row('T2')],'T3':[first],'T4':[second]}
        datasets,_=derive_matched_samples(groups,CharacterTokenizer())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);manifest={'methods':{}}
            for method,rows in datasets.items():
                (root/(method+'.jsonl')).write_text(''.join(json.dumps(row)+'\n' for row in rows))
                manifest['methods'][method]={'samples':method+'.jsonl'}
            actual=validate_matched_data(manifest,root)
            self.assertEqual({key:len(rows) for key,rows in actual.items()},{'T1':1,'T2':1,'T3':1,'T4':1})

    def test_new_teacher_preselection_keeps_oversize_patch_unchanged(self):
        manifest={'student_preselection':{'max_context_tokens':8192,'max_new_tokens':1024}}
        context=self.context();task={key:value for key,value in context['visible_contract'].items() if key in PACKET_FIELDS}
        task['visible_sources']=context['base_source'];large=self.patch+'+'+'x'*1200+'\n'
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)
            result=preselect_student_action(manifest,task,context['visible_feedback'],large,'train_collection_c08',out,CharacterTokenizer())
            self.assertFalse(result['accepted']);self.assertEqual(result['reason'],'ordinary_action_output_budget')
            self.assertEqual(json.loads((out/'student_target_action.json').read_text())['patch'],large)

    def test_minimal_teacher_field_becomes_ordinary_diff_without_changing_physics(self):
        context=self.context();context['visible_contract']['documents']['source_edit_policy']='Keep every unaffected line. The entire returned module is mechanically differenced.'
        saved=copy.deepcopy(context);request=student_request(context)
        policy=request['task_packet']['documents']['source_edit_policy']
        self.assertIn('minimal unified diff',policy);self.assertNotIn('returned module',policy)
        self.assertEqual(request['task_packet']['visible_sources'],saved['base_source'])
        self.assertEqual(request['task_packet']['contract'],saved['visible_contract']['contract'])
        self.assertEqual(request['visible_history'],saved['visible_feedback']);self.assertEqual(context,saved)

    def test_prompt_bytes_are_independent_of_process_hash_seed(self):
        code='import json,sys;from src.student_interface import student_request;from src.local_model_adapter import decision_prompt;print(decision_prompt(student_request(json.load(sys.stdin))))'
        outputs=[subprocess.check_output([sys.executable,'-c',code],input=json.dumps(self.context()).encode(),
            cwd=Path(__file__).resolve().parents[1],env={**os.environ,'PYTHONHASHSEED':seed,'PYTHONDONTWRITEBYTECODE':'1'}) for seed in ['1','923']]
        self.assertEqual(outputs[0],outputs[1])

    def test_larger_context_requires_new_explicit_interface(self):
        with self.assertRaisesRegex(ValueError,'context window'):interface_definition(VERSION,12288)
        for length in [12288,16384]:
            definition=interface_definition(CONTEXT_VERSION,length)
            self.assertEqual(definition['history_policy'],'current_source_and_feedback_v1')
            record=mapped_record(self.row(),CharacterTokenizer(),length,interface_version=CONTEXT_VERSION)
            self.assertEqual(record['student_request']['task_packet']['budget']['maximum_context_tokens'],length)
            self.assertEqual(validate_mapped_record(record),self.row())
        with self.assertRaises(ValueError):interface_definition(CONTEXT_VERSION,8192)

    def test_context_v2_retains_physical_feedback_and_complete_current_source(self):
        context=self.context();context['visible_feedback'].append({'action':{'action':'propose_patch','patch':self.patch},
            'observation':{'S2':False,'corners':{'ss':{'gain':{'value':22.126,'unit':'dB'}}}}})
        old=student_request(context);request=student_request(context,CONTEXT_VERSION,12288)
        self.assertIn('patch',old['visible_history'][-1]['action'])
        self.assertNotIn('maximum_context_tokens',old['task_packet']['budget'])
        self.assertNotIn('patch',request['visible_history'][-1]['action'])
        self.assertTrue(request['visible_history'][-1]['action']['raw_patch_retained_in_trial_log'])
        self.assertEqual(request['visible_history'][-1]['observation'],context['visible_feedback'][-1]['observation'])
        self.assertEqual(request['task_packet']['contract'],old['task_packet']['contract'])
        self.assertEqual(request['task_packet']['visible_sources'],context['base_source'])
        self.assertEqual(json.dumps(old),json.dumps(student_request(context,VERSION,8192)))

    def test_context_v2_matched_report_and_record_budget_binding(self):
        groups={'T1':[self.row('T1')],'T2':[self.row('T2')],'T3':[],'T4':[]}
        data,report=derive_matched_samples(groups,CharacterTokenizer(),12288,interface_version=CONTEXT_VERSION)
        self.assertEqual(report['history_policy'],'current_source_and_feedback_v1')
        self.assertEqual(data['T1'][0]['student_request'],data['T2'][0]['student_request'])
        altered=copy.deepcopy(data['T1'][0]);altered['student_request']['task_packet']['budget']['maximum_context_tokens']=8192
        with self.assertRaises(ValueError):validate_mapped_record(altered)


if __name__=='__main__':unittest.main()
