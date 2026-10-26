"""Freezer file/contract/software controls; these fixtures are not EDA evidence."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.freeze_e3 import (actual_gpu_calibration, committed_implementation, copy_task,
    digest, freeze, same_electrical_domain, save, validate_dispatch, verify_policy_control)
from tests.test_e3_original_baseline import software_task


def domain_fixture(root):
    task = software_task('draft_E3_toy_edit01')
    task.update(target='toy', parent_lineage='toy_lineage')
    for point in task['configurations']:
        reference = root/'refs'/(point['configuration_id']+'.spice');reference.parent.mkdir(exist_ok=True)
        reference.write_text('* software independent reference '+point['reference_id'])
        point['reference_file'] = str(reference)
        point['contract'].update(reference_id=point['reference_id'], required_corners=['tt'],
            specifications=[{'name': 'gain', 'unit': 'V/V', 'min': 1.}],
            analysis_contracts={'ac': {'kind': 'ac', 'columns': 3, 'points': 3}}, immutable_parameters=point['parameters'])
    e1 = copy.deepcopy(task);e1.update(task_id='draft_E1_toy_s01', target_logic_id='toy_lineage')
    for point in e1['configurations']:
        point['contract'].update(task_id=e1['task_id'], objective={'metric': 'wirelength', 'unit': 'um', 'direction': 'min'})
    return task, e1


class E3FreezeTests(unittest.TestCase):
    def test_actual_dispatch_plans_are_frozen_without_claiming_future_E4_F3_ready(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root/'configs/experiments/e3_matched_draft.json').read_text())
        tasks = {name: {'target': 'unused'} for name in manifest['task_ids']}
        for name, target in zip(manifest['fidelity_task_ids'], ('five_t', 'compact_miller')):
            tasks[name]['target'] = target
        self.assertEqual(validate_dispatch(manifest, tasks), {
            'gpt': 480, 'parameter': 80, 'local': 1080, 'signals': 80, 'fidelity': 10, 'instance': 8})
        bad = copy.deepcopy(manifest);bad['selector_ablation_weights']['without_margin']['uncertainty'] = 0
        with self.assertRaisesRegex(ValueError, 'named channel'):validate_dispatch(bad, tasks)
        bad = copy.deepcopy(manifest);bad['global_release_parts'].remove('fidelity')
        with self.assertRaisesRegex(ValueError, 'five declared'):validate_dispatch(bad, tasks)
        bad = copy.deepcopy(manifest);bad['e4_evaluation']['T0_independent_training_seeds'] = 3
        with self.assertRaisesRegex(ValueError, 'independent T0'):validate_dispatch(bad, tasks)

    def test_exact_committed_bytes_and_E1_dependencies_are_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);(root/'own.py').write_text('# actual own source\n');(root/'dep.py').write_text('# E1 source\n')
            index = {'revision': 'a'*40, 'files_sha256': {name: digest(root/name) for name in ('own.py', 'dep.py')}}
            e1 = {'implementation_sha256': {'dep.py': index['files_sha256']['dep.py']}}
            with patch('scripts.freeze_e3.ROOT', root), patch('scripts.freeze_e3.LIVE_IMPLEMENTATION', ('own.py',)):
                self.assertEqual(committed_implementation(index, e1), index['files_sha256'])
                (root/'own.py').write_text('# drift\n')
                with self.assertRaisesRegex(ValueError, 'committed-source index'):
                    committed_implementation(index, e1)

    def test_objective_can_change_but_N_sizing_role_and_electrical_limits_cannot(self):
        with tempfile.TemporaryDirectory() as temporary:
            task, e1 = domain_fixture(Path(temporary))
            same_electrical_domain(task, e1)
            bad = copy.deepcopy(task);bad['configurations'][3]['parameters']['width'] += 1
            with self.assertRaises(ValueError):same_electrical_domain(bad, e1)
            bad = copy.deepcopy(task);bad['configurations'][3]['role'] = 'hidden'
            with self.assertRaises(ValueError):same_electrical_domain(bad, e1)
            bad = copy.deepcopy(task);bad['configurations'][3]['contract']['specifications'][0]['min'] = .5
            with self.assertRaises(ValueError):same_electrical_domain(bad, e1)

    def test_copy_relocates_full_binary_capsule_sources_refs_and_P_bindings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);task, e1 = domain_fixture(root)
            pack = root/'old_pack';pack.mkdir()
            for name, value in {'generator.py': b'# original wrapper\n', 'layout.py': b'# original complete module\n',
                    'primitive.gds': b'\xff\x00binary PCell fixture'}.items():
                (pack/name).write_bytes(value)
            editable = root/'initial.py';editable.write_bytes(b'# different complete module\n')
            wrapper = root/'wrapper.py';wrapper.write_bytes(b'# single-GDS export fixture\n')
            export = root/'export.patch';export.write_text('# exact patch fixture\n')
            initial = root/'initial.patch';initial.write_text('# exact initial patch fixture\n')
            pdk = root/'PDK.json';save(pdk, {'actual_rule_fixture': 1})
            task.update(E1_binding='/old/private/draft_E1_toy_s01/task.json', source_pack_base=str(pack),
                source_files=['generator.py', 'layout.py', 'primitive.gds'], editable_paths=['layout.py'],
                source_overrides={'layout.py': str(editable)}, frozen_source_overrides={'generator.py': str(wrapper)},
                expanded_parameter_baseline={'immutable_original_module': str(pack/'layout.py'), 'frozen_PDK_rules': str(pdk)},
                parameter_baseline={'immutable_original_module': str(pack/'layout.py')},
                export_transport={'original_generator': str(pack/'generator.py'), 'patch': str(export)},
                ancestry={'base_module': str(pack/'layout.py'), 'initial_patch': str(initial)})
            e1_root = root/'frozen_E1';e1['trusted_template'] = str(e1_root/'private/draft_E1_toy_s01/trusted_template')
            save(e1_root/'private/draft_E1_toy_s01/task.json', e1)
            preparation = root/'draft';save(preparation/'public'/task['task_id']/'packet.json', {'complete_source': 'verbatim'})
            result = copy_task(preparation, root/'freeze', task, {'packet_root': str(e1_root)})
            self.assertEqual(result['status'], 'FROZEN_E3_TASK')
            self.assertEqual((Path(result['source_pack_base'])/'primitive.gds').read_bytes(), (pack/'primitive.gds').read_bytes())
            self.assertEqual(Path(result['source_overrides']['layout.py']).read_bytes(), editable.read_bytes())
            self.assertEqual(Path(result['expanded_parameter_baseline']['immutable_original_module']).read_bytes(), (pack/'layout.py').read_bytes())
            self.assertEqual(Path(result['configurations'][-1]['reference_file']).read_bytes(), Path(task['configurations'][-1]['reference_file']).read_bytes())
            self.assertTrue(str(result['source_pack_base']).startswith(str(root/'freeze')))
            self.assertEqual((root/'freeze/packets/public'/task['task_id']/'packet.json').read_bytes(),
                (preparation/'public'/task['task_id']/'packet.json').read_bytes())

    def test_same_context_actual_GPU_stages_and_restore_are_mandatory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);cache = {'snapshot': str(root/'snapshot'), 'revision': 'pinned_revision'}
            save(root/'configs/training/backbone_cache.json', cache)
            context = 12288
            stages = [{'name': 'SFT_optimizer_update', 'allocated_sequence_tokens': context, 'prompt_tokens': context-160,
                'loss': .2, 'wall_seconds': 3., 'peak_allocated_bytes': 100},
                {'name': 'DPO_12288_pair_optimizer_update', 'prompt_tokens': context-160, 'loss': .69,
                    'wall_seconds': 9., 'peak_allocated_bytes': 100, 'frozen_reference_bitwise_unchanged': True},
                {'name': 'actual_saved_adapter_optimizer_RNG_disk_restore', 'adapter_bitwise_equal': True,
                    'optimizer_state_bitwise_equal': True, 'next_CPU_and_CUDA_RNG_equal': True}]
            report = {'scope': 'development_gpu_algorithm_calibration_not_E4', 'status': 'COMPLETED',
                'allocated_sequence_tokens': context, 'stages': stages, 'snapshot': cache['snapshot'],
                'recipe': {'backbone': 'Qwen/Qwen2.5-Coder-32B-Instruct', 'revision': cache['revision'],
                    'quantization': {'load_in_4bit': True, 'bnb_4bit_quant_type': 'nf4',
                        'bnb_4bit_use_double_quant': True, 'compute_dtype': 'bfloat16'}}}
            with patch('scripts.freeze_e3.ROOT', root), patch('scripts.freeze_e3.subprocess.run', return_value=SimpleNamespace(stdout='NVIDIA H100 80GB HBM3\n')):
                self.assertTrue(actual_gpu_calibration(report, context)['disk_restore_verified'])
                report['stages'][-1]['next_CPU_and_CUDA_RNG_equal'] = False
                with self.assertRaises(ValueError):actual_gpu_calibration(report, context)
                report['stages'][-1]['next_CPU_and_CUDA_RNG_equal'] = True
                report['stages'][0]['prompt_tokens'] = 512
                with self.assertRaises(ValueError):actual_gpu_calibration(report, context)

    def test_policy_summary_without_actual_invocation_PID_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);raw = root/'raw';preparation = root/'packets'
            source = root/'layout.py';source.write_text('complete software fixture module\n')
            task = {'editable_paths': ['layout.py'], 'source_overrides': {'layout.py': str(source)}}
            save(preparation/'private/task/task.json', task)
            packet = {'task_id': 'task', 'goal': 'fixture', 'contract': {}, 'allowed_paths': ['layout.py'],
                'visible_sources': {'layout.py': source.read_text()}, 'documents': {'action_gateway': {'read_source_paths': ['layout.py']}},
                'visible_configurations': ['anchor'], 'budget': {}}
            save(raw/'session.json', {'packet': packet, 'config': {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high',
                'max_context_tokens': 12288, 'max_new_tokens': 1024}, 'history': [{}, {}], 'output': '/original/local/decisions/session'})
            save(raw/'decisions/session/decision_000/invocation.json', {'status': 'COMPLETED'})
            save(raw/'decisions/session/decision_000/token_budget.json', {})
            report = {'status': 'COMPLETE_POLICY_INTERFACE_CONTROL', 'scope': 'development_only', 'method': 'C',
                'maximum_decisions': 2, 'actual_model_cli_invocations': 2, 'hidden_calls': 0, 'task_id': 'task',
                'raw_directory': str(raw)}
            with self.assertRaisesRegex(ValueError, 'real bounded tool-disabled'):
                verify_policy_control(report, {'budget': {'maximum_context_tokens': 12288}}, preparation, root)


if __name__ == '__main__':
    unittest.main()
