"""The prospective goal must not alter devices, specs or historical evidence."""
import copy
import json
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

from scripts.prepare_train_ugb_terminal_pilot import (
    prospective_points, baseline_cells, OBJECTIVE, TASK_ID, SPEC,
)
from scripts import run_train_ugb_terminal_baselines as runner


def fixture():
    points = []
    for i in range(9):
        name = 'z' + str(i)
        points.append({'configuration_id': name, 'reference_id': 'N'+name, 'domain_role': 'anchor' if i == 0 else 'development',
            'parameters': {'circuit': {'circuit_id': 'C08'}, 'sizing': {'M1': {'w': i+1, 'l': .6, 'nf': 2}}},
            'gold_control': {'run_directory': 'old/' + name},
            'contract': {'task_id': 'old', 'configuration_id': name, 'reference_id': 'N'+name,
                'scope': 'old_area', 'objective': {'metric': 'area'},
                'specifications': [{'name': 'ugb_Hz', 'min': 1e7, 'unit': 'Hz'}],
                'analysis_contracts': {'op': {'expected_rows': 1}},
                'required_corners': ['tt', 'ss', 'ff']}})
    files = {'evaluate.py': 'readonly\n', 'references/z0.spice': 'M1 D G S B nch w=1 l=.6\n'}
    files.update({'contracts/'+p['configuration_id']+'.json': json.dumps(p['contract']) for p in points})
    for point in points: point['trusted_evaluator_files'] = copy.deepcopy(files)
    return points


