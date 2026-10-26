import unittest
from pathlib import Path
import tempfile
from src.model_adapter import validate_action,GptDecisionAdapter


class GatewayBoundaryTests(unittest.TestCase):
    def test_each_experiment_discloses_its_same_context_to_policy_and_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter=GptDecisionAdapter(Path(tmp),executable='/bin/true',tokenizer=object())
            for context in [8192,12288]:
                packet={'task_id':'fixture','goal':'fixture','contract':{},'allowed_paths':['generator.py'],
                    'visible_sources':{'generator.py':'pass\n'},'documents':{},'visible_configurations':['anchor'],
                    'budget':{'maximum_context_tokens':context,'maximum_output_tokens':1024}}
                config={'max_context_tokens':context,'max_new_tokens':1024}
                session=adapter.start(packet,config)
                self.assertEqual(session['packet']['budget']['maximum_context_tokens'],context)
                with self.assertRaises(ValueError):adapter.start(packet,{**config,'max_context_tokens':context+1024})

    def setUp(self):
        self.packet={"allowed_paths":["generator.py"],"visible_sources":{"generator.py":""},
                     "visible_configurations":["anchor","dev_01"]}
        self.action={"action":"propose_patch","path":"generator.py","configuration_ids":[],
            "fidelity":"","summary":"Change the route clearance", "patch":
            "--- a/generator.py\n+++ b/generator.py\n@@ -1 +1 @@\n-gap = .1\n+gap = .4\n"}

    def test_source_content_patch_is_accepted(self):
        self.assertEqual(validate_action(self.action,self.packet),self.action)

    def test_patch_cannot_hide_evaluator_rename_after_allowed_hunk(self):
        self.action["patch"]+="diff --git a/generator.py b/evaluator.py\nsimilarity index 100%\nrename from generator.py\nrename to evaluator.py\n"
        with self.assertRaises(ValueError):
            validate_action(self.action,self.packet)

    def test_hidden_configurations_and_unlisted_source_reads_are_rejected(self):
        self.action.update(action="request_evaluation",patch="",configuration_ids=["hidden_01"],fidelity="pex_spice")
        with self.assertRaises(ValueError):validate_action(self.action,self.packet)
        self.action.update(action="read_source",path="../evaluator.py",configuration_ids=[])
        with self.assertRaises(ValueError):validate_action(self.action,self.packet)


if __name__=="__main__":unittest.main()
