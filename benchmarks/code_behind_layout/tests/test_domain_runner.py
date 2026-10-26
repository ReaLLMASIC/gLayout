"""Logical domain fixtures; only scripts/domain_smoke.py produces physical data."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.domain_runner import DevelopmentDomainRunner, classify_analysis_failure, inspect_point, validate_domain
from src.measurement import assess


def task_fixture():
    points=[]
    for i in range(25):
        name="point_%02d"%i
        contract={"task_id":"unit_domain","configuration_id":name,"reference_id":"unit_ref_"+str(i),
            "required_corners":["tt"],"specifications":[{"name":"id","unit":"A","min":1e-6}],
            "analysis_contracts":{"OP":{"kind":"op","columns":4,"expected_rows":1}}}
        points.append({"configuration_id":name,"role":"anchor" if i==0 else ("development" if i<9 else "hidden"),
            "parameters":{"width":i+1,"gap":.2},"contract":contract,"reference_netlist":"* independent unit reference\n"})
    return {"phase":"development_domain_pilot","task_id":"unit_domain","parent_lineage":"unit_fixture",
        "pdk_revision":"unit_revision","source_paths":["generator.py"],"editable_paths":["generator.py"],
        "entrypoint":"generator.py","representation":"G1","configurations":points,
        "trusted_evaluator_files":{"evaluate.py":"# unit evaluator fixture\n"},
        "immutable_parameters":["width"],"tunable_layout_parameters":{"gap":{"min":.14,"max":1.}}}


def passing(point):
    return {"configuration_id":point["configuration_id"],"S0":True,"S1":True,"S2":True,
        "execution_integrity":"valid","failure_class":None,"reason":None}


class DomainExecutionTests(unittest.TestCase):
    def make_runner(self,root,workers=1):
        source=root/"input";source.mkdir();(source/"generator.py").write_text("gap=.1\n")
        runner=DevelopmentDomainRunner(task_fixture(),root/"runs",None,None,workers=workers)
        return runner,source

    def test_shape_visibility_and_shared_source_seal(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner,source=self.make_runner(Path(tmp))
            packet=runner.visible_packet({"generator.py":"gap=.1\n"})
            self.assertEqual(len(packet["visible_configurations"]),9)
            self.assertNotIn("point_24",json.dumps(packet))
            packet["contract"]["configurations"][0]["parameters"]["width"]=999
            self.assertEqual(runner.task["configurations"][0]["parameters"]["width"],1)
            runner.freeze(source,patch="--- a/generator.py\n+++ b/generator.py\n@@ -1 +1 @@\n-gap=.1\n+gap=.4\n")
            self.assertEqual(runner.frozen,{"generator.py":"gap=.4\n"})
            with patch.object(runner,"_point",side_effect=passing):
                runner.evaluate_visible()
                before=(runner.output/"public/visible_feedback.json").read_text()
                report=runner.run_hidden()
            self.assertTrue(report["complete_domain_evaluation"])
            self.assertEqual(report["groups"]["hidden"]["S2_coverage"],1.)
            self.assertIsNone(report["regression"])
            self.assertEqual(before,(runner.output/"public/visible_feedback.json").read_text())
            restored=DevelopmentDomainRunner.resume(runner.output,None,None)
            self.assertEqual(restored.report(),report)
            with self.assertRaises(ValueError):restored.run_hidden()

    def test_hidden_requests_and_post_visible_source_mutation_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner,source=self.make_runner(Path(tmp));runner.freeze(source)
            with self.assertRaises(ValueError):runner.evaluate_visible(["point_24"])
            with patch.object(runner,"_point",side_effect=passing):runner.evaluate_visible()
            path=runner.source_dir/"generator.py";path.chmod(0o644);path.write_text("gap=999\n")
            with self.assertRaises(ValueError):runner.run_hidden()

    def test_anchor_only_selection_does_not_receive_post_freeze_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner,source=self.make_runner(Path(tmp));runner.freeze(source)
            with patch.object(runner,"_point",side_effect=passing):
                feedback=runner.evaluate_visible(["point_00"])
                before=(runner.output/"public/visible_feedback.json").read_text()
                report=runner.run_hidden()
            self.assertEqual(set(feedback),{"point_00"})
            self.assertEqual(before,(runner.output/"public/visible_feedback.json").read_text())
            self.assertEqual((report["selection_calls"],report["post_freeze_calls"],report["hidden_calls"]),(1,8,16))
            self.assertTrue(report["complete_domain_evaluation"])
            with self.assertRaises(ValueError):runner.evaluate_visible(["point_01"])

    def test_parameter_controls_cannot_edit_source_or_resize_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner,source=self.make_runner(Path(tmp))
            with self.assertRaises(ValueError):runner.freeze(source,mode="parameter",parameter_values={"width":9})
            with self.assertRaises(ValueError):runner.freeze(source,patch="content",mode="parameter")
            runner.freeze(source,mode="parameter",parameter_values={"gap":.4})
            self.assertEqual(runner.frozen,{"generator.py":"gap=.1\n"})
            self.assertEqual(runner.state["parameter_values"],{"gap":.4})

    def test_incomplete_evidence_pauses_new_points_without_inventing_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner,source=self.make_runner(Path(tmp));runner.freeze(source)
            bad={**passing(runner.task["configurations"][0]),"S2":False,
                "execution_integrity":"incomplete","failure_class":"infrastructure"}
            with patch.object(runner,"_point",return_value=bad) as called:runner.evaluate_visible()
            self.assertEqual(called.call_count,1)
            report=runner.report()
            self.assertFalse(report["complete_domain_evaluation"])
            self.assertIsNone(report["groups"]["hidden"]["S2_coverage"])
            self.assertEqual(report["groups"]["hidden"]["declared"],16)
            with self.assertRaises(ValueError):runner.evaluate_visible()
            with self.assertRaises(ValueError):runner.run_hidden()

    def test_instance_stream_exposes_current_arrival_and_is_not_hidden_transfer(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner,source=self.make_runner(Path(tmp));runner.freeze(source,mode="instance")
            self.assertEqual(runner.next_instance()["configuration_id"],"point_00")
            with patch.object(runner,"_point",side_effect=lambda p,*args:passing(p)):
                runner.evaluate_instance(source)
            self.assertEqual(runner.next_instance()["configuration_id"],"point_01")
            self.assertFalse(runner.report()["strict_hidden_transfer"])
            with self.assertRaises(ValueError):runner.run_hidden()

    def test_finite_partial_analysis_cannot_keep_summary_S2(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);evidence=run/"evidence";evidence.mkdir();(run/"source").mkdir()
            (run/"source/generator.py").write_text("pass\n")
            point=task_fixture()["configurations"][0]
            point["contract"]["analysis_contracts"]["OP"]["expected_rows"]=2
            context={"configuration_id":point["configuration_id"]}
            manifest={"status":"EVALUATED","source_files":["generator.py"],"context":context,
                "candidate":{"container_state":{"Running":False},"returncode":0,"status":"COMPLETED"}}
            (run/"manifest.json").write_text(json.dumps(manifest));(run/"configuration.json").write_text(json.dumps(point["parameters"]))
            (evidence/"provenance.json").write_text(json.dumps({"producer":"trusted_container","candidate_container_stopped":True,"context":context}))
            (evidence/"drc.rpt").write_text("device4 count: 0\n----------------------------------------\n")
            (evidence/"drc.json").write_text(json.dumps({"completed":True,"style":"drc(full)"}))
            (evidence/"lvs.rpt").write_text("Final result:\nCircuits match uniquely.\n")
            fixture=Path(__file__).parent/"fixtures/device4_allnet_pex.spice"
            (evidence/"pex.spice").write_text(fixture.read_text())
            (evidence/"op.dat").write_text("scale gate drain current\n0 .9 .9 -.0001\n")
            (evidence/"op.log").write_text("ngspice-44.2 done\n")
            observation={k:point["contract"][k] for k in ["task_id","configuration_id","reference_id"]}
            observation.update(executed=True,gds_emitted=True,checks={k:True for k in ["drc","lvs","devices","ports","intent"]},
                pex={"executed":True,"kind":"physical_rc","resistance_extracted":True,"capacitance_extracted":True},
                corners={"tt":{"converged":True,"operating_point_valid":True,"metrics":{"id":{"value":.0001,"unit":"A"}}}})
            artifacts={"drc":{"report":"drc.rpt","metadata":"drc.json"},"lvs":{"report":"lvs.rpt"},
                "pex":{"netlist":"pex.spice","top_cell":"device4_rc","ports":["D","G","S","B"]},
                "spice":{"tt":{"analyses":{"OP":{"data":"op.dat","log":"op.log","returncode":0}}}}}
            record={"contract":point["contract"],"observation":observation,"artifacts":artifacts,"assessment":assess(point["contract"],observation)}
            self.assertTrue(record["assessment"]["S2"])
            (evidence/"validation.json").write_text(json.dumps(record))
            checked=inspect_point({"run_directory":str(run)},point,{"generator.py":"pass\n"},point["parameters"])
            self.assertFalse(checked["S2"])
            self.assertEqual(checked["execution_integrity"],"incomplete")
            self.assertEqual(checked["failure_class"],"unknown")

    def test_numerical_failure_requires_completed_gold_and_partial_rows_stay_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/"op.log").write_text("doAnalyses: OP: no convergence\nngspice-44.2 done\n")
            validations={"tt":{"OP":{"complete":False}}}
            records={"tt":{"OP":{"log":"op.log","returncode":1}}}
            for status,expected in [("complete","candidate"),("unavailable","unknown"),("invalid","unknown"),("failed","infrastructure")]:
                result=classify_analysis_failure(validations,records,root,{"status":status})
                self.assertEqual(result["failure_class"],expected)
                self.assertEqual(result["numerical_failure_established"],expected=="candidate")
            (root/"op.log").write_text("ngspice-44.2 done\n")
            result=classify_analysis_failure(validations,records,root,{"status":"complete"})
            self.assertEqual(result["failure_class"],"unknown")
            records["tt"]["OP"].update(returncode=None,timeout=True)
            result=classify_analysis_failure(validations,records,root,{"status":"complete"})
            self.assertEqual(result["failure_class"],"candidate")
            self.assertEqual(result["execution_integrity"],"valid")

    def test_candidate_exit_and_budget_timeout_are_not_tool_start_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/"source").mkdir();(root/"source/generator.py").write_text("pass\n")
            (root/"configuration.json").write_text('{"width":3}')
            candidate={"status":"FAILED","returncode":125,"resource_usage_available":True,
                "container_state":{"Running":False,"Error":"","OOMKilled":False}}
            manifest={"status":"CANDIDATE_FAILED","source_files":["generator.py"],"candidate":candidate}
            for expected,changes in [("candidate",{}),("infrastructure",{"resource_usage_available":False}),
                    ("candidate",{"status":"TIMEOUT","returncode":None,"resource_usage_available":False})]:
                manifest["candidate"]={**candidate,**changes}
                (root/"manifest.json").write_text(json.dumps(manifest))
                record=inspect_point({"run_directory":str(root)},{},{"generator.py":"pass\n"},{"width":3})
                self.assertEqual(record["failure_class"],expected)


if __name__=="__main__":unittest.main()
