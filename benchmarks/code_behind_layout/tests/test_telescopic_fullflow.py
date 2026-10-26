"""Software coverage of the new fixed bench transport; no simulator fixtures."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts.telescopic_ota_fullflow import bench_decks, printed_mos_OP, power, bound_design, OLD_FACTORY_CALL, NEW_FACTORY_CALL
from src.generators.telescopic_ota_reference import PORTS, DEFAULT, schematic


class TelescopicFullflowTests(unittest.TestCase):
    def test_declared_analyses_keep_exact_axes_and_feedback(self):
        declaration = json.loads(Path('configs/development/telescopic_ota_fullflow.json').read_text())
        prefix, analyses = bench_decks(Path('/test/rc.spice'),'telescopic_mirror_ota_rc',
            list(reversed(PORTS)),{'VBN_V':1.4,'VBP_V':.6},declaration)
        self.assertEqual(set(analyses),{'op','ac','transient','dc'})
        self.assertIn('CL out 0 2p',prefix)
        self.assertIn('IREF vdd bias 10u',prefix)
        self.assertIn('out out',analyses['dc'][1])
        self.assertIn('out vn',analyses['ac'][1])
        self.assertEqual(analyses['dc'][3]['expected_axis'],[.9,.95,1.,1.05,1.1])
        self.assertEqual(analyses['transient'][3]['end'],16e-6)
        with self.assertRaises(ValueError):
            bench_decks(Path('/test/rc.spice'),'wrong',PORTS[:-1],{},declaration)

    def test_printed_actual_mos_inventory_rejects_alias_or_missing_fields(self):
        # Artificial parser values, not circuit measurements.
        table = 'device m.xdut.x0.msky13\ngm 1\ngds 2\nid 3\nvds .2\nvdsat .1\n'
        self.assertTrue(printed_mos_OP(table,1)['complete'])
        self.assertFalse(printed_mos_OP(table,2)['complete'])
        self.assertFalse(printed_mos_OP(table+table,1)['complete'])
        self.assertFalse(printed_mos_OP(table.replace('gm 1','gm nan'),1)['complete'])
        self.assertFalse(printed_mos_OP(table.replace('vdsat .1\n',''),1)['complete'])
        self.assertAlmostEqual(power([0,0,0,0,0,-1e-5,0,0],{'VBN_V':1.4,'VBP_V':.6},5),18e-6)

    def test_v5_adopts_only_the_exact_api_fix_without_changing_N_or_bench(self):
        # Artificial binding records exercise transport, never report physics.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);original=root/'old';ideal=root/'ideal';failed=root/'failed';new=root/'v5'
            for p in [original/'source_snapshot',original/'b00',ideal,failed,new/'source_snapshot',
                    root/'src/generators',root/'configs/development']:
                p.mkdir(parents=True,exist_ok=True)
            for name in ['telescopic_ota.py','telescopic_ota_reference.py','terminal_access.py']:
                text=(Path('src/generators')/name).read_text()
                if name=='telescopic_ota.py':text=text.replace(NEW_FACTORY_CALL,OLD_FACTORY_CALL)
                (original/'source_snapshot'/name).write_text(text)
                shutil.copyfile(Path('src/generators')/name,root/'src/generators'/name)
                shutil.copyfile(Path('src/generators')/name,new/'source_snapshot'/name)
            def save(path,value):path.write_text(json.dumps(value))
            declaration=json.loads(Path('configs/development/telescopic_ota_fullflow.json').read_text())
            save(root/'configs/development/telescopic_ota_fullflow.json',declaration)
            save(new/'original_fullflow_declaration.json',declaration)
            save(original/'design_manifest.json',{'controls':[{'id':'b00','VBN_V':1.25,'VBP_V':.45}],
                'immutable_per_finger_sizing':DEFAULT,'design':{'application':declaration['application']}})
            (original/'b00/independent_reference.spice').write_text(schematic())
            save(ideal/'summary.json',{'actual_OP_AC_corner_calls':12,'all12_corner_calls_complete':True,
                'positive_controls':['b00'],'first_predeclared_positive_control':'b00'})
            save(ideal/'input_preparation_binding.json',{'preparation':str(original)})
            old_full=Path('scripts/telescopic_ota_fullflow.py')
            shutil.copyfile(old_full,new/'prior_fullflow_source.py');shutil.copyfile(old_full,failed/'telescopic_ota_fullflow.py')
            save(failed/'pilot_manifest.json',{'status':'FAILED'})
            save(new/'engineering_amendment.json',{'original_ideal_run_relative':'ideal',
                'original_failed_fullflow_relative':'failed','engineering_source_identity':'engineering_v5'})
            with patch('scripts.telescopic_ota_fullflow.ROOT',root):
                result=bound_design(new)
                self.assertEqual(result['control']['id'],'b00')
                self.assertEqual(result['engineering_amendment']['new_ideal_calls'],0)
                self.assertTrue(result['engineering_amendment']['independent_reference_bytes_identical'])
                for path,extra in [(root/'src/generators/telescopic_ota.py','\n# extra unapproved source change\n'),
                                   (original/'b00/independent_reference.spice','\n* altered intent\n')]:
                    before=path.read_bytes();path.write_bytes(before+extra.encode())
                    with self.assertRaises(ValueError):bound_design(new)
                    path.write_bytes(before)


if __name__ == '__main__':
    unittest.main()
