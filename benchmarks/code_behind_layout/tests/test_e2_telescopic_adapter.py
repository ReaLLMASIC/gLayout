"""Trusted transport fixtures only; none are physical measurements."""
import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.e2_telescopic_adapter import point,pool_class,variant
from scripts.e2_telescopic_frozen_bench import normalize
from src.generators.telescopic_ota_reference import DEFAULT


class TelescopicAdapterTests(unittest.TestCase):
    def test_variant_cannot_change_circuit_sizing_or_source_body(self):
        source=Path('src/generators/telescopic_ota.py').read_text()
        controls={'branch_gap':125.,'stack_pitch':90.,'join_width':1.,'track_stagger':28.}
        before=ast.parse(source);after=ast.parse(variant(source,controls))
        first=next(n for n in before.body if isinstance(n,ast.FunctionDef) and n.name=='build')
        second=next(n for n in after.body if isinstance(n,ast.FunctionDef) and n.name=='build')
        second.args.kw_defaults=first.args.kw_defaults
        self.assertEqual(ast.dump(before,include_attributes=False),ast.dump(after,include_attributes=False))
        with self.assertRaises(ValueError):variant(source,{**controls,'input_width':1.})

    def test_point_retains_separate_original_op_ac_and_full_limits(self):
        result=point({**DEFAULT,'input_width':2.7},'s0',Path('/fixture/reference.spice'))
        contracts=result['contract']['analysis_contracts']
        self.assertEqual(contracts['op']['columns'],8)
        self.assertEqual(contracts['ac']['points'],241)
        self.assertEqual(contracts['dc']['expected_axis'],[.9,.95,1.,1.05,1.1])
        self.assertEqual(contracts['tran']['end'],16e-6)
        limits={r['name']:r for r in result['contract']['specifications']}
        self.assertEqual(limits['phase_margin']['min'],60)
        self.assertEqual(result['contract']['immutable_parameters']['input_width'],2.7)

    def test_incomplete_normalized_row_has_no_fabricated_electrical_metrics(self):
        row={'complete':False,'operating_point_valid':False,'specifications_passed':False,'metrics':{},
            'analyses':{k:{'process':{'returncode':None}} for k in ['op','ac','transient','dc']}}
        result=normalize({'tt':row},'/fixture')['corners']['tt']
        self.assertFalse(result['converged']);self.assertEqual(result['metrics'],{})
        self.assertEqual(result['analyses']['op']['log'],'/fixture/tt/op.log')
        self.assertEqual(result['analyses']['tran']['data'],'/fixture/tt/transient.dat')

    def test_only_derived_nominal_capsule_counts_two_spice_calls(self):
        cls=pool_class();instance=cls.__new__(cls)
        shared=Path('scripts/e2_stage_prepare.py');original=shared.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'telescopic_nominal_bench.py').write_text('# source-specific two-deck fixture\n')
            (root/'evaluate.py').write_text("record={'physical_tool_calls':{'DRC':0,'LVS':0,'PEX':0,'SPICE':1}}\n")
            with patch('scripts.e2_execution.Pool.execute',return_value={'fixture':True}):
                result=instance.execute(root,[],root,[],'pex_spice','actual_nominal_TT_OP_AC',0)
            self.assertTrue(result['fixture'])
            self.assertIn("'SPICE':2",(root/'evaluate.py').read_text())
            self.assertEqual((root/'e2_nominal_bench.py').read_text(),(root/'telescopic_nominal_bench.py').read_text())
        self.assertEqual(shared.read_bytes(),original)

    def test_complete_no_crossing_or_response_remains_observed_spec_failure(self):
        row={'complete':True,'operating_point_valid':True,'specifications_passed':False,
            'metrics':{'gain_at_10Hz_dB':-3.,'transient_final_plateau_relative_errors':[None,None],
                'sampled_dc_input_output_V':[{'output_V':.8},{'output_V':.8}]},
            'analyses':{k:{'process':{'returncode':0}} for k in ['op','ac','transient','dc']}}
        result=normalize({'tt':row},'/fixture')['corners']['tt']
        self.assertTrue(result['converged']);self.assertTrue(result['operating_point_valid'])
        self.assertFalse(result['original_development_constraints_passed'])
        self.assertNotIn('ugb',result['metrics']);self.assertNotIn('transient_plateau_error',result['metrics'])
        self.assertEqual(result['metrics']['gain']['value'],-3.)


if __name__=='__main__':unittest.main()
