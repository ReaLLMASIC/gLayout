"""NF-only interface metadata fixtures, never physical or model evidence."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.train_nf_span_bundle import load_bundle,CONTEXTS,NF_VERSION,with_readonly_entrypoint
from src.train_span_proposer import MODE,ROLE,VERSION,teacher_request,mapping_proof
from tests.test_train_span_proposer import request
from scripts.freeze_nf_span_teacher import freeze,prepare


def fixture(root):
    contexts=[]
    for (pool,sid),circuit in zip(CONTEXTS,['c02','c07']):
        directory=root/sid;directory.mkdir();context={'parent_collection_id':pool,'initial_state_id':sid}
        for key in ['original_request','teacher_request','student_request','mapping_proof','initial_state','baseline_results','effective_registry','parent_collection','label_rule']:
            value={'software_fixture':True}
            if key in ['original_request','teacher_request','student_request']:
                value=with_readonly_entrypoint({'task_packet':{'allowed_paths':['textbook_sharing/layout.py','glayout/sharing/enumeration.py'],'documents':{}}},'# software fixture complete entrypoint\n')
            if key=='mapping_proof':value={'teacher_and_original_map_to_identical_ordinary_request':True}
            if key=='effective_registry':value={'configurations':[{'configuration_id':f'{circuit}_matched_nf_{a}_{b}'} for a in (4,8,12) for b in (4,8,12)]}
            file=directory/(key+'.json');file.write_text(json.dumps(value));context[key]=str(file.relative_to(root))
        file=directory/'readonly_generator.py';file.write_text('# software fixture complete entrypoint\n');context['readonly_entrypoint']=str(file.relative_to(root))
        contexts.append(context)
    manifest={'status':'DRAFT_NO_MODEL_CALLS','role':'train_proposal_collection','NF_bundle_version':NF_VERSION,
        'source_role':ROLE,'teacher_interface_version':VERSION,'contexts':contexts,'planned_proposals':16,
        'new_physical_domain_contexts':2,'new_initial_source_ASTs':0,'new_lineages':0,
        'rules_ready_path':'/software_fixture/rules_ready.json','joint_acceptance_plan':'/software_fixture/acceptance.json',
        'sampling':{'backend':'isolated_gpt_cli','model':'gpt-6.1-sol','reasoning_effort':'high','mode':MODE,
            'trials':list(range(1,9)),'seed':None,'proposal_workers':2,'max_new_tokens':3072,'max_context_tokens':16384,'timeout_seconds':240},
        'endpoint':'http://127.0.0.1:8116/spans/decision',
        'student_preselection':{'interface_version':'ordinary_policy_action_context_v2','max_new_tokens':1024,'max_context_tokens':16384,'stage':'before_physics'}}
    (root/'collection.json').write_text(json.dumps(manifest))
    audit={'phase':'formal_train','all_eighteen_points_complete':True,
        'records':[{'S2':True,'full_RC_device_graph_clean':True,'software_fixture_only':True} for _ in range(18)],
        'input_files_sha256':{}}
    (root/'baseline_audit.json').write_text(json.dumps(audit))
    flights=[{'actual_fresh_formal_feedback':True,'source_or_contract_truncated':False,
        'token_counts':{key:{'fits_with_full_output_reserve':True} for key in ['teacher','student']}} for _ in range(2)]
    (root/'teacher_context_preflight.json').write_text(json.dumps(flights))
    (root/'tokenizer_inventory.json').write_text('{}');(root/'hypothesis.json').write_text('{}')
    return manifest


def writable(root):
    for p in [root,*root.rglob('*')]:p.chmod(0o755 if p.is_dir() else 0o644)


class NFTeacherInterfaceTests(unittest.TestCase):
    def test_actual_readonly_entrypoint_is_preserved_for_teacher_and_student_without_changing_physics(self):
        original=request();packet=original['task_packet'];packet['allowed_paths']=['textbook_sharing/layout.py','glayout/sharing/enumeration.py']
        packet['visible_sources']={'textbook_sharing/layout.py':'a=1\n','glayout/sharing/enumeration.py':'plans=[1,2]\n'}
        before=copy.deepcopy(original);source='from library import build\nresult=build(mode="independent")\n'
        visible=with_readonly_entrypoint(original,source);proof=mapping_proof(visible,teacher_request(visible))
        self.assertEqual(original,before)
        for value in [visible,teacher_request(visible),proof['ordinary_request']]:
            self.assertEqual(value['task_packet']['documents']['readonly_execution_entrypoint']['source'],source)
            self.assertEqual(value['task_packet']['contract'],before['task_packet']['contract'])
            self.assertEqual(value['task_packet']['visible_sources'],before['task_packet']['visible_sources'])
            self.assertEqual(value['task_packet']['allowed_paths'],before['task_packet']['allowed_paths'])
            self.assertEqual(value['visible_history'],before['visible_history'])
            self.assertNotIn('generator.py',value['task_packet']['allowed_paths'])

    def test_exact_frozen_collector_imports_the_new_nf_loader_without_health_or_model_call(self):
        # Actual subprocess import/validate boundary; all metadata below remains a fixture.
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fixture(root);interface=root/'interface';(interface/'src').mkdir(parents=True)
            (interface/'src/__init__.py').write_text('')
            for name in ['train_span_proposer','student_interface','local_model_adapter','model_adapter',
                         'policy_state','training','measurement','report_parsers','spice_validation']:
                shutil.copyfile(Path('src')/(name+'.py'),interface/'src'/(name+'.py'))
            shutil.copyfile('src/train_nf_span_bundle.py',interface/'src/train_span_bundle.py')
            shutil.copyfile('scripts/collect_train_span_proposals.py',interface/'collector.py')
            try:
                freeze(root/'collection.json')
                result=subprocess.run([sys.executable,str(interface/'collector.py'),'--collection',str(root/'collection.json'),'--validate-only'],
                    cwd=d,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(json.loads(result.stdout)['status'],'VALIDATED_FROZEN_SPAN_COLLECTION_NO_REQUESTS')
            finally:writable(root)

    def test_separate_nf_freeze_keeps_18grid_and_immutable_files(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fixture(root)
            try:
                freeze(root/'collection.json');self.assertEqual(load_bundle(root/'collection.json')['new_initial_source_ASTs'],0)
                (root/'hypothesis.json').chmod(0o644)
                with self.assertRaisesRegex(ValueError,'writable'):load_bundle(root/'collection.json')
            finally:writable(root)

    def test_development_partial_or_selected_subset_never_loads_as_formal18(self):
        for mutation in ['phase','incomplete','subset','old_context','overflow']:
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as d:
                root=Path(d);m=fixture(root)
                if mutation in ['phase','incomplete']:
                    file=root/'baseline_audit.json';audit=json.loads(file.read_text())
                    if mutation=='phase':audit['phase']='development'
                    else:audit['records'][8]['S2']=False
                    file.write_text(json.dumps(audit))
                elif mutation=='subset':
                    file=root/m['contexts'][0]['effective_registry'];value=json.loads(file.read_text());value['configurations'].pop();file.write_text(json.dumps(value))
                elif mutation=='old_context':
                    m['contexts'][0]['initial_state_id']='planning_c01_program_038';(root/'collection.json').write_text(json.dumps(m))
                else:
                    file=root/'teacher_context_preflight.json';value=json.loads(file.read_text());value[0]['token_counts']['student']['fits_with_full_output_reserve']=False;file.write_text(json.dumps(value))
                try:
                    with self.assertRaises(ValueError):freeze(root/'collection.json')
                finally:writable(root)

    def test_audit_to_freeze_context_change_requires_real_reaudit(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);m=fixture(root);file=root/m['contexts'][0]['original_request']
            audit=json.loads((root/'baseline_audit.json').read_text());audit['input_files_sha256'][str(file.relative_to(root))]=hashlib.sha256(file.read_bytes()).hexdigest()
            (root/'baseline_audit.json').write_text(json.dumps(audit));file.write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError,'changed after'):freeze(root/'collection.json')
            self.assertEqual(json.loads((root/'collection.json').read_text())['status'],'DRAFT_NO_MODEL_CALLS')

    def test_inflight_formal_baseline_has_no_prepare_side_effect_or_tokenizer_load(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);actual=root/'actual';actual.mkdir();(actual/'completion.json').write_text(json.dumps({'status':'RUNNING_FORMAL_FRESH18'}))
            with patch('scripts.freeze_nf_span_teacher.load',return_value=({'output_root':str(actual)},[])):
                with self.assertRaisesRegex(ValueError,'complete fresh formal18'):prepare(root/'plan.json',root/'never_created',root/'tokenizer')
            self.assertFalse((root/'never_created').exists())


if __name__=='__main__':unittest.main()
