"""Declared legal grids keep each electrical matching pair internally identical."""
import copy
import json
from pathlib import Path
import unittest

from scripts.prepare_train_pair_nf_domains import ROOT, declare, reference
from scripts.corpus_matched_pair_ideal import qualified


class MatchedPairDomainTests(unittest.TestCase):
    def test_real_train_graphs_preserve_all_nine_pair_balanced_perfinger_references(self):
        for cid, folder in [('C02', 'c02_action_v1'), ('C07', 'c07_action_v1')]:
            registry = json.loads((ROOT / 'tests/fixtures/train_pair_nf_parent_anchors.json').read_text())['registries'][cid]
            domain = declare(cid, registry)
            self.assertEqual(len(domain['configurations']), 9)
            nf_grid = set()
            original = next(p for p in registry['configurations'] if p['domain_role'] == 'anchor')
            for point in domain['configurations']:
                sizes = point['parameters']['sizing']
                for left, right in domain['matched_pairs']:
                    self.assertEqual(sizes[left], sizes[right])
                    self.assertEqual(sizes[left]['w'] / sizes[left]['nf'], .5)
                nf_grid.add(tuple(sizes[pair[0]]['nf'] for pair in domain['matched_pairs']))
                text = reference(point['parameters']['circuit'], sizes, point['parameters']['top_cell'])
                self.assertEqual(sum(line.startswith('XM') for line in text.splitlines()), sum(size['nf'] for size in sizes.values()))
                self.assertEqual(point['contract']['specifications'], original['contract']['specifications'])
                self.assertEqual(point['contract']['nominal_operating_point'], original['contract']['nominal_operating_point'])
                self.assertEqual(point['contract']['analysis_contracts'], original['contract']['analysis_contracts'])
            self.assertEqual(nf_grid, {(a, b) for a in (4, 8, 12) for b in (4, 8, 12)})

    def test_a_complete_finite_ideal_vector_does_not_pass_missing_corners_or_metrics(self):
        contract = {'required_corners': ['tt', 'ss', 'ff'], 'specifications': [{'name': 'current_error', 'max': .05}]}
        values = {name: {'complete': True, 'operating_point_valid': True, 'metrics': {'current_error': .01}}
                  for name in contract['required_corners']}
        self.assertTrue(qualified(values, contract))
        incomplete = copy.deepcopy(values); incomplete.pop('ff')
        self.assertFalse(qualified(incomplete, contract))
        values['ss']['metrics'] = {}
        self.assertFalse(qualified(values, contract))


if __name__ == '__main__':
    unittest.main()
