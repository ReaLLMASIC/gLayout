"""Fixed-two source/producer/serial-consumer regressions, all software fixtures."""
import copy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from src import train_natural_terminal_span_bundle as bundle
from src.train_span_proposer import MODE,ROLE,VERSION,teacher_request,mapping_proof
from scripts import freeze_natural_terminal_span_teacher as freezer
from scripts import evaluate_natural_terminal_span_proposals as consumer
from tests.test_train_span_proposer import request


def writable(root):
    for p in [root,*root.rglob('*')]:p.chmod(0o755 if p.is_dir() else 0o644)


def fixture(root):
    contexts=[]
    for (pool,sid),points in zip(bundle.CONTEXTS,bundle.POINTS):
        folder=root/sid;folder.mkdir();entry={'parent_collection_id':pool,'initial_state_id':sid}
        original=request();original['task_packet']['allowed_paths']=bundle.MODULES
        source={bundle.MODULES[0]:'x=1\n',bundle.MODULES[1]:'plans=[1,2]\n'}
        caller='result=build(mode="independent") # SOFTWARE FIXTURE ONLY\n'
        original['task_packet']['visible_sources']=source
        original['task_packet']['documents']['readonly_generator_py']=caller
        teacher=teacher_request(original);proof=mapping_proof(original,teacher);student=proof.pop('ordinary_request')
        values={'original_request':original,'teacher_request':teacher,'student_request':student,'mapping_proof':proof,
            'initial_state':{'initial_state_id':sid,'base_source':source},'baseline_results':{'software_fixture':True},
            'effective_registry':{'configurations':[{'configuration_id':p} for p in points]},
            'parent_collection':{'software_fixture':True},'label_rule':{'software_fixture':True}}
        for key,value in values.items():
            path=folder/(key+'.json');path.write_text(json.dumps(value));entry[key]=str(path.relative_to(root))
        path=folder/'readonly_generator.py';path.write_text(caller);entry['readonly_entrypoint']=str(path.relative_to(root));contexts.append(entry)
    manifest={'status':'DRAFT_NO_MODEL_CALLS','role':'train_proposal_collection','bundle_version':bundle.BUNDLE_VERSION,
        'source_role':ROLE,'teacher_interface_version':VERSION,'contexts':contexts,'planned_proposals':16,
        'new_physical_domain_contexts':0,'new_initial_source_ASTs':2,'new_lineages':0,
        'sampling':{'backend':'isolated_gpt_cli','model':'gpt-6.1-sol','reasoning_effort':'high','mode':MODE,
            'trials':list(range(1,9)),'seed':None,'proposal_workers':2,'max_new_tokens':3072,'max_context_tokens':16384,'timeout_seconds':240},
        'endpoint':'http://127.0.0.1:8116/spans/decision','student_preselection':{
            'interface_version':'ordinary_policy_action_context_v2','max_new_tokens':1024,'max_context_tokens':16384,'stage':'before_physics'}}
    (root/'collection.json').write_text(json.dumps(manifest))
    (root/'baseline_audit.json').write_text(json.dumps({'phase':'formal_train','all_eighteen_points_complete':True,
        'records':[{'S2':True,'full_RC_device_graph_clean':True,'software_fixture_only':True} for _ in range(18)],'input_files_sha256':{}}))
    (root/'teacher_context_preflight.json').write_text(json.dumps([{'actual_fresh_formal_feedback':True,
        'source_or_contract_truncated':False,'token_counts':{k:{'fits_with_full_output_reserve':True} for k in ['teacher','student']}} for _ in range(2)]))
    (root/'tokenizer_inventory.json').write_text('{}');return manifest


