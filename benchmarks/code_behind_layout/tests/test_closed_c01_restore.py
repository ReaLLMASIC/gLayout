"""Tiny engineering filesystem fixtures, not formal raw/admission evidence."""
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from scripts.rehearse_closed_c01_restore import COHORT, compare_tree, swap_physical


class RestoreTests(unittest.TestCase):
    def fixture(self, root):
        tree = root/'cohort'; tree.mkdir(); tree.chmod(0o775)
        (tree/'source.py').write_bytes(b'complete_source\n'); (tree/'source.py').chmod(0o444)
        (tree/'empty.log').write_bytes(b''); (tree/'empty.log').chmod(0o664)
        archive = root/'fixture.tar.gz'
        with tarfile.open(archive,'w:gz') as output:
            output.add(tree,arcname=COHORT)
        return tree,archive

    def test_reopens_exact_bytes_modes_and_empty_file(self):
        with tempfile.TemporaryDirectory() as directory:
            tree,archive=self.fixture(Path(directory))
            result=compare_tree(archive,tree)
            self.assertEqual(result['regular_files_reopened'],2)
            self.assertTrue(result['path_bytes_and_modes_exact'])

    def test_changed_bytes_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            tree,archive=self.fixture(Path(directory))
            (tree/'source.py').chmod(0o644); (tree/'source.py').write_bytes(b'different______\n'); (tree/'source.py').chmod(0o444)
            with self.assertRaisesRegex(ValueError,'bytes differ|type/size'):
                compare_tree(archive,tree)

    def test_swap_success_retains_original_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); old=root/'physical'; new=root/'restored'
            old.mkdir(); new.mkdir(); (old/'source').write_text('original'); (new/'source').write_text('restored')
            state={}; saved=[]
            def verify():
                self.assertEqual((old/'source').read_text(),'restored')
                return {'software_fixture_only':True}
            swap_physical(old,new,root/'held',root/'failed',verify,state,lambda:saved.append(dict(state)))
            self.assertEqual((root/'held/source').read_text(),'original')
            self.assertEqual((old/'source').read_text(),'restored')
            self.assertFalse((root/'failed').exists())
            self.assertEqual(saved[-1]['status'],'RESTORE_DRILL_COMPLETED_ORIGINAL_RETAINED')

    def test_failed_admission_rolls_back_and_preserves_failed_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); old=root/'physical'; new=root/'restored'
            old.mkdir(); new.mkdir(); (old/'source').write_text('original'); (new/'source').write_text('restored')
            state={}
            def verify(): raise ValueError('engineering fixture admission refused')
            with self.assertRaisesRegex(ValueError,'admission refused'):
                swap_physical(old,new,root/'held',root/'failed',verify,state,lambda:None)
            self.assertEqual((old/'source').read_text(),'original')
            self.assertEqual((root/'failed/source').read_text(),'restored')
            self.assertFalse((root/'held').exists())
            self.assertTrue(state['original_restored'])

    def test_prior_holding_directory_blocks_automatic_second_swap(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('physical','restored','held'):(root/name).mkdir()
            with self.assertRaisesRegex(ValueError,'automatic resume is forbidden'):
                swap_physical(root/'physical',root/'restored',root/'held',root/'failed',lambda:None,{},lambda:None)
            self.assertTrue((root/'physical').exists())
            self.assertTrue((root/'restored').exists())

    def test_failed_rollback_is_not_reported_as_original_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); old=root/'physical'; new=root/'restored'; held=root/'held'
            old.mkdir(); new.mkdir(); (old/'source').write_text('original'); (new/'source').write_text('restored')
            original_rename=Path.rename
            def rename(path,destination):
                if path==held:raise OSError('engineering fixture rename I/O failure')
                return original_rename(path,destination)
            def verify():raise ValueError('engineering fixture admission refused')
            state={}
            with patch.object(Path,'rename',rename):
                with self.assertRaisesRegex(OSError,'rename I/O failure'):
                    swap_physical(old,new,held,root/'failed',verify,state,lambda:None)
            self.assertEqual(state['status'],'ROLLBACK_FAILED_MANUAL_RECOVERY_REQUIRED')
            self.assertFalse(state['original_restored'])
            self.assertEqual((held/'source').read_text(),'original')
            self.assertEqual((root/'failed/source').read_text(),'restored')


if __name__=='__main__':unittest.main()
