"""Software controls only: no model, simulator, physical tool or READY cohort."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import prepare_telescopic_supplement as prep
from scripts import qualify_telescopic_supplement as qualify
from src.generators.telescopic_ota_reference import DEFAULT, schematic


class SupplementTests(unittest.TestCase):
    def test_fixed_cartesian_split_and_finger_intent(self):
        rows = prep.grid(DEFAULT)
        self.assertEqual(len(rows), 25)
        self.assertEqual(len({json.dumps(r['parameters'], sort_keys=True) for r in rows}), 25)
        self.assertEqual({role: sum(r['role'] == role for r in rows)
            for role in ('anchor', 'development', 'hidden')}, {'anchor': 1, 'development': 8, 'hidden': 16})
        anchor = next(r for r in rows if r['role'] == 'anchor')
        self.assertEqual(anchor['parameters'], DEFAULT)
        for row in rows:
            parameters = row['parameters']
            for key in DEFAULT:
                if key not in ('input_width', 'input_length'):
                    self.assertEqual(parameters[key], DEFAULT[key])
            devices = [line.split() for line in schematic(parameters).splitlines() if line.startswith('X')]
            self.assertEqual(len(devices), 32)
            self.assertEqual(len({d[0] for d in devices}), 32)
            inputs = [d for d in devices if d[0].startswith(('XN1_', 'XN2_'))]
            self.assertEqual(len(inputs), 4)
            self.assertTrue(all('w=%g' % parameters['input_width'] in d and
                'l=%g' % parameters['input_length'] in d for d in inputs))

    def test_contract_changes_only_declared_id_sizing_and_direction(self):
        original = {'task_id': 'E2_telescopic', 'configuration_id': 'telescopic_s1', 'reference_id': 'old',
            'immutable_parameters': DEFAULT, 'specifications': [{'name': 'ugb', 'unit': 'Hz', 'min': 1e6}],
            'analysis_contracts': {'ac': {'kind': 'ac', 'points': 241}},
            'objective': {'direction': 'maximize', 'metric': 'ugb', 'unit': 'Hz', 'corner_aggregation': 'worst'}}
        before = copy.deepcopy(original); row = prep.grid(DEFAULT)[0]
        actual = prep.point_contract(original, row)
        self.assertEqual(original, before)
        self.assertEqual(actual['objective']['direction'], 'max')
        for key in ('specifications', 'analysis_contracts'):
            self.assertEqual(actual[key], original[key])
        self.assertEqual(actual['immutable_parameters'], row['parameters'])
        with self.assertRaises(ValueError):
            prep.point_contract({**original, 'objective': {**original['objective'], 'direction': 'min'}}, row)

    def test_mac_prepare_rejected_before_private_materialization(self):
        if prep.ROOT == prep.SERVER: self.skipTest('local-only boundary test')
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'never_created'
            with self.assertRaisesRegex(ValueError, 'research server'):
                prep.prepare(Path(directory)/'nonexistent_manifest', output)
            self.assertFalse(output.exists())

    def fixture(self, directory):
        """Tiny temporary closure, explicitly not an actual qualification."""
        root = Path(directory); private = root/'preparation/private'; private.mkdir(parents=True)
        source = private/'source_pack'; source.mkdir(); (source/'fixture.py').write_text('# software only\n')
        rows = prep.grid(DEFAULT)
        task = {'configurations': rows, 'qualification': {'each_phase_dispatch_window_seconds': 10}}
        prep.save(private/'task.json', task)
        prep.save(private/'manifest.json', {'snapshot_sha256': {'task.json': prep.digest(private/'task.json'),
            'source_pack/fixture.py': prep.digest(source/'fixture.py')}, 'implementation_sha256': {},
            'roles': {'anchor': 1, 'development': 8, 'hidden': 16}})
        return root/'preparation', task

    def test_prepared_bytes_binding_rejects_changed_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            preparation, task = self.fixture(directory)
            self.assertEqual(len(prep.validate(preparation)['configurations']), 25)
            (preparation/'private/source_pack/fixture.py').write_text('# changed\n')
            with self.assertRaisesRegex(ValueError, 'changed'):
                prep.validate(preparation)

    def test_prepare_reuses_original_bound_bytes_and_only_draft_no_calls(self):
        from scripts.e2_telescopic_adapter import point
        original_root = prep.ROOT
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); origin = root/'old_source'; origin.mkdir()
            names = [prep.TARGET, 'src/generators/telescopic_ota_reference.py',
                'src/generators/terminal_access.py', 'generator.py']
            for name in names:
                target = origin/name; target.parent.mkdir(parents=True, exist_ok=True)
                data = (original_root/name).read_bytes() if name != 'generator.py' else b'# software fixture, no execution\n'
                target.write_bytes(data)
                live = root/name; live.parent.mkdir(parents=True, exist_ok=True); live.write_bytes(data)
            gold = root/'old_reference.spice'; gold.write_text(schematic(DEFAULT))
            old_point = point(DEFAULT, 's1', gold); prep.save(root/'point.json', old_point)
            trusted = root/'old_trusted'; trusted.mkdir()
            (trusted/'reference.spice').write_bytes(gold.read_bytes())
            prep.save(trusted/'contract.json', old_point['contract']); prep.save(trusted/'telescopic_bias.json', prep.BIAS)
            (trusted/'original_bench.py').write_text('# software fixture, no measurement\n')
            (trusted/'telescopic_declaration.json').write_bytes((original_root/'configs/development/telescopic_ota_fullflow.json').read_bytes())
            inputs = [root/'point.json', gold]+[origin/name for name in names]+list(trusted.iterdir())
            before = {str(path): path.read_bytes() for path in inputs}
            manifest = root/'old_manifest.json'
            prep.save(manifest, {'status': 'FROZEN', 'formal_execution_allowed': True,
                'immutable_input_sha256': {str(path): prep.digest(path) for path in inputs},
                'pools': [{'pool_id': 'telescopic_s1', 'point': str(root/'point.json'),
                    'source_dir': str(origin), 'source_paths': names, 'full_trusted': str(trusted),
                    'entrypoint': 'generator.py', 'top_cell': 'telescopic_mirror_ota'}]})
            manifest.chmod(0o444)
            output = root/'runtime/task_preparation/software_only'
            try:
                with patch.object(prep, 'ROOT', root), patch.object(prep, 'SERVER', root), \
                        patch.object(prep, 'IMPLEMENTATION', []):
                    summary = prep.prepare(manifest, output)
                    task = prep.validate(output)
                self.assertEqual(summary['new_physical_calls'], 0)
                self.assertFalse(summary['formal_dispatch_allowed'])
                self.assertEqual(len(summary['visible_configurations']), 9)
                self.assertEqual(len(task['configurations']), 25)
                self.assertEqual({str(path): path.read_bytes() for path in inputs}, before)
                self.assertTrue(all(path.stat().st_mode & 0o222 == 0
                    for path in (output/'private').rglob('*') if path.is_file()))
            finally:
                for parent, directories, _ in os.walk(root):
                    Path(parent).chmod(0o700)
                    for name in directories: (Path(parent)/name).chmod(0o700)

    def test_missing_full_ideal_gate_starts_no_output_or_container(self):
        with tempfile.TemporaryDirectory() as directory:
            preparation, _ = self.fixture(directory); root = Path(directory).resolve()
            with patch.object(qualify, 'ROOT', root), patch.object(qualify, 'SERVER', root), \
                    patch.object(qualify, 'full_point') as physical:
                with self.assertRaises(OSError):
                    qualify.run(preparation, root/'runs/development/telescopic_supplement_qualification/new',
                        'full', root/'ideal_missing')
                physical.assert_not_called()
                self.assertFalse((root/'runs').exists())

    def test_unknown_stops_fixed_domain_without_retry_or_hiding_denominator(self):
        with tempfile.TemporaryDirectory() as directory:
            preparation, task = self.fixture(directory); root = Path(directory).resolve()
            output = root/'runs/development/telescopic_supplement_qualification/software_control'
            with patch.object(qualify, 'ROOT', root), patch.object(qualify, 'SERVER', root), \
                    patch.object(qualify, 'verify_ideal_family', return_value=task), \
                    patch.object(qualify, 'resource_gate', return_value={}), \
                    patch.object(qualify, 'full_point', side_effect=ValueError('software unknown')) as physical:
                summary = qualify.run(preparation, output, 'full', root/'unused')
                self.assertEqual(summary['status'], 'UNKNOWN_STOPPED')
                self.assertEqual(summary['attempted_configurations'], 1)
                self.assertEqual(summary['complete_configurations'], 0)
                self.assertEqual(summary['not_run'], 24)
                self.assertFalse(summary['formal_admission'])
                self.assertFalse(summary['hidden_vectors_exported'])
                self.assertEqual(physical.call_count, 1)
                with self.assertRaises(FileExistsError):
                    qualify.run(preparation, output, 'full', root/'unused')
                self.assertEqual(physical.call_count, 1)

    def test_S1_with_missing_actual_full_RC_is_unknown_and_never_store_positive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); run = root/'actual_run'; (run/'evidence').mkdir(parents=True)
            output = root/'attempt'; output.mkdir(); source = root/'source'; source.mkdir()
            point = {'configuration_id': 'z12', 'reference_id': 'independent_z12',
                'parameters': {}, 'contract': {'configuration_id': 'z12'}, 'trusted_dir': str(root/'trusted'),
                'trusted_files': [], 'pdk_revision': prep.PDK}
            task = {'source_pack': str(source), 'source_files': [], 'entrypoint': 'generator.py',
                'task_id': prep.TASK, 'parent_lineage': prep.LINEAGE, 'top_cell': 'fixture', 'ports': ['IN', 'OUT']}
            prep.save(run/'evidence/validation.json', {'contract': point['contract'], 'artifacts': {'pex': {
                'netlist': 'missing_unsimplified_RC.spice', 'top_cell': 'fixture_rc', 'ports': task['ports']}}})
            result = {'run_directory': str(run), 'physical_result': {'assessment': {'S1': True}}}
            with patch('src.candidate_executor.CandidateExecutor') as executor, \
                    patch('src.domain_runner.source_contents', return_value={}), \
                    patch('src.domain_runner.inspect_point', return_value={'S0': True, 'S1': True,
                        'S2': True, 'execution_integrity': 'valid'}), \
                    patch('src.training.TrustedPhysicalStore.inspect_development_run') as store, \
                    patch('scripts.e2_execution.measured_cost', return_value={}):
                executor.return_value.execute.return_value = result
                actual = qualify.full_point(task, point, output, 9999999999)
                store.assert_not_called()
            self.assertFalse(actual['checked']['S2'])
            self.assertEqual(actual['checked']['failure_class'], 'unknown')
            audit = prep.read(output/'full_rc_intent_audit.json')
            self.assertEqual(audit['status'], 'QUARANTINED_UNKNOWN')
            self.assertIn('Missing/empty trusted evidence artifact', audit['error'])
            self.assertGreaterEqual(audit['wall_seconds'], 0)
            self.assertGreaterEqual(audit['actual_CPU_seconds'], 0)
            self.assertFalse(audit['original_RC_changed'])


if __name__ == '__main__':
    unittest.main()
