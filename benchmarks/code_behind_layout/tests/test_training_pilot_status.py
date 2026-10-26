"""Inventory deduplicates actual admitted program pairs rather than diff text."""
import argparse
import json
from pathlib import Path
import tempfile
import unittest

from scripts.training_pilot_status import admission_inventory, main


class TrainingPilotInventoryTests(unittest.TestCase):
    def fixture(self, root, name, *, reverse_family=False, version=None, comment=''):
        pack = root / 'pack'
        original = {'textbook_sharing/layout.py': 'value = 0\n',
                    'glayout/sharing/enumeration.py': 'def plans():\n    return []\n'}
        for path, source in original.items():
            target = pack / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source)
        raw = root / name
        derived = root / (name + '_custom_current_directory')
        raw.mkdir(); derived.mkdir()
        def save(path, value):
            path.write_text(json.dumps(value))
        rule = {'status': 'frozen', 'version': name}
        if version:
            rule['sft_selection'] = {'version': version}
        save(raw / 'rule.json', rule)
        save(raw / 'collection_manifest.json', {'source_pack': str(pack), 'label_rule_path': str(raw / 'rule.json')})
        save(raw / 'effective_registry.json', {'configurations': [
            {'parameters': {'circuit': {'circuit_id': 'C01'}, 'sizing': {'w': 3}}}]})
        base = {'textbook_sharing/layout.py': original['textbook_sharing/layout.py']}
        state = name + '_state'
        context = json.dumps({'base_source': base, 'visible_contract': {'contract': {'objective': 'area'}},
                              'visible_feedback': []})
        candidates = [{'candidate_id': name + suffix, 'candidate_patch': name + suffix + comment,
                       'initial_state_id': state, 'base_source': base,
                       'candidate_source': {'textbook_sharing/layout.py': f'value = {number}\n' + comment}}
                      for suffix, number in (('_A', 1), ('_B', 2))]
        (raw / 'candidates.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in candidates))
        common = {'initial_state_id': state, 'context': context, 'source_role': 'formal_train'}
        sft = {**common, 'candidate_id': candidates[0]['candidate_id'], 'patch': candidates[0]['candidate_patch']}
        pair = {**common, 'pair_id': name, 'chosen_candidate_id': candidates[0]['candidate_id'],
                'rejected_candidate_id': candidates[1]['candidate_id'],
                'chosen': candidates[0]['candidate_patch'], 'rejected': candidates[1]['candidate_patch']}
        opposite = {**pair, 'chosen': pair['rejected'], 'rejected': pair['chosen'],
                    'chosen_candidate_id': pair['rejected_candidate_id'],
                    'rejected_candidate_id': pair['chosen_candidate_id']}
        for method, row in [('T1', sft), ('T2', sft), ('T3', pair),
                            ('T4', opposite if reverse_family else pair)]:
            (derived / (method + '.jsonl')).write_text(json.dumps({'raw_sample': row}) + '\n')
        save(derived / 'physical_readmission.json', {'status': 'RE_ADMITTED_FROM_RAW'})
        save(derived / 'student_selection.json', {'raw_evidence_re_admitted': True,
            'raw_collection_root': str(raw), 'collection_scope': {'original_planned_proposals': 24,
                'selected_returned_proposals': 16, 'original_remaining_unrun_or_unselected_proposals': 8,
                'whole_collection_claimed_complete': False}})
        return raw, derived

    def test_same_complete_program_pair_is_counted_once_across_diff_text_and_methods(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, first = self.fixture(root, 'teacher_one', reverse_family=True)
            _, second = self.fixture(root, 'teacher_two', reverse_family=True, comment='# formatting only\n')
            report = admission_inventory([first, second, first])
            result = report['selection_cohorts']['unique_best_v1']
            self.assertEqual(result['unique_useful_student_initial_contexts_after_current_gate'], 1)
            self.assertEqual(result['unique_usable_DPO_pairs_after_current_gate'], 1)
            self.assertEqual(result['Point_Family_opposite_pairs_by_physical_problem'], 1)
            self.assertEqual(result['raw_usable_rows_by_method_before_cross_pool_dedup']['T3'], 2)
            self.assertEqual(len(report['derived_pools']), 2)

    def test_label_versions_are_alternatives_and_interrupted_raw_stays_without_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw, first = self.fixture(root, 'v1')
            _, second = self.fixture(root, 'v2', version='equivalent_best_earliest_actual_trial_v2')
            report = admission_inventory([first, second])
            self.assertEqual(len(report['selection_cohorts']), 2)
            for count in report['selection_cohorts'].values():
                self.assertEqual(count['unique_usable_DPO_pairs_after_current_gate'], 1)
            self.assertFalse((raw / 'completion.json').exists())
            self.assertIsNone(report['derived_pools'][0]['raw_completion'])
            self.assertEqual(report['derived_pools'][0]['collection_scope']['selected_returned_proposals'], 16)

    def test_a_derived_patch_cannot_be_bound_to_another_terminal_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            _, derived = self.fixture(Path(directory), 'binding')
            row = json.loads((derived / 'T3.jsonl').read_text())
            row['raw_sample']['chosen'] = 'different actual patch'
            (derived / 'T3.jsonl').write_text(json.dumps(row) + '\n')
            with self.assertRaisesRegex(ValueError, 'actual admitted candidate'):
                admission_inventory([derived])

    def test_explicit_index_includes_custom_readmission_directory_without_legacy_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, derived = self.fixture(root, 'custom')
            index = root / 'index.json'; output = root / 'report.json'
            index.write_text(json.dumps({'derived_directories': [str(derived)]}))
            main(argparse.Namespace(admission_directory=[], admission_index=index,
                                    admissions_only=True, output=output))
            report = json.loads(output.read_text())
            self.assertEqual(report['selection_cohorts']['unique_best_v1']['unique_usable_DPO_pairs_after_current_gate'], 1)
            self.assertEqual(report['new_physical_calls'], 0)


if __name__ == '__main__':
    unittest.main()
