"""Instance-interface software controls; no fixtures are physical measurements."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.e3_instance_episode import (CACHE, VERSION, WARM_START, InstanceGateway,
    choose_library, cumulative_costs, current_packet, exact_bindings, instance_settings, start_study, verify_cached)
from scripts.e3_episode import Gateway
from src.candidate_executor import IMAGE, PREFIX
from scripts.e3_instance_episode import ROOT


class InstanceConsumerTests(unittest.TestCase):
    def test_formal_study_without_shared_release_starts_no_candidate_or_arrival(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            budget = dict.fromkeys(('wall_seconds', 'decisions', 'patches', 'full_evaluations', 'maximum_context_tokens'), 1)
            budget['maximum_output_tokens'] = 1024
            manifest = {'status': 'FROZEN_E3', 'formal_dispatch': True, 'freeze_id': 'software_fixture',
                'hidden_release_file': str(root/'absent_release.json'), 'original_baseline_plan': str(root/'plan.json'),
                'instance_baseline': {'algorithm': VERSION, 'warm_start': WARM_START, 'cache': CACHE,
                    'deployment_verification_maximum_physical_calls': 1, 'budget': budget}}
            filename = root/'manifest.json';filename.write_text(json.dumps(manifest))
            with patch('scripts.e3_instance_episode.ROOT', root), patch('scripts.e3_instance_episode.verify') as verify, patch(
                    'scripts.e3_instance_episode.capsule') as candidate:
                with self.assertRaisesRegex(RuntimeError, 'Global hidden evaluation release is absent'):
                    start_study({'manifest': str(filename), 'formal': True, 'trial_id': '1', 'task_id': 'task'})
                verify.assert_not_called();candidate.assert_not_called()
            self.assertFalse((root/'runs').exists())

    def test_current_packet_excludes_future_domain_and_rebinds_graph(self):
        with tempfile.TemporaryDirectory() as temporary:
            reference = Path(temporary)/'reference.spice'
            reference.write_text('.subckt toy D G S B\nX0 D G S B sky130_fd_pr__nfet_01v8 w=3 l=1 m=2\n.ends toy\n')
            point = {'parameters': {'w': 3}, 'reference_file': str(reference),
                'contract': {'task_id': 'private_task', 'configuration_id': 'private_future_id',
                    'reference_id': 'private_future_reference', 'required_corners': ['tt']}}
            base = {'task_id': 'base', 'goal': 'base', 'contract': {}, 'allowed_paths': ['layout.py'],
                'visible_sources': {}, 'visible_configurations': ['future_secret_id'], 'budget': {},
                'documents': {'PDK': {'complete_rules': True}, 'visible_sizings': {'future_secret_id': {'w': 999}},
                    'family_relationship': {'future_secret_id': True}, 'intended_anchor_graph': {'old_graph': True}}}
            task = {'task_id': 'editing', 'editable_paths': ['layout.py'], 'top_cell': 'toy'}
            previous = [{'parameters': {'w': 2}, 'S2': True}]
            library = [{'library_id': 'own0', 'parameters': {'w': 2}, 'objective': 10.,
                'arrival_ordinal': 0, 'source_directory': '/private/backend/library'}]
            packet = current_packet(base, task, point, {'layout.py': 'complete module\n'}, 1,
                previous, library, {'full_evaluations': 3}, '2026-10-19T05:00:00+00:00')
            self.assertNotIn('future_secret_id', json.dumps(packet))
            self.assertNotIn('private_future_reference', json.dumps(packet))
            self.assertNotIn('/private/backend/library', json.dumps(packet))
            self.assertEqual(packet['visible_configurations'], ['current'])
            self.assertEqual(packet['contract']['configuration_id'], 'current')
            self.assertEqual(packet['documents']['intended_anchor_graph']['expanded_MOS_count'], 2)
            self.assertEqual(packet['documents']['past_arrivals']['rows'][0][1], previous[0]['parameters'])
            self.assertTrue(packet['documents']['past_arrivals']['rows'][0][4])
            self.assertEqual(packet['visible_sources']['layout.py'], 'complete module\n')
            self.assertEqual(packet['documents']['action_gateway']['read_source_paths'], list(packet['visible_sources']))

    def test_library_uses_all_retained_past_programs(self):
        entries = [{'library_index': 0, 'parameters': {'w': 2}},
            {'library_index': 1, 'parameters': {'w': 8}},
            {'library_index': 2, 'parameters': {'w': 2}}]
        self.assertIs(choose_library(entries, {'w': 2}), entries[2])
        self.assertIs(choose_library(entries, {'w': 8}), entries[1])
        self.assertEqual(len(entries), 3)

    def test_cache_binding_rejects_source_reference_and_PDK_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);run = root/'prior';trusted = root/'current_trusted'
            for path in (run/'source', run/'trusted', trusted):
                path.mkdir(parents=True)
            (run/'source/layout.py').write_bytes(b'actual source bytes\n')
            for path in (run/'trusted', trusted):
                (path/'evaluate.py').write_text('# software binding fixture\n')
                (path/'reference.spice').write_text('* software fixture, not a physical reference\n')
            configuration = {'parameters': {'w': 3}}
            (run/'configuration.json').write_text(json.dumps(configuration))
            point = {'configuration_id': 'z0', 'reference_id': 'r0'}
            runtime = str(ROOT/'runtime/GLdev')+':'+PREFIX+':ro'
            magic = str(ROOT/'runtime/magic-8.3.685')+':/work/runtime/magic-8.3.685:ro'
            manifest = {'fidelity': 'pex_spice', 'source_files': ['layout.py'], 'trusted_files': ['evaluate.py', 'reference.spice'],
                'context': {'pdk_revision': '0fe599b2afb6708d281543108caf8310912f54af', **point},
                'candidate': {'argv': [IMAGE, runtime]}, 'trusted': {'argv': [IMAGE, runtime, magic]}}
            path = run/'manifest.json';path.write_text(json.dumps(manifest))
            expected = {'layout.py': b'actual source bytes\n'}
            self.assertTrue(exact_bindings(run, expected, point, configuration, trusted))
            self.assertFalse(exact_bindings(run, {'layout.py': b'different source\n'}, point, configuration, trusted))
            (trusted/'reference.spice').write_text('* changed reference\n')
            self.assertFalse(exact_bindings(run, expected, point, configuration, trusted))
            (trusted/'reference.spice').write_bytes((run/'trusted/reference.spice').read_bytes())
            manifest['context']['pdk_revision'] = 'different';path.write_text(json.dumps(manifest))
            self.assertFalse(exact_bindings(run, expected, point, configuration, trusted))

    def test_incomplete_raw_inspection_cannot_be_a_cache_hit(self):
        with patch('scripts.e3_instance_episode.exact_bindings', return_value=True), patch(
            'scripts.e3_instance_episode.inspect_point', return_value={'execution_integrity': 'incomplete'}):
            self.assertIsNone(verify_cached({'run_directory': '/software_fixture'}, {},
                {'parameters': {}}, Path('/software_fixture')))

    def test_instance_budget_and_algorithm_are_explicit(self):
        budget = {key: 1 for key in ('wall_seconds', 'decisions', 'patches', 'full_evaluations', 'maximum_context_tokens')}
        budget['maximum_output_tokens'] = 1024
        manifest = {'instance_baseline': {'algorithm': VERSION, 'warm_start': WARM_START, 'cache': CACHE,
            'deployment_verification_maximum_physical_calls': 1, 'budget': budget}}
        self.assertEqual(instance_settings(manifest)['budget'], budget)
        manifest['instance_baseline']['budget']['maximum_output_tokens'] = 3072
        with self.assertRaises(ValueError):
            instance_settings(manifest)

    def test_feedback_omits_parser_paths_without_changing_raw(self):
        gateway = InstanceGateway.__new__(InstanceGateway)
        gateway.state = SimpleNamespace(value={'revision': 0, 'status': 'RUNNING'})
        gateway.packet = {'task_id': 'current_task', 'contract': {'reference_id': 'current_ref'}}
        row = {'checked': {'S0': True, 'S1': True, 'S2': True, 'execution_integrity': 'valid',
            'analysis_validation': {'tt': {'data_path': '/private/full/raw.dat'}}}, 'objective': 10.,
            'physical_feedback': {'corners': {'tt': {'metrics': {'area': {'unit': 'um2', 'value': 10.}}}}}}
        visible = gateway.feedback(row)
        self.assertNotIn('/private', json.dumps(visible))
        self.assertIn('analysis_validation', row['checked'])
        self.assertEqual(visible['physical_feedback']['corner_metric_table']['corners']['tt']['values'], [10.])

    def test_future_configuration_action_rejected_before_physical(self):
        gateway = InstanceGateway.__new__(InstanceGateway)
        gateway.state = SimpleNamespace(value={'sealed': False, 'status': 'RUNNING', 'decisions': 0})
        gateway.manifest = {'budget': {'decisions': 5}}
        gateway.packet = {'allowed_paths': ['layout.py'], 'visible_sources': {'layout.py': 'whole source'},
            'visible_configurations': ['current'], 'budget': {'deadline_utc': (datetime.now(timezone.utc)+timedelta(seconds=30)).isoformat()}}
        gateway.write = lambda: None
        proposal = {'action': 'request_evaluation', 'path': '', 'patch': '', 'configuration_ids': ['future'],
            'fidelity': 'pex_spice', 'summary': 'Software invalid request'}
        with self.assertRaises(ValueError):
            gateway.action(proposal)
        self.assertEqual(gateway.state.value['decisions'], 1)

    def test_unknown_instance_does_not_deploy(self):
        with tempfile.TemporaryDirectory() as temporary:
            gateway = InstanceGateway.__new__(InstanceGateway)
            gateway.out = Path(temporary);gateway.private = gateway.out/'private';gateway.private.mkdir()
            (gateway.out/'public').mkdir()
            (gateway.out/'public/search.json').write_text(json.dumps({'policy_statistics': {}}))
            gateway.state = SimpleNamespace(value={'sealed': True, 'deployment_started': False,
                'status': 'INCOMPLETE_UNKNOWN', 'physical_events': [], 'cache_events': [], 'resource_waits': []})
            with patch.object(Gateway, 'physical', side_effect=AssertionError('No physical dispatch allowed')):
                result = gateway.deploy()
            self.assertFalse(result['complete'])
            self.assertIsNone(result['objective'])

    def test_cache_lookup_cost_is_not_double_counted(self):
        arrival = {'costs_by_stage': {'search': {'physical_calls': 1, 'waited_child_CPU_seconds': 2.,
            'stage_wall_seconds': 4., 'missing_CPU_records': 0}},
            'policy_statistics': {'model_cli_invocations': 3, 'decision_step_attempts': 4},
            'preparation_cost': {'wall_seconds': 5., 'process_CPU_seconds': .4},
            'cache_events': [{'stage': 'arrival_cache_deployment_verification', 'wall_seconds': 2., 'process_CPU_seconds': .2},
                {'stage': 'deployment_verification', 'wall_seconds': .5, 'process_CPU_seconds': .1}],
            'resource_waits': [{'actual_wait_wall_seconds': 1.}]}
        result = cumulative_costs([arrival])
        self.assertEqual(result['preparation_wall_seconds'], 5.)
        self.assertEqual(result['additional_cache_wall_seconds'], .5)
        self.assertEqual(result['model_cli_invocations'], 3)
        self.assertIsNone(result['provider_queue_or_GPU_seconds'])


if __name__ == '__main__':
    unittest.main()
