import copy
import unittest

from src.policy_state import current_state_request


class VisibleStateTests(unittest.TestCase):
    def test_replaces_only_obsolete_source_and_diff_preserving_physical_evidence(self):
        physical={"anchor":{"tiers":{"S0":True,"S1":False,"S2":False},"counterexample":"missing drain connection"}}
        packet={"visible_sources":{"generator.py":"read through gateway"},"contract":{"gain_min":5},"budget":{"decisions":10}}
        history=[{"observation":{"path":"generator.py","content":"old complete source"},
            "action":{"action":"propose_patch","patch":"actual full diff","summary":"connect drain"}},
            {"observation":{"status":"rejected_action","error":"corrupt patch at line7"}},
            {"observation":physical}]
        originals=copy.deepcopy((packet,history))
        result=current_state_request(packet,history,{"generator.py":"complete current source\n"})
        self.assertEqual(result["task_packet"]["visible_sources"]["generator.py"],"complete current source\n")
        self.assertEqual(result["visible_history"][-1]["observation"],physical)
        self.assertEqual(result["visible_history"][1],history[1])
        self.assertNotIn("patch",result["visible_history"][0]["action"])
        self.assertEqual((packet,history),originals)

    def test_does_not_substitute_a_partial_or_undeclared_source_map(self):
        packet={"visible_sources":{"a.py":"","b.py":""}}
        for incomplete in [{"a.py":"full a"},{"a.py":"full a","b.py":"full b","gold.py":"hidden"}]:
            with self.assertRaises(ValueError):current_state_request(packet,[],incomplete)


if __name__=="__main__":unittest.main()
