"""Gateway boundary tests use explicit fake points, never physical evidence."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import e3_episode as runner
from src.e3_episode_state import EpisodeState


def action(kind, ids=None, diff=''):
    return {'action': kind, 'path': '', 'patch': diff, 'configuration_ids': ids or [],
        'fidelity': 'pex_spice' if kind == 'request_evaluation' else '', 'summary': 'test fixture'}


def make(directory):
    out = Path(directory)
    (out/'private/revisions/000/source').mkdir(parents=True)
    (out/'public').mkdir()
    source = out/'private/revisions/000/source/layout.py'
    source.write_text('value = 1\n')
    points = [{'configuration_id': ident, 'role': 'anchor' if ident == 'anchor' else 'development',
               'parameters': {'w': width}}
              for ident, width in [('anchor', 1), ('dev', 2)]]
    gateway = runner.Gateway.__new__(runner.Gateway)
    gateway.out = out
    gateway.private = out/'private'
    gateway.task = {'task_id': 'fixture', 'logical_group': 'fixture', 'merge_sensitivity_group': 'fixture',
        'editable_paths': ['layout.py'], 'configurations': points}
    gateway.manifest = {'budget': {'decisions': 10, 'patches': 2, 'full_evaluations': 3}}
    gateway.packet = {'visible_sources': {'layout.py': 'value = 1\n'}, 'allowed_paths': ['layout.py'],
        'visible_configurations': ['anchor', 'dev'],
        'budget': {'deadline_utc': (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}}
    gateway.state = EpisodeState('B', points, 41, 'min')
    gateway.state.value.update(status='RUNNING', decisions=0, patch_attempts=0, full_evaluations=0,
        in_flight=None, physical_events=[], post_freeze_started=False, formal_trial=False)
    return gateway


def point(ident='anchor', valid=True):
    return {'configuration_id': ident, 'checked': {'execution_integrity': 'valid' if valid else 'incomplete',
            'S0': True, 'S1': True, 'S2': valid}, 'objective': 20 if valid else None,
        'physical_feedback': {'status': 'EXPLICIT_SOFTWARE_FIXTURE'}}


class GatewayTests(unittest.TestCase):
    def test_formal_trial_cannot_change_its_frozen_selection_seed(self):
        manifest = {'status': 'FROZEN_E3', 'formal_dispatch': True,
            'fidelity_policy': 'F0_actual_full_each_selected_configuration',
            'task_ids': ['fixture'], 'selection_seeds': [41, 73, 109, 167, 223]}
        with patch.object(runner, 'read', return_value=manifest), patch.object(runner, 'verify'):
            for trial, seed in [('1', 73), ('development', 41), ('6', 41)]:
                with self.assertRaisesRegex(ValueError, 'trial identity'):
                    runner.initialize({'manifest': 'fixture.json', 'task_id': 'fixture',
                        'method': 'A', 'formal': True, 'trial_id': trial, 'selection_seed': seed})

    def test_real_anchor_required_and_rejected_check_spends_no_physical_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = make(directory)
            with self.assertRaisesRegex(ValueError, 'original anchor'):
                gateway.action(action('propose_patch', diff='--- a/layout.py\n+++ b/layout.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n'))
            with patch.object(gateway, 'physical') as physical:
                with self.assertRaisesRegex(ValueError, 'Controlled next check'):
                    gateway.action(action('request_evaluation', ['dev']))
                physical.assert_not_called()
            self.assertEqual(gateway.state.value['full_evaluations'], 0)

    def test_patch_changes_complete_revision_and_invalidates_old_outcomes(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = make(directory)
            gateway.state.observe(point())
            gateway.action(action('propose_patch', diff='--- a/layout.py\n+++ b/layout.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n'))
            self.assertEqual(gateway.sources(), {'layout.py': 'value = 2\n'})
            self.assertEqual(gateway.state.current()['results'], {})
            self.assertEqual(gateway.next(), 'anchor')
            self.assertEqual((gateway.source(0)/'layout.py').read_text(), 'value = 1\n')

    def test_hidden_waits_for_seal_and_unknown_never_dispatches_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = make(directory)
            with self.assertRaisesRegex(ValueError, 'sealed'):
                gateway.post_freeze()
            gateway.seal('INCOMPLETE_UNKNOWN', {})
            with patch.object(gateway, 'physical') as physical:
                report = gateway.post_freeze()
                physical.assert_not_called()
            self.assertFalse(report['post_freeze_complete'])
            self.assertEqual(report['hidden_incomplete'], 16)
            with self.assertRaisesRegex(ValueError, 'runs once'):
                gateway.post_freeze()

    def test_hidden_rows_stay_private_and_only_aggregate_leaves_gateway(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = make(directory)
            gateway.task['configurations'] += [{'configuration_id': 'private_hidden', 'role': 'hidden'}]
            gateway.state.observe(point())
            gateway.seal('SEARCH_FINISHED', {})
            with patch.object(gateway, 'physical', side_effect=lambda ident, revision, stage: point(ident)):
                report = gateway.post_freeze()
            self.assertNotIn('private_hidden', json.dumps(report))
            raw = json.loads((gateway.private/'post_freeze_points.json').read_text())
            self.assertEqual(raw[-1]['configuration_id'], 'private_hidden')
            self.assertFalse(report['hidden_point_records_exported'])

    def test_post_evaluation_persists_unknown_and_leaves_remaining_points_not_run(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = make(directory)
            gateway.task['configurations'] += [{'configuration_id': 'hidden_%02d' % n,
                'role': 'hidden'} for n in range(16)]
            gateway.state.observe(point())
            gateway.seal('SEARCH_FINISHED', {})
            unknown = point('anchor')
            unknown['checked'].update(execution_integrity='incomplete', S1=False, S2=False)
            with patch.object(gateway, 'physical', return_value=unknown) as physical:
                report = gateway.post_freeze()
            self.assertEqual(physical.call_count, 1)
            self.assertEqual(report['hidden_incomplete'], 16)
            self.assertFalse(report['post_freeze_complete'])
            self.assertEqual(report['post_freeze_points_NOT_RUN'], len(gateway.task['configurations'])-1)
            self.assertEqual(len(json.loads((gateway.private/'post_freeze_points.json').read_text())), 1)


if __name__ == '__main__':
    unittest.main()
