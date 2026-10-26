import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.release_e3_hidden import inspect_indices
from src.e3_dispatch import identity, plan


class GlobalReleaseTests(unittest.TestCase):
    def setUp(self):
        filename = Path(__file__).resolve().parents[1]/'configs/experiments/e3_matched_draft.json'
        self.manifest = json.loads(filename.read_text())
        self.manifest.update(status='FROZEN_E3', formal_dispatch=True)
        self.rows = [dict(row, status='RECORDED', episode_directory='/not-a-measurement/'+row['job_id'])
            for part in self.manifest['global_release_parts'] for row in plan(self.manifest, part)]

    def inspect(self, rows):
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory)/'search_index.json'
            filename.write_text(json.dumps(rows))
            return inspect_indices(self.manifest, [filename])

    def test_every_part_must_be_present_even_when_other_searches_sealed(self):
        self.assertEqual(len(self.inspect(self.rows)), 1730)
        with self.assertRaisesRegex(ValueError, 'Missing'):
            self.inspect([r for r in self.rows if r['part'] != 'fidelity'])

    def test_not_run_or_duplicate_does_not_open_test_oracle(self):
        pending = copy.deepcopy(self.rows);pending[-1]['status'] = 'NOT_RUN'
        with self.assertRaisesRegex(ValueError, 'Every declared'):
            self.inspect(pending)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.inspect(self.rows+[self.rows[0]])

    def test_signal_variants_have_distinct_fixed_identities(self):
        rows = plan(self.manifest, 'signals')
        self.assertEqual(len({identity(row) for row in rows}), 80)
        bad = copy.deepcopy(self.rows)
        bad[0]['selection_seed'] += 1
        with self.assertRaisesRegex(ValueError, 'seed'):
            self.inspect(bad)


if __name__ == '__main__':
    unittest.main()
