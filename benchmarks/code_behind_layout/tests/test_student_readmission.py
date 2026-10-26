"""Training derives labels from newly inspected raw evidence, never old labels."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.prepare_student_data import bound_registry,re_admit,completed_state_scope,interrupted_context_overflow


class StudentReadmissionTests(unittest.TestCase):
    def test_only_backend_control_references_can_extend_the_frozen_registry(self):
        frozen={'status':'frozen','lineages':[{'lineage_id':'x'}],'configurations':[{'configuration_id':'anchor','parameters':{'w':1}}]}
        effective=json.loads(json.dumps(frozen));effective['configurations'][0]['gold_control']={'run_directory':'/actual/control'}
        self.assertEqual(bound_registry(frozen,effective),effective)
        effective['configurations'][0]['parameters']['w']=2
        with self.assertRaisesRegex(ValueError,'more than permitted'):bound_registry(frozen,effective)

    def test_rebuild_uses_raw_candidate_and_current_store_without_opening_old_labels(self):
        candidate={'candidate_id':'real_candidate'};selected={key:[] for key in ['T1','T2','T3','T4']}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'candidates.jsonl').write_text(json.dumps(candidate)+'\n')
            (root/'T1.jsonl').write_text('this old derived file is deliberately invalid JSON')
            with patch('scripts.prepare_student_data.TrustedPhysicalStore') as store,patch('scripts.prepare_student_data.admit_candidates',return_value=[candidate]) as gate,patch('scripts.prepare_student_data.build_matched_samples',return_value=(selected,{'initial_states':1})) as labels:
                groups,report=re_admit(root,{'registry':'frozen'},{'rule':'frozen'})
                gate.assert_called_once_with([candidate],{'registry':'frozen'},store.return_value)
                labels.assert_called_once_with([candidate],{'rule':'frozen'})
            self.assertEqual(groups,selected);self.assertFalse(report['old_derived_T1_T4_used'])

    def test_failed_reaudit_quarantines_the_dataset_instead_of_making_negative_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'candidates.jsonl').write_text('{"candidate_id":"bad_graph"}\n')
            with patch('scripts.prepare_student_data.TrustedPhysicalStore'),patch('scripts.prepare_student_data.admit_candidates',side_effect=ValueError('terminal graph differs')),patch('scripts.prepare_student_data.build_matched_samples') as labels:
                groups,report=re_admit(root,{},{});labels.assert_not_called()
            self.assertIsNone(groups);self.assertEqual(report['status'],'QUARANTINED')
            self.assertFalse(report['quarantined_candidates_are_negative_labels'])


class CompletedStateScopeTests(unittest.TestCase):
    def fixture(self,root):
        state={'initial_state_id':'actual_completed','parent_lineage':'train_compiler'}
        statefile=root/'states.jsonl';statefile.write_text(json.dumps(state)+'\n'+json.dumps({**state,'initial_state_id':'not_run_1'})+'\n'+json.dumps({**state,'initial_state_id':'not_run_2'})+'\n')
        manifest={'initial_states_path':str(statefile),'sampling':{'mode':'train_collection_source_gpt','trials':list(range(1,9))}}
        points=[{'configuration_id':'p'+str(i),'parent_lineage':'train_compiler'} for i in range(9)]
        registry={'configurations':points};work=root/'actual_completed';work.mkdir()
        (work/'baseline_results.json').write_text(json.dumps({p['configuration_id']:{} for p in points}))
        attempts=[{'initial_state_id':'actual_completed','trial_id':i,'candidate_id':'candidate_'+str(i),
            'status':'DECLARED_DOMAIN_ATTEMPTS_COMPLETE' if i==1 else 'semantic_duplicate_before_physics'} for i in range(1,9)]
        (root/'attempts.json').write_text(json.dumps(attempts))
        row={'initial_state_id':'actual_completed','candidate_id':'candidate_1','outcomes':[{'configuration_id':p['configuration_id']} for p in points]}
        (root/'candidates.jsonl').write_text(json.dumps(row)+'\n')
        return manifest,registry,attempts,row

    def test_whole_returned_state_retains_the_24_attempt_plan_and_paused_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);manifest,registry,_,_=self.fixture(root)
            completion={'status':'PAUSED_ADMISSION_UNCERTAINTY'}
            selected,scope=completed_state_scope(root,manifest,registry,['actual_completed'],completion)
            self.assertEqual(selected,{'actual_completed'});self.assertEqual(scope['original_planned_proposals'],24)
            self.assertEqual(scope['selected_returned_proposals'],8);self.assertEqual(scope['original_remaining_unrun_or_unselected_proposals'],16)
            self.assertFalse(scope['whole_collection_claimed_complete']);self.assertFalse(scope['raw_completion_changed'])
            self.assertEqual(completion,{'status':'PAUSED_ADMISSION_UNCERTAINTY'})

    def test_partial_model_pool_or_missing_physical_point_cannot_produce_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);manifest,registry,attempts,row=self.fixture(root)
            completion={'status':'PAUSED_ADMISSION_UNCERTAINTY'}
            (root/'attempts.json').write_text(json.dumps(attempts[:-1]))
            with self.assertRaisesRegex(ValueError,'eight frozen'):completed_state_scope(root,manifest,registry,['actual_completed'],completion)
            (root/'attempts.json').write_text(json.dumps(attempts));row['outcomes'].pop()
            (root/'candidates.jsonl').write_text(json.dumps(row)+'\n')
            with self.assertRaisesRegex(ValueError,'nine point'):completed_state_scope(root,manifest,registry,['actual_completed'],completion)

    def test_context_exit_scope_preserves_missing_terminal_and_all_unselected_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);manifest,registry,_,_=self.fixture(root);manifest['collection_id']='fixture_context_exit'
            evidence={'status':'READ_ONLY_TRAIN_COLLECTION_EVIDENCE','actual_processes':[],
                'collections':[{'collection':manifest['collection_id'],'output_root':str(root),
                    'raw_paths':{'completion.json':{'exists':False}},
                    'logs':[{'last_120_lines':'RuntimeError: Full source/contract exceeds frozen context; no proposal requested and no truncation allowed'}]}]}
            path=root/'host_evidence.json';path.write_text(json.dumps(evidence))
            interruption=interrupted_context_overflow(root,manifest,path)
            selected,scope=completed_state_scope(root,manifest,registry,['actual_completed'],{},interruption)
            self.assertEqual(selected,{'actual_completed'});self.assertIsNone(scope['raw_collection_status'])
            self.assertEqual(scope['original_remaining_unrun_or_unselected_proposals'],16)
            self.assertFalse(scope['whole_collection_claimed_complete']);self.assertFalse((root/'completion.json').exists())
            evidence['actual_processes']=[{'argv':['python','run_frozen_training_collection.py','--manifest',
                str((Path(__file__).resolve().parents[1]/'runtime/train_collections/fixture_context_exit/collection.json').resolve()),'--execute']}]
            path.write_text(json.dumps(evidence))
            with self.assertRaisesRegex(ValueError,'active owner'):interrupted_context_overflow(root,manifest,path)


if __name__=='__main__':unittest.main()