class NaturalTerminalSpanTests(unittest.TestCase):
    def test_fixed_new_bundle_imports_in_real_collector_validate_only_without_http(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fixture(root);interface=root/'interface';(interface/'src').mkdir(parents=True)
            (interface/'src/__init__.py').write_text('')
            for name in ['train_span_proposer','student_interface','local_model_adapter','model_adapter',
                    'policy_state','training','measurement','report_parsers','spice_validation']:
                shutil.copyfile(Path('src')/(name+'.py'),interface/'src'/(name+'.py'))
            shutil.copyfile('src/train_natural_terminal_span_bundle.py',interface/'src/train_span_bundle.py')
            shutil.copyfile('scripts/collect_train_span_proposals.py',interface/'collector.py')
            try:
                freezer.freeze(root/'collection.json');manifest=bundle.load_bundle(root/'collection.json')
                self.assertEqual(manifest['new_initial_source_ASTs'],2)
                p=subprocess.run([sys.executable,str(interface/'collector.py'),'--collection',str(root/'collection.json'),'--validate-only'],
                    cwd=d,capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stderr)
                self.assertEqual(json.loads(p.stdout)['status'],'VALIDATED_FROZEN_SPAN_COLLECTION_NO_REQUESTS')
            finally:writable(root)

    def test_old_context_subset_incomplete_or_unequal_caller_cannot_freeze(self):
        for mutation in ['old_id','subset','incomplete','caller']:
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as d:
                root=Path(d);m=fixture(root)
                if mutation=='old_id':m['contexts'][0]['initial_state_id']='c01_observed_T0_seed_241_source_teacher_v2';(root/'collection.json').write_text(json.dumps(m))
                elif mutation=='subset':
                    p=root/m['contexts'][0]['effective_registry'];r=json.loads(p.read_text());r['configurations'].pop();p.write_text(json.dumps(r))
                elif mutation=='incomplete':
                    p=root/'baseline_audit.json';r=json.loads(p.read_text());r['records'][8]['S2']=False;p.write_text(json.dumps(r))
                else:
                    p=root/m['contexts'][0]['teacher_request'];r=json.loads(p.read_text());r['task_packet']['documents']['readonly_generator_py']='wrong caller';p.write_text(json.dumps(r))
                try:
                    with self.assertRaises(ValueError):freezer.freeze(root/'collection.json')
                finally:writable(root)

    def test_immutable_aliases_need_all78_bytes_and_same_split_without_mutating_original(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);registries=[]
            for cid in ['C01','C02']:
                source=root/cid;source.mkdir()
                for i in range(78):(source/('immutable'+str(i))).write_text('same '+str(i))
                registries.append({'lineages':[{'lineage_id':'textbook_universal_compiler_cropped','split':'train',
                    'frozen_source_pack':str(source),'frozen_source_files':['immutable'+str(i) for i in range(78)],'editable_paths':bundle.MODULES}]})
            before=copy.deepcopy(registries);result,proof=bundle.canonical_immutable_registries(registries)
            self.assertEqual(registries,before);self.assertEqual(result[0]['lineages'],result[1]['lineages'])
            self.assertEqual(proof['immutable_files_compared'],78)
            (root/'C02/immutable3').write_text('different helper')
            with self.assertRaisesRegex(ValueError,'not byte-equivalent'):bundle.canonical_immutable_registries(registries)

    def test_running_baselines_have_no_prepare_side_effect_or_tokenizer_load(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);actual=root/'actual';actual.mkdir();(actual/'completion.json').write_text(json.dumps({'status':'RUNNING_FORMAL_FRESH18'}))
            fake=types.SimpleNamespace(AutoTokenizer=types.SimpleNamespace(from_pretrained=lambda *a,**k:self.fail('No tokenizer load before complete eighteen')))
            with patch.dict(sys.modules,{'transformers':fake}),patch.object(freezer,'load',return_value=({'output_root':str(actual)},[])):
                with self.assertRaisesRegex(ValueError,'complete fresh formal18'):freezer.prepare(root/'plan',root/'never',root/'tokenizer')
            self.assertFalse((root/'never').exists())

    def test_late_eligible_model_return_is_drained_before_complete_and_reject_is_not_NOT_RUN(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);raw=root/'raw';raw.mkdir();output=root/'out';output.mkdir();executed=[]
            state={'status':'RUNNING','cells':[{'initial_state_id':'fixture','trial_id':1,'status':'PHYSICAL_PENDING'},
                {'initial_state_id':'fixture','trial_id':2,'status':'NOT_RUN'},{'initial_state_id':'fixture','trial_id':3,'status':'NOT_RUN'}]}
            def scan(*a):
                if (raw/'completion.json').exists():
                    if state['cells'][1]['status']=='NOT_RUN':state['cells'][1]['status']='PHYSICAL_PENDING'
                    state['cells'][2]['status']='STUDENT_BUDGET_REJECTED_BEFORE_PHYSICS'
            def execute(*a):
                active=[c for c in state['cells'] if c['status']=='PHYSICAL_PENDING'];self.assertEqual(len(active),1)
                executed.append(active[0]['trial_id']);active[0]['status']='ADMITTED_COMPLETE_DOMAIN';(raw/'completion.json').write_text('{}')
            with patch.object(consumer.span,'scan_returned',side_effect=scan),patch.object(consumer,'serial_physical_pass',side_effect=execute), \
                    patch.object(consumer,'derive_contexts'),patch.object(consumer.span,'raw_matrix',return_value={}):
                consumer.cycle({}, {'output_root':str(raw)},{},[],{},state,output,None,root,lambda:None)
                self.assertEqual(state['status'],'RUNNING');self.assertEqual(state['cells'][1]['status'],'PHYSICAL_PENDING')
                consumer.cycle({}, {'output_root':str(raw)},{},[],{},state,output,None,root,lambda:None)
            self.assertEqual(executed,[1,2]);self.assertEqual(state['status'],'COMPLETE')
            self.assertEqual(state['cells'][2]['status'],'STUDENT_BUDGET_REJECTED_BEFORE_PHYSICS')

    def test_serial_durable_reservation_unknown_stops_second_job_and_counts_no_retry(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'candidate.json').write_text(json.dumps({'candidate_id':'fixture','candidate_source':{},'outcomes':[]}))
            state={'status':'RUNNING','deadline_utc':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'resource_samples':[],
                'cells':[{'status':'PHYSICAL_PENDING','parent_collection':'fixture','candidate_file':'candidate.json',
                    'points':[{'configuration_id':'z1','status':'NOT_RUN'},{'configuration_id':'z2','status':'NOT_RUN'}]}]}
            calls=[]
            def execute(*a):
                saved=json.loads((root/'state.json').read_text());self.assertEqual(saved['cells'][0]['points'][0]['status'],'DISPATCH_RESERVED')
                calls.append(a);raise RuntimeError('Software fixture unknown before any tools')
            store=types.SimpleNamespace(_configuration=lambda *a:{'configuration_id':'z1'})
            with patch.object(consumer,'TrustedPhysicalStore',return_value=store):
                consumer.serial_physical_pass({}, {'fixture':{}},{},state,root,lambda:None,
                    sample=lambda:{'available_disk_GiB':5,'actual_busy_cores':1,'RAM_used_GiB':20},execute_point=execute)
            self.assertEqual(len(calls),1);self.assertEqual(state['status'],'PAUSED_UNKNOWN')
            self.assertEqual(state['cells'][0]['physical_point_reservations'],1)
            self.assertEqual(state['cells'][0]['points'][1]['status'],'NOT_RUN')

    def test_serial_s1_missing_RC_keeps_actual_audit_error_and_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);run=root/'actual_run';(run/'evidence').mkdir(parents=True)
            (run/'evidence/validation.json').write_text(json.dumps({'assessment':{'S1':True},
                'artifacts':{'pex':{'ports':['IN','OUT'],'top_cell':'fixture','netlist':'missing.spice'}}}))
            (root/'candidate.json').write_text(json.dumps({'candidate_id':'fixture','candidate_source':{},'outcomes':[]}))
            state={'status':'RUNNING','deadline_utc':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'resource_samples':[],
                'cells':[{'status':'PHYSICAL_PENDING','parent_collection':'fixture','candidate_file':'candidate.json',
                    'points':[{'configuration_id':'z','status':'NOT_RUN'}]}]}
            point={'parameters':{'circuit':{'ports':['IN','OUT']}}};store=types.SimpleNamespace(_configuration=lambda *a:point)
            def execute(*a):a[4].mkdir(parents=True);return {'run_directory':str(run)}
            with patch.object(consumer,'TrustedPhysicalStore',return_value=store):
                consumer.serial_physical_pass({}, {'fixture':{}},{},state,root,lambda:None,
                    sample=lambda:{'available_disk_GiB':5,'actual_busy_cores':1,'RAM_used_GiB':20},execute_point=execute)
            report=json.loads(next(root.glob('candidates/*/points/*/full_RC_device_graph_audit.json')).read_text())
            self.assertEqual(report['audit']['status'],'UNKNOWN_RC_GRAPH_QUARANTINE');self.assertIn('missing.spice',report['audit']['error'])
            self.assertEqual(state['status'],'PAUSED_UNKNOWN');self.assertFalse(report['simulation_netlist_simplified'])


if __name__=='__main__':unittest.main()
