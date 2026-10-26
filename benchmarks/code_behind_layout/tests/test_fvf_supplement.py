"""Software equivalence/scope fixtures; no model or physical evidence."""
import copy
from pathlib import Path
import tempfile
import unittest
from scripts.prepare_fvf_supplement import full_module_proof,complete_module_caller,packet,EDITABLE,source_closure


class FVFSupplementTests(unittest.TestCase):
    original='import math\ndef super_class_AB_OTA(pdk):\n    x=pdk+1\n    a=x*2\n    b=x*3\n    return a+b\n'
    hoisted='import math\ndef super_class_AB_OTA(pdk):\n    x=pdk+1\n    a,b=place_and_route_local_bias(x)\n    return a+b\n'
    face='import math\ndef place_and_route_local_bias(x):\n    a=x*2\n    b=x*3\n    return a,b\n'

    def test_complete_module_reconstructed_with_actual_input_output_binding(self):
        self.assertTrue(full_module_proof(self.original,self.hoisted,self.face)['entire_original_module_AST_reconstructed'])

    def test_changed_helper_return_does_not_pass_by_ignoring_return_node(self):
        with self.assertRaisesRegex(ValueError,'dataflow'):
            full_module_proof(self.original,self.hoisted,self.face.replace('return a,b','return b,a'))

    def test_changed_code_outside_face_refused(self):
        with self.assertRaisesRegex(ValueError,'assembly algorithm'):
            full_module_proof(self.original,self.hoisted.replace('return a+b','return a-b'),self.face)

    def test_caller_only_removes_unused_face_injection(self):
        before="def build(parameters,output):\n    module=get_module()\n    # Old injection\n    face=get_face()\n    exec(face,module.__dict__)\n    return module.super_class_AB_OTA(parameters)\n"
        after=complete_module_caller(before)
        self.assertNotIn('exec(',after)
        self.assertIn('return module.super_class_AB_OTA(parameters)',after)

    def test_packet_scope_exact_full_source_and_readonly_complete_caller(self):
        before={'task_id':'old','goal':'old','contract':{'specifications':[{'name':'gain','min':30}],
            'required_corners':['tt','ss','ff']},'allowed_paths':['face.py'],'visible_sources':{'face.py':'old'},
            'documents':{'natural_shortfall':'old10p failure'},'visible_configurations':['anchor'],'budget':{}}
        saved=copy.deepcopy(before);out=packet(before,self.original,'complete caller')
        self.assertEqual(before,saved)
        self.assertEqual(out['allowed_paths'],[EDITABLE])
        self.assertEqual(out['visible_sources'],{EDITABLE:self.original})
        self.assertEqual(out['documents']['action_gateway']['read_source_paths'],[EDITABLE])
        self.assertEqual(out['contract']['specifications'],before['contract']['specifications'])
        self.assertNotIn('natural_shortfall',out['documents'])
        self.assertEqual(out['budget']['maximum_context_tokens'],16384)

    def test_real_qualified_pack_cache_is_not_declared_but_data_remains(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'__pycache__').mkdir()
            (root/'module.py').write_text('complete_source=True\n')
            (root/'data.gds').write_bytes(b'engineering_binary_fixture')
            (root/'__pycache__/module.cpython-310.pyc').write_bytes(b'cached')
            (root/'standalone.pyc').write_bytes(b'cached')
            self.assertEqual(source_closure(root),['data.gds','module.py'])


if __name__=='__main__':unittest.main()
