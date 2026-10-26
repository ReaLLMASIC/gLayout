"""Matched T0 interface fixtures; no model loads or physical outcomes."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.collect_matched_t0_proposals import identity
from scripts.serve_matched_t0_proposals import MODE,SEEDS,validate_request


class MatchedT0Tests(unittest.TestCase):
    def fixture(self,root):
        request={'task_packet':{'task_id':'matched_fixture','goal':'Use the actual physical fixture','contract':{'corner':'fixture'},
            'allowed_paths':['layout.py','enumeration.py'],'visible_sources':{'layout.py':'x=1\n','enumeration.py':'y=2\n'},
            'documents':{'full_API':'fixture'},'visible_configurations':['anchor'],
            'budget':{'maximum_context_tokens':16384,'maximum_output_tokens':1024}},
            'visible_history':[{'observation':{'actual_baseline':'fixture','error':None}}]}
        task=root/'task_packet.json';history=root/'visible_history.json'
        task.write_text(json.dumps(request['task_packet']));history.write_text(json.dumps(request['visible_history']))
        plan={'contexts':[{'task_id':'matched_fixture','base_source':copy.deepcopy(request['task_packet']['visible_sources']),
            'materialized_task_packet':str(task),'materialized_visible_history':str(history)}]}
        body={'variant':'T0','mode':MODE,'sampling':{'temperature':.7,'top_p':.95,'seed':SEEDS[0]},'request':request}
        return body,plan

    def test_real_seed_is_outside_exact_same_complete_context(self):
        with tempfile.TemporaryDirectory() as directory:
            body,plan=self.fixture(Path(directory));before=copy.deepcopy(body['request'])
            first,sampling=validate_request(body,plan)
            self.assertEqual(sampling,{'do_sample':True,'temperature':.7,'top_p':.95,'seed':101})
            body['sampling']['seed']=971;last,_=validate_request(body,plan)
            self.assertEqual(first,last);self.assertEqual(body['request'],before)

    def test_changed_physical_feedback_or_source_is_not_a_matched_request(self):
        with tempfile.TemporaryDirectory() as directory:
            body,plan=self.fixture(Path(directory));changed=copy.deepcopy(body)
            changed['request']['visible_history'][0]['observation']['actual_baseline']='different'
            with self.assertRaisesRegex(ValueError,'exact materialized'):validate_request(changed,plan)
            body['request']['task_packet']['visible_sources']['layout.py']='x=3\n'
            with self.assertRaisesRegex(ValueError,'source contexts'):validate_request(body,plan)

    def test_engineering_or_trained_adapter_variant_and_unfrozen_seed_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            body,plan=self.fixture(Path(directory))
            for variant in ['T1','development_SFT_calibration']:
                changed=copy.deepcopy(body);changed['variant']=variant
                with self.assertRaisesRegex(ValueError,'only matched T0'):validate_request(changed,plan)
            body['sampling']['seed']=41
            with self.assertRaisesRegex(ValueError,'eight frozen real seeds'):validate_request(body,plan)

    def test_proposal_dedup_preserves_actual_semantics_and_parse_failures(self):
        self.assertEqual(identity({'f.py':'x=1\n'}),identity({'f.py':'x = 1 # comment\n'}))
        self.assertNotEqual(identity({'f.py':'x=1\n'}),identity({'f.py':'x=2\n'}))
        self.assertNotEqual(identity({'f.py':'x=1\n'}),identity({'f.py':'y=1\n'}))
        self.assertNotEqual(identity({'f.py':'def bad('}),identity({'f.py':'def bad( '}))


if __name__=='__main__':unittest.main()
