"""Software-only Git replay tests, not physical or model results."""
import unittest
from scripts.diagnose_e3_patch_rejection import classify, hunk_counts, replay


class PatchRejectionDiagnosisTests(unittest.TestCase):
    def test_actual_git_rejects_corrupt_hunk_and_accepts_same_source_control(self):
        patch = '--- a/module.py\n+++ b/module.py\n@@ -1,2 +1,2 @@\n-a=1\n+a=2\n'
        value = replay({'module.py': 'a=1\n'}, patch, 'module.py')
        self.assertEqual(value['returncode'], 128)
        self.assertEqual(value['known_valid_same_source_control']['returncode'], 0)
        self.assertTrue(value['source_unchanged'])
        self.assertEqual(classify(value, 128, 'module.py'), 'candidate_corrupt_unified_diff')
        self.assertEqual(hunk_counts(patch)[0]['declared_old'], 2)
        self.assertEqual(hunk_counts(patch)[0]['observed_old'], 1)

    def test_exit_number_or_unavailable_positive_control_is_not_enough(self):
        value = {'returncode': 128, 'stderr': 'fatal: cannot open source: Permission denied\n',
            'known_valid_same_source_control': {'returncode': 0}, 'source_unchanged': True}
        self.assertEqual(classify(value, 128, 'module.py'), 'UNRESOLVED_NO_CANDIDATE_CLASSIFICATION')
        value.update(stderr='error: corrupt patch at line 8\n', known_valid_same_source_control={'returncode': 128})
        self.assertEqual(classify(value, 128, 'module.py'), 'UNRESOLVED_NO_CANDIDATE_CLASSIFICATION')

    def test_original_exit_must_reproduce(self):
        value = {'returncode': 128, 'stderr': 'error: corrupt patch at line 8\n',
            'known_valid_same_source_control': {'returncode': 0}, 'source_unchanged': True}
        self.assertEqual(classify(value, 1, 'module.py'), 'UNRESOLVED_NO_CANDIDATE_CLASSIFICATION')


if __name__ == '__main__':unittest.main()
