"""Software fixtures only: no model service, Docker or physical result is invoked."""
import copy
from datetime import datetime, timedelta, timezone
import difflib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import evaluate_matched_t0_proposals as followup


class TokenizerFixture:
    eos_token_id = 0
    def apply_chat_template(self, *args, **kwargs):return [1]*5
    def __call__(self, text, **kwargs):return {'input_ids': [1]*len(text)}


def proposal_fixture(root, after='x=2\n'):
    base = {'layout.py': 'x=1\n'}
    context = {'initial_state_id': 'fixture_state', 'task_id': 'fixture_task', 'base_source': base,
        'materialized_task_packet': str(root/'task.json'), 'materialized_visible_history': str(root/'history.json')}
    request = {'task_packet': {'task_id': 'fixture_task', 'goal': 'software fixture', 'contract': {},
        'allowed_paths': ['layout.py'], 'visible_sources': base, 'documents': {}, 'visible_configurations': ['anchor'],
        'budget': {'maximum_context_tokens': 16384, 'maximum_output_tokens': 1024}}, 'visible_history': []}
    followup.save(root/'task.json', request['task_packet']);followup.save(root/'history.json', [])
    body = {'variant': 'T0', 'mode': followup.MODE, 'sampling': {'temperature': .7, 'top_p': .95, 'seed': 101}, 'request': request}
    action = {'action': 'propose_patch', 'path': 'layout.py', 'patch': ''.join(difflib.unified_diff(
        ['x=1\n'], after.splitlines(keepends=True), fromfile='a/layout.py', tofile='b/layout.py')),
        'configuration_ids': [], 'fidelity': '', 'summary': ''}
    usage = {'decoding_settings': {'do_sample': True, **body['sampling']}, 'request_mode': followup.MODE,
        'output_format': 'ordinary_action_json', 'maximum_context_tokens': 16384, 'max_new_tokens': 1024,
        'input_tokens': 5, 'output_tokens': len(json.dumps(action))+1, 'eos_terminated': True, 'server_wall_seconds': 1}
    model = {'variant': 'T0', 'base_revision': followup.REVISION, 'tokenizer_revision': followup.REVISION,
        'source_role': 'base_model_formal_train_action_proposals', 'adapter': None,
        'settings': {'quantization': 'NF4', 'double_quantization': True, 'compute_dtype': 'bfloat16',
            'attention_backend': 'sdpa', 'max_new_tokens': 1024, 'maximum_context_tokens': 16384}}
    response = {'inference_id': 'software_fixture_inference', 'native_tools': [], 'model': model, 'usage': usage,
        'action': action, 'raw_action_text': json.dumps(action)}
    attempt = {'initial_state_id': 'fixture_state', 'seed': 101, 'model_calls_attempted': 1,
        'inference_id': response['inference_id'], 'usage': copy.deepcopy(usage), 'model': copy.deepcopy(model),
        'http_status': 200, 'error': None, 'wall_seconds': 1.1}
    directory = root/'seed_101';directory.mkdir()
    for name, data in [('request', body), ('response', response), ('attempt', attempt), ('candidate_source', {'layout.py': after})]:
        followup.save(directory/(name+'.json'), data)
    return {'contexts': [context]}, context, directory


