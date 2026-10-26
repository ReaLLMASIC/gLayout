import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.training import TrustedPhysicalStore


class PhysicalStoreBoundaryTests(unittest.TestCase):
    def test_frozen_compiler_name_collision_is_a_gold_controlled_candidate_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)/'run';(run/'source').mkdir(parents=True);(run/'trusted').mkdir();(run/'candidate_stage').mkdir()
            (run/'source/layout.py').write_text('candidate_source=1\n')
            (run/'trusted/evaluate.py').write_text('trusted_fixture=1\n')
            (run/'configuration.json').write_text('{"width":3}')
            stage={'status':'FAILED','returncode':1,'container_state':{'Running':False}}
            manifest={'status':'CANDIDATE_FAILED','run_id':'controlled_failure','source_files':['layout.py'],
                'trusted_files':['evaluate.py'],'candidate':stage}
            (run/'manifest.json').write_text(json.dumps(manifest))
            (run/'candidate_stage/invocation.json').write_text(json.dumps(stage))
            console=run/'candidate_stage/console.log'
            console.write_text('textbook_sharing.assembly.engine.AssemblyError: could not rename assembled cell to corpus_c05\n')
            point={'configuration_id':'anchor','parameters':{'width':3},'editable_paths':['layout.py'],'trusted_evaluator_files':{'evaluate.py':'trusted_fixture=1\n'},
                   'contract':{'objective':{'id':'area','metric':'area','unit':'um2','direction':'min','corner_aggregation':'worst'}}}
            checked={'execution_integrity':'valid','failure_class':'candidate','S0':False,'S1':False,'S2':False,
                     'gold_control':{'status':'complete'}}
            with patch('src.domain_runner.inspect_point',return_value=checked):
                result=TrustedPhysicalStore._inspect_execution_run(run,point,{'layout.py':'candidate_source=1\n'})
            self.assertTrue(result['point_evaluation_complete']);self.assertFalse(result['S2'])
            self.assertEqual(result['generation_failure_exception'],'textbook_sharing.assembly.engine.AssemblyError')
            with patch('src.domain_runner.inspect_point',return_value={**checked,'gold_control':{'status':'unavailable'}}):
                with self.assertRaisesRegex(ValueError,'complete same-configuration trusted gold'):
                    TrustedPhysicalStore._inspect_execution_run(run,point,{'layout.py':'candidate_source=1\n'})
            console.write_text('PermissionError: environment denied access\n')
            with patch('src.domain_runner.inspect_point',return_value=checked):
                with self.assertRaisesRegex(ValueError,'Generation failure is not established'):
                    TrustedPhysicalStore._inspect_execution_run(run,point,{'layout.py':'candidate_source=1\n'})

    def test_exact_nine_point_domain_and_baselines_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            configs=[{"configuration_id":"p%d"%i,"split":"train","role":"train_development","domain_role":"anchor" if i==0 else "development",
                "parent_lineage":"compiler","contract":{"task_id":"same_task"}} for i in range(9)]
            store=TrustedPhysicalStore(directory,{"status":"frozen","lineages":[{"lineage_id":"compiler","split":"train","topology_family":"mirror"}],"configurations":configs})
            outcomes=[{"configuration_id":"p%d"%i,"role":"anchor" if i==0 else "development","evidence_path":"e","baseline_evidence_path":"b","baseline_candidate_id":"base"} for i in range(9)]
            candidate={"parent_lineage":"compiler","candidate_id":"candidate","candidate_source":{},"base_source":{},"outcomes":outcomes[:2]}
            with patch.object(store,"_read_run") as reader:
                with self.assertRaisesRegex(ValueError,"exact frozen"):store(candidate)
                reader.assert_not_called()
            candidate["outcomes"]=outcomes
            with patch.object(store,"_read_run",side_effect=lambda name,row,cfg,*rest:{"configuration_id":cfg,"S2":True,"run_id":name+cfg} ) as reader:
                result=store(candidate)
            self.assertEqual(reader.call_count,18)
            self.assertTrue(result["complete_domain_evaluation"])
            self.assertEqual(len(result["family"]),8)
            self.assertEqual(len(result["baseline"]["family"]),8)

    def test_binary_frozen_dependency_is_compared_before_physics(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run=root/"run";pack=root/"pack"
            (run/"source").mkdir(parents=True);pack.mkdir()
            (run/"source/layout.py").write_text("x=1\n")
            (pack/"frozen.gds").write_bytes(b"\x89\x00\xffreference")
            (run/"source/frozen.gds").write_bytes(b"\x89\x00\xffchanged")
            (run/"manifest.json").write_text(json.dumps({"source_files":["layout.py","frozen.gds"]}))
            point={"frozen_source_pack":str(pack),"frozen_source_files":["frozen.gds"],"editable_paths":["layout.py"]}
            with self.assertRaisesRegex(ValueError,"immutable source-capsule"):
                TrustedPhysicalStore._inspect_execution_run(run,point,{"layout.py":"x=1\n"})

    def test_unexposed_lineage_module_is_frozen_for_this_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run=root/"run";pack=root/"pack"
            (run/"source").mkdir(parents=True);pack.mkdir()
            (run/"source/layout.py").write_text("x=2\n")
            (pack/"enumeration.py").write_text("RULE=1\n")
            (run/"source/enumeration.py").write_text("RULE=2\n")
            (run/"manifest.json").write_text(json.dumps({"source_files":["layout.py","enumeration.py"]}))
            point={"frozen_source_pack":str(pack),"frozen_source_files":[],"editable_paths":["layout.py"],
                "lineage_editable_paths":["layout.py","enumeration.py"]}
            with self.assertRaisesRegex(ValueError,"immutable source-capsule"):
                TrustedPhysicalStore._inspect_execution_run(run,point,{"layout.py":"x=2\n"})


if __name__=="__main__":unittest.main()
