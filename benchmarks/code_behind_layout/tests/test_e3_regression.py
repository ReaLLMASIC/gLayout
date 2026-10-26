import unittest

from src.e3_regression import summarize


def row(ident, passed, valid=True):
    return {'configuration_id': ident, 'checked': {'S2': passed,
        'execution_integrity': 'valid' if valid else 'incomplete'}}


class RegressionTests(unittest.TestCase):
    def test_original_failures_do_not_enter_regression_denominator(self):
        points = [{'configuration_id': name, 'role': 'hidden'} for name in ('a', 'b', 'c')]
        result = summarize(points, [row('a', True), row('b', False), row('c', True)],
            [row('a', False), row('b', False), row('c', True)])
        hidden = result['groups']['hidden']
        self.assertEqual(hidden['original_verified_S2'], 2)
        self.assertEqual(hidden['verified_regressions'], 1)
        self.assertEqual(hidden['regression_rate'], .5)
        self.assertNotIn('configuration_id', str(result))

    def test_unknown_original_and_selected_remain_unknown(self):
        points = [{'configuration_id': name, 'role': 'hidden'} for name in ('a', 'b')]
        result = summarize(points, [row('a', True), row('b', False, False)], [row('a', False, False)])
        hidden = result['groups']['hidden']
        self.assertEqual(result['status'], 'INCOMPLETE_UNKNOWN')
        self.assertIsNone(hidden['regression_rate'])
        self.assertEqual(hidden['conditional_on_known_original_passes_identification_bounds'], [0, 1])
        self.assertEqual(hidden['original_unknown'], 1)
        self.assertEqual(hidden['verified_regressions'], 0)

    def test_absent_original_passes_are_undefined_and_duplicates_rejected(self):
        points = [{'configuration_id': 'a', 'role': 'hidden'}]
        result = summarize(points, [row('a', False)], [row('a', True)])
        self.assertIsNone(result['groups']['hidden']['regression_rate'])
        with self.assertRaises(ValueError):
            summarize(points, [row('a', True), row('a', True)], [])


if __name__ == '__main__':
    unittest.main()
