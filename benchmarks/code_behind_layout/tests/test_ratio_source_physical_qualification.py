"""Interface/graph fixtures only; none are measured physical results."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.ratio_source_physical_probe import physical_wrapper, contracted_rc_devices, completed_corner_summary
from src.train_generators.ratio_source_intent import point, reference_spice
from src.device_intent import compare_device_intent
import scripts.ratio_source_physical_qualification as qualification
import scripts.ratio_source_pad_then_qualification as pad_gate


class RatioPhysicalInterfaceTests(unittest.TestCase):
    def test_wrapper_uses_actual_named_order_without_changing_original_top(self):
        text = physical_wrapper('/fixture/full.spice', 'ratio_rc', ['IOUT2', 'IREF', 'VSS', 'IOUT1'],
            'ratio_cs_k2_r1', ['VSS', 'IREF', 'IOUT1', 'IOUT2'])
        self.assertIn('.subckt ratio_cs_k2_r1 VSS IREF IOUT1 IOUT2', text)
        self.assertIn('Xphysical IOUT2 IREF VSS IOUT1 ratio_rc', text)
        with self.assertRaises(ValueError):
            physical_wrapper('/fixture/full.spice', 'ratio_rc', ['IOUT2', 'IREF', 'VSS'], 'ratio',
                ['VSS', 'IREF', 'IOUT1', 'IOUT2'])

    def fixture_rc(self):
        gold = reference_spice(point(2, 1)); lines = gold.splitlines()
        lines[0] = '.subckt ratio_rc VSS IREF IOUT1 IOUT2'
        for index, line in enumerate(lines):
            if line.startswith('X'):
                fields = line.split(); fields[1:5] = [n + '_metal' for n in fields[1:5]]; lines[index] = ' '.join(fields)
        return '\n'.join(lines[:-1] + ['Rwire' + p + ' ' + p + ' ' + p + '_metal 5' for p in ['VSS', 'IREF', 'IOUT1', 'IOUT2']]
            + ['Cphysical IOUT1 VSS 1f', '.ends ratio_rc', '']), gold

    @unittest.skipUnless(importlib.util.find_spec('networkx'), 'Full exact graph test requires the installed EDA environment networkx')
    def test_positive_rc_graph_keeps_each_finger_and_body(self):
        rc, gold = self.fixture_rc()
        view = contracted_rc_devices(rc, 'ratio_rc', ['VSS', 'IREF', 'IOUT1', 'IOUT2'])
        self.assertTrue(compare_device_intent(view, gold)['is_clean'])
        broken = rc.replace('XMOUT1_f0 IOUT1_metal IREF_metal VSS_metal VSS_metal',
            'XMOUT1_f0 IOUT1_metal IREF_metal VSS_metal IOUT1_metal')
        view = contracted_rc_devices(broken, 'ratio_rc', ['VSS', 'IREF', 'IOUT1', 'IOUT2'])
        self.assertFalse(compare_device_intent(view, gold)['is_clean'])

    def test_total_positive_rc_cannot_hide_a_missing_finger_or_port_short(self):
        rc, gold = self.fixture_rc()
        missing = '\n'.join(line for line in rc.splitlines() if not line.startswith('XMOUT2_f1 '))
        view = contracted_rc_devices(missing, 'ratio_rc', ['VSS', 'IREF', 'IOUT1', 'IOUT2'])
        self.assertFalse(compare_device_intent(view, gold)['is_clean'])
        with self.assertRaises(ValueError):
            contracted_rc_devices(rc.replace('Cphysical', 'Rshort IOUT1 IOUT2 1\nCphysical'),
                'ratio_rc', ['VSS', 'IREF', 'IOUT1', 'IOUT2'])


class RatioCompletionSemanticsTests(unittest.TestCase):
    def corners(self, passed=True):
        return {name: {'complete': True, 'ideal_application_constraints_pass': passed}
                for name in ('tt', 'ss', 'ff')}

    def test_all_complete_passing_corners_are_S2(self):
        self.assertEqual(completed_corner_summary(self.corners(), ['tt', 'ss', 'ff']),
            {'analysis_complete': True, 'S2': True, 'status': 'COMPLETE'})

    def test_complete_performance_rejection_remains_known(self):
        self.assertEqual(completed_corner_summary(self.corners(False), ['tt', 'ss', 'ff']),
            {'analysis_complete': True, 'S2': False, 'status': 'COMPLETE'})

    def test_partial_missing_empty_or_extra_corners_are_unknown(self):
        incomplete = self.corners(); incomplete['ss']['complete'] = False
        extra = self.corners(); extra['fs'] = {'complete': True, 'ideal_application_constraints_pass': True}
        for corners in (incomplete, {'tt': self.corners()['tt']}, {}, extra):
            self.assertEqual(completed_corner_summary(corners, ['tt', 'ss', 'ff']),
                {'analysis_complete': False, 'S2': False, 'status': 'UNESTABLISHED_UNKNOWN'})


class RatioPhysicalDispatchTests(unittest.TestCase):
    def run_fixture(self, result_status):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); prepared = root / 'prepared'; prepared.mkdir()
            points = qualification.fixed_points()
            (prepared / 'physical_plan.json').write_text(json.dumps({'original_ideal_run': '/fixture/ideal',
                'configurations': points, 'source_files': [], 'vendor_revision': 'fixture',
                'fixed_order': [p['configuration_id'] for p in points],
                'new_dispatch_resource_gate_horizon_s_from_plan_start': 3600}))
            raw = root / 'raw'; raw.mkdir()
            if result_status is not None:
                (raw / 'physical_qualification.json').write_text(json.dumps({'status': result_status, 'S2': False}))

            def execute(command, **kwargs):
                kwargs['stdout'].write(json.dumps({'run_id': 'software_fixture', 'output': str(raw)}) + '\n')
                return type('Process', (), {'returncode': 0})()

            with patch.object(qualification, 'ROOT', root), patch.object(qualification, 'SOURCES', []), \
                    patch.object(qualification, 'ideal_binding'), \
                    patch.object(qualification, 'resource_gate', return_value={'fixture': True}), \
                    patch.object(qualification.subprocess, 'check_output', return_value='fixture'), \
                    patch.object(qualification.subprocess, 'run', side_effect=execute) as run:
                result = qualification.run(prepared, root / 'output')
                state = json.loads((root / 'output/state.json').read_text())
                return result, state, run.call_count

    def test_unknown_or_missing_actual_result_stops_remaining_without_retry(self):
        for status in [None, 'UNESTABLISHED_UNKNOWN']:
            result, state, calls = self.run_fixture(status)
            self.assertEqual(result['status'], 'PAUSED_UNKNOWN_NO_RETRY')
            self.assertEqual(calls, 1)
            self.assertEqual(len(state['not_started']), 8)
            self.assertTrue(all(r['status'] == 'NOT_RUN' for r in state['not_run_dispositions']))
            self.assertEqual(len(state['records']), 1)

    def test_completed_physical_rejections_keep_the_fixed_nine_denominator(self):
        result, state, calls = self.run_fixture('COMPLETE_PHYSICAL_REJECTION')
        self.assertEqual(result['status'], 'COMPLETED_FIXED_NINE_PHYSICAL_ATTEMPTS')
        self.assertEqual(calls, 9)
        self.assertEqual(len(state['records']), 9)
        self.assertEqual(state['not_started'], [])

    def test_expired_gate_returns_without_sampling_or_launch(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(qualification.time, 'monotonic', return_value=3601):
            self.assertIsNone(qualification.resource_gate(Path(tmp), 3600))
            result = json.loads((Path(tmp) / 'resource_gate_latest.json').read_text())
            self.assertFalse(result['new_job_dispatched'])


class RatioPadGateTests(unittest.TestCase):
    def gate_fixture(self, passed):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); raw = root / 'raw'; raw.mkdir()
            (raw / 'pad_smoke.json').write_text(json.dumps({'passed': passed,
                'new_tool_calls': {'GDS_generation': 1, 'DRC': 0, 'LVS': 0, 'PEX': 0, 'SPICE': 0}}))
            (raw / 'resource_usage.json').write_text(json.dumps({'scope': 'software_fixture_no_physical_run'}))
            def execute(command, **kwargs):
                kwargs['stdout'].write(json.dumps({'run_id': 'software_fixture', 'output': str(raw)}) + '\n')
                return type('Process', (), {'returncode': 0})()
            with patch.object(pad_gate, 'ROOT', root), \
                    patch.object(pad_gate, 'resource_gate', return_value={'fixture': True}), \
                    patch.object(pad_gate.subprocess, 'run', side_effect=execute) as generate, \
                    patch.object(pad_gate, 'run', return_value={'status': 'SOFTWARE_FIXTURE'}) as full:
                result = pad_gate.main(root / 'prepared', root / 'nine', root / 'controls')
                return result, generate.call_count, full.call_count

    def test_incorrect_actual_pad_layer_blocks_all_full_dispatch(self):
        result, generations, full = self.gate_fixture(False)
        self.assertEqual(generations, 1)
        self.assertEqual(full, 0)
        self.assertEqual(result['status'], 'PAUSED_S0_GEOMETRY_UNKNOWN_OR_FAILED_NO_FULL_DISPATCH')

    def test_verified_fresh_pad_control_allows_only_one_fixed_nine_consumer(self):
        result, generations, full = self.gate_fixture(True)
        self.assertEqual(generations, 1)
        self.assertEqual(full, 1)
        self.assertEqual(result['status'], 'FIXED_NINE_RETURNED')


if __name__ == '__main__':
    unittest.main()