class MatchedT0PhysicalFollowupTests(unittest.TestCase):
    def test_exact_real_patch_replay_binds_full_source_and_preserves_raw(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan, context, directory = proposal_fixture(Path(temporary))
            before = {p.name: p.read_bytes() for p in directory.iterdir()}
            result = followup.verify_raw(plan, context, 101, directory, TokenizerFixture())
            self.assertEqual(result['status'], 'ELIGIBLE_UNIQUE_CHECK_PENDING')
            self.assertEqual(result['source'], {'layout.py': 'x=2\n'})
            self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir()})

    def test_changed_usage_or_matched_feedback_cannot_enter_physics(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan, context, directory = proposal_fixture(Path(temporary))
            response = followup.read(directory/'response.json');response['usage']['output_tokens'] += 1
            followup.save(directory/'response.json', response)
            with self.assertRaisesRegex(ValueError, 'usage binding'):
                followup.verify_raw(plan, context, 101, directory, TokenizerFixture())
            body = followup.read(directory/'request.json');body['request']['visible_history'] = [{'invented': 'feedback'}]
            followup.save(directory/'request.json', body)
            with self.assertRaisesRegex(ValueError, 'exact materialized'):
                followup.verify_raw(plan, context, 101, directory, TokenizerFixture())

    def test_raw_patch_never_repaired_and_semantic_noop_is_not_a_sample(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan, context, directory = proposal_fixture(Path(temporary), 'x = 1 # comment\n')
            self.assertEqual(followup.verify_raw(plan, context, 101, directory, TokenizerFixture())['status'], 'SEMANTIC_NOOP')
            response = followup.read(directory/'response.json')
            response['action']['patch'] = '--- a/layout.py\n+++ b/layout.py\n@@ -1,3 +1,3 @@\n-x=1\n+x=2\n'
            response['raw_action_text'] = json.dumps(response['action']);followup.save(directory/'response.json', response)
            result = followup.verify_raw(plan, context, 101, directory, TokenizerFixture())
            self.assertEqual(result['status'], 'INVALID_ORIGINAL_PATCH')
            self.assertIn('corrupt patch', result['stderr'])

    def test_trained_adapter_or_late_proposal_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan, context, directory = proposal_fixture(Path(temporary))
            response = followup.read(directory/'response.json');attempt = followup.read(directory/'attempt.json')
            response['model']['adapter'] = 'not_base';attempt['model'] = copy.deepcopy(response['model'])
            followup.save(directory/'response.json', response);followup.save(directory/'attempt.json', attempt)
            with self.assertRaisesRegex(ValueError, 'Actual T0'):
                followup.verify_raw(plan, context, 101, directory, TokenizerFixture())
            response['model']['adapter'] = None;attempt['model'] = copy.deepcopy(response['model']);attempt['wall_seconds'] = 241
            followup.save(directory/'response.json', response);followup.save(directory/'attempt.json', attempt)
            with self.assertRaisesRegex(ValueError, 'finite inference budget'):
                followup.verify_raw(plan, context, 101, directory, TokenizerFixture())

    def test_registry_merge_does_not_multiply_shared_lineage_and_rejects_config_collision(self):
        first = {'lineages': [{'lineage_id': 'shared', 'split': 'train'}], 'configurations': [{'configuration_id': 'c01'}]}
        second = {'lineages': copy.deepcopy(first['lineages']), 'configurations': [{'configuration_id': 'c02'}]}
        self.assertEqual(len(followup.merge_registries([first, second])['lineages']), 1)
        second['configurations'][0]['configuration_id'] = 'c01'
        with self.assertRaisesRegex(ValueError, 'IDs must remain distinct'):followup.merge_registries([first, second])

    def test_unknown_point_stops_new_calls_and_never_automatically_retries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);output = root/'output';output.mkdir()
            row = {'candidate_id': 'candidate', 'initial_state_id': 'state', 'parent_lineage': 'shared',
                'visible_contract': {'task_id': 'task'}, 'outcomes': [], 'candidate_source': {'layout.py': 'x=2\n'}}
            followup.save(output/'candidate.json', row)
            followup.save(output/'baseline.json', {name: {'evidence_path': name+'/manifest.json', 'baseline_candidate_id': 'base'} for name in ['p0', 'p1', 'p2']})
            cell = {'status': 'PHYSICAL_PENDING', 'candidate_file': 'candidate.json', 'baseline_adoption': 'baseline.json',
                'parent_collection': 'parent', 'points': [{'configuration_id': name, 'status': 'NOT_RUN'} for name in ['p0', 'p1', 'p2']]}
            state = {'status': 'RUNNING', 'deadline_utc': (datetime.now(timezone.utc)+timedelta(seconds=60)).isoformat(),
                'cells': [cell], 'resource_samples': []}
            registry = {'status': 'frozen', 'lineages': [{'lineage_id': 'shared', 'split': 'train', 'topology_family': 'fixture'}],
                'configurations': [{'configuration_id': name, 'parent_lineage': 'shared', 'contract': {'task_id': 'task'}, 'domain_role': 'anchor'} for name in ['p0', 'p1', 'p2']]}
            calls = []
            def point(*args):calls.append(args[1]['configuration_id']);return {'run_directory': str(root/'actual_fixture_return')}
            resources = lambda: {'available_disk_GiB': 10, 'actual_busy_cores': 0, 'RAM_used_GiB': 1}
            with patch.object(followup, 'ROOT', root), patch.object(followup.TrustedPhysicalStore, '_read_run', side_effect=ValueError('unknown physical fixture')):
                followup.physical_pass({}, {'parent': {}}, registry, state, output, sample=resources, execute_point=point)
                first = len(calls)
                self.assertEqual(state['status'], 'PAUSED_UNKNOWN')
                self.assertLessEqual(first, 2)
                followup.physical_pass({}, {'parent': {}}, registry, state, output, sample=resources, execute_point=point)
                self.assertEqual(len(calls), first)
            self.assertFalse((output/'T1.jsonl').exists())

    def test_reserved_orphan_is_unknown_and_original96_denominator_survives(self):
        definition = {'physical': {'maximum_dispatch_hours': 8}, 'contexts': [
            {'initial_state_id': str(n), 'parent_collection': 'parent'} for n in range(12)]}
        state = followup.initial_state(definition)
        state['cells'][0]['points'] = [{'configuration_id': 'p0', 'status': 'DISPATCH_RESERVED'}]
        followup.mark_orphaned_reservations(state)
        report = followup.completion(state)
        self.assertEqual(report['planned_proposals'], 96)
        self.assertEqual(report['original_proposal_status_counts'], {'NOT_RUN': 96})
        self.assertEqual(state['status'], 'PAUSED_UNKNOWN')
        self.assertEqual(report['actual_reserved_candidate_points'], 1)
        self.assertFalse(report['automatic_retry'])

    def test_actual_resource_thresholds_prevent_dispatch_until_finite_window_ends(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            registry = {'status': 'frozen', 'lineages': [{'lineage_id': 'shared', 'split': 'train', 'topology_family': 'fixture'}]}
            for resource in [
                {'available_disk_GiB': 10, 'actual_busy_cores': 23, 'RAM_used_GiB': 1},
                {'available_disk_GiB': 10, 'actual_busy_cores': 0, 'RAM_used_GiB': 191},
                {'available_disk_GiB': 3.9, 'actual_busy_cores': 0, 'RAM_used_GiB': 1}]:
                state = {'status': 'RUNNING', 'deadline_utc': (datetime.now(timezone.utc)+timedelta(milliseconds=5)).isoformat(),
                    'cells': [{'status': 'PHYSICAL_PENDING', 'points': [{'configuration_id': 'p0', 'status': 'NOT_RUN'}]}], 'resource_samples': []}
                with patch.object(followup.time, 'sleep'), patch.object(followup, 'point_call') as forbidden:
                    followup.physical_pass({}, {}, registry, state, output, sample=lambda: resource,
                        execute_point=forbidden)
                    forbidden.assert_not_called()
                self.assertEqual(state['cells'][0]['points'][0]['status'], 'NOT_RUN')

    def test_quarantine_invalidates_old_derived_metadata_without_rewriting_raw(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);(root/'T1.jsonl').write_text('retained prior derived bytes\n')
            followup.invalidate_derivation(root)
            self.assertEqual(followup.read(root/'trusted_evidence_manifest.json')['status'], 'quarantined')
            self.assertEqual((root/'T1.jsonl').read_text(), 'retained prior derived bytes\n')


if __name__ == '__main__':unittest.main()
