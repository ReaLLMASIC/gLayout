"""New16k collection controls only; fixtures are not model/physical outcomes."""
import json
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.collect_planning_trajectories import load,packet,preselect_student_action,sample
from scripts.gpt_teacher_transport_gate import upstream_for
from scripts.train_collection_queue import PLANNING_COLLECTIONS,planning_workers,run as run_queue
from scripts.freeze_planning_trajectory_batch import freeze
from scripts.prepare_planning_trajectory_batch import ASSIGNMENTS
from tests.test_student_interface import CharacterTokenizer


class PlanningInterfaceTests(unittest.TestCase):
    def test_exited_C05_predecessor_pauses_without_wait_or_future_T0_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('c05_minimal_gpt_teacher_v1','c05_collection_v1'):
                (root/'runs/train_collection'/name).mkdir(parents=True)
            args=SimpleNamespace(include_action_teacher=True,include_c07_action=False,overlap_teacher_stages=False,
                include_natural_c05_action=False,include_trajectory_c02=False,include_planning_trajectories=False,max_hours=8)
            with patch('scripts.train_collection_queue.ROOT',root),patch('scripts.train_collection_queue.load'),\
                 patch('scripts.train_collection_queue.existing_collector',return_value=None),\
                 patch('scripts.train_collection_queue.resource_sample') as resources,\
                 patch('scripts.train_collection_queue.subprocess.Popen') as launch,redirect_stdout(io.StringIO()):
                run_queue(args);resources.assert_not_called();launch.assert_not_called()
            records=list((root/'runs/train_collection_queues').glob('*/queue.json'));self.assertEqual(len(records),1)
            state=json.loads(records[0].read_text());self.assertEqual(state['status'],'PAUSED')
            self.assertTrue(any(e['lane']=='T0' and e['event']=='LANE_PAUSED_UNKNOWN' for e in state['events']))
            self.assertFalse((root/'runs/train_collection/c05_collection_v1/completion.json').exists())

    def test_old_routes_and_disabled_new_route_remain_unchanged(self):
        self.assertEqual(upstream_for(8116,'/decision',False),(8116,'/decision'))
        self.assertEqual(upstream_for(8116,'/decision',True),(8116,'/decision'))
        self.assertEqual(upstream_for(8115,'/decision',True),(8115,'/decision'))
        self.assertEqual(upstream_for(8116,'/context16384/decision',False),(8116,'/context16384/decision'))
        self.assertEqual(upstream_for(8116,'/context16384/decision',True),(8118,'/decision'))
        self.assertEqual(upstream_for(8116,'/context16384/health',True),(8118,'/health'))
        self.assertEqual(upstream_for(8115,'/context16384/decision',True),(8115,'/context16384/decision'))
        self.assertEqual(upstream_for(8116,'/context12288/decision',True),(8116,'/context12288/decision'))

    def test_batch_workers_count_actual_owners_and_reject_two_worker_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in PLANNING_COLLECTIONS[:2]:
                path=root/'runtime/train_collections'/name;path.mkdir(parents=True)
                (path/'collection.json').write_text(json.dumps({'physical':{'workers':1}}))
            owners={name:{'pid':i+1,'argv':['fixture']} for i,name in enumerate(PLANNING_COLLECTIONS[:2])}
            with patch('scripts.train_collection_queue.existing_collector',side_effect=lambda root,name:owners.get(name)):
                self.assertEqual(len(planning_workers(root)),2)
                (root/'runtime/train_collections'/PLANNING_COLLECTIONS[0]/'collection.json').write_text(json.dumps({'physical':{'workers':2}}))
                with self.assertRaisesRegex(ValueError,'one physical worker'):planning_workers(root)

    def test_new_collector_cannot_be_used_as_an_old8k_interface(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'freeze_identity.json').write_text('{}')
            registry={'status':'frozen','lineages':[{'lineage_id':'train','split':'train','topology_family':'compiler'}]}
            (root/'registry.json').write_text(json.dumps(registry));(root/'states.jsonl').write_text(json.dumps({'initial_state_id':'s'}))
            manifest={'status':'frozen','role':'train_collection','registry_path':str(root/'registry.json'),'initial_states_path':str(root/'states.jsonl'),
                'sampling':{'mode':'train_collection_action_gpt','backend':'isolated_gpt_cli','model':'gpt-6.1-sol','reasoning_effort':'high',
                    'trials':list(range(1,9)),'proposal_workers':2,'seed':None,'max_new_tokens':1024,'max_context_tokens':8192,'timeout_seconds':240}}
            path=root/'collection.json';path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'budgets changed'):load(path)
            manifest['sampling']['mode']='train_collection_source';path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'ordinary ACTION proposals only'):load(path)

    def test_shorter_draft_cannot_freeze_even_with_six_programs_and_twelve_contexts(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);contexts=[{'program_id':p,'circuit_id':c,
                'context_preflight':{'16384':{'fits_with_full_output_reserve':True}}} for p,cs in ASSIGNMENTS.items() for c in cs]
            plan={'status':'DRAFT_FIXED_BATCH_NO_MODEL_OR_PHYSICAL_CALLS','programs':6,'contexts':contexts,
                'planned_proposals':96,'model_calls':0,'physical_calls':0,'sampling':{'max_context_tokens':12288,'max_new_tokens':1024}}
            path=root/'plan.json';path.write_text(json.dumps(plan))
            with self.assertRaisesRegex(ValueError,'approved fixed'):freeze(path,root/'no_calibration.json')
            self.assertEqual(sorted(p.name for p in root.iterdir()),['plan.json'])

    def test_complete_generation_console_and_template_API_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);console=''.join('actual fixture line%d\n'%i for i in range(200))
            (root/'candidate_stage').mkdir();(root/'candidate_stage/console.log').write_text(console)
            template={'goal':'fixed planning tradeoff fixture','documents':{'assembly_api':{'complete':'RowSpec fixture'},'enumeration_api':{'complete':'SharingPlan fixture'}},'contract':{'unchanged':'physical fixture'}}
            (root/'template.json').write_text(json.dumps(template))
            manifest={'collection_id':'fixture','teacher_packet_template':str(root/'template.json'),'sampling':{'mode':'train_collection_action_gpt'}}
            state={'initial_state_id':'s','base_source':{'layout.py':'whole layout fixture','enumeration.py':'whole planning fixture'}}
            point={'configuration_id':'a','domain_role':'anchor','parameters':{'circuit':{'circuit_id':'C01'},'sizing':{}},
                'contract':{'task_id':'C01','objective':{'metric':'area','direction':'min'},'specifications':[],
                    'required_corners':['tt'],'analysis_contracts':{},'nominal_operating_point':{}}}
            baseline={'a':{'checked':{'S0':False,'S1':False,'S2':False,'failure_class':'candidate'},
                'result':{'status':'CANDIDATE_FAILED','run_directory':str(root)}}}
            task,history=packet(manifest,state,[point],baseline)
            self.assertEqual(task['visible_sources'],state['base_source']);self.assertEqual(task['documents'],template['documents'])
            self.assertEqual(task['budget']['maximum_context_tokens'],16384)
            self.assertEqual(history[0]['observation']['baseline_generation_diagnostics'][0]['console_excerpt'],console)

    def test_student_preselection_uses_the_explicit_same16k_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);task={'task_id':'fixture','goal':'teacher','contract':{'actual':'fixture'},'allowed_paths':['g.py'],
                'visible_sources':{'g.py':'a=1\n'},'documents':{},'visible_configurations':['a'],
                'budget':{'maximum_context_tokens':16384,'maximum_output_tokens':1024}}
            diff='--- a/g.py\n+++ b/g.py\n@@ -1 +1 @@\n-a=1\n+a=2\n'
            result=preselect_student_action({'student_preselection':{'max_context_tokens':16384,'max_new_tokens':1024}},task,
                [{'observation':{'complete':'fixture'}}],diff,'fixture',root,CharacterTokenizer())
            request=json.loads((root/'student_request.json').read_text())
            self.assertTrue(result['accepted']);self.assertEqual(result['student_interface_version'],'ordinary_policy_action_context_v2')
            self.assertEqual(request['task_packet']['budget']['maximum_context_tokens'],16384)


if __name__=='__main__':unittest.main()
