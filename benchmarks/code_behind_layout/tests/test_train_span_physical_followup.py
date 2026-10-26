"""Software fixtures: no model, Docker, physical measurements or training."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts import evaluate_train_span_proposals as consumer
from src.train_span_proposer import MODE, ROLE, VERSION, teacher_request, proposal_prompt, compile_proposal, mapped_student_request
from src.student_interface import canonical_action
from src.model_adapter import prompt_token_budget
from tests import test_training_selection_v2 as selection_fixtures
from src.training_selection_v2 import make_rule


class TokenizerFixture:
    eos_token_id = 0
    def apply_chat_template(self, *args, **kwargs): return [1]*5
    def __call__(self, text, **kwargs): return {'input_ids': [1]*len(text)}


def raw_fixture(root, replacement='x=2\n', make_compiled=True):
    base = {'layout.py': 'x=1\n', 'enumeration.py': 'plans=[1,2]\n'}
    original = {'task_packet': {'task_id': 'raw_cohort__state', 'goal': 'software fixture', 'contract': {'unit': 'A', 'corners': ['tt','ss','ff']},
        'allowed_paths': list(base), 'visible_sources': base, 'documents': {'patch_format': 'ordinary fixture', 'API': 'complete fixture'},
        'visible_configurations': ['point'+str(i) for i in range(9)], 'budget': {'decisions': 1, 'maximum_output_tokens': 1024, 'maximum_context_tokens': 16384}},
        'visible_history': [{'observation': {'actual_baseline_fixture': 'preserved in full'}}]}
    request = teacher_request(original); state = {'initial_state_id': 'state', 'base_source': base, 'parent_lineage': 'compiler', 'origin': 'natural', 'ancestry': {'software_fixture': True}}
    context = {'initial_state_id': 'state', 'base_source': base, 'state': state, 'teacher_request_value': request}
    proposal = {'edits': [{'path': 'layout.py', 'old': base['layout.py'], 'new': replacement}]}
    raw = json.dumps(proposal); tokenizer = TokenizerFixture()
    flight = prompt_token_budget(tokenizer, proposal_prompt(request), {'max_new_tokens': 3072, 'max_context_tokens': 16384})
    count = len(tokenizer(raw)['input_ids'])+1
    flight.update(completion_tokens_including_EOS=count, actual_total_tokens=flight['prompt_tokens']+count, output_within_budget=True)
    response = {'inference_id': 'fixture_id', 'collection_sha256': 'fixture_collection_sha', 'native_tools': [], 'producer_status': 'COMPLETED',
        'raw_proposal_text': raw, 'proposal': proposal, 'model': {'source_role': ROLE, 'requested_model': 'gpt-6.1-sol', 'teacher_interface_version': VERSION,
            'settings': {'reasoning_effort': 'high', 'max_new_tokens': 3072, 'maximum_context_tokens': 16384, 'sampling_seed': None}},
        'usage': {'request_mode': MODE, 'output_format': 'literal_span_edits_json', 'public_cli_usage': {'input_tokens': 100, 'output_tokens': 20},
            'model_call_issued': True, 'server_wall_seconds': 1, 'policy_token_budget': flight}}
    body = {'mode': MODE, 'initial_state_id': 'state', 'trial_id': 1, 'request': request}
    attempt = {'initial_state_id': 'state', 'trial_id': 1, 'inference_id': 'fixture_id', 'http_status': 200, 'client_wall_seconds': 1.1,
               'usage': copy.deepcopy(response['usage']), 'model': copy.deepcopy(response['model'])}
    directory = root/'state/trial_1'; directory.mkdir(parents=True)
    for name, value in [('request', body), ('response', response), ('attempt', attempt)]: consumer.save(directory/(name+'.json'), value)
    if make_compiled:
        compiled = compile_proposal(base, proposal); mapped = mapped_student_request(request)
        consumer.save(directory/'compiled.json', compiled); consumer.save(directory/'student_request.json', mapped)
        (directory/'student_action.json').write_text(canonical_action(compiled['patch'], mapped)+'\n'); consumer.save(directory/'student_budget.json', {})
    parent = {'manifest': {'pdk_revision': 'fixture_pdk'}, 'registry': {'configurations': [
        {'configuration_id': 'point'+str(i), 'contract': {'task_id': 'physical_task'}} for i in range(9)]}}
    return {'output_root': str(root)}, context, directory, parent


class SpanPhysicalFollowupTests(unittest.TestCase):
    def test_raw_compiler_and_ACTION_replay_preserve_every_original_file(self):
        with tempfile.TemporaryDirectory() as directory:
            plan, context, raw, parent = raw_fixture(Path(directory)); before = {p.name: p.read_bytes() for p in raw.iterdir()}
            result = consumer.verify_raw(plan, context, 1, raw, TokenizerFixture(), 'fixture_collection_sha')
            self.assertEqual(result['status'], 'ELIGIBLE_UNIQUE_CHECK_PENDING')
            row = consumer.candidate_row(context, parent, result, 1); proof = consumer.student_identity_proof(context, row, str(raw))
            self.assertEqual(proof['raw_teacher_task_id'], 'raw_cohort__state'); self.assertEqual(proof['physical_contract_task_id'], 'physical_task')
            self.assertFalse(proof['raw_and_physical_packets_byte_identical']); self.assertTrue(proof['compiled_action_text_unchanged'])
            self.assertTrue(proof['source_physical_contract_and_feedback_equal']); self.assertEqual(row['proposal_generation']['teacher_mode'], MODE)
            self.assertNotIn('T0', row['candidate_id']); self.assertEqual(before, {p.name: p.read_bytes() for p in raw.iterdir()})

    def test_changed_actual_usage_compiler_source_or_context_is_quarantined(self):
        for mutate in ('usage', 'source', 'context'):
            with tempfile.TemporaryDirectory() as directory:
                plan, context, raw, _ = raw_fixture(Path(directory))
                if mutate == 'usage':
                    value = consumer.read(raw/'attempt.json'); value['usage']['server_wall_seconds'] += 1; consumer.save(raw/'attempt.json', value)
                elif mutate == 'source':
                    value = consumer.read(raw/'compiled.json'); value['candidate_source']['layout.py'] = 'x=99\n'; consumer.save(raw/'compiled.json', value)
                else:
                    value = consumer.read(raw/'request.json'); value['request']['visible_history'] = []; consumer.save(raw/'request.json', value)
                with self.assertRaises(ValueError): consumer.verify_raw(plan, context, 1, raw, TokenizerFixture(), 'fixture_collection_sha')

    def test_role_or_timeout_cannot_be_relabelled_as_T0_or_physical_negative(self):
        with tempfile.TemporaryDirectory() as directory:
            plan, context, raw, _ = raw_fixture(Path(directory))
            response = consumer.read(raw/'response.json'); response['producer_status'] = 'TIMEOUT'; consumer.save(raw/'response.json', response)
            with self.assertRaisesRegex(ValueError, 'unknown'): consumer.verify_raw(plan, context, 1, raw, TokenizerFixture(), 'fixture_collection_sha')
            response['producer_status'] = 'COMPLETED'; response['model']['source_role'] = 'base_model_formal_train_action_proposals'
            attempt = consumer.read(raw/'attempt.json'); attempt['model'] = copy.deepcopy(response['model'])
            consumer.save(raw/'response.json', response); consumer.save(raw/'attempt.json', attempt)
            with self.assertRaisesRegex(ValueError, 'producer identity'): consumer.verify_raw(plan, context, 1, raw, TokenizerFixture(), 'fixture_collection_sha')

    def test_invalid_python_and_AST_noop_stop_before_physics(self):
        for replacement, expected in [('x=(\n', 'SOURCE_NOT_PARSEABLE_NO_PHYSICAL_LABEL'), ('x = 1 # comment\n', 'SEMANTIC_NOOP')]:
            with tempfile.TemporaryDirectory() as directory:
                plan, context, raw, _ = raw_fixture(Path(directory), replacement)
                result = consumer.verify_raw(plan, context, 1, raw, TokenizerFixture(), 'fixture_collection_sha')
                self.assertEqual(result['status'], expected); self.assertNotIn('outcomes', result)

    def test_other_physical_field_or_feedback_changes_fail_the_task_identity_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            plan, context, raw, parent = raw_fixture(Path(directory)); result = consumer.verify_raw(plan, context, 1, raw, TokenizerFixture(), 'fixture_collection_sha')
            original = consumer.candidate_row(context, parent, result, 1)
            for field in ('contract', 'visible_feedback', 'base_source'):
                row = copy.deepcopy(original)
                if field == 'contract': row['visible_contract']['contract'] = {'changed': 'forbidden'}
                elif field == 'base_source': row['base_source']['layout.py'] += 'y=3\n'
                else: row[field] = []
                with self.assertRaises(ValueError): consumer.student_identity_proof(context, row)

    def test_student_oversize_does_not_re_read_baseline_or_dispatch_physics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); plan, context, raw, parent = raw_fixture(root/'raw', 'x="'+'z'*1100+'"\n')
            context.update(parent_collection='parent'); cell = {'initial_state_id': 'state', 'parent_collection': 'parent', 'trial_id': 1, 'status': 'NOT_RUN'}
            matrix = {('state', 1): {'status': 'STUDENT_BUDGET_REJECTED_BEFORE_PHYSICS', 'attempt_directory': str(raw)}}
            output = root/'output'; output.mkdir()
            with patch.object(consumer, 'raw_matrix', return_value=matrix), patch.object(consumer.physical, 'baseline_bindings') as baseline, patch.object(consumer, 'workspace') as workspace:
                consumer.scan_returned({'proposal_collection_sha256': 'fixture_collection_sha'}, plan, {'parent': parent}, [context], {}, {'cells': [cell]}, output, TokenizerFixture())
                baseline.assert_not_called(); workspace.assert_not_called()
            self.assertEqual(cell['status'], 'STUDENT_BUDGET_REJECTED_BEFORE_PHYSICS'); self.assertNotIn('candidate_file', cell)

    def test_durable_orphan_reservation_preserves_sixteen_denominator_and_unknown_stop(self):
        definition = {'contexts': [{'initial_state_id': name, 'parent_collection': name} for name in ('a', 'b')],
            'trials': list(range(1, 9)), 'physical': {'maximum_dispatch_hours': 8}}
        state = consumer.initial_state(definition); state['cells'][0]['points'] = [{'configuration_id': 'p0', 'status': 'DISPATCH_RESERVED'}]
        consumer.physical.mark_orphaned_reservations(state); report = consumer.completion(state)
        self.assertEqual(report['planned_proposals'], 16); self.assertEqual(report['maximum_candidate_points'], 144)
        self.assertEqual(report['status'], 'PAUSED_UNKNOWN'); self.assertEqual(report['actual_reserved_candidate_points'], 1)
        self.assertFalse(report['automatic_retry']); self.assertEqual(report['new_model_calls'], 0)

    def test_baseline_control_proves_context_identity_without_inventing_a_candidate_ACTION(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); _, context, _, parent = raw_fixture(root)
            context['parent_collection'] = 'parent'
            with patch.object(consumer, 'load_acceptance', return_value=({}, {}, {'parent': parent}, [context], {})), \
                    patch.object(consumer.physical, 'baseline_bindings', return_value={'fixture': {'checked': {'software_fixture_only': True}}}):
                report = root/'report.json'; result = consumer.baseline_control(root/'DRAFT.json', report)
            self.assertEqual(result['new_model_calls'], 0); self.assertEqual(result['new_physical_calls'], 0)
            proof = consumer.read(report)['contexts'][0]['student_identity_proof']
            self.assertIsNone(proof['ordinary_action_text']); self.assertIsNone(proof['compiled_action_text_unchanged'])
            self.assertTrue(proof['source_physical_contract_and_feedback_equal'])

    def test_derived_wiring_keeps_common_pool_v2_and_counts_one_useful_state(self):
        # Deliberately synthetic selection control; never an admission/physical result.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); output = root/'output'; output.mkdir(); folder = root/'plan'
            (folder/'interface/src').mkdir(parents=True)
            shutil.copyfile('src/training_selection_v2.py', folder/'interface/src/training_selection_v2.py')
            (folder/'interface/base_selection.py').write_text(consumer.frozen_base_selection(Path('src/training.py').read_text()))
            rule, sampling, outcome_fixture = selection_fixtures.SelectionV2Tests().fixture()
            consumer.save(folder/'rules/parent.json', make_rule(rule, sampling))
            definition = {'contexts': [{'initial_state_id': sid, 'parent_collection': 'parent'} for sid in ('state', 'other')],
                'trials': list(range(1, 9)), 'physical': {'maximum_dispatch_hours': 8}}
            state = consumer.initial_state(definition); verified = {}
            for index, area in [(0, 80), (1, 90)]:
                _, context, raw, parent = raw_fixture(root/('raw'+str(index)), 'x='+str(index+2)+'\n')
                proposal = consumer.verify_raw({}, context, 1, raw, TokenizerFixture(), 'fixture_collection_sha')
                row = consumer.candidate_row(context, parent, proposal, index+1)
                file = 'candidate'+str(index)+'.json'; consumer.save(output/file, row)
                state['cells'][index].update(candidate_file=file, status='PHYSICAL_PENDING',
                    points=[{'configuration_id': str(i), 'status': 'COMPLETE'} for i in range(9)])
                verified[row['candidate_id']] = {**row, 'verified': outcome_fixture('fixture', index+1, area)['verified']}
            for cell in state['cells'][2:8]: cell['status'] = 'ORIGINAL_PRODUCER_REJECTED'
            registry = {'status': 'frozen', 'lineages': [{'lineage_id': 'compiler', 'split': 'train', 'topology_family': 'fixture'}]}
            with patch.object(consumer, 'admit_candidates', side_effect=lambda rows, *args: [verified[rows[0]['candidate_id']]]):
                consumer.derive(definition, {'parent': {}}, registry, state, output, TokenizerFixture(), folder)
            result = consumer.read(output/'student_selection.json')
            self.assertEqual(result['effective_samples_by_method'], {method: 1 for method in ('T1','T2','T3','T4')})
            self.assertEqual(result['unique_useful_SFT_contexts'], 1); self.assertEqual(result['unique_DPO_contexts'], 1)
            self.assertEqual(result['planned_proposals'], 16); self.assertFalse(result['old40_failed_patch_pool_used'])
            self.assertFalse(result['formal_training_started']); self.assertEqual(result['closed_initial_states'], ['state'])


if __name__ == '__main__': unittest.main()
