"""Software consumers of the parameter-only action boundary; no physical data."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.e3_parameter_episode import (CONTROL, Gateway, ParameterGateway, canonical,
    draw_controls, parse_controls, patch_action, post_search, start, validate_baseline)
from scripts.e3_parameter_binding_check import inspect as inspect_binding
from src.candidate_executor import apply_source_patch
from src.e3_episode_state import EpisodeState
from src.e3_parameters import interface
from src.model_adapter import validate_action


class ParameterConsumerTests(unittest.TestCase):
    def test_parameter_packet_replaces_stale_main_read_source_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);private = root/'episode/private';source = private/'revisions/000/source'
            source.mkdir(parents=True);(source/'layout.py').write_text('complete initial module\n')
            (private/'task.json').write_text(json.dumps({'task_id': 'software_fixture', 'target': 'mirror',
                'editable_paths': ['layout.py'], 'parameter_controls': {'route_extension_multiplier': 3}}))
            (private/'state.json').write_text(json.dumps({'revision': 0}))
            manifest = root/'manifest.json'
            manifest.write_text(json.dumps({'parameter_baseline': {'configuration_selector': 'C',
                'strategies': ['random'], 'interface': 'prospective_expanded_layout_grid_v1'}}))
            initial = {'episode_directory': str(private.parent), 'packet': {'documents': {'action_gateway': {
                'read_source_paths': ['layout.py']}}, 'visible_sources': {'layout.py': 'complete initial module\n'}}}
            with patch('scripts.e3_parameter_episode.initialize', return_value=initial), patch(
                    'scripts.e3_parameter_episode.binding', return_value=({'version': 'software_fixture'}, {}, 'complete initial module\n')), patch(
                    'scripts.e3_parameter_episode.render', return_value='complete initial module\n'):
                result = start({'manifest': str(manifest), 'strategy': 'random', 'selection_seed': 41, 'formal': False})
            self.assertEqual(result['packet']['documents']['action_gateway']['read_source_paths'], [CONTROL])
            self.assertEqual(list(result['packet']['visible_sources']), [CONTROL])

    def test_formal_parameter_search_seals_without_dispatching_hidden(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with patch('scripts.e3_parameter_episode.transport', side_effect=AssertionError('No test oracle before global release')):
                result = post_search('/private/episode', output, {'status': 'SEARCH_FINISHED'}, True)
            self.assertFalse(result['hidden_dispatched'])
            self.assertEqual(result['post_freeze_status'], 'WAITING_GLOBAL_EVALUATION_RELEASE')
            self.assertTrue((output/'sealed_search.json').is_file())
            self.assertFalse((output/'episode.json').exists())

    def test_random_grid_is_reproducible_and_not_an_oracle(self):
        pdk = {'rules': {name: {name: {'min_width': minimum}} for name, minimum in
            [('met3', .14), ('met4', .3), ('met5', .3)]}}
        domain = interface('five_t', pdk)
        first = draw_controls(domain, 41, 0)
        self.assertEqual(first, draw_controls(domain, 41, 0))
        self.assertNotEqual(first, draw_controls(domain, 41, 1))
        self.assertEqual(set(first), set(domain['parameters']))
        for name, value in first.items():
            rule = domain['parameters'][name]
            self.assertGreaterEqual(value, rule['min'])
            self.assertLessEqual(value, rule['max'])

    def test_json_patch_can_only_change_parameter_file(self):
        before, after = canonical({'route_extension_multiplier': 3}), canonical({'route_extension_multiplier': 5})
        proposal = patch_action(before, after, 'Software fixture')
        packet = {'allowed_paths': [CONTROL], 'visible_sources': {CONTROL: before}, 'visible_configurations': ['anchor']}
        validate_action(proposal, packet)
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            (source/CONTROL).write_text(before)
            apply_source_patch(source, proposal['patch'], [CONTROL])
            self.assertEqual(parse_controls((source/CONTROL).read_text()), {'route_extension_multiplier': 5})
        proposal['patch'] = proposal['patch'].replace(CONTROL, 'src/generators/five_t.py')
        with self.assertRaises(ValueError):
            validate_action(proposal, packet)
        with self.assertRaises(ValueError):
            parse_controls('{"width":1,"width":2}')

    def test_C_selector_must_be_explicit_and_preserved(self):
        manifest = {'parameter_baseline': {'configuration_selector': 'C',
            'strategies': ['random', 'gpt_feedback'], 'interface': 'prospective_expanded_layout_grid_v1'}}
        self.assertEqual(validate_baseline(manifest, 'gpt_feedback')['configuration_selector'], 'C')
        del manifest['parameter_baseline']['configuration_selector']
        with self.assertRaises(KeyError):
            validate_baseline(manifest, 'random')

    def test_binding_reads_actual_prepared_source_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdk = root/'pdk.json';pdk.write_text(json.dumps({'rules': {}}))
            original = root/'original.py'
            original.write_text('def build():\n    route(extension=3*maxmet_sep)\n    route(extension=3*maxmet_sep)\n')
            initial = root/'initial.py';initial.write_bytes(original.read_bytes())
            task = {'task_id': 'software_fixture', 'target': 'mirror', 'editable_paths': ['layout.py'],
                'parameter_controls': {'route_extension_multiplier': 3}, 'source_overrides': {'layout.py': str(initial)},
                'expanded_parameter_baseline': {**interface('mirror', {'rules': {}}),
                    'frozen_PDK_rules': str(pdk), 'immutable_original_module': str(original)}}
            path = root/'task.json';path.write_text(json.dumps(task))
            self.assertTrue(inspect_binding(path)['source_bytes_identical'])
            initial.write_text(initial.read_text()+'# actual bytes differ\n')
            self.assertFalse(inspect_binding(path)['source_bytes_identical'])

    def test_post_freeze_uses_current_aggregate_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            gateway = ParameterGateway.__new__(ParameterGateway)
            gateway.out = Path(temporary);(gateway.out/'public').mkdir()
            gateway.costs = lambda: {}
            for incomplete, passed in [(0, 12), (16, 0)]:
                aggregate = {'hidden_domain_size': 16, 'hidden_incomplete': incomplete,
                    'hidden_S2_verified': passed, 'hidden_point_records_exported': False,
                    'post_freeze_complete': incomplete == 0}
                with patch.object(Gateway, 'post_freeze', return_value=aggregate):
                    result = gateway.post_freeze()
                self.assertEqual(result['hidden'], {'declared': 16, 'known': 16-incomplete, 'S2_passed': passed})
                self.assertNotIn('selected_source_evaluation', result)

    def test_random_schedule_evaluates_anchor_then_shared_selector(self):
        points = [{'configuration_id': name, 'role': 'anchor' if i == 0 else 'development',
            'parameters': {'W': i+1.}} for i, name in enumerate(['anchor', 'dev1', 'dev2'])]
        gateway = ParameterGateway.__new__(ParameterGateway)
        gateway.state = EpisodeState('B', points, 41, 'min')
        value = gateway.state.value
        value.update(parameter_strategy='random', parameter_prior_retained={'0': []},
            parameter_draw_index=0, parameter_seed=41, patch_attempts=0)
        gateway.packet = {'budget': {'deadline_utc': (datetime.now(timezone.utc)+timedelta(seconds=30)).isoformat()}}
        gateway.manifest = {'budget': {'patches': 3}}
        gateway.domain = {'parameters': {'route_extension_multiplier': {'min': .5, 'max': 12, 'step': .05}}}
        gateway.write = lambda: None
        gateway.sources = lambda: {CONTROL: canonical({'route_extension_multiplier': 3})}
        self.assertEqual(gateway.random_action()['configuration_ids'], ['anchor'])
        gateway.state.observe({'configuration_id': 'anchor', 'objective': 100.,
            'checked': {'execution_integrity': 'valid', 'S2': True}})
        selected = gateway.random_action()
        self.assertEqual(selected['action'], 'request_evaluation')
        self.assertNotEqual(selected['configuration_ids'], ['anchor'])
        gateway.state.observe({'configuration_id': selected['configuration_ids'][0], 'objective': 102.,
            'checked': {'execution_integrity': 'valid', 'S2': True}})
        self.assertEqual(gateway.random_action()['action'], 'propose_patch')

    def test_transaction_renders_only_layout_and_preserves_rejected_attempt(self):
        original = ('def build():\n'
            '    device = mos(width=3, length=1, fingers=2)\n'
            '    first = route(extension=3*maxmet_sep)\n'
            '    second = route(extension=3*maxmet_sep)\n')
        points = [{'configuration_id': name, 'role': 'anchor' if i == 0 else 'development',
            'parameters': {'W': i+1.}} for i, name in enumerate(['anchor', 'dev1'])]
        with tempfile.TemporaryDirectory() as temporary:
            gateway = ParameterGateway.__new__(ParameterGateway)
            gateway.private = Path(temporary)
            gateway.task = {'target': 'mirror', 'editable_paths': ['layout.py']}
            gateway.pdk = {'rules': {}}
            gateway.original = original
            gateway.state = EpisodeState('B', points, 41, 'min')
            gateway.state.value.update(status='RUNNING', decisions=0, patch_attempts=0,
                parameter_attempts=[], parameter_prior_retained={'0': []},
                parameter_interface_cost={'renderer_wall_seconds': 0., 'renderer_process_CPU_seconds': 0.})
            gateway.manifest = {'budget': {'decisions': 10, 'patches': 3}}
            initial = canonical({'route_extension_multiplier': 3})
            gateway.packet = {'allowed_paths': [CONTROL], 'visible_sources': {CONTROL: initial},
                'visible_configurations': ['anchor', 'dev1'],
                'budget': {'deadline_utc': (datetime.now(timezone.utc)+timedelta(seconds=30)).isoformat()}}
            source = gateway.source()
            source.mkdir(parents=True)
            (source/'layout.py').write_text(original)
            (source/'generator.py').write_text('frozen export transport\n')
            controls = gateway.control_dir()
            controls.mkdir(parents=True)
            (controls/CONTROL).write_text(initial)
            with self.assertRaises(ValueError):
                gateway.action(patch_action(initial, canonical({'route_extension_multiplier': 5}), 'Too early fixture'))
            self.assertEqual(gateway.state.value['patch_attempts'], 0)
            gateway.state.observe({'configuration_id': 'anchor', 'objective': 100.,
                'checked': {'execution_integrity': 'valid', 'S2': True}})
            result = gateway.action(patch_action(initial, canonical({'route_extension_multiplier': 5}), 'Software fixture'))
            self.assertEqual(result['revision'], 1)
            actual = (gateway.source()/'layout.py').read_text()
            self.assertEqual(actual.count('extension=5*maxmet_sep'), 2)
            self.assertIn('mos(width=3, length=1, fingers=2)', actual)
            self.assertEqual((gateway.source()/'generator.py').read_text(), 'frozen export transport\n')
            self.assertEqual(sorted(p.name for p in gateway.source().iterdir()), ['generator.py', 'layout.py'])
            rejected = patch_action(gateway.sources()[CONTROL], canonical({'route_extension_multiplier': .51}), 'Off-grid fixture')
            with self.assertRaises(ValueError):
                gateway.action(rejected)
            self.assertEqual(gateway.state.value['revision'], 1)
            self.assertEqual(gateway.state.value['patch_attempts'], 2)
            self.assertEqual(gateway.state.value['parameter_attempts'][-1]['status'], 'REJECTED')
            self.assertFalse(gateway.control_dir(2).exists())
            self.assertEqual((gateway.source()/'layout.py').read_text(), actual)


if __name__ == '__main__':
    unittest.main()