class UGBPreparationTests(unittest.TestCase):
    def test_only_prospective_identity_objective_and_embedded_contracts_change(self):
        old = fixture(); before = copy.deepcopy(old); new = prospective_points(old)
        self.assertEqual(old, before)
        for a, b in zip(old, new):
            self.assertEqual(a['parameters'], b['parameters'])
            self.assertNotIn('gold_control', b)
            self.assertEqual(b['contract']['objective'], OBJECTIVE)
            self.assertEqual(b['contract']['task_id'], TASK_ID)
            for key in set(a['contract']) - {'task_id', 'scope', 'objective'}:
                self.assertEqual(a['contract'][key], b['contract'][key])
            files = b['trusted_evaluator_files']
            self.assertEqual(json.loads(files['contracts/'+b['configuration_id']+'.json']), b['contract'])
            for name in ['evaluate.py', 'references/z0.spice']:
                self.assertEqual(files[name], a['trusted_evaluator_files'][name])

    def test_misbound_parent_contract_and_wrong_circuit_rejected(self):
        points = fixture(); points[0]['contract']['specifications'][0]['min'] = 9
        with self.assertRaisesRegex(ValueError, 'parent independent contract'): prospective_points(points)
        points = fixture(); points[3]['parameters']['circuit']['circuit_id'] = 'C11'
        with self.assertRaisesRegex(ValueError, 'train-admitted C08'): prospective_points(points)

    def test_exactly_three_anchor_controls_then_all_eight_other_points(self):
        points = fixture(); cells = baseline_cells(points)
        self.assertEqual(len(cells), 11)
        self.assertEqual([c['configuration_id'] for c in cells[:3]], ['z0']*3)
        self.assertEqual([c['configuration_id'] for c in cells[3:]], ['z'+str(i) for i in range(1,9)])
        self.assertEqual(len({c['cell_id'] for c in cells}), 11)
        points[1]['domain_role'] = 'anchor'
        with self.assertRaises(ValueError): baseline_cells(points)

    def test_fixed_extraction_tolerance_rejects_one_percent_and_nonfinite(self):
        self.assertFalse(runner.control_spread([100, 101, 100])['passes'])
        self.assertTrue(runner.control_spread([100, 100.99, 100])['passes'])
        for values in [[100, 100], [100, float('nan'), 100], [0, 1, 1]]:
            with self.assertRaises(ValueError): runner.control_spread(values)

    def test_reserved_exception_stops_ten_points_and_cannot_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); output = root/'output'; points = prospective_points(fixture())
            plan = {'output_root': str(output), 'cells': baseline_cells(points)}
            collection = {'source_pack': 'fixture', 'source_files': [], 'trusted_bundle': 'fixture',
                'magic_runtime': 'fixture', 'container_image': 'fixture', 'pdk_revision': 'fixture'}
            initial = {'initial_state_id': SPEC['initial_state_id'], 'parent_lineage': 'fixture'}
            calls = []
            def fail(**args):
                state = runner.read(output/'state.json')
                self.assertEqual(state['cells'][0]['status'], 'DISPATCH_RESERVED')
                self.assertEqual(state['physical_call_reservations'], 1)
                self.assertEqual(args['phase'], 'formal_train'); calls.append(args)
                raise RuntimeError('Software fixture only; no EDA/model executed')
            with patch.object(runner, 'verify', return_value=(plan, collection, {'configurations': points}, initial)):
                state = runner.run(root/'plan', execute=fail, gate=lambda *args: {})
                self.assertEqual(len(state['not_run']), 10); self.assertEqual(state['new_model_calls'], 0)
                with self.assertRaises(FileExistsError): runner.run(root/'plan', execute=fail)
            self.assertEqual(len(calls), 1)

    def test_variable_anchor_controls_prevent_all_eight_development_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); output = root/'output'; points = prospective_points(fixture())
            plan = {'output_root': str(output), 'cells': baseline_cells(points)}
            collection = {'source_pack': 'fixture', 'source_files': [], 'trusted_bundle': 'fixture',
                'magic_runtime': 'fixture', 'container_image': 'fixture', 'pdk_revision': 'fixture'}
            initial = {'initial_state_id': SPEC['initial_state_id'], 'parent_lineage': 'fixture'}
            calls = []
            def call(**args): calls.append(args); return {'run_directory': str(root/str(len(calls)))}
            def checked(*args): return {'objective': [100, 100, 101][len(calls)-1], 'S2': True}
            with patch.object(runner, 'verify', return_value=(plan, collection, {'configurations': points}, initial)), \
                    patch.object(runner, 'check_result', side_effect=checked):
                state = runner.run(root/'plan', execute=call, gate=lambda *args: {}, geometry=lambda *args: {'equal': True})
            self.assertEqual(len(calls), 3); self.assertEqual(len(state['not_run']), 8)
            self.assertEqual(state['status'], 'CONTROL_VARIATION_EXCEEDS_PREDECLARED_BOUND_NO_TEACHER')

    def test_relative_prepared_path_binds_new_readonly_copy_and_preserves_old(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); draft = root/'draft'; draft.mkdir()
            code = root/'consumer.py'; code.write_text('x=1\n'); (draft/'code').mkdir()
            (draft/'code/consumer.py').write_bytes(code.read_bytes())
            points = prospective_points(fixture())
            collection = {'registry_path': str(draft/'registry.json'), 'initial_state_path': str(draft/'initial.json')}
            runner.save(draft/'collection.json', collection); runner.save(draft/'registry.json', {'configurations': points})
            runner.save(draft/'initial.json', {'initial_state_id': SPEC['initial_state_id'], 'task_id': TASK_ID})
            plan = {'status': 'DRAFT_CPU_ONLY_NO_DISPATCH', 'collection': str(draft/'collection.json'),
                'CODE': ['consumer.py'], 'maximum_new_full_points': 11, 'workers': 1,
                'initial_state_id': SPEC['initial_state_id'], 'phase': 'formal_train', 'automatic_retry': False,
                'new_model_calls': 0, 'dispatch_horizon_seconds': 14400, 'cells': baseline_cells(points)}
            runner.save(draft/'baseline_plan_DRAFT.json', plan)
            index = root/'source_index.json'; runner.save(index, {'revision': 'a'*40, 'files_sha256': {'consumer.py': runner.sha(code)}})
            before = (draft/'collection.json').read_bytes(); mode = (draft/'collection.json').stat().st_mode
            import os
            previous = Path.cwd()
            try:
                os.chdir(root)
                with patch.object(runner, 'ROOT', root), patch.object(runner, 'CODE', ['consumer.py']):
                    receipt = runner.freeze(Path('draft'), root/'runtime/protocol_freezes/new', index)
                    bound, copied, *_ = runner.verify(receipt['plan'])
                    self.assertEqual(Path(copied['registry_path']).parent, root/'runtime/protocol_freezes/new')
                    self.assertFalse(Path(receipt['plan']).stat().st_mode & 0o222)
            finally: os.chdir(previous)
            self.assertEqual(before, (draft/'collection.json').read_bytes())
            self.assertEqual(mode, (draft/'collection.json').stat().st_mode)

    def test_GDS_control_equality_keeps_absolute_coordinates_and_labels(self):
        import gdstk
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def write(name, shift=0, label='VOUT'):
                lib = gdstk.Library(unit=1e-6, precision=1e-9); top = lib.new_cell('C08')
                top.add(gdstk.rectangle((shift, 0), (shift+1, 1), layer=68))
                top.add(gdstk.Label(label, (shift+.5, .5), layer=68))
                lib.write_gds(root/name); return root/name
            first = write('first.gds'); same = write('same.gds')
            translated = write('translated.gds', shift=.001); renamed = write('renamed.gds', label='VDD')
            self.assertTrue(runner.exact_geometry(first, same)['equal'])
            self.assertFalse(runner.exact_geometry(first, translated)['equal'])
            self.assertFalse(runner.exact_geometry(first, renamed)['equal'])


if __name__ == '__main__': unittest.main()
