import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.run_e1_suite import collect, plan


class E1SuiteTests(unittest.TestCase):
    def manifest(self):
        tasks = [{'task_id': 't%02d' % i} for i in range(24)]
        return {'status': 'FROZEN_E1', 'formal_dispatch': True, 'tasks': tasks,
                'task_ids': [row['task_id'] for row in tasks], 'methods': ['G0','G1','G2'],
                'trials': 5, 'runtime': {'candidate_CPUs': 2}, 'dispatch_order_seed': 20261018,
                'backend_manifest_path':'/srv/frozen/E1/manifest.json'}

    def test_fixed_matrix_is_complete_and_block_randomized(self):
        jobs = plan(self.manifest())
        self.assertEqual(len(jobs), 360)
        self.assertEqual(len({(j['task_id'],j['method'],j['trial_id']) for j in jobs}), 360)
        self.assertEqual(jobs, plan(self.manifest()))
        for index in range(0, 360, 3):
            block = jobs[index:index+3]
            self.assertEqual(len({(j['task_id'],j['trial_id']) for j in block}), 1)
            self.assertEqual({j['method'] for j in block}, {'G0','G1','G2'})

    def test_draft_or_changed_trial_budget_cannot_dispatch(self):
        for key, value in [('status','DRAFT_E1_RUNNER'), ('trials',6), ('formal_dispatch',False)]:
            manifest = copy.deepcopy(self.manifest()); manifest[key] = value
            with self.assertRaises(ValueError): plan(manifest)

    def test_interruption_preserves_unresolved_trial_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = {'task_id':'t00','method':'G1','trial_id':'1','dispatch_record':str(Path(tmp)/'absent.json')}
            collect(job)
            self.assertEqual(job['status'], 'UNRESOLVED_PROCESS_EXIT')
            self.assertNotIn('episode_json', job)
            record = Path(tmp)/'client.json'
            record.write_text(json.dumps({'task_id':'another','method':'G1','trial_id':'1','formal':True}))
            job['dispatch_record'] = str(record)
            with self.assertRaises(ValueError): collect(job)


if __name__ == '__main__': unittest.main()
