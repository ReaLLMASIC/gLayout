import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import e1_matched_runner as runner


class FrozenImplementationTest(unittest.TestCase):
    def test_exact_source_binding_and_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);filename=root/'executor.py';filename.write_text('original\n')
            manifest={'status':'FROZEN_E1','implementation_sha256':{'executor.py':hashlib.sha256(filename.read_bytes()).hexdigest()}}
            with patch.object(runner,'ROOT',root):
                runner.verify_implementation(manifest)
                filename.write_text('changed\n')
                with self.assertRaisesRegex(runner.BackendInfrastructureError,'executor.py'):
                    runner.verify_implementation(manifest)

    def test_frozen_manifest_requires_binding(self):
        with self.assertRaisesRegex(runner.BackendInfrastructureError,'no implementation binding'):
            runner.verify_implementation({'status':'FROZEN_E1'})
        runner.verify_implementation({'status':'DRAFT_E1_RUNNER'})

    def test_drift_stops_point_before_capsule_or_container(self):
        with tempfile.TemporaryDirectory() as directory:
            private=Path(directory)
            (private/'freeze_manifest.json').write_text(json.dumps({'status':'FROZEN_E1','implementation_sha256':{'missing.py':'0'*64}}))
            backend=runner.Backend.__new__(runner.Backend);backend.private=private
            with patch.object(backend,'prepare_capsule') as prepare:
                with self.assertRaises(runner.BackendInfrastructureError):
                    backend.evaluate('anchor','pex_spice','search')
                prepare.assert_not_called()

    def test_dispatch_index_precedes_tokenizer_initialization(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);record=root/'dispatch.json';source=root/'policy.py';source.write_text('original\n')
            args=SimpleNamespace(manifest='frozen.json',task='task',method='G1',trial='2',formal=True,dispatch_record=record)
            tokenizer=SimpleNamespace(from_pretrained=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('tokenizer unavailable')))
            with patch.object(runner,'ROOT',root),patch.object(runner,'transport',return_value={'episode_directory':'/backend/episode','packet':{},'implementation_sha256':{'policy.py':hashlib.sha256(source.read_bytes()).hexdigest()}}),patch.dict('sys.modules',{'transformers':SimpleNamespace(AutoTokenizer=tokenizer)}):
                with self.assertRaisesRegex(RuntimeError,'tokenizer unavailable'):runner.run_policy(args)
            self.assertEqual(json.loads(record.read_text()),{'episode_directory':'/backend/episode',
                'local_output_directory':str(root/'runs/formal/E1_policy/episode'),'task_id':'task','method':'G1','trial_id':'2','formal':True})

    def test_local_drift_is_detected_before_tokenizer(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);record=root/'dispatch.json'
            args=SimpleNamespace(manifest='frozen.json',task='task',method='G0',trial='1',formal=True,dispatch_record=record)
            with patch.object(runner,'ROOT',root),patch.object(runner,'transport',return_value={'episode_directory':'/backend/drift','packet':{},'implementation_sha256':{'missing_policy.py':'0'*64}}),patch.dict('sys.modules',{'transformers':SimpleNamespace(AutoTokenizer=None)}):
                with self.assertRaisesRegex(runner.BackendInfrastructureError,'missing_policy.py'):runner.run_policy(args)
            self.assertEqual(json.loads(record.read_text())['episode_directory'],'/backend/drift')

    def test_context_rejection_is_not_a_model_invocation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for index,record in enumerate([None,{'status':'RUNNING'},{'pid':123,'status':'COMPLETED'}]):
                point=root/('decision_%03d'%index);point.mkdir()
                if record is not None:(point/'invocation.json').write_text(json.dumps(record))
            usage=[{'input_tokens':1234,'output_tokens':56}]
            statistics=runner.policy_statistics({'output':str(root),'history':[{}, {}, {}],'usage':usage},root)
            self.assertEqual(statistics['decision_step_attempts'],3)
            self.assertEqual(statistics['model_cli_invocations'],1)
            self.assertEqual(statistics['actual_provider_usage'],usage)
            self.assertEqual(len(statistics['invocation_records']),2)

    def test_transport_uses_pinned_physical_python(self):
        with patch.object(runner.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='{"result":{"status":"ok"}}',stderr='')) as call:
            self.assertEqual(runner.transport({'op':'summary'}),{'status':'ok'})
        command=call.call_args.args[0][-1]
        self.assertIn(runner.REMOTE+'/runtime/GLdev/bin/python scripts/e1_matched_runner.py --backend',command)


if __name__=='__main__':unittest.main()
