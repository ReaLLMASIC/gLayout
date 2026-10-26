"""Collection transport binds actual model provenance and keeps raw failures."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.collect_training import sample,sample_rule,source_patch,source_identity
from src.candidate_executor import apply_source_patch


class Response:
    status = 200

    def __init__(self, text):
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False

    def read(self):
        return self.text.encode()


class CollectionTransportTests(unittest.TestCase):
    def call_sample(self, response):
        manifest = {'sampling': {'mode':'train_collection','temperature': .7, 'top_p': .95, 'timeout_seconds': 60}}
        packet = {'allowed_paths': ['layout.py'], 'visible_configurations': ['anchor']}
        with tempfile.TemporaryDirectory() as directory:
            with patch('scripts.collect_training.urllib.request.urlopen', return_value=Response(response)):
                record, action = sample(manifest, packet, [], 101, Path(directory))
            raw = (Path(directory) / 'response.json').read_text()
        return record, action, raw

    def response(self):
        return {'model': {'base_revision': '381fc969f78efac66bc87ff7ddeadb7e73c218a7',
                         'variant': 'T0', 'source_role': 'base_model_formal_train_collection'},
                'usage': {'request_mode': 'train_collection', 'decoding_settings': {
                    'do_sample': True, 'temperature': .7, 'top_p': .95, 'seed': 101}},
                'action': {'action': 'propose_patch', 'path': '', 'configuration_ids': [],
                           'fidelity': '', 'summary': '', 'patch':
                           '--- a/layout.py\n+++ b/layout.py\n@@ deliberately bad hunk\n-a\n+b\n'}}

    def test_development_model_role_rejected(self):
        body = self.response()
        body['model']['source_role'] = 'base_model_development'
        record, _, _ = self.call_sample(json.dumps(body))
        self.assertIn('model role', record['error'])

    def test_bad_hunk_kept_without_silent_repair(self):
        body = self.response()
        record, action, _ = self.call_sample(json.dumps(body))
        self.assertIsNone(record['error'])
        self.assertEqual(action['patch'], body['action']['patch'])
        # The separate real git-apply gateway rejects the hunk; transport does not repair it.

    def test_non_json_response_preserved_as_failure(self):
        record, action, raw = self.call_sample('invalid transport response')
        self.assertIn('not a JSON object', record['error'])
        self.assertIsNone(action)
        self.assertEqual(raw, 'invalid transport response\n')

    def test_mechanical_source_diff_preserves_missing_final_newline(self):
        before='value = 1\n';after='value = 2'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'layout.py').write_text(before)
            apply_source_patch(root,source_patch(before,after,'layout.py'),['layout.py'])
            self.assertEqual((root/'layout.py').read_text(),after)

    def test_ast_dedup_retains_constants_identifiers_and_docstrings(self):
        key=lambda text:source_identity({'layout.py':text},True)
        self.assertEqual(key('value = 1\n'),key('# A new comment\nvalue=1\n'))
        self.assertNotEqual(key('value=1'),key('value=2'))
        self.assertNotEqual(key('value=1'),key('other=1'))
        self.assertNotEqual(key('"old docs"\nvalue=1'),key('"new docs"\nvalue=1'))
        self.assertNotEqual(key('if: invalid'),key('if: different invalid'))

    def test_full_source_teacher_preserves_unparseable_program(self):
        path='textbook_sharing/layout.py';text='if: genuinely invalid source\n'
        body=self.response();body.pop('action')
        body['model'].update(source_role='base_model_formal_train_collection_source',settings={'max_new_tokens':3072})
        body['usage'].update(request_mode='train_collection_source',output_format='complete_module_source');body['proposal']={'source_text':text}
        manifest={'sampling':{'mode':'train_collection_source','temperature':.7,'top_p':.95,'timeout_seconds':240}}
        packet={'allowed_paths':[path],'visible_configurations':['anchor'],'visible_sources':{path:'value=1\n'}}
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)
            with patch('scripts.collect_training.urllib.request.urlopen',return_value=Response(json.dumps(body))):
                record,action=sample(manifest,packet,[],101,out)
            self.assertIsNone(record['error'])
            self.assertEqual((out/'proposed_layout.py').read_text(),text)
            target=out/path;target.parent.mkdir();target.write_text('value=1\n')
            apply_source_patch(out,action['patch'],[path])
            self.assertEqual(target.read_text(),text)

    def test_gpt_teacher_records_trial_without_inventing_seed(self):
        path='textbook_sharing/layout.py'
        body={'model':{'requested_model':'gpt-6.1-sol','source_role':'isolated_GPT_formal_train_source_teacher','settings':{'reasoning_effort':'high','max_new_tokens':3072}},
              'usage':{'request_mode':'train_collection_source_gpt','output_format':'complete_module_source','public_cli_usage':{'input_tokens':100,'output_tokens':30}},
              'native_tools':[],'proposal':{'source_text':'value=2\n'}}
        manifest={'sampling':{'mode':'train_collection_source_gpt','timeout_seconds':240}}
        packet={'allowed_paths':[path],'visible_configurations':['anchor'],'visible_sources':{path:'value=1\n'}}
        tokenizer=lambda *args,**kwargs:{'input_ids':[1,2,3]}
        with tempfile.TemporaryDirectory() as directory:
            with patch('scripts.collect_training.urllib.request.urlopen',return_value=Response(json.dumps(body))):
                record,_=sample(manifest,packet,[],1,Path(directory),tokenizer)
            request=json.loads((Path(directory)/'request.json').read_text())
        self.assertIsNone(record['error']);self.assertIsNone(record['seed']);self.assertEqual(record['trial_id'],1)
        self.assertNotIn('sampling',request);self.assertEqual(request['trial_id'],1)

    def test_rule_source_is_exactly_applied_without_model_request(self):
        path='textbook_sharing/layout.py';before='plan = nm.get(mode) or nm["independent"]\n'
        manifest={'sampling':{'rule_proposer_path':str(Path(__file__).resolve().parents[1]/'scripts/corpus_rule_proposer.py'),'timeout_seconds':5}}
        packet={'allowed_paths':[path],'visible_configurations':['anchor'],'visible_sources':{path:before}}
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)
            with patch('scripts.collect_training.urllib.request.urlopen',side_effect=AssertionError('Rules must not call a model service')):
                record,action=sample_rule(manifest,packet,[],'combined_plan',out)
            target=out/path;target.parent.mkdir();target.write_text(before)
            apply_source_patch(out,action['patch'],[path])
            self.assertEqual(target.read_text(),'plan = nm.get("combined") or nm["independent"]\n')
        self.assertIsNone(record['error']);self.assertIsNone(record['model']);self.assertIsNone(record['seed'])
        self.assertEqual(record['usage']['model_inferences'],0)

    def test_action_teacher_retains_exact_bad_diff_and_targets_its_separate_port(self):
        action=self.response()['action']
        body={'model':{'requested_model':'gpt-6.1-sol','source_role':'isolated_GPT_formal_train_action_teacher',
                       'settings':{'reasoning_effort':'high','max_new_tokens':1024}},
              'usage':{'request_mode':'train_collection_action_gpt'},'native_tools':[],
              'action':action,'raw_action_text':json.dumps(action)}
        manifest={'sampling':{'mode':'train_collection_action_gpt','timeout_seconds':240}}
        packet={'allowed_paths':['layout.py','enumeration.py'],'visible_configurations':['anchor']}
        with tempfile.TemporaryDirectory() as directory:
            with patch('scripts.collect_training.urllib.request.urlopen',return_value=Response(json.dumps(body))) as transport:
                record,actual=sample(manifest,packet,[],1,Path(directory),lambda text,**unused:{'input_ids':list(text.encode())})
            self.assertEqual(transport.call_args[0][0].full_url,'http://127.0.0.1:8116/decision')
        self.assertIsNone(record['error']);self.assertEqual(actual['patch'],action['patch']);self.assertIsNone(record['seed'])

    def test_action_teacher_rejects_overlong_raw_text_even_if_compact_action_fits(self):
        action=self.response()['action']
        body={'model':{'requested_model':'gpt-6.1-sol','source_role':'isolated_GPT_formal_train_action_teacher',
                       'settings':{'reasoning_effort':'high','max_new_tokens':1024}},
              'usage':{'request_mode':'train_collection_action_gpt'},'native_tools':[],
              'action':action,'raw_action_text':' '*1200+json.dumps(action)}
        manifest={'sampling':{'mode':'train_collection_action_gpt','timeout_seconds':240}}
        with tempfile.TemporaryDirectory() as directory:
            with patch('scripts.collect_training.urllib.request.urlopen',return_value=Response(json.dumps(body))):
                record,_=sample(manifest,{'allowed_paths':['layout.py'],'visible_configurations':['anchor']},[],1,Path(directory),lambda text,**unused:{'input_ids':list(text.encode())})
            self.assertEqual(json.loads((Path(directory)/'response.json').read_text())['raw_action_text'],body['raw_action_text'])
        self.assertIn('raw ACTION exceeds',record['error'])


if __name__ == '__main__':
    unittest.main()
