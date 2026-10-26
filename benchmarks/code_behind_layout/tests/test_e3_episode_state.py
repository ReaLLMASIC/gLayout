import copy
import unittest

from src.e3_episode_state import EpisodeState


POINTS = [{'configuration_id': name, 'role': 'anchor' if name == 'anchor' else 'development',
           'parameters': {'width': width, 'length': 1}}
          for name, width in [('anchor', 2), ('lo', 1), ('hi', 3)]]


def outcome(ident, passed=True, objective=20):
    return {'configuration_id': ident, 'checked': {'S2': passed, 'execution_integrity': 'valid'},
            'objective': objective if passed else None}


class ControlledEpisodeStateTest(unittest.TestCase):
    def test_deferred_points_do_not_skip_retained_checks_or_become_labels(self):
        state = EpisodeState('B', POINTS, 41, 'min')
        self.assertEqual(state.next_configuration(excluded=['anchor', 'lo']), 'anchor')
        state.observe(outcome('anchor'))
        self.assertEqual(state.next_configuration(excluded=['lo']), 'hi')
        self.assertNotIn('lo', state.current()['results'])
        self.assertEqual(state.value['counterexamples'], [])
        self.assertEqual(state.value['required_passes'], ['anchor'])
        state.observe(outcome('lo', False))
        state.new_revision()
        state.observe(outcome('anchor'))
        self.assertEqual(state.next_configuration(excluded=['lo']), 'lo')
        with self.assertRaisesRegex(ValueError, 'public'):
            state.next_configuration(excluded=['hidden_01'])

    def test_edit_invalidates_results_and_retains_both_failure_and_pass_checks(self):
        state = EpisodeState('B', POINTS, 41, 'min')
        state.observe(outcome('anchor'))
        state.observe(outcome('lo', False))
        state.new_revision()
        self.assertEqual(state.current()['results'], {})
        self.assertEqual(state.next_configuration(), 'anchor')
        state.observe(outcome('anchor', objective=19))
        self.assertEqual(state.next_configuration(), 'lo')
        state.observe(outcome('lo', objective=18))
        self.assertEqual(state.next_configuration(), 'hi')

    def test_unrechecked_high_quality_patch_cannot_win_selection(self):
        state = EpisodeState('R', POINTS, 73, 'min')
        state.observe(outcome('anchor'))
        state.observe(outcome('lo'))
        state.new_revision()
        state.observe(outcome('anchor', objective=1))
        selected = state.select_source()
        self.assertEqual(selected['revision'], 0)
        self.assertTrue(selected['retained_checks_established'])
        with self.assertRaisesRegex(ValueError, 'sealed'):
            state.new_revision()

    def test_anchor_only_leaves_regression_budget_unspent(self):
        state = EpisodeState('A', POINTS, 109, 'max')
        state.observe(outcome('anchor'))
        self.assertIsNone(state.next_configuration())
        state.new_revision()
        self.assertEqual(state.next_configuration(), 'anchor')
        state.observe(outcome('anchor', objective=21))
        self.assertEqual(state.select_source()['revision'], 1)

    def test_better_anchor_cannot_hide_worse_retained_family_objective(self):
        state = EpisodeState('B', POINTS, 41, 'min')
        state.observe(outcome('anchor', objective=20))
        state.observe(outcome('lo', objective=20))
        state.new_revision()
        state.observe(outcome('anchor', objective=1))
        state.observe(outcome('lo', objective=50))
        self.assertEqual(state.select_source()['revision'], 0)

    def test_unknown_is_not_a_failure_or_automatic_retry(self):
        state = EpisodeState('B', POINTS, 41, 'min')
        invalid = outcome('anchor', False)
        invalid['checked']['execution_integrity'] = 'incomplete'
        with self.assertRaisesRegex(ValueError, 'reconciliation'):
            state.observe(invalid)
        self.assertEqual(state.value['counterexamples'], [])
        state.observe(outcome('anchor'))
        with self.assertRaisesRegex(ValueError, 'repeated'):
            state.observe(outcome('anchor'))
        with self.assertRaisesRegex(ValueError, 'Hidden'):
            state.observe(outcome('hidden_01'))

    def test_private_rows_and_unfitted_C_are_refused(self):
        hidden = copy.deepcopy(POINTS)
        hidden[-1]['role'] = 'hidden'
        with self.assertRaisesRegex(ValueError, 'Hidden'):
            EpisodeState('B', hidden, 41, 'min')
        with self.assertRaisesRegex(ValueError, 'frozen weights'):
            EpisodeState('C', POINTS, 41, 'min')


if __name__ == '__main__':
    unittest.main()
