"""Finite dispatch software fixture; no source generation or simulation."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.e2_default_source_controls import IDS,run


class DefaultControlTests(unittest.TestCase):
    def test_only_three_unpatched_original_defaults_and_no_repeat(self):
        pools=[{'pool_id':family+'_'+sid,'sizing_id':sid,'parameters':{'fixture':family+sid}}
            for family in ['five_t','compact_miller','fvf','legacy_miller','telescopic'] for sid in ['s0','s1','s2']]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manifest=root/'manifest.json';manifest.write_text(json.dumps({'pools':pools}))
            def fixture(definition,pool,output):
                return {'pool_id':pool['pool_id'],'status':'SOFTWARE_FIXTURE_NOT_MEASURED','S2_established':False}
            with patch('scripts.e2_default_source_controls.control',side_effect=fixture) as mocked:
                result=run(manifest,root/'batch',2)
                self.assertEqual(mocked.call_count,3)
                self.assertEqual([call.args[1]['pool_id'] for call in mocked.call_args_list],IDS)
                self.assertFalse(result['all_three_positive'])
                with self.assertRaises(FileExistsError):run(manifest,root/'batch',2)
                self.assertEqual(mocked.call_count,3)
            plan=json.loads((root/'batch/plan.json').read_text())
            self.assertEqual(plan['maximum_new_full'],3)
            self.assertEqual(plan['telescopic_control_invocations'],0)
            self.assertFalse(plan['source_N_bench_and_layout_constants_changed'])


if __name__=='__main__':unittest.main()
