"""Software-only checks of independent intent, matching and bench arithmetic."""
import ast
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.prepare_ratio_source_train_domain import prepare
from src.train_generators.ratio_source import device_dimensions
from src.train_generators.ratio_source_intent import K_VALUES, R_VALUES, point, reference_spice
from src.train_generators.ratio_source_bench import analysis_decks, measure


class RatioSourceTrainDomainTests(unittest.TestCase):
    def test_all_nine_independent_Ns_have_branch_specific_dimensions_and_readonly_contracts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'declared'; result = prepare(root)
            self.assertEqual(result['new_ideal_calls'], 0)
            declaration = json.loads((root / 'domain.json').read_text())
            self.assertEqual(len(declaration['configurations']), 9)
            for row in declaration['configurations']:
                config = row['parameters']; k, ratio = config['K'], config['R']
                sizes = config['sizing']; actual = device_dimensions(config)
                for name, size in sizes.items():
                    self.assertEqual(actual[name]['fingers'], size['nf'])
                    self.assertEqual(actual[name]['per_finger_width'], size['w'] / size['nf'])
                    self.assertEqual(actual[name]['length'], size['l'])
                self.assertEqual(sizes['MOUT2']['nf'], k * ratio)
                path = root / row['reference_file']; source = path.read_text()
                self.assertEqual(source, reference_spice(row))
                self.assertEqual(sum(line.startswith('XM') for line in source.splitlines()), k * (2 + ratio))
                self.assertFalse(path.stat().st_mode & 0o222)
                expected = 300000 / ratio
                self.assertEqual(next(s['min'] for s in row['contract']['specifications']
                    if s['name'] == 'branch2_output_resistance_ohm'), expected)
            self.assertFalse((root / 'domain.json').stat().st_mode & 0o222)

    def test_independent_port_excitations_and_exact_declared_outputs_are_present(self):
        config = point(4, 2); decks = analysis_decks(config, Path('/trusted/reference.spice'), 'ss')
        self.assertEqual(set(decks), {'ac1', 'ac2', 'dc1', 'dc2', 'tran1', 'tran2'})
        self.assertIn('XDUT 0 bias out1 out2 ratio_cs_k4_r2', decks['dc1'])
        self.assertIn('VOUT1 out1 0 .9 ac 1', decks['ac1'])
        self.assertIn('VOUT2 out2 0 .9 ac 0', decks['ac1'])
        self.assertIn('VOUT1 out1 0 .9 ac 0', decks['ac2'])
        self.assertIn('VOUT2 out2 0 .9 ac 1', decks['ac2'])
        self.assertIn('dc VOUT2 0 1.8 .1', decks['dc2'])
        self.assertIn('tran 5n 4u', decks['tran2'])
        self.assertIn('wrdata op.dat v(bias) i(vout1) i(vout2) i(vsupply)', decks['ac1'])

    def tables(self, ratio):
        currents = {1: 5e-6, 2: 5e-6 * ratio}
        data = {'op': [[0, .8, -currents[1], -currents[2], -5e-6]]}
        for driven in (1, 2):
            data['dc' + str(driven)] = []
            for index in range(19):
                voltage = index / 10
                values = {branch: currents[branch] * (1 + .01 * (voltage - .9) if branch == driven else 1)
                          for branch in (1, 2)}
                data['dc' + str(driven)].append([voltage, voltage, -values[1], -values[2], .8, -5e-6])
            data['tran' + str(driven)] = []
            for time, voltage in [(0, .875), (1.9e-6, .925), (2.9e-6, .875), (4e-6, .875)]:
                outputs = {branch: voltage if branch == driven else .9 for branch in (1, 2)}
                values = {branch: currents[branch] * (1 + .01 * (outputs[branch] - .9)) for branch in (1, 2)}
                data['tran' + str(driven)].append([time, outputs[1], outputs[2], -values[1], -values[2], .8, -5e-6])
        data['ac1'] = [[10, -currents[1] * .01, 0, 0, 0]]
        data['ac2'] = [[10, 0, 0, -currents[2] * .01, 0]]
        return data

    def test_current_column_sign_ratio_conductance_and_both_port_settling_are_measured(self):
        config = point(8, 4); data = self.tables(4); result = measure(config, data)
        self.assertTrue(result['ideal_application_constraints_pass'])
        self.assertAlmostEqual(result['metrics']['branch1_output_resistance_ohm'] / 20e6, 1, places=10)
        self.assertAlmostEqual(result['metrics']['branch2_output_resistance_ohm'] / 5e6, 1, places=10)
        self.assertAlmostEqual(result['metrics']['branch2_nominal_current_A'], 20e-6)
        self.assertAlmostEqual(result['metrics']['external_reference_supply_work_W'], 9e-6)
        self.assertLess(result['metrics']['max_settled_relative_current_error_vs_DC'], 1e-12)
        drift = copy.deepcopy(data)
        drift['tran1'][1][4] *= 1.01  # Inactive output2 must also settle under output1 excitation.
        self.assertFalse(measure(config, drift)['ideal_application_constraints_pass'])

    def test_high_level_layout_does_not_import_any_circuit_assembly_or_compiler(self):
        source = Path(__file__).resolve().parents[1] / 'src/train_generators/ratio_source.py'
        tree = ast.parse(source.read_text())
        allowed = {'gdsfactory', 'glayout', 'glayout.primitives.fet', 'src.generators.terminal_access',
                   'argparse', 'json', 'sys', 'pathlib'}
        modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        modules.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
        self.assertTrue(modules.issubset(allowed))
        self.assertIn('glayout.primitives.fet', modules)


if __name__ == '__main__':
    unittest.main()
