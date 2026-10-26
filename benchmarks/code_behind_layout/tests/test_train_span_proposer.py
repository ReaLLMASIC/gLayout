"""Software fixtures only: exact edits, isolated producer and unchanged student consumer."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from src.train_span_proposer import compile_proposal, teacher_request, mapping_proof, proposal_prompt, source_identity, ROLE, MODE
from src.train_span_cli import command, DISABLED_FEATURES, run_cli
from scripts.collect_train_span_proposals import process_response
from scripts.serve_train_span_teacher import validate_body
from scripts.freeze_train_span_teacher import freeze
from src.train_span_bundle import load_bundle


class TinyTokenizer:
    eos_token_id = 151645
    def __call__(self, text, **unused): return {'input_ids': list(text.encode())}
    def apply_chat_template(self, messages, **unused): return list(messages[0]['content'].encode())


def request():
    return {'task_packet': {'task_id': 'software_fixture', 'goal': 'ordinary teacher fixture',
        'contract': {'required_corners': ['tt', 'ss', 'ff'], 'specifications': [{'metric': 'I', 'unit': 'A', 'min': .001}]},
        'allowed_paths': ['layout.py', 'enum.py'], 'visible_sources': {'layout.py': 'a=1\nb=2\n', 'enum.py': 'plans=[1,2]\n'},
        'documents': {'patch_format': 'ordinary ACTION fixture', 'complete_API': {'unchanged': 'all functions'}},
        'visible_configurations': ['anchor', 'dev'], 'budget': {'decisions': 1, 'maximum_output_tokens': 1024, 'maximum_context_tokens': 16384}},
        'visible_history': [{'observation': {'baseline': [{'configuration_id': 'anchor', 'S2': True, 'area': 23.4}], 'diagnostics': 'actual fixture feedback'}}]}


class FakeProcess:
    pid = 123
    def __init__(self, argv, *, stdin, stdout, stderr, text, raw=None, native=False):
        self.argv = argv; self.out = stdout; self.returncode = 0
        self.raw = raw or json.dumps({'edits': [{'path': 'layout.py', 'old': 'a=1', 'new': 'a=3'}]})
        self.native = native
    def communicate(self, prompt=None, timeout=None):
        self.out.write(json.dumps({'type': 'turn.started'}) + '\n')
        if self.native: self.out.write(json.dumps({'type': 'item.completed', 'item': {'type': 'command_execution'}}) + '\n')
        self.out.write(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 11, 'output_tokens': 22}}) + '\n'); self.out.flush()
        Path(self.argv[self.argv.index('--output-last-message') + 1]).write_text(self.raw)
    def kill(self): self.returncode = -9


class SpanProposerTests(unittest.TestCase):
    def test_frozen_bundle_is_read_only_and_even_unchanged_writable_bytes_are_rejected(self):
        # This metadata fixture exercises freeze modes only, never physical admission.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'bundle'; root.mkdir()
            contexts = []
            for pool, sid in [('c01_planning_trajectories_context_v2', 'planning_c01_program_038'),
                    ('c02_planning_trajectories_context_v2', 'planning_c02_program_039')]:
                context = {'parent_collection_id': pool, 'initial_state_id': sid}
                directory = root / sid; directory.mkdir()
                for key in ('original_request', 'teacher_request', 'student_request', 'mapping_proof', 'initial_state', 'baseline_results', 'effective_registry', 'parent_collection', 'label_rule'):
                    file = directory / (key + '.json')
                    file.write_text(json.dumps({'teacher_and_original_map_to_identical_ordinary_request': True} if key == 'mapping_proof' else {'software_fixture': True}))
                    context[key] = str(file.relative_to(root))
                contexts.append(context)
            manifest = {'status': 'DRAFT_NO_MODEL_CALLS', 'role': 'train_proposal_collection', 'source_role': ROLE,
                'teacher_interface_version': 'literal_span_teacher_v1', 'contexts': contexts, 'planned_proposals': 16,
                'independent_contexts_added': 0, 'endpoint': 'http://127.0.0.1:8116/spans/decision',
                'sampling': {'backend': 'isolated_gpt_cli', 'model': 'gpt-6.1-sol', 'reasoning_effort': 'high', 'mode': MODE,
                    'trials': list(range(1, 9)), 'seed': None, 'proposal_workers': 2, 'max_new_tokens': 3072, 'max_context_tokens': 16384, 'timeout_seconds': 240},
                'student_preselection': {'interface_version': 'ordinary_policy_action_context_v2', 'max_new_tokens': 1024, 'max_context_tokens': 16384, 'stage': 'before_physics'}}
            (root / 'collection.json').write_text(json.dumps(manifest))
            (root / 'baseline_audit.json').write_text(json.dumps({'all_eighteen_points_complete': True,
                'records': [{'software_fixture_only': True}] * 18, 'input_files_sha256': {}}))
            (root / 'tokenizer_inventory.json').write_text('{}')
            try:
                freeze(root / 'collection.json'); load_bundle(root / 'collection.json')
                for file in [root, *root.rglob('*')]:
                    self.assertEqual(file.stat().st_mode & 0o777, 0o555 if file.is_dir() else 0o444)
                unchanged = root / contexts[0]['teacher_request']; unchanged.chmod(0o644)
                with self.assertRaisesRegex(ValueError, 'writable'): load_bundle(root / 'collection.json')
            finally:
                for file in [root, *root.rglob('*')]: file.chmod(0o755 if file.is_dir() else 0o644)

    def test_two_original_spans_do_not_cascade_and_git_proves_all_modules(self):
        base = {'b.py': 'value=2\n', 'a.py': 'alpha=1\nbeta=2\ngamma=3\n'}; before = copy.deepcopy(base)
        result = compile_proposal(base, {'edits': [{'path': 'a.py', 'old': 'alpha=1', 'new': 'alpha=2'},
            {'path': 'a.py', 'old': 'beta=2', 'new': 'beta=1'}]})
        self.assertEqual(base, before); self.assertEqual(result['candidate_source']['a.py'], 'alpha=2\nbeta=1\ngamma=3\n')
        self.assertEqual(result['candidate_source']['b.py'], base['b.py'])
        self.assertTrue(result['compiler_proof']['full_editable_source_byte_equal'])
        self.assertEqual([r['returncode'] for r in result['compiler_proof']['git_invocations']], [0, 0])
        self.assertIn('@@ -1,3 +1,3 @@', result['patch'])

    def test_ambiguity_including_overlapping_occurrences_and_edit_overlap_rejected(self):
        for base, edits in [({'g.py': 'aaa'}, [{'path': 'g.py', 'old': 'aa', 'new': 'b'}]),
                ({'g.py': 'abcdef'}, [{'path': 'g.py', 'old': 'abc', 'new': 'x'}, {'path': 'g.py', 'old': 'bcde', 'new': 'y'}]),
                ({'g.py': 'x'}, [{'path': 'g.py', 'old': 'missing', 'new': 'y'}])]:
            with self.assertRaises(ValueError): compile_proposal(base, {'edits': edits})

    def test_deletion_insertion_unicode_and_missing_EOF_newline_preserved(self):
        result = compile_proposal({'g.py': '# 中文\na=1\nb=2'}, {'edits': [
            {'path': 'g.py', 'old': '# 中文\n', 'new': '# 中文\nc=3\n'}, {'path': 'g.py', 'old': 'b=2', 'new': ''}]})
        self.assertEqual(result['candidate_source']['g.py'], '# 中文\nc=3\na=1\n')
        self.assertIn('\\ No newline at end of file', result['patch'])
        edit = result['compiler_proof']['matches'][1]
        self.assertGreater(edit['start_utf8_byte'], edit['start_character'])

    def test_unauthorized_noop_empty_and_malformed_proposals_are_not_repaired(self):
        for proposal in [{'edits': []}, {'edits': [{'path': '../x', 'old': 'a', 'new': 'b'}]},
                {'edits': [{'path': 'g.py', 'old': '', 'new': 'b'}]},
                {'edits': [{'path': 'g.py', 'old': 'a', 'new': 'a'}]}, {'patch': 'old failed diff'}]:
            with self.assertRaises(ValueError): compile_proposal({'g.py': 'a'}, proposal)

    def test_exact_AST_dedup_retains_constants_and_docstrings(self):
        self.assertEqual(source_identity({'g.py': 'a=1\n'}), source_identity({'g.py': '# comment\na = 1\n'}))
        self.assertNotEqual(source_identity({'g.py': 'a=1'}), source_identity({'g.py': 'a=2'}))
        self.assertNotEqual(source_identity({'g.py': '"one"\na=1'}), source_identity({'g.py': '"two"\na=1'}))

    def test_ordinary_mapping_replaces_all_span_instructions_and_preserves_physics_and_feedback(self):
        original = request(); original['task_packet']['documents']['source_edit_policy'] = 'original fixture'
        span = teacher_request(original); proof = mapping_proof(original, span); student = proof['ordinary_request']
        self.assertTrue(proof['teacher_and_original_map_to_identical_ordinary_request'])
        self.assertEqual(student['task_packet']['contract'], original['task_packet']['contract'])
        self.assertEqual(student['task_packet']['visible_sources'], original['task_packet']['visible_sources'])
        self.assertEqual(student['visible_history'], original['visible_history'])
        self.assertEqual(student['task_packet']['documents']['complete_API'], original['task_packet']['documents']['complete_API'])
        self.assertNotIn('literal-span', json.dumps(student)); self.assertEqual(student['task_packet']['budget']['maximum_output_tokens'], 1024)
        self.assertEqual(span['task_packet']['budget']['maximum_output_tokens'], 3072)
        with self.assertRaises(ValueError):
            bad = copy.deepcopy(span); bad['task_packet']['documents']['new_span_instructions'] = 'unexpected leak'; mapping_proof(original, bad)

    def test_independent_CLI_has_exact_native_isolation_without_monkeypatch(self):
        argv = command('/fixture/gpt', '/tmp/fixture')
        for flag in ['--ignore-user-config', '--ephemeral', '--skip-git-repo-check', '--json', '--output-schema']:
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index('--sandbox') + 1], 'read-only')
        self.assertIn('mcp_servers={}', argv); self.assertIn('project_doc_max_bytes=0', argv)
        disabled = [argv[i + 1] for i, item in enumerate(argv) if item == '--disable']
        self.assertEqual(disabled, DISABLED_FEATURES)

    def test_CLI_preserves_public_usage_and_raw_on_native_or_oversize_rejection(self):
        for native, raw in [(True, None), (False, json.dumps({'edits': [{'path': 'layout.py', 'old': 'a', 'new': 'x'*3100}]}))]:
            with tempfile.TemporaryDirectory() as directory:
                work = Path(directory) / 'session'
                response = run_cli('/fixture/gpt', TinyTokenizer(), teacher_request(request()), work,
                    runner=lambda *a, **kw: FakeProcess(*a, **kw, raw=raw, native=native))
                self.assertIn('error', response); self.assertIn('raw_proposal_text', response)
                self.assertEqual(response['usage']['public_cli_usage']['output_tokens'], 22)
                self.assertTrue(json.loads((work/'invocation.json').read_text())['model_call_issued'])
                if native: self.assertEqual(response['native_tools'], ['command_execution'])

    def test_context_overflow_issues_no_process(self):
        oversized = request(); oversized['task_packet']['visible_sources']['layout.py'] = 'x'*17000
        with tempfile.TemporaryDirectory() as directory:
            def forbidden(*a, **kw): self.fail('No inference may be issued for an oversize complete packet')
            response = run_cli('/fixture/gpt', TinyTokenizer(), teacher_request(oversized), Path(directory)/'s', runner=forbidden)
            self.assertIn('error', response)
            self.assertFalse(json.loads((Path(directory)/'s/invocation.json').read_text())['model_call_issued'])

    def test_exact_frozen_context_order_trial_and_mode_are_bound_outside_the_prompt(self):
        visible = teacher_request(request()); frozen = {'fixture_state': visible}
        body = {'mode': MODE, 'initial_state_id': 'fixture_state', 'trial_id': 1, 'request': visible}
        self.assertEqual(validate_body(body, frozen), ('fixture_state', 1))
        for field, value in [('mode', 'train_collection_action_gpt'), ('trial_id', True), ('trial_id', 9), ('initial_state_id', 'other')]:
            with self.assertRaises(ValueError): validate_body({**body, field: value}, frozen)
        altered = copy.deepcopy(body); altered['request']['task_packet']['contract']['required_corners'] = ['tt']
        with self.assertRaises(ValueError): validate_body(altered, frozen)
        reordered = copy.deepcopy(body); reordered['request'] = dict(reversed(list(reordered['request'].items())))
        with self.assertRaises(ValueError): validate_body(reordered, frozen)

    def test_successful_span_response_compiles_to_the_unchanged_canonical_student_ACTION(self):
        teacher = teacher_request(request()); proposal = {'edits': [{'path': 'layout.py', 'old': 'a=1', 'new': 'a=3'}]}
        response = {'native_tools': [], 'model': {'source_role': ROLE}, 'usage': {'request_mode': MODE},
                    'proposal': proposal, 'raw_proposal_text': json.dumps(proposal)}
        with tempfile.TemporaryDirectory() as directory:
            result = process_response(response, teacher, teacher['task_packet']['visible_sources'], TinyTokenizer(), Path(directory))
            self.assertEqual(result['status'], 'COMPILED_STUDENT_FIT_PROPOSAL_ONLY')
            action = json.loads((Path(directory)/'student_action.json').read_text())
            self.assertEqual(set(action), {'action', 'path', 'patch', 'configuration_ids', 'fidelity', 'summary'})
            self.assertEqual(action['action'], 'propose_patch'); self.assertEqual(action['configuration_ids'], [])
            self.assertEqual(action['summary'], ''); self.assertIn('+a=3\n', action['patch'])

    def test_inference_timeout_is_unknown_and_pauses_without_a_physical_negative(self):
        response = {'native_tools': [], 'model': {'source_role': ROLE}, 'usage': {'request_mode': MODE},
                    'producer_status': 'TIMEOUT', 'error': 'fixture provider timeout'}
        with tempfile.TemporaryDirectory() as directory:
            teacher = teacher_request(request())
            result = process_response(response, teacher, teacher['task_packet']['visible_sources'], TinyTokenizer(), Path(directory))
            self.assertEqual(result['status'], 'UNKNOWN_PRODUCER_PAUSE'); self.assertTrue(result['dispatch_pause_required'])
            self.assertFalse((Path(directory)/'compiled.json').exists())

    def test_compiled_student_budget_precedes_physics_without_shortening(self):
        teacher = teacher_request(request()); proposal = {'edits': [{'path': 'layout.py', 'old': 'a=1', 'new': 'a="'+'x'*1100+'"'}]}
        response = {'native_tools': [], 'model': {'source_role': ROLE}, 'usage': {'request_mode': MODE},
                    'proposal': proposal, 'raw_proposal_text': json.dumps(proposal)}
        with tempfile.TemporaryDirectory() as directory:
            result = process_response(response, teacher, teacher['task_packet']['visible_sources'], TinyTokenizer(), Path(directory))
            self.assertEqual(result['status'], 'STUDENT_BUDGET_REJECTED_BEFORE_PHYSICS')
            compiled = json.loads((Path(directory)/'compiled.json').read_text())
            self.assertIn('x'*1100, compiled['patch']); self.assertEqual(compiled['candidate_source']['layout.py'], proposal['edits'][0]['new']+'\nb=2\n')


if __name__ == '__main__': unittest.main()
