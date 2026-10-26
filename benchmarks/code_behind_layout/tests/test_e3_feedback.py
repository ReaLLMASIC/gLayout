import copy
import unittest

from src.e3_feedback import compact, expand


class FeedbackTests(unittest.TestCase):
    def test_all_numbers_units_states_and_diagnostics_roundtrip(self):
        feedback = {'checks': {'drc': True}, 'diagnostic_samples': {'generation': 'trace'},
            'corners': {name: {'converged': True, 'operating_point_valid': True,
                'metrics': {'power': {'value': 1.234567890123456e-5, 'unit': 'W'},
                            'gain': {'value': 42.12345678901234, 'unit': 'dB'}}}
                        for name in ('tt', 'ss', 'ff')}}
        before = copy.deepcopy(feedback)
        encoded = compact(feedback)
        self.assertNotIn('corners', encoded)
        self.assertEqual(expand(encoded), before)
        self.assertEqual(feedback, before)

    def test_inconsistent_units_or_missing_metrics_keep_full_original_feedback(self):
        feedback = {'corners': {'tt': {'metrics': {'gain': {'value': 2, 'unit': '1'}}},
                               'ss': {'metrics': {'gain': {'value': 6, 'unit': 'dB'}}}}}
        self.assertEqual(compact(feedback), feedback)
        del feedback['corners']['ss']['metrics']['gain']
        self.assertEqual(compact(feedback), feedback)


if __name__ == '__main__':
    unittest.main()
