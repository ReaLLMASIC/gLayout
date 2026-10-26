"""Software fixtures for freeze gates; no fixture is research measurement."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.e4_methods import (IMPLEMENTATION_FILES,METHODS,REVISION,SEEDS,SELECTION_RULE,build_methods_freeze,
                            file_digest,frozen_serving_method,inspect_formal_run,validate_context_calibration,validate_selection)
from src.student_interface import CONTEXT_VERSION,interface_definition


class E4MethodsTests(unittest.TestCase):
    def save(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return path

    def setup(self,root):
        definition=interface_definition(CONTEXT_VERSION,12288)
        registry={'status':'frozen','lineages':[{'lineage_id':'val','split':'validation','topology_family':'independent_ota'}],
            'configurations':[{'configuration_id':'v1','parent_lineage':'val','split':'validation','role':'validation',
                'contract':{'task_id':'validation_ota'}}]}
        registry_path=self.save(root/'registry.json',registry)
        plan={'status':'FROZEN_E4_VALIDATION_PLAN','selection_rule':SELECTION_RULE,
            'split_registry_sha256':file_digest(registry_path),'frozen_at_utc':'2026-10-19T00:00:00+00:00',
            'points':[{'task_id':'validation_ota','configuration_id':'v1'}]}
        plan_path=self.save(root/'validation_plan.json',plan);plan_path.chmod(0o444)
        calibration={'scope':'development_gpu_algorithm_calibration_not_E4','status':'COMPLETED',
            'allocated_sequence_tokens':12288,'snapshot':'/fixture/'+REVISION,'dpo_model_training':True,
            'dpo_gradient_checkpointing':True,'stages':[
                {'name':'SFT_optimizer_update','allocated_sequence_tokens':12288,'prompt_tokens':12165,'wall_seconds':10,'peak_allocated_bytes':56539899392},
                {'name':'DPO_12288_pair_optimizer_update','prompt_tokens':12165,'wall_seconds':38,'peak_allocated_bytes':57900447232,
                    'frozen_reference_bitwise_unchanged':True},
                {'name':'actual_saved_adapter_optimizer_RNG_disk_restore','adapter_bitwise_equal':True,
                    'optimizer_state_bitwise_equal':True,'next_CPU_and_CUDA_RNG_equal':True}]}
        calibration_path=self.save(root/'calibration.json',calibration)
        entries=[{'method':m,'seed':s,'run_directory':str(root/m/str(s)),'training_manifest':'manifest.json',
                  'selected_checkpoint':str(root/m/str(s)/'checkpoint-0000001'),'validation_selection':'selection.json'} for m in METHODS for s in SEEDS]
        draft={'status':'DRAFT_E4_METHODS','student_interface':definition,'split_registry':str(registry_path),
            'context_calibration':str(calibration_path),'validation_plan':str(plan_path),'formal_training_runs':entries,
            'decoding_settings':{'do_sample':False,'max_new_tokens':1024}}
        return draft,registry,plan,plan_path

    def test_exact_twelve_runs_required_and_engineering_count_never_substitutes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);draft,*_=self.setup(root)
            draft['formal_training_runs']=draft['formal_training_runs'][:-1]
            draft['engineering_training_runs']=100
            with self.assertRaisesRegex(ValueError,'twelve actual formal runs'):build_methods_freeze(draft,root)
            draft['formal_training_runs'].append(copy.deepcopy(draft['formal_training_runs'][0]))
            with self.assertRaisesRegex(ValueError,'twelve actual formal runs'):build_methods_freeze(draft,root)

    def test_larger_context_requires_actual_same_length_gpu_work_and_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);draft,*_=self.setup(root)
            with self.assertRaisesRegex(ValueError,'exact context window'):
                validate_context_calibration(draft['context_calibration'],interface_definition(CONTEXT_VERSION,16384))
            record=json.loads(Path(draft['context_calibration']).read_text())
            record['stages'][-1]['optimizer_state_bitwise_equal']=False
            self.save(Path(draft['context_calibration']),record)
            with self.assertRaisesRegex(ValueError,'exact restore'):validate_context_calibration(draft['context_calibration'],draft['student_interface'])

    def test_completed_engineering_run_is_not_a_formal_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);draft,*_=self.setup(root);entry=draft['formal_training_runs'][0]
            self.save(Path(entry['run_directory'])/'run.json',{'method':'T1','seed':41,'status':'COMPLETED',
                'scope':'development_gpu_algorithm_calibration_not_E4','updates':1})
            with patch('scripts.train_policy.prepare',return_value=({}, {}, {}, [1], {'registry':'fixed'})):
                with self.assertRaisesRegex(ValueError,'Engineering, incomplete'):
                    inspect_formal_run(entry,root,draft['student_interface'],'fixed')

    def test_validation_recomputes_complete_denominator_and_earliest_update_tie(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);draft,registry,plan,plan_path=self.setup(root);entry=draft['formal_training_runs'][0]
            checkpoints=[];evaluations=[]
            for update in [1,2]:
                checkpoint=root/('checkpoint-%07d'%update);checkpoints.append(checkpoint)
                self.save(checkpoint/'complete.json',{'updates':update})
                model=checkpoint/'adapter/policy/adapter_model.safetensors';model.parent.mkdir(parents=True);model.write_bytes(b'SOFTWARE_FIXTURE_ONLY')
                self.save(model.parent/'adapter_config.json',{'fixture':True})
                run=root/('physical%d'%update);digest=file_digest(model)
                self.save(run/'manifest.json',{'phase':'development_E4_checkpoint_validation',
                    'context':{'source_role':'E4_validation_checkpoint_selection','method':'T1','training_seed':41,'model_adapter_sha256':digest},
                    'candidate':{'started_at_utc':'2026-10-19T01:00:00+00:00'}})
                evaluations.append({'checkpoint':str(checkpoint),'adapter_sha256':digest,
                    'task_sources':{'validation_ota':{'layout.py':'complete source fixture'}},
                    'points':[{'task_id':'validation_ota','configuration_id':'v1','run_directory':str(run)}]})
            entry['selected_checkpoint']=str(checkpoints[0]);entry['validation_selection']=str(root/'selection.json')
            selection={'status':'COMPLETED_E4_VALIDATION_CHECKPOINT_SELECTION','method':'T1','seed':41,
                'validation_plan_sha256':file_digest(plan_path),'selected_checkpoint':str(checkpoints[0]),'checkpoint_evaluations':evaluations}
            self.save(root/'selection.json',selection)
            with patch('src.e4_methods.TrustedPhysicalStore._inspect_execution_run',return_value={'S1':True,'S2':True}) as inspector:
                result=validate_selection(entry,{'checkpoints':checkpoints},root,registry,plan,plan_path)
                self.assertEqual(inspector.call_count,2);self.assertEqual(result['selected_checkpoint'],str(checkpoints[0].resolve()))
                selection['selected_checkpoint']=entry['selected_checkpoint']=str(checkpoints[1]);self.save(root/'selection.json',selection)
                with self.assertRaisesRegex(ValueError,'predeclared physical validation rule'):
                    validate_selection(entry,{'checkpoints':checkpoints},root,registry,plan,plan_path)
                selection['checkpoint_evaluations'][0]['points']=[];self.save(root/'selection.json',selection)
                with self.assertRaisesRegex(ValueError,'denominator'):
                    validate_selection(entry,{'checkpoints':checkpoints},root,registry,plan,plan_path)

    def test_evaluation_lineage_cannot_select_a_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);draft,registry,plan,plan_path=self.setup(root);entry=draft['formal_training_runs'][0]
            self.save(root/'selection.json',{'status':'COMPLETED_E4_VALIDATION_CHECKPOINT_SELECTION','method':'T1','seed':41,
                'validation_plan_sha256':file_digest(plan_path)})
            registry['lineages'][0]['split']='test'
            with self.assertRaisesRegex(ValueError,'test or hidden'):
                validate_selection(entry,{'checkpoints':[]},root,registry,plan,plan_path)

    def test_same_seed_t1_reference_is_mandatory_and_freeze_does_not_release_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);draft,*_=self.setup(root)
            def training(entry,*unused):
                return {'run_directory':entry['run_directory'],'training_manifest':entry['training_manifest'],
                    'manifest':{'backbone_snapshot':'/fixture/'+REVISION},
                    'config':{'fixed':'recipe','quantization':{'load_in_4bit':True},'lora':{'r':32}},
                    'run':{'updates':1,'samples':1,'allocated_sequence_tokens_per_epoch':12288,'identities':{'registry':'same','datasets':{'T1':'data1','T2':'data2','T3':'data3','T4':'data4'}},
                        'reference_checkpoint':str(root/'T1'/str(entry['seed'])/'checkpoint-0000001/adapter/policy') if entry['method'] in ('T3','T4') else None}}
            def selection(entry,*unused):
                return {'selected_adapter':str(Path(entry['selected_checkpoint'])/'adapter/policy'),'selected_checkpoint':entry['selected_checkpoint']}
            with patch('src.e4_methods.inspect_formal_run',side_effect=training),patch('src.e4_methods.validate_selection',side_effect=selection):
                result=build_methods_freeze(draft,root)
                self.assertEqual(result['formal_training_runs'],12);self.assertEqual(result['engineering_runs_counted'],0)
                self.assertFalse(result['hidden_evaluation_released']);self.assertEqual(set(result['variants']),{'T0','T1','T2','T3','T4'})
                self.assertEqual(result['variants']['T0']['actual_training_seeds'],[])
                self.assertEqual(result['variants']['T0']['actual_model_count'],1)
                self.assertEqual(result['variants']['T0']['matched_evaluation_seed_slots'],[41,73,109])
            def wrong_reference(entry,*args):
                value=training(entry,*args)
                if entry['method']=='T4':value['run']['reference_checkpoint']='other adapter'
                return value
            with patch('src.e4_methods.inspect_formal_run',side_effect=wrong_reference),patch('src.e4_methods.validate_selection',side_effect=selection):
                with self.assertRaisesRegex(ValueError,'same-seed T1 adapter'):build_methods_freeze(draft,root)

    def test_serving_rejects_draft_unfrozen_and_changed_selected_weights(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);draft,*_=self.setup(root)
            path=self.save(root/'fixture.json',draft)
            with self.assertRaisesRegex(ValueError,'actual frozen E4 methods'):frozen_serving_method(path,'T1',41)
            model=root/'adapter/adapter_model.safetensors';model.parent.mkdir();model.write_bytes(b'SOFTWARE_ONLY')
            config=self.save(model.parent/'adapter_config.json',{'fixture':True})
            project=Path(__file__).resolve().parents[1]
            value={'status':'FROZEN_E4_METHODS','formal_training_runs':12,'base_revision':REVISION,
                'student_interface':draft['student_interface'],'implementation_sha256':{n:file_digest(project/n) for n in IMPLEMENTATION_FILES},'backbone_snapshot':'/fixture/'+REVISION,
                'decoding_settings':{'do_sample':False,'max_new_tokens':1024},'quantization':{'load_in_4bit':True},
                'variants':{'T1':{'seeds':{'41':{'selected_adapter':str(model.parent),'adapter_sha256':file_digest(model),'adapter_config_sha256':file_digest(config)}}}}}
            self.save(path,value);path.chmod(0o444)
            result=frozen_serving_method(path,'T1',41)
            self.assertEqual(result['student_interface']['max_context_tokens'],12288)
            self.assertEqual(result['adapter_path'],str(model.parent.resolve()))
            model.write_bytes(b'CHANGED')
            with self.assertRaisesRegex(ValueError,'frozen weights'):frozen_serving_method(path,'T1',41)


if __name__=='__main__':unittest.main()
