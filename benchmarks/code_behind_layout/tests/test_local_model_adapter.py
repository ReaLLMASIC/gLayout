import json
from pathlib import Path
import sys
import tempfile
import unittest

from src.local_model_adapter import LocalDecisionAdapter,decision_prompt,source_proposal_prompt,validate_source_proposal
from src.model_adapter import ACTION_SCHEMA


class LocalPolicyInterfaceTests(unittest.TestCase):
    def packet(self):
        return {"task_id":"test","goal":"read","contract":{},"allowed_paths":["generator.py"],
            "visible_sources":{"generator.py":"declared"},"documents":{},"visible_configurations":["anchor"],
            "budget":{"decisions":1}}

    def test_same_packet_schema_and_visible_history(self):
        request={"task_packet":self.packet(),"visible_history":[{"observation":{"status":"start"}}]}
        prompt=decision_prompt(request)
        self.assertTrue(prompt.endswith(json.dumps(request)))
        with self.assertRaises(ValueError):decision_prompt({**request,"hidden_configurations":["secret"]})

    def test_teacher_complete_source_is_separate_from_action_protocol(self):
        request={"task_packet":self.packet(),"visible_history":[]}
        prompt=source_proposal_prompt(request)
        self.assertIn("complete replacement source",prompt)
        self.assertEqual(validate_source_proposal({"source_text":"def build():\n    pass\n"}),{"source_text":"def build():\n    pass\n"})
        with self.assertRaises(ValueError):validate_source_proposal({"source_text":"x=1","action":"finish"})
        request["task_packet"]["allowed_paths"].append("second.py")
        with self.assertRaises(ValueError):source_proposal_prompt(request)

    def test_transport_is_fixed_and_action_uses_shared_validator(self):
        with tempfile.TemporaryDirectory() as directory:
            script=Path(directory)/"transport.py"
            script.write_text('''import json,sys
body=json.load(sys.stdin)
assert set(body)=={"variant","request"}
action={"action":"read_source","path":"generator.py","patch":"","configuration_ids":[],"fidelity":"","summary":"read"}
print(json.dumps({"inference_id":"test","action":action,"usage":{"input_tokens":3,"output_tokens":4},"model":{"base_revision":"pinned","variant":body["variant"]}}))
''')
            adapter=LocalDecisionAdapter(Path(directory)/"runs",[sys.executable,str(script)])
            session=adapter.start(self.packet(),{"variant":"T0","base_revision":"pinned","timeout_seconds_per_decision":5})
            action=adapter.step(session,{"status":"start"})
            self.assertEqual(set(action),set(ACTION_SCHEMA["required"]))
            self.assertEqual(session["history"][0]["action"]["action"],"read_source")
            self.assertEqual(session["usage"][0]["input_tokens"],3)
            with self.assertRaises(ValueError):adapter.step(session,{})
            adapter.finish(session)
            self.assertTrue((Path(session["output"])/"session.json").is_file())


if __name__=="__main__":unittest.main()
