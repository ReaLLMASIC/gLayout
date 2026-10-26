"""Boundary behavior tests; physical evidence comes from the remote smoke only."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.candidate_executor import CandidateExecutor, accepted_gds, apply_source_patch, copy_declared_files, VisibleActionGateway


class CandidateBoundaryTests(unittest.TestCase):
    def test_e3_cannot_relabel_undeclared_source_roles(self):
        from datetime import datetime,timedelta,timezone
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);runtime=root/'runtime';(runtime/'lib/python3.10/site-packages').mkdir(parents=True)
            source=root/'source';source.mkdir();(source/'generator.py').write_text('pass\n')
            trusted=root/'trusted';trusted.mkdir();(trusted/'evaluate.py').write_text('pass\n')
            executor=CandidateExecutor(runtime,root/'runs',runtime)
            args=dict(source_dir=source,source_paths=['generator.py'],entrypoint='generator.py',representation='G2',
                configuration={},trusted_dir=trusted,trusted_paths=['evaluate.py'],phase='formal_E3',
                execution_deadline_utc=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())
            with self.assertRaises(ValueError):executor.execute(**args,context={'source_role':'formal_train'})
            with patch.object(executor,'_run') as run:
                result=executor.execute(**args,context={'source_role':'formal_E3_candidate'})
            run.assert_not_called();self.assertEqual(result['status'],'BUDGET_EXHAUSTED')

    def test_total_deadline_caps_generation_and_prevents_next_container_stage(self):
        from datetime import datetime,timedelta,timezone
        import json
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);runtime=root/'runtime';(runtime/'lib/python3.10/site-packages').mkdir(parents=True)
            source=root/'source';source.mkdir();(source/'generator.py').write_text('print("source fixture")\n')
            trusted=root/'trusted';trusted.mkdir();(trusted/'evaluate.py').write_text('print("trusted fixture")\n')
            executor=CandidateExecutor(runtime,root/'runs',runtime)
            end=(datetime.now(timezone.utc)+timedelta(seconds=10)).isoformat()
            with patch('src.candidate_executor.remaining_utc_budget',side_effect=[10,0,0]),patch.object(executor,'_run',return_value={'returncode':0}) as run:
                result=executor.execute(source_dir=source,source_paths=['generator.py'],entrypoint='generator.py',representation='G2',
                    configuration={},trusted_dir=trusted,trusted_paths=['evaluate.py'],execution_deadline_utc=end)
            self.assertEqual(run.call_count,1)
            self.assertEqual(run.call_args.args[-1],10)
            self.assertEqual(result['status'],'BUDGET_EXHAUSTED')
            manifest=json.loads((Path(result['run_directory'])/'manifest.json').read_text())
            self.assertNotIn('trusted',manifest)

    def test_expired_total_deadline_never_starts_a_container(self):
        from datetime import datetime,timedelta,timezone
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);runtime=root/'runtime';(runtime/'lib/python3.10/site-packages').mkdir(parents=True)
            source=root/'source';source.mkdir();(source/'generator.py').write_text('print("source fixture")\n')
            trusted=root/'trusted';trusted.mkdir();(trusted/'evaluate.py').write_text('print("trusted fixture")\n')
            executor=CandidateExecutor(runtime,root/'runs',runtime)
            end=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
            with patch.object(executor,'_run') as run:
                result=executor.execute(source_dir=source,source_paths=['generator.py'],entrypoint='generator.py',representation='G2',
                    configuration={},trusted_dir=trusted,trusted_paths=['evaluate.py'],execution_deadline_utc=end)
            run.assert_not_called();self.assertEqual(result['status'],'BUDGET_EXHAUSTED')

    def test_stage_timeout_is_passed_and_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);executor=CandidateExecutor(root,root/"runs",root,timeout=600)
            def fake_run(argv,**kwargs):
                from types import SimpleNamespace
                if argv[:2]==["docker","inspect"]:return SimpleNamespace(stdout='{"Running":false}')
                return SimpleNamespace(returncode=0)
            with patch("src.candidate_executor.subprocess.run",side_effect=fake_run) as run:
                record=executor._run(root/"stage","calibration",["docker","run"],240)
            self.assertEqual(run.call_args_list[0].kwargs["timeout"],240)
            self.assertEqual(record["timeout_seconds"],240)

    def test_only_declared_regular_sources_are_copied(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/"src";source.mkdir();out=root/"out"
            (source/"generator.py").write_text("gap=.1\n")
            (source/"hidden.json").write_text("secret")
            copy_declared_files(source,["generator.py"],out)
            self.assertEqual([p.name for p in out.iterdir()],["generator.py"])
            (source/"alias.py").symlink_to(source/"hidden.json")
            with self.assertRaises(ValueError):copy_declared_files(source,["alias.py"],out)
            with self.assertRaises(ValueError):copy_declared_files(source,["../hidden.json"],out)

    def test_candidate_reports_and_symlink_gds_never_cross_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/"candidate.gds").write_bytes(b"gds-fixture")
            self.assertEqual(accepted_gds(root),root/"candidate.gds")
            (root/"validation.json").write_text('{"S2":true}')
            with self.assertRaises(ValueError):accepted_gds(root)
            (root/"validation.json").unlink();(root/"candidate.gds").unlink()
            (root/"candidate.gds").symlink_to("/etc/passwd")
            with self.assertRaises(ValueError):accepted_gds(root)

    def test_visible_gateway_applies_real_patch_and_blocks_hidden_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/"generator.py").write_text("gap=.1\n")
            packet={"allowed_paths":["generator.py"],"visible_sources":{"generator.py":"gap=.1\n"},
                "visible_configurations":["anchor"]}
            gateway=VisibleActionGateway(packet,root,lambda name,fidelity:{"configuration":name})
            action={"action":"propose_patch","path":"","patch":
                "--- a/generator.py\n+++ b/generator.py\n@@ -1 +1 @@\n-gap=.1\n+gap=.4\n",
                "configuration_ids":[],"fidelity":"","summary":"repair"}
            gateway.dispatch(action)
            self.assertEqual((root/"generator.py").read_text(),"gap=.4\n")
            action.update(action="request_evaluation",patch="",fidelity="pex_spice",configuration_ids=["hidden_01"])
            with self.assertRaises(ValueError):gateway.dispatch(action)
            action["configuration_ids"]=["anchor"]
            self.assertEqual(gateway.dispatch(action),{"anchor":{"configuration":"anchor"}})

    def test_allowed_patch_cannot_write_an_unlisted_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/"generator.py").write_text("gap=.1\n")
            patch="--- a/generator.py\n+++ b/trusted.py\n@@ -1 +1 @@\n-gap=.1\n+gap=.4\n"
            with self.assertRaises(ValueError):apply_source_patch(root,patch,["generator.py"])
            self.assertFalse((root/"trusted.py").exists())


if __name__=="__main__":unittest.main()
