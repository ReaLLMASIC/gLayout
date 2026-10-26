"""Boundary and adapter-lifecycle fixtures; no GPU or model training is claimed."""
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from scripts.serve_frozen_policy import AdapterBank,QUANTIZATION,validate_methods,validate_request
from src.e4_methods import METHODS,SEEDS
from src.student_interface import CONTEXT_VERSION,interface_definition


class FakeParameter:
    def requires_grad_(self,value):self.value=value


class FakeModel:
    def __init__(self):self.config=SimpleNamespace(use_cache=False);self.parameter=FakeParameter();self.events=[];self.enabled=True
    def parameters(self):return [self.parameter]
    def eval(self):self.events.append('eval')
    def set_adapter(self,name):self.events.append(('set',name))
    def delete_adapter(self,name):self.events.append(('delete',name))
    def load_adapter(self,path,**kwargs):self.events.append(('load',path,kwargs))
    @contextmanager
    def disable_adapter(self):
        self.enabled=False
        try:yield
        finally:self.enabled=True


class FrozenServiceTests(unittest.TestCase):
    def packet(self):
        return {'task_packet':{'task_id':'fixture','goal':'edit','contract':{'frozen':'fixture'},
            'allowed_paths':['generator.py'],'visible_sources':{'generator.py':'complete = True\n'},'documents':{},
            'visible_configurations':['a'],'budget':{'maximum_context_tokens':12288,'maximum_output_tokens':1024}},
            'visible_history':[{'observation':{'S2':False,'reason':'complete actual feedback fixture'}}]}

    def test_only_fixed_ordinary_action_request_with_exact_visible_budgets(self):
        body={'variant':'T4','training_seed':73,'request':self.packet()};definition=interface_definition(CONTEXT_VERSION,12288)
        before=copy.deepcopy(body);self.assertIn('complete = True',validate_request(body,definition));self.assertEqual(body,before)
        for field,value in [('mode','train_collection_source'),('sampling',{'temperature':.7}),('adapter_path','other')]:
            invalid={**body,field:value}
            with self.assertRaisesRegex(ValueError,'Expected only'):validate_request(invalid,definition)
        for seed in [True,42,'41']:
            with self.assertRaisesRegex(ValueError,'actual training seed'):validate_request({**body,'training_seed':seed},definition)
        body['request']['task_packet']['budget']['maximum_output_tokens']=3072
        with self.assertRaisesRegex(ValueError,'1024ordinary'):validate_request(body,definition)

    def test_unknown_engineering_variant_and_expired_decision_cannot_reach_model(self):
        definition=interface_definition(CONTEXT_VERSION,12288);body={'variant':'development_SFT_calibration','training_seed':41,'request':self.packet()}
        with self.assertRaisesRegex(ValueError,'Unknown frozen E4'):validate_request(body,definition)
        body['variant']='T0';body['request']['task_packet']['budget']['deadline_utc']='2000-01-01T00:00:00+00:00'
        with self.assertRaises(TimeoutError):validate_request(body,definition)

    def test_all_twelve_actual_adapters_are_resolved_but_t0_is_one_model(self):
        artifact={'variants':{'T0':{'actual_model_count':1,'actual_training_seeds':[],'matched_evaluation_seed_slots':list(SEEDS)},
            **{m:{'seeds':{str(s):{} for s in SEEDS}} for m in METHODS}},'training_seeds':list(SEEDS),'quantization':QUANTIZATION}
        def resolver(path,method,seed):return {'student_interface':interface_definition(CONTEXT_VERSION,12288),'backbone_snapshot':'fixed'}
        with patch('scripts.serve_frozen_policy.Path.read_text',return_value=json.dumps(artifact)),patch('scripts.serve_frozen_policy.frozen_serving_method',side_effect=resolver) as resolve:
            _,models=validate_methods('/fixture')
            self.assertEqual(resolve.call_count,15);self.assertEqual(len(models),15)
        del artifact['variants']['T3']['seeds']['109']
        with patch('scripts.serve_frozen_policy.Path.read_text',return_value=json.dumps(artifact)):
            with self.assertRaisesRegex(ValueError,'three selected adapters'):validate_methods('/fixture')

    def test_variant_switch_reuses_base_and_keeps_only_one_lora(self):
        base=FakeModel();wrapped=FakeModel();wrapped.base=base;loads=[]
        def first(model,path,**kwargs):loads.append((model,path,kwargs));return wrapped
        def resolver(path,variant,seed):return {'adapter_path':None if variant=='T0' else '/'+variant+'/'+str(seed),
            'training_seed':None if variant=='T0' else seed,'evaluation_seed_slot':seed}
        bank=AdapterBank(base,Path('/fixture'),first,'fixture_digest')
        with patch('scripts.serve_frozen_policy.file_digest',return_value='fixture_digest'),patch('scripts.serve_frozen_policy.frozen_serving_method',side_effect=resolver) as resolve:
            identity=bank.activate('T0',73);self.assertIsNone(identity['training_seed']);self.assertEqual(identity['evaluation_seed_slot'],73)
            self.assertIs(bank.model,base);bank.activate('T1',41);bank.activate('T1',41)
            self.assertEqual(len(loads),1);self.assertIs(loads[0][0],base)
            self.assertEqual(resolve.call_count,2)
            bank.activate('T0',109)
            with bank.context('T0'):self.assertFalse(wrapped.enabled)
            self.assertTrue(wrapped.enabled);bank.activate('T4',109)
            self.assertIs(bank.model,wrapped);self.assertIs(wrapped.base,base)
            deletions=[v for v in wrapped.events if isinstance(v,tuple) and v[0]=='delete'];self.assertEqual(deletions,[('delete','policy')])
            self.assertEqual(bank.resident,('T4',109));self.assertFalse(wrapped.parameter.value)

    def test_failed_switch_quarantines_without_serving_wrong_variant(self):
        model=FakeModel();bank=AdapterBank(model,Path('/fixture'),lambda *a,**k:model,'fixture_digest')
        with patch('scripts.serve_frozen_policy.file_digest',return_value='fixture_digest'),patch('scripts.serve_frozen_policy.frozen_serving_method',return_value={'adapter_path':'/T1'}):bank.activate('T1',41)
        with patch.object(model,'load_adapter',side_effect=RuntimeError('GPU load fixture failure')):
            with patch('scripts.serve_frozen_policy.file_digest',return_value='fixture_digest'),patch('scripts.serve_frozen_policy.frozen_serving_method',return_value={'adapter_path':'/T2'}):
                with self.assertRaisesRegex(RuntimeError,'GPU load'):bank.activate('T2',41)
        with self.assertRaisesRegex(RuntimeError,'quarantined'):bank.activate('T0',41)

    def test_current_draft_fails_validate_only_without_gpu_loading_or_ready_claim(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([sys.executable,str(root/'scripts/serve_frozen_policy.py'),'--validate-only',
            '--methods',str(root/'configs/training/manifest.draft.json')],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertNotIn('READY',result.stdout)
        self.assertIn('all five matched variants',result.stderr)


if __name__=='__main__':unittest.main()
