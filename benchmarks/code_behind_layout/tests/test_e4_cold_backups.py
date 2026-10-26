"""Tiny filesystem/software controls only: no trained model or formal freeze."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.prepare_training import checkpoint_backup_relative,REMOTE_ROOT,FORMAL_E4_CHECKPOINT_ROOT
import scripts.prepare_training as preparation
import scripts.audit_e4_cold_run as audit
import scripts.freeze_e4_cold_backups as cold


class ColdBackupTests(unittest.TestCase):
    def save(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return path

    def tiny(self,root):
        """Real small bytes exercise storage checks, never model-quality claims."""
        root=root.resolve()
        server=root/'server';mac=root/'mac';run=server/'T1/seed-41';cp=run/'checkpoint-0000001'
        entry={'method':'T1','seed':41,'run_directory':str(run)}
        files={'adapter/policy/adapter_model.safetensors':b'SOFTWARE_FIXTURE_NOT_MODEL',
            'adapter/policy/adapter_config.json':b'{"fixture":true}',
            'training_state.pt':b'TINY_CPU_STORAGE_CONTROL_NOT_TORCH_STATE',
            'complete.json':b'{"optimizer_boundary":true,"updates":1}',
            'tokenizer/tokenizer_config.json':b'{"fixture":true}',
            'metadata/training_manifest.json':b'{"scope":"software_only"}',
            'metadata/training_config.json':b'{"scope":"software_only"}',
            'metadata/run.json':b'{"scope":"software_only"}',
            'metadata/metrics.jsonl':b'{"fixture":true}\n'}
        for name,content in files.items():
            path=cp/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
        self.save(run/'run.json',{'status':'SOFTWARE_FIXTURE_NOT_FORMAL'})
        rows=audit.inventory(cp)
        closed={'status':'CLOSED_ACTUAL_E4_RUN_INVENTORY','method':'T1','seed':41,'run_directory':str(run),
            'expected_updates':[1],'checkpoints':[{'checkpoint':str(cp),'files':rows}],
            'run_file':audit.file_row(run/'run.json'),'run_text':(run/'run.json').read_text(),
            'run_files':[audit.file_row(run/'run.json')]}
        target=mac/'T1/seed-41'/cp.name
        for name,content in files.items():
            path=target/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
        self.save(target/'backup_manifest.json',{'status':'CHECKSUM_VERIFIED','checkpoint':str(cp),'files':rows})
        (target.parent/'run.json').write_bytes((run/'run.json').read_bytes())
        return server,mac,entry,closed,cp,target

    def test_old_backup_mapping_unchanged_and_only_one_new_owned_root(self):
        self.assertEqual(checkpoint_backup_relative(REMOTE_ROOT+'/checkpoints/dev/ckpt'),Path('dev/ckpt'))
        self.assertEqual(checkpoint_backup_relative(FORMAL_E4_CHECKPOINT_ROOT+'/T2/seed-73/checkpoint-0000100'),
            Path('formal_e4/T2/seed-73/checkpoint-0000100'))
        for value in ['/dev/shm/other/T1/seed-41/checkpoint-0000001',FORMAL_E4_CHECKPOINT_ROOT+'/T0/seed-41/checkpoint-0000001',
            FORMAL_E4_CHECKPOINT_ROOT+'/T1/seed-42/checkpoint-0000001',FORMAL_E4_CHECKPOINT_ROOT+'/../other']:
            with self.assertRaises(ValueError):checkpoint_backup_relative(value)

    def test_expected_cadence_includes_interval_and_every_epoch_end(self):
        config={'sft':{'epochs':2},'dpo':{'epochs':1},'gradient_accumulation':16,'checkpoint_interval_updates':100}
        self.assertEqual(audit.expected_updates(config,'T1',1000),[63,100,126])
        self.assertEqual(audit.expected_updates(config,'T3',1000),[63])
        config['gradient_accumulation']=0
        with self.assertRaises(ValueError):audit.expected_updates(config,'T1',1000)

    def test_actual_tiny_byte_reopen_not_status_receipt(self):
        with tempfile.TemporaryDirectory()as directory:
            server,mac,entry,closed,cp,target=self.tiny(Path(directory))
            with patch.object(audit,'CHECKPOINT_ROOT',server),patch.object(cold,'MAC_ROOT',mac):
                result=cold.verify_backups(entry,closed)
                self.assertEqual(result[0]['files'],closed['checkpoints'][0]['files'])
                (target/'training_state.pt').write_bytes(b'CHANGED')
                with self.assertRaisesRegex(ValueError,'bytes missing/changed'):cold.verify_backups(entry,closed)

    def test_missing_optimizer_and_added_checkpoint_or_file_rejected(self):
        with tempfile.TemporaryDirectory()as directory:
            server,mac,entry,closed,cp,target=self.tiny(Path(directory))
            with patch.object(audit,'CHECKPOINT_ROOT',server),patch.object(cold,'MAC_ROOT',mac):
                optimizer=(target/'training_state.pt').read_bytes();(target/'training_state.pt').unlink()
                with self.assertRaises(ValueError):cold.verify_backups(entry,closed)
                (target/'training_state.pt').write_bytes(optimizer);(target/'extra.txt').write_text('UNDECLARED')
                with self.assertRaises(ValueError):cold.verify_backups(entry,closed)
                bad=copy.deepcopy(closed);bad['checkpoints']=[]
                with self.assertRaisesRegex(ValueError,'denominator'):audit.check_closed(bad,entry)

    def test_closed_root_metadata_is_required_and_never_synthesized_from_CP(self):
        with tempfile.TemporaryDirectory()as directory:
            server,mac,entry,closed,_,target=self.tiny(Path(directory))
            with patch.object(audit,'CHECKPOINT_ROOT',server),patch.object(cold,'MAC_ROOT',mac):
                (target.parent/'run.json').unlink()
                with self.assertRaisesRegex(ValueError,'Missing actual audit input'):cold.verify_backups(entry,closed)
                bad=copy.deepcopy(closed);bad['run_files']=[]
                with self.assertRaisesRegex(ValueError,'root run.json'):audit.check_closed(bad,entry)

    def test_restore_plan_preserves_actual_bytes_and_waits_without_deletion(self):
        with tempfile.TemporaryDirectory()as directory:
            server,mac,entry,closed,cp,target=self.tiny(Path(directory));optimizer=cp/'training_state.pt';optimizer.unlink()
            with patch.object(audit,'CHECKPOINT_ROOT',server),patch.object(audit,'capacity',return_value={'status':'WAITING_RETIREMENT'}):
                result=audit.restore_plan(entry,closed)
                self.assertEqual(result['status'],'WAITING_RETIREMENT');self.assertFalse(optimizer.exists())
                self.assertEqual(result['deleted_files'],0)
            with patch.object(audit,'CHECKPOINT_ROOT',server),patch.object(audit,'capacity',return_value={'status':'READY'}):
                result=audit.restore_plan(entry,closed)
                self.assertEqual(result['missing'][0]['path'],str(optimizer))
                # Actual tiny local copy stands for a transfer; original validator still decides admission.
                optimizer.write_bytes((target/'training_state.pt').read_bytes())
                self.assertEqual(audit.inventory(cp),closed['checkpoints'][0]['files'])
                self.assertEqual(audit.restore_plan(entry,closed)['missing'],[])

    def test_changed_existing_bytes_are_never_overwritten(self):
        with tempfile.TemporaryDirectory()as directory:
            server,_,entry,closed,cp,_=self.tiny(Path(directory));(cp/'training_state.pt').write_bytes(b'OTHER')
            with patch.object(audit,'CHECKPOINT_ROOT',server):
                with self.assertRaisesRegex(ValueError,'no overwrite'):audit.restore_plan(entry,closed)
            self.assertEqual((cp/'training_state.pt').read_bytes(),b'OTHER')

    def test_symlink_checkpoint_is_rejected(self):
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);(root/'original').write_text('tiny');(root/'alias').symlink_to(root/'original')
            with self.assertRaisesRegex(ValueError,'Ordinary'):audit.file_row(root/'alias')

    def test_actual_unknown_original_inspector_failure_is_not_an_audit(self):
        with tempfile.TemporaryDirectory()as directory:
            server,_,entry,closed,_,_=self.tiny(Path(directory))
            with patch.object(audit,'CHECKPOINT_ROOT',server),patch.object(audit,'inspect_formal_run',side_effect=ValueError('unknown physical/run evidence')):
                with self.assertRaisesRegex(ValueError,'unknown'):audit.audit(entry,{'definition':{},'registry_sha256':'fixture'},closed)

    def test_no_actual_twelve_runs_means_no_freeze_or_remote_call(self):
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);state={'runs':{},'events':[]}
            with patch.object(cold,'load',return_value=(root,{},state)),patch.object(cold,'rpc')as remote:
                result=cold.finalize(root,root/'must_not_exist.json')
            self.assertEqual(result['status'],'NOT_READY_ALL12_ACTUAL_RUN_AUDITS_REQUIRED')
            self.assertFalse(result['formal_methods_written']);self.assertFalse((root/'must_not_exist.json').exists());remote.assert_not_called()

    def test_local_mutation_cannot_use_an_unchanged_server_audit_for_assembly(self):
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);entry={'method':'T1','seed':41}
            original={'closed_inventory':{'run_files':[]},'training':{'fixture':'original'},'selection':{'fixture':'original'}}
            digest=hashlib.sha256((json.dumps(original,indent=2,allow_nan=False)+'\n').encode()).hexdigest()
            changed=copy.deepcopy(original);changed['training']['fixture']='accidentally changed local content'
            self.save(root/'audits/T1_41.json',{'audit':changed,'audit_path':'/server/original/audit.json','audit_sha256':digest})
            state={'runs':{str(i):{'status':'AUDITED'}for i in range(12)},'events':[]}
            recheck={'status':'ACTUAL_AUDITED_RAW_BYTES_REOPENED','audit_path':'/server/original/audit.json','audit_sha256':digest}
            with patch.object(cold,'load',return_value=(root,{'entries':[entry]},state)),\
                patch.object(cold,'matching_header',return_value={}),patch.object(cold,'verify_backups',return_value=[]),\
                patch.object(cold,'rpc',return_value=recheck)as remote,patch.object(cold,'assemble')as assemble:
                with self.assertRaisesRegex(ValueError,'Local audit differs'):cold.finalize(root,root/'never_frozen.json')
            remote.assert_called_once();assemble.assert_not_called();self.assertFalse((root/'never_frozen.json').exists())

    def test_direct_backup_CLI_failure_records_actual_totals_and_unknown_transfer_bytes(self):
        with tempfile.TemporaryDirectory()as directory:
            log=Path(directory)/'backup_invocations.jsonl'
            with patch.object(preparation,'BACKUP_INVOCATION_LOG',log),\
                patch('sys.argv',['prepare_training.py','backup-checkpoint','--remote-checkpoint',REMOTE_ROOT+'/checkpoints/tiny']),\
                patch.object(preparation,'backup_checkpoint',side_effect=ValueError('software controlled failure')):
                with self.assertRaisesRegex(ValueError,'controlled failure'):preparation.main()
            row=json.loads(log.read_text());self.assertFalse(row['success'])
            for name in ('payload_file_bytes','transferred_file_bytes','wire_bytes','remote_CPU_seconds'):
                self.assertIsNone(row[name])
            for name in ('wall_seconds','local_process_CPU_seconds','local_child_CPU_seconds'):
                self.assertGreaterEqual(row[name],0)

    def test_incomplete_audit_set_cannot_assemble_formal_methods(self):
        draft={'status':'DRAFT_E4_METHODS','student_interface':{'version':'ordinary_policy_action_context_v2',
            'max_context_tokens':16384,'max_new_tokens':1024,'history_policy':'current_source_and_feedback_v1'},
            'formal_training_runs':[{'method':m,'seed':s,'run_directory':str(Path(FORMAL_E4_CHECKPOINT_ROOT)/m/('seed-'+str(s)))}
                for m in audit.METHODS for s in audit.SEEDS]}
        with self.assertRaisesRegex(ValueError,'All12'):cold.assemble(draft,{},[])

    def test_early_unknown_selected_paths_cannot_create_the_final_journal(self):
        with tempfile.TemporaryDirectory()as directory:
            draft={'status':'DRAFT_E4_METHODS','student_interface':{'version':'ordinary_policy_action_context_v2',
                'max_context_tokens':16384,'max_new_tokens':1024,'history_policy':'current_source_and_feedback_v1'},
                'formal_training_runs':[{'method':m,'seed':s,'run_directory':str(Path(FORMAL_E4_CHECKPOINT_ROOT)/m/('seed-'+str(s))),
                    'selected_checkpoint':None}for m in audit.METHODS for s in audit.SEEDS]}
            path=self.save(Path(directory)/'early.json',draft)
            out=cold.ROOT/'runtime/e4_cold_completion'/('software_not_created_'+Path(directory).name)
            with self.assertRaisesRegex(ValueError,'all12 known original absolute'):cold.prepare(path,REMOTE_ROOT+'/runtime/early.json',out)
            self.assertFalse(out.exists())

    def test_cross_run_reference_and_data_changes_reject_before_any_freeze(self):
        # Synthetic semantics exercise only the failure predicates; no successful
        # FROZEN artifact is generated or written by this fixture.
        header={'draft_sha256':'fixture','implementation_sha256':{},'completion_implementation_sha256':{},'registry_sha256':'fixture'}
        values=[]
        for method in audit.METHODS:
            for seed in audit.SEEDS:
                values.append({'status':'ACTUAL_E4_COLD_RUN_AUDIT_COMPLETE','method':method,'seed':seed,**header,
                    'training':{'config':{'fixture':True},'run':{'identities':{'datasets':{'fixture':'same'},'registry':'fixture'},
                        'updates':1,'samples':1,'allocated_sequence_tokens_per_epoch':1,
                        'reference_checkpoint':'CHANGED_REFERENCE'if method in ('T3','T4')else None}},
                    'selection':{'selected_adapter':'original_T1_'+str(seed)}})
        with patch.object(cold,'static_draft',return_value=[]):
            with self.assertRaisesRegex(ValueError,'T1 canonical'):cold.assemble({},header,values)
            values[1]['training']['run']['identities']['datasets']={'fixture':'changed'}
            with self.assertRaisesRegex(ValueError,'dataset bytes'):cold.assemble({},header,values)

    def test_transfer_paths_do_not_accept_arbitrary_shell_or_parent_paths(self):
        self.assertEqual(cold.transfer_path('/dev/shm/cbl-formal-e4/checkpoints/T1/seed-41/x'),
            '/dev/shm/cbl-formal-e4/checkpoints/T1/seed-41/x')
        for path in ['/x/../y','/x/$(bad)','/x/space name']:
            with self.assertRaises(ValueError):cold.transfer_path(path)

    def test_one_explicit_restore_coordinator_at_a_time(self):
        with tempfile.TemporaryDirectory()as directory,patch.object(cold,'MAC_ROOT',Path(directory).resolve()):
            with cold.restore_lock():
                with self.assertRaises(BlockingIOError):
                    with cold.restore_lock():self.fail('A second restore coordinator entered')


if __name__=='__main__':unittest.main()
