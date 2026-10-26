import contextlib
import copy
import io
import json
import unittest
from unittest.mock import patch

from scripts.request_frozen_policy import exchange,verify_response


class FrozenTransportTests(unittest.TestCase):
    def body(self,variant='T2'):
        return {'variant':variant,'request':{'task_packet':{'visible_sources':{'g.py':'complete source'},'allowed_paths':['g.py'],
            'visible_configurations':['a'],'budget':{'maximum_context_tokens':12288,'maximum_output_tokens':1024}},'visible_history':[]}}

    def response(self,variant='T2'):
        identity={'variant':variant,'training_seed':None if variant=='T0' else 73,'evaluation_seed_slot':73,
            'methods_manifest_sha256':'methods','adapter_sha256':None if variant=='T0' else 'adapter'}
        return {'inference_id':'software-fixture','native_tools':[],'model_identity':identity,'model':{**identity,'base_revision':'pinned'},
            'action':{'action':'finish','path':'','patch':'','configuration_ids':[],'fidelity':'','summary':'done'},
            'usage':{'input_tokens':100,'output_tokens':20,'max_new_tokens':1024,'maximum_context_tokens':12288,'eos_terminated':True}}

    def test_shim_adds_only_declared_slot_and_preserves_success_payload(self):
        body=self.body();response=self.response();before=copy.deepcopy(body);captured=[]
        def open_url(request,**kwargs):captured.append(json.loads(request.data));return io.BytesIO(json.dumps(response).encode())
        stdout=io.StringIO()
        with patch('scripts.request_frozen_policy.urllib.request.urlopen',side_effect=open_url),contextlib.redirect_stdout(stdout):
            result=exchange(body,73,'methods','adapter','http://127.0.0.1:8117/decision')
        self.assertEqual(result,0);self.assertEqual(captured,[{**body,'training_seed':73}]);self.assertEqual(body,before)
        self.assertEqual(json.loads(stdout.getvalue()),response)

    def test_t0_slot_is_not_an_actual_trained_seed(self):
        response=self.response('T0')
        self.assertEqual(verify_response(response,self.body('T0'),73,'methods',None),response)
        response['model_identity']['training_seed']=73
        with self.assertRaisesRegex(ValueError,'Actual frozen model'):verify_response(response,self.body('T0'),73,'methods',None)

    def test_wrong_identity_is_retained_as_failed_response_with_actual_usage(self):
        response=self.response();response['model_identity']['evaluation_seed_slot']=41;stdout=io.StringIO()
        with patch('scripts.request_frozen_policy.urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())),contextlib.redirect_stdout(stdout):
            code=exchange(self.body(),73,'methods','adapter','http://127.0.0.1:8117/decision')
        raw=json.loads(stdout.getvalue());self.assertEqual(code,2);self.assertEqual(raw['usage'],response['usage'])
        self.assertIn('FrozenPolicyIdentityError',raw['error'])

    def test_native_tools_truncation_and_undeclared_endpoint_are_rejected(self):
        for key,value in [('native_tools',['shell'])]:
            response=self.response();response[key]=value
            with self.assertRaises(ValueError):verify_response(response,self.body(),73,'methods','adapter')
        response=self.response();response['usage']['eos_terminated']=False
        with self.assertRaisesRegex(ValueError,'1024/EOS'):verify_response(response,self.body(),73,'methods','adapter')
        with patch('scripts.request_frozen_policy.urllib.request.urlopen') as call:
            with self.assertRaisesRegex(ValueError,'endpoint'):exchange(self.body(),73,'methods','adapter','http://127.0.0.1:8114/decision')
            call.assert_not_called()


if __name__=='__main__':unittest.main()
