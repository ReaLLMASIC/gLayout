"""Checkpoint serving software fixtures; no training, weights or GPU results."""
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import scripts.serve_checkpoint_policy as service


class CheckpointPolicyTests(unittest.TestCase):
    @contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); checkpoint = root / 'training/checkpoint-0000005'
            names = ['adapter/policy/adapter_config.json', 'adapter/policy/adapter_model.safetensors',
                     'training_state.pt', 'tokenizer/tokenizer_config.json', 'metadata/training_manifest.json',
                     'metadata/training_config.json', 'metadata/run.json', 'metadata/metrics.jsonl']
            for name in names:
                path = checkpoint / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'software fixture')
            (checkpoint / 'complete.json').write_text(json.dumps({'optimizer_boundary': True, 'updates': 5}))
            snapshot = root / service.REVISION; snapshot.mkdir()
            manifest = root / 'training_manifest.json'; manifest.write_text(json.dumps({'status': 'development'}))
            plan = root / 'validation_plan.json'; plan.write_text(json.dumps({'status': 'FROZEN_E4_VALIDATION_PLAN',
                'selection_rule': service.SELECTION_RULE, 'split_registry_sha256': 'fixture_registry',
                'points': [{'task_id': 'software_fixture', 'configuration_id': 'z'}],
                'budget': {'maximum_context_tokens': 16384, 'maximum_output_tokens': 1024}})); plan.chmod(0o444)
            args = SimpleNamespace(validation_plan=plan, run_directory=checkpoint.parent,
                training_manifest=manifest, checkpoint=checkpoint, method='T2', training_seed=73,
                adapter_sha256=service.file_digest(checkpoint / 'adapter/policy/adapter_model.safetensors'))
            inspected = {'checkpoints': [checkpoint], 'config': {'quantization': dict(service.QUANTIZATION),
                'backbone': 'Qwen/Qwen2.5-Coder-32B-Instruct'}, 'manifest': {'backbone_snapshot': str(snapshot)}}
            yield args, inspected

    def test_unselected_completed_checkpoint_has_a_distinct_role_and_exact_actual_binding(self):
        with self.fixture() as (args, training), patch.object(service, 'inspect_formal_run') as inspect:
            inspect.return_value = training
            identity = service.validate_checkpoint(args)
            self.assertEqual(identity['source_role'], 'E4_checkpoint_validation_not_selected')
            self.assertFalse(identity['selected_checkpoint'])
            self.assertEqual(identity['variant'], 'T2'); self.assertEqual(identity['training_seed'], 73)
            self.assertEqual(identity['checkpoint_update'], 5)
            self.assertEqual(identity['adapter_sha256'], args.adapter_sha256)
            self.assertEqual(inspect.call_args.args[-1], 'fixture_registry')
            self.assertNotIn('methods_manifest_sha256', identity)

    def test_engineering_or_unadmitted_manifest_cannot_be_used_as_a_formal_checkpoint(self):
        with self.fixture() as (args, training):
            # Exercise the real formal-run gate, rather than the fixture mock.
            with self.assertRaises(ValueError):
                service.validate_checkpoint(args)

    def test_changed_weights_foreign_checkpoint_or_incomplete_optimizer_boundary_reject(self):
        with self.fixture() as (args, training), patch.object(service, 'inspect_formal_run', return_value=training):
            args.adapter_sha256 = '0' * 64
            with self.assertRaisesRegex(ValueError, 'weight SHA'):
                service.validate_checkpoint(args)
        with self.fixture() as (args, training), patch.object(service, 'inspect_formal_run', return_value={**training, 'checkpoints': []}):
            with self.assertRaisesRegex(ValueError, 'outside'):
                service.validate_checkpoint(args)
        with self.fixture() as (args, training), patch.object(service, 'inspect_formal_run', return_value=training):
            (args.checkpoint / 'complete.json').write_text(json.dumps({'optimizer_boundary': False, 'updates': 5}))
            with self.assertRaisesRegex(ValueError, 'optimizer boundary'):
                service.validate_checkpoint(args)

    def test_empty_draft_validation_or_different_precision_cannot_load(self):
        with self.fixture() as (args, training), patch.object(service, 'inspect_formal_run') as inspect:
            args.validation_plan.chmod(0o644)
            args.validation_plan.write_text(json.dumps({'status': 'DRAFT_E4_VALIDATION_PLAN', 'points': []}))
            args.validation_plan.chmod(0o444)
            with self.assertRaisesRegex(ValueError, 'predeclared'):
                service.validate_checkpoint(args)
            inspect.assert_not_called()
        with self.fixture() as (args, training), patch.object(service, 'inspect_formal_run', return_value=training):
            training['config']['quantization']['compute_dtype'] = 'float16'
            with self.assertRaisesRegex(ValueError, 'precision'):
                service.validate_checkpoint(args)

    def request(self):
        packet = {'task_id': 'software_fixture', 'goal': 'repair', 'contract': {},
            'allowed_paths': ['layout.py'], 'visible_sources': {'layout.py': 'x = 1\n'},
            'documents': {}, 'visible_configurations': ['z'],
            'budget': {'maximum_output_tokens': 1024, 'maximum_context_tokens': 16384}}
        return {'variant': 'T2', 'request': {'task_packet': packet, 'visible_history': []}}

    def test_ordinary_body_remains_byte_identical_in_prompt_and_cannot_select_a_checkpoint(self):
        body = self.request(); identity = {'variant': 'T2', 'training_seed': 73}
        self.assertEqual(service.validate_request(body, identity), service.decision_prompt(body['request']))
        with self.assertRaises(ValueError):
            service.validate_request({**body, 'checkpoint': '/policy-chosen-path'}, identity)
        with self.assertRaises(ValueError):
            service.validate_request({**body, 'variant': 'T1'}, identity)
        with self.assertRaises(ValueError):
            service.validate_request({**body, 'variant': 'T0'}, identity)
        body['request']['task_packet']['budget']['maximum_context_tokens'] = 8192
        with self.assertRaises(ValueError):
            service.validate_request(body, identity)

    def test_failed_generation_keeps_identity_and_native_boundary_without_inventing_usage(self):
        identity = {'variant': 'T2', 'adapter_sha256': 'software_fixture'}
        usage = {'input_tokens': 17, 'output_tokens': 1024, 'eos_terminated': False}
        failed = service.failed_decision('fixture_id', ValueError('missing EOS'), identity, usage, True)
        self.assertEqual(failed['model'], identity)
        self.assertEqual(failed['native_tools'], [])
        self.assertEqual(failed['usage'], usage)
        self.assertEqual(failed['failure_class'], 'policy_output_or_budget')
        unknown = service.failed_decision('fixture_id', RuntimeError('CUDA failure'), identity, None, True)
        self.assertEqual(unknown['failure_class'], 'unknown')
        self.assertNotIn('usage', unknown)
        self.assertEqual(unknown['native_tools'], [])
        self.assertEqual(unknown['model'], identity)


if __name__ == '__main__':
    unittest.main()
