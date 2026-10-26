"""CPU-only request identity controls; no model/GPU capacity result is implied."""
import copy
import unittest
from scripts.calibrate_ordinary_inference_memory import ordinary_request


class OrdinaryInferenceMemoryTests(unittest.TestCase):
    def body(self):
        return {'variant':'T0','mode':'matched_train_action_t0','sampling':{'seed':101},'request':{'task_packet':{
            'task_id':'software_fixture','goal':'ordinary edit','contract':{'physical':'same'},
            'allowed_paths':['layout.py'],'visible_sources':{'layout.py':'complete_source = True\n'},
            'documents':{'readonly_caller':'all lines'},'visible_configurations':['a'],
            'budget':{'maximum_context_tokens':16384,'maximum_output_tokens':1024}},
            'visible_history':[{'observation':{'complete_feedback':True}}]}}

    def test_original_full_packet_and_history_are_preserved(self):
        body=self.body();before=copy.deepcopy(body);request=ordinary_request(body)
        self.assertEqual(body,before);self.assertIs(request,body['request'])
        self.assertEqual(request['task_packet']['visible_sources'],before['request']['task_packet']['visible_sources'])

    def test_no_silent_budget_or_incomplete_source_window_conversion(self):
        for key,value in [('maximum_output_tokens',3072),('maximum_context_tokens',8192)]:
            body=self.body();body['request']['task_packet']['budget'][key]=value
            with self.assertRaises(ValueError):ordinary_request(body)
        body=self.body();del body['request']['task_packet']['documents']
        with self.assertRaises(ValueError):ordinary_request(body)


if __name__=='__main__':unittest.main()
