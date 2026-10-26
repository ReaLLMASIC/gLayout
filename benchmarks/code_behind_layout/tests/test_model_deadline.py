from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

from src.model_adapter import GptDecisionAdapter,check_utc_budget


class PolicyDeadlineTests(unittest.TestCase):
    def packet(self,deadline):
        return {"task_id":"unit","goal":"finish","contract":{},"allowed_paths":[],"visible_sources":{},
            "documents":{},"visible_configurations":["anchor"],"budget":{"decisions":1,"deadline_utc":deadline.isoformat()}}

    def test_expired_start_never_spawns_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter=GptDecisionAdapter(tmp,executable="/nonexistent/never-run")
            session=adapter.start(self.packet(datetime.now(timezone.utc)-timedelta(seconds=1)),{"model":"unit","reasoning_effort":"low","timeout_seconds_per_decision":2})
            with self.assertRaises(TimeoutError):adapter.step(session,{})
            self.assertEqual(session["history"],[])

    def test_late_completed_action_and_usage_are_retained_but_not_returned(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);script=root/"fake_cli"
            script.write_text('#!'+sys.executable+'\n'+'''import json,sys
from pathlib import Path
answer=Path(sys.argv[sys.argv.index('--output-last-message')+1])
answer.write_text(json.dumps({'action':'finish','path':'','patch':'','configuration_ids':[],'fidelity':'','summary':'done'}))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':2,'output_tokens':3}}))
''');script.chmod(0o755)
            adapter=GptDecisionAdapter(root/"runs",executable=str(script))
            session=adapter.start(self.packet(datetime.now(timezone.utc)+timedelta(seconds=10)),{"model":"unit","reasoning_effort":"low","timeout_seconds_per_decision":5})
            with patch('src.model_adapter.remaining_utc_budget',side_effect=[5,5,-1]):
                with self.assertRaises(RuntimeError):adapter.step(session,{})
            record=json.loads((Path(session['output'])/'decision_000/invocation.json').read_text())
            self.assertEqual(record['status'],'UTC_BUDGET_EXCEEDED')
            self.assertGreater(record['pid'],0)
            self.assertEqual(session['usage'][0]['output_tokens'],3)
            self.assertNotIn('action',session['history'][0])
            self.assertTrue((Path(session['output'])/'decision_000/action.json').exists())

    def test_full_source_context_overflow_never_spawns_cli(self):
        class Tokenizer:
            def apply_chat_template(self,*args,**kwargs):return {'input_ids':list(range(8000))}
        with tempfile.TemporaryDirectory() as tmp:
            adapter=GptDecisionAdapter(tmp,executable='/nonexistent/never-run',tokenizer=Tokenizer())
            packet=self.packet(datetime.now(timezone.utc)+timedelta(seconds=10))
            packet['budget'].update(maximum_output_tokens=1024,maximum_context_tokens=8192)
            session=adapter.start(packet,
                {'model':'unit','reasoning_effort':'low','timeout_seconds_per_decision':2,'max_context_tokens':8192,'max_new_tokens':1024})
            with self.assertRaisesRegex(ValueError,'no inference issued'):adapter.step(session,{})
            work=Path(session['output'])/'decision_000'
            self.assertFalse((work/'invocation.json').exists())
            self.assertFalse(json.loads((work/'token_budget.json').read_text())['fits_with_full_output_reserve'])

    def test_overlong_gpt_action_retains_raw_output_and_public_cost(self):
        class Tokenizer:
            def apply_chat_template(self,*args,**kwargs):return list(range(10))
            def __call__(self,text,**kwargs):return {'input_ids':list(range(len(text)))}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);script=root/'fake_cli'
            script.write_text('#!'+sys.executable+'\n'+'''import json,sys
from pathlib import Path
answer=Path(sys.argv[sys.argv.index('--output-last-message')+1])
answer.write_text(json.dumps({'action':'finish','path':'','patch':'','configuration_ids':[],'fidelity':'','summary':'x'*1100}))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':2,'output_tokens':1100}}))
''');script.chmod(0o755)
            adapter=GptDecisionAdapter(root/'runs',executable=str(script),tokenizer=Tokenizer())
            packet=self.packet(datetime.now(timezone.utc)+timedelta(seconds=10))
            packet['budget'].update(maximum_output_tokens=1024,maximum_context_tokens=8192)
            session=adapter.start(packet,
                {'model':'unit','reasoning_effort':'low','timeout_seconds_per_decision':5,'max_context_tokens':8192,'max_new_tokens':1024})
            with self.assertRaisesRegex(ValueError,'action not applied'):adapter.step(session,{})
            work=Path(session['output'])/'decision_000'
            self.assertEqual(json.loads((work/'invocation.json').read_text())['status'],'REJECTED_SHARED_OUTPUT_BUDGET')
            self.assertTrue((work/'action.json').exists())
            self.assertEqual(session['usage'][0]['output_tokens'],1100)
            self.assertNotIn('action',session['history'][0])


if __name__=='__main__':unittest.main()
