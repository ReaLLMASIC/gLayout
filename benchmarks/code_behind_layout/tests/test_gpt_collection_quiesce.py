"""Maintenance scope/batch tests; no real process is ever signalled."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.quiesce_gpt_teacher_collection import boundary, collector, process, same_process, save


class GPTQuiesceTests(unittest.TestCase):
    def test_terminated_zombie_is_gone_even_without_readable_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);entry=root/'1456867';entry.mkdir()
            (entry/'stat').write_text('1456867 (python3) Z '+' '.join(['0']*25))
            with patch('scripts.quiesce_gpt_teacher_collection.Path',lambda value:root):
                self.assertIsNone(process(1456867))

    def test_process_disappearing_after_signal_is_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('scripts.quiesce_gpt_teacher_collection.Path',lambda value:root):
                self.assertIsNone(process(1456867))

    def test_global_mod8_does_not_hide_next_queued_batch_or_partial_HTTP(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);state=root/'state';state.mkdir()
            def proposal(i,terminal=True):
                p=state/('collection__state%d__trial_%d'%((i-1)//8,(i-1)%8+1));p.mkdir()
                for name in ['request.json','response.json','attempt.json'] if terminal else []:(p/name).write_text('{}')
            for i in range(1,17):proposal(i)
            (root/'attempts.json').write_text(json.dumps([{}]*13))
            self.assertFalse(boundary(root)['safe_eight_trial_boundary'])
            (root/'attempts.json').write_text(json.dumps([{}]*16))
            self.assertTrue(boundary(root)['safe_eight_trial_boundary'])
            for i in range(17,25):proposal(i,False)
            checked=boundary(root)
            self.assertEqual(checked['attempt_mod8'],0)
            self.assertFalse(checked['safe_eight_trial_boundary'])
            self.assertEqual(len(checked['pending_HTTP_or_queued_proposals']),8)

    def test_only_exact_research_executing_GPT_collector_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();manifest=root/'runtime/train_collections/frozen/collection.json';manifest.parent.mkdir(parents=True)
            data={'status':'frozen','role':'train_collection','sampling':{'backend':'isolated_gpt_cli','mode':'train_collection_action_gpt','trials':list(range(1,9))},'output_root':str(root/'runs/train_collection/frozen')}
            manifest.write_text(json.dumps(data))
            proc={'pid':10,'argv':['python3','scripts/run_frozen_training_collection.py','--manifest',str(manifest),'--execute'],'cwd':str(root),'start_ticks':'123','state':'S'}
            with patch('scripts.quiesce_gpt_teacher_collection.ROOT',root):
                self.assertEqual(collector(proc)['pid'],10)
                for argv in [proc['argv']+['--other'],['python3','other/collect_training.py',*proc['argv'][2:]],
                             ['python3',proc['argv'][1],'--manifest',str(manifest),'--validate-only']]:
                    self.assertIsNone(collector({**proc,'argv':argv}))
                data['sampling']['backend']='T0';manifest.write_text(json.dumps(data))
                self.assertIsNone(collector(proc))

    def test_restore_identity_rejects_pid_reuse_or_argv_change(self):
        row={'pid':10,'argv':['exact'],'start_ticks':'123','cwd':'/research'}
        self.assertTrue(same_process(row,{**row,'state':'T'}))
        self.assertFalse(same_process(row,{**row,'start_ticks':'124'}))
        self.assertFalse(same_process(row,{**row,'argv':['another']}))
        self.assertFalse(same_process(row,None))

    def test_recovery_record_is_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'maintenance/resume.json';save(path,{'no_signals_in_fixture':True})
            self.assertEqual(path.stat().st_mode&0o777,0o600)


if __name__=='__main__':unittest.main()
