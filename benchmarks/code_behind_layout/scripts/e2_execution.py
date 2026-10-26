"""Execute the fixed E2 stream and real online geometry heuristics.

Formal dispatch requires a separately approved FROZEN manifest. Development
invocations are never relabeled. This runner contains no surrogate training and
does not read another execution's oracle labels. Each full measurement reuses
only its own exact GDS-bound independent physical RC acquisition.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.e2_stage_prepare import build, cached
from scripts.archive_e2_run import archive
from src.candidate_executor import CandidateExecutor
from src.report_parsers import spice_literal

COPY = "import argparse,shutil\np=argparse.ArgumentParser();p.add_argument('--configuration');p.add_argument('--output');a=p.parse_args()\nshutil.copyfile('/source/input.gds',a.output)\n"


def write(path, value):
    temporary = path.with_suffix(path.suffix+".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n")
    temporary.replace(path)


def resource_gate():
    """Actual shared-host context, never allocated-CPU cost accounting."""
    def cpu():
        row = list(map(int, Path("/proc/stat").read_text().splitlines()[0].split()[1:9]))
        return sum(row), row[3]+row[4]
    while True:
        first = cpu()
        time.sleep(1)
        second = cpu()
        busy = (1-(second[1]-first[1])/(second[0]-first[0]))*os.cpu_count()
        memory = {line.split()[0].rstrip(":"): int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()}
        used = (memory["MemTotal"]-memory["MemAvailable"])/1024**2
        free_disk = shutil.disk_usage(ROOT).free/1024**3
        if busy+2 <= 24 and used <= 190 and free_disk >= 4:
            return {"sample_utc": datetime.now(timezone.utc).isoformat(), "busy_cores": busy, "used_RAM_GiB": used}
        time.sleep(10)


def measured_cost(run):
    run = Path(run)
    manifest = json.loads((run / "manifest.json").read_text())
    stages = {}
    for name in ["candidate", "trusted"]:
        if name not in manifest:
            continue
        usage_path = run / (name+"_stage/resource_usage.json")
        usage = json.loads(usage_path.read_text()) if usage_path.is_file() else None
        stages[name] = {"wall_seconds": manifest[name]["wall_seconds"], "returncode": manifest[name]["returncode"],
            "waited_child_CPU_seconds": usage["child_user_cpu_seconds"]+usage["child_system_cpu_seconds"] if usage else None,
            "CPU_scope": "actual waited child processes" if usage else "missing; no allocated-CPU estimate substituted"}
    return stages


class Pool:
    def __init__(self, manifest, pool, output, method, formal, calibration=None):
        self.manifest, self.pool, self.method, self.formal = manifest, pool, method, formal
        self.out = Path(output)
        self.out.mkdir(parents=True, exist_ok=False)
        self.point = json.loads(Path(pool["point"]).read_text())
        self.calibration = calibration
        self.executor = CandidateExecutor(ROOT / "runtime/GLdev", self.out / "physical", ROOT / "runtime/magic-8.3.685", timeout=600)
        self.source = self.out / "sampler_source"
        shutil.copytree(pool["source_dir"], self.source)
        self.state = {"pool_id": pool["pool_id"], "method": method, "phase": "formal_E2" if formal else "development_E2_execution",
            "scope": "independently_executed_online" if method != "full_oracle" else "fixed_candidate_full_oracle",
            "started_at_utc": datetime.now(timezone.utc).isoformat(), "attempts": [], "accepted": [], "full_evaluations": [],
            "promotion_decisions": [], "status": "RUNNING_GEOMETRY", "oracle_labels_read": False,
            "full_query_budget": 64 if method == "full_oracle" else manifest["heuristics"]["full_budget"],
            "proxy_is_UGB_prediction": False, "calibrated_F3_used": False}
        self.state["physical_observations"] = {}
        self.state["nominal_observations"] = {}
        self.save()

    def save(self):
        write(self.out / "state.json", self.state)

    def execute(self, source, source_paths, trusted, paths, fidelity, stage, index):
        queued = time.monotonic()
        sample = resource_gate()
        event = {**sample, "stage": stage, "stream_index": index, "queue_wait_seconds": time.monotonic()-queued}
        self.state.setdefault("dispatch_events", []).append(event)
        self.save()
        result = self.executor.execute(source_dir=source, source_paths=source_paths, entrypoint="generator.py",
            representation="G2" if stage == "source_to_geometry" else "G0", configuration={"parameters": self.point["parameters"]},
            trusted_dir=trusted, trusted_paths=paths, fidelity=fidelity,
            phase="formal_E2" if self.formal else "development_E2_execution",
            context={"source_role": "formal_E2_candidate" if self.formal else "trusted_engineering_sampler",
                "pool_id": self.pool["pool_id"], "method": self.method, "stream_index": index,
                "configuration_id": self.point["configuration_id"], "reference_id": self.point["reference_id"],
                "stage": stage, "generation_or_PEX_reuse_is_recorded_at_origin": stage != "source_to_geometry"},
            generation_timeout_seconds=300 if stage == "source_to_geometry" else 30,
            evaluator_timeout_seconds=90 if fidelity == "geometry" else 600 if fidelity == "pex" else 5400)
        result["cost"] = measured_cost(result["run_directory"])
        result["queue_wait_seconds"] = event["queue_wait_seconds"]
        return result

    def geometry(self):
        template = self.out / "geometry_trusted"
        paths = build("geometry", template, top=self.pool["top_cell"])
        layer = json.loads((template / "meta.json").read_text())["excluded_layer_datatypes"]
        prior = [{"candidate_id": "development_"+str(i), "source_scope": "retained_development_mask_only", "gds": path}
            for i, path in enumerate(self.pool["development_mask_paths"])]
        for candidate in self.pool["candidate_stream"]:
            if len(self.state["accepted"]) >= self.manifest["candidate_pool_size"]:
                break
            index = candidate["stream_index"]
            # Every candidate is derived from the same frozen initial source,
            # never by accumulating edits from the preceding stream member.
            (self.source / self.pool["layout_target"]).write_bytes(Path(self.pool["source_snapshot"]).read_bytes())
            patch = subprocess.run(["patch", "--batch", "--fuzz=0", "-p0", "-i", candidate["patch"]], cwd=self.source,
                capture_output=True, text=True)
            if patch.returncode:
                raise ValueError("Frozen source/patch binding changed; not a candidate physical failure: "+patch.stderr)
            result = self.execute(self.source, self.pool["source_paths"], template, paths, "geometry", "source_to_geometry", index)
            run = Path(result["run_directory"])
            row = {"stream_index": index, "controls": candidate["controls"], "geometry_execution": result,
                "generation_succeeded": (run / "accepted/candidate.gds").is_file(), "accepted": False}
            physical = result.get("physical_result") or {}
            if row["generation_succeeded"] and physical.get("requested_fidelity_complete"):
                work = self.out / "mask_comparisons" / f"{index:03d}"
                work.mkdir(parents=True)
                inputs = {"candidate_gds": str(run / "accepted/candidate.gds"), "excluded_layer_datatypes": layer, "previous_masks": prior}
                write(work / "inputs.json", inputs)
                with (work / "console.log").open("w") as log:
                    subprocess.run([str(ROOT / "runtime/GLdev/bin/python"), str(ROOT / "scripts/e2_mask_stage.py"),
                        "--inputs", str(work / "inputs.json"), "--output", str(work / "result.json")], stdout=log, stderr=subprocess.STDOUT, check=True)
                comparison = json.loads((work / "result.json").read_text())
                for learned in comparison["new_prior_trusted_summaries"]:
                    for item in prior:
                        if item["gds"] == learned["gds"]:
                            item["trusted_mask_summary"] = learned["trusted_mask_summary"]
                row.update(geometry=physical["geometry"], mask_comparison=str(work / "result.json"),
                    mask_comparison_CPU_seconds=comparison["software_CPU_seconds"], mask_comparison_wall_seconds=comparison["wall_seconds"],
                    duplicate=comparison["duplicate"])
                row["accepted"] = comparison["duplicate"] is None
                if row["accepted"]:
                    accepted = {"stream_index": index, "gds": str(run / "accepted/candidate.gds"), "geometry": physical["geometry"],
                        "source_generation_and_geometry_run": str(run)}
                    self.state["accepted"].append(accepted)
                    prior.append({"candidate_id": str(index), "source_scope": "same_fixed_source_sizing_execution", "gds": accepted["gds"],
                        "trusted_mask_summary": physical["geometry"]["canonical_masks"]})
            elif row["generation_succeeded"]:
                # Tool/transport failure after a valid generated GDS cannot be
                # hidden by selecting the next stream member.
                self.state["status"] = "PAUSED_UNKNOWN_GEOMETRY_CONTROL"
            self.state["attempts"].append(row)
            row["terminal_raw_archive"] = archive(run, retain_accepted_gds=row["accepted"])
            self.save()
            if self.state["status"].startswith("PAUSED"):
                return False
        self.state["status"] = "GEOMETRY_POOL_COMPLETE" if len(self.state["accepted"]) == self.manifest["candidate_pool_size"] else "INSUFFICIENT_DISTINCT_GEOMETRIES"
        self.save()
        return self.state["status"] == "GEOMETRY_POOL_COMPLETE"

    def physical(self, candidate):
        index = candidate["stream_index"]
        previous = self.state["physical_observations"].get(str(index))
        if previous is not None:
            return previous
        work = self.out / "full_inputs" / f"{index:03d}"
        source = work / "source"
        source.mkdir(parents=True)
        (source / "generator.py").write_text(COPY)
        # Retain one inode for the immutable accepted geometry. The executor
        # still makes its own declared isolated snapshot; this is a host-side
        # temporary input, never a symlink crossing the boundary.
        os.link(candidate["gds"], source / "input.gds")
        trusted = work / "pex_trusted"
        files = build("pex", trusted, top=self.pool["top_cell"], point=self.point, full_trusted=self.pool["full_trusted"])
        physical = self.execute(source, ["generator.py", "input.gds"], trusted, files, "pex", "actual_physical_PEX", index)
        record = physical.get("physical_result") or {}
        if record.get("requested_fidelity_complete") and record.get("assessment", {}).get("S1"):
            evidence = Path(physical["run_directory"]) / "evidence"
            inventory = json.loads((evidence / "rc_inventory.json").read_text())
            if inventory["has_real_RC"]:
                values = {"R": [], "C": []}
                text = (evidence / record["artifacts"]["pex"]["netlist"]).read_text()
                for line in text.splitlines():
                    fields = line.split()
                    if len(fields) >= 4 and fields[0][0].upper() in values:
                        values[fields[0][0].upper()].append(spice_literal(fields[3]))
                resistance, capacitance = sum(values["R"]), sum(values["C"])
                physical["post_PEX_features"] = {"R_sum_ohm": resistance, "C_sum_F": capacitance,
                    "R_sum_times_C_sum_s": resistance*capacitance, "fidelity": "actual_full_RC_PEX",
                    "feature_meaning": "Literal sums of extracted R and parasitic C; not effective network resistance, delay or a UGB prediction",
                    "acquisition_run": physical["run_directory"], "acquisition_cost": physical["cost"]}
        shutil.rmtree(trusted)
        self.state["physical_observations"][str(index)] = physical
        self.save()
        return physical

    def nominal(self, candidate):
        index = candidate["stream_index"]
        physical = self.physical(candidate)
        record = physical.get("physical_result") or {}
        observation = {"stream_index": index, "physical": physical, "nominal_execution": None,
            "nominal_complete": False, "prediction": None, "forced_full_reason": None}
        if record.get("requested_fidelity_complete") and record.get("assessment", {}).get("S1"):
            work = self.out / "full_inputs" / f"{index:03d}"
            trusted = work / "nominal_trusted"
            files = cached(trusted, point=self.point, full_trusted=self.pool["full_trusted"], physical_run=physical["run_directory"], nominal=True)
            actual = self.execute(work / "source", ["generator.py", "input.gds"], trusted, files, "pex_spice", "actual_nominal_TT_OP_AC", index)
            shutil.rmtree(trusted)
            observation["nominal_execution"] = actual
            nominal = (actual.get("physical_result") or {}).get("nominal", {})
            ugb = nominal.get("metrics", {}).get("tt_ugb_Hz")
            observation["nominal_complete"] = bool(nominal.get("complete"))
            if observation["nominal_complete"] and nominal.get("operating_point_valid") and ugb is not None:
                observation["prediction"] = self.calibration.predict(ugb)
            else:
                observation["forced_full_reason"] = "nominal_incomplete_or_unhealthy_or_no_unity_crossing"
            observation["nominal_raw_archive"] = archive(actual["run_directory"], retain_accepted_gds=False)
        elif record.get("failure_class") == "candidate" and record.get("requested_fidelity_complete"):
            observation["known_completed_physical_rejection"] = True
        else:
            observation["forced_full_reason"] = "unknown_physical_model"
        self.state["nominal_observations"][str(index)] = observation
        self.save()
        return observation

    def full(self, candidate):
        index = candidate["stream_index"]
        physical = self.physical(candidate)
        work = self.out / "full_inputs" / f"{index:03d}"
        source = work / "source"
        evidence = physical.get("physical_result") or {}
        result = {"stream_index": index, "physical": physical, "full_electrical": None, "S1": evidence.get("assessment", {}).get("S1", False),
            "S2": False, "complete": False, "worst_ugb_Hz": None}
        if evidence.get("requested_fidelity_complete") and result["S1"]:
            complete_trusted = work / "electrical_trusted"
            files = cached(complete_trusted, point=self.point, full_trusted=self.pool["full_trusted"], physical_run=physical["run_directory"])
            electrical = self.execute(source, ["generator.py", "input.gds"], complete_trusted, files, "pex_spice", "full_electrical_on_retained_PEX", index)
            measured = electrical.get("physical_result") or {}
            result.update(full_electrical=electrical, S2=measured.get("assessment", {}).get("S2", False),
                complete=bool(measured.get("point_evaluation_complete")))
            corners = measured.get("observation", {}).get("corners", {})
            if result["complete"] and len(corners) == 3 and all("ugb" in row["metrics"] for row in corners.values()):
                result["worst_ugb_Hz"] = min(row["metrics"]["ugb"]["value"] for row in corners.values())
        elif evidence.get("failure_class") == "candidate" and evidence.get("requested_fidelity_complete"):
            result["complete"] = True
        self.state["full_evaluations"].append(result)
        result["physical_archive"] = archive(physical["run_directory"], retain_accepted_gds=False)
        if result["full_electrical"]:
            result["electrical_archive"] = archive(result["full_electrical"]["run_directory"], retain_accepted_gds=False)
        shutil.rmtree(work)
        self.save()
        return result

    def calibrated_promotions(self, remaining):
        # Acquire each feature at its actual fidelity/cost. All outcomes below
        # are this execution's own visible nominal observations, never labels
        # from the separate full-oracle run.
        self.state["calibrated_F3_used"] = True
        for candidate in remaining:
            self.nominal(candidate)
        remaining = [row for row in remaining if not self.state["nominal_observations"][str(row["stream_index"])].get("known_completed_physical_rejection")]
        while remaining and len(self.state["full_evaluations"]) < self.state["full_query_budget"]:
            verified = [row["worst_ugb_Hz"] for row in self.state["full_evaluations"] if row["S2"] and row["worst_ugb_Hz"] is not None]
            best = max(verified) if verified else None
            eligible = []
            for row in remaining:
                observed = self.state["nominal_observations"][str(row["stream_index"])]
                prediction = observed["prediction"]
                force = prediction is None or prediction["force_full"]
                upper = None if prediction is None else prediction["upper_ugb_Hz"]
                if force or best is None or upper >= best:
                    eligible.append((row, force, upper))
            if not eligible:
                break
            eligible.sort(key=lambda item: (not item[1], -(item[2] if item[2] is not None else float("inf")), item[0]["stream_index"]))
            selected, forced, upper = eligible[0]
            self.state["promotion_decisions"].append({"after_full_queries": len(self.state["full_evaluations"]),
                "selected_stream_indices": [selected["stream_index"]], "observed_ranking_key": "independent_calibration_upper_UGB",
                "force_full": forced, "upper_ugb_Hz": upper, "best_actually_verified_feasible_ugb_Hz": best,
                "prediction_establishes_S2": False, "oracle_or_unobserved_full_labels_read": False})
            self.save()
            self.full(selected)
            remaining.remove(selected)
        self.state["unpromoted_due_to_budget_or_empirical_interval"] = [row["stream_index"] for row in remaining]
        self.state["forced_full_left_when_budget_exhausted"] = sum(
            self.state["nominal_observations"][str(row["stream_index"])]["prediction"] is None
            or self.state["nominal_observations"][str(row["stream_index"])]["prediction"]["force_full"] for row in remaining)
        # Unselected raw PEX is retained compressed. No unselected prediction
        # becomes a feasible design or an observed electrical rejection.
        for row in self.state["nominal_observations"].values():
            physical = row["physical"]
            row["physical_raw_archive"] = archive(physical["run_directory"], retain_accepted_gds=False)
        for path in (self.out / "full_inputs").glob("*"):
            if path.is_dir():
                shutil.rmtree(path)

    def RC_heuristic_promotions(self, remaining):
        for candidate in remaining:
            self.physical(candidate)
        def rank(row):
            observed = self.state["physical_observations"][str(row["stream_index"]) ]
            feature = observed.get("post_PEX_features")
            return (feature["R_sum_times_C_sum_s"] if feature else float("inf"), row["stream_index"])
        remaining.sort(key=rank)
        for candidate in remaining[:self.state["full_query_budget"]]:
            self.state["promotion_decisions"].append({"selected_stream_indices": [candidate["stream_index"]],
                "observed_ranking_key": "R_sum_times_C_sum_s", "feature_fidelity": "actual_full_RC_PEX",
                "heuristic_only_no_calibrated_UGB_prediction": True})
            self.full(candidate)
        for physical in self.state["physical_observations"].values():
            physical["raw_archive"] = archive(physical["run_directory"], retain_accepted_gds=False)
        for path in (self.out / "full_inputs").glob("*"):
            if path.is_dir():
                shutil.rmtree(path)

    def run(self):
        if not self.geometry():
            return self.state
        remaining = list(self.state["accepted"])
        feasible_in_last_batch = True
        budget = self.state["full_query_budget"]
        if self.method == "f3_calibrated":
            self.calibrated_promotions(remaining)
            remaining = []
        if self.method == "fixed_rc_product":
            self.RC_heuristic_promotions(remaining)
            remaining = []
        while remaining and len(self.state["full_evaluations"]) < budget:
            key = "physical_mask_bbox_area_um2" if self.method != "adaptive_geometry" or feasible_in_last_batch else "union_rectilinear_proxy_um"
            remaining.sort(key=lambda row: (row["stream_index"],) if self.method == "full_oracle" else (row["geometry"][key], row["stream_index"]))
            batch = remaining[:min(2, budget-len(self.state["full_evaluations"]))]
            del remaining[:len(batch)]
            self.state["promotion_decisions"].append({"after_full_queries": len(self.state["full_evaluations"]),
                "selected_stream_indices": [row["stream_index"] for row in batch], "observed_ranking_key": key,
                "previous_batch_had_feasible": feasible_in_last_batch, "oracle_or_unobserved_labels_read": False})
            self.save()
            observed = [self.full(candidate) for candidate in batch]
            feasible_in_last_batch = any(row["S2"] for row in observed)
        rows = self.state["full_evaluations"]
        feasible = [row["worst_ugb_Hz"] for row in rows if row["S2"] and row["worst_ugb_Hz"] is not None]
        self.state.update(status="TERMINAL", completed_at_utc=datetime.now(timezone.utc).isoformat(),
            observed_feasible=len(feasible), observed_unknown=sum(not row["complete"] for row in rows),
            best_observed_feasible_ugb_Hz=max(feasible) if feasible else None,
            finite_pool_oracle_defined=self.method == "full_oracle" and bool(feasible) and all(row["complete"] for row in rows),
            regret=None, regret_reason="Requires separately sealed complete feasible oracle; never read by the running method")
        self.state["full_measurements_completed_or_attempted"] = len(rows)
        self.state["not_full_measured"] = len(self.state["accepted"])-len(rows)
        selected_indices = {row["stream_index"] for row in rows}
        known = sum((record.get("physical_result") or {}).get("failure_class") == "candidate"
            and (record.get("physical_result") or {}).get("requested_fidelity_complete")
            for index, record in self.state["physical_observations"].items() if int(index) not in selected_indices)
        self.state["unselected_completed_physical_rejections"] = known
        self.state["unselected_unknown_S2"] = self.state["not_full_measured"]-known
        self.state["predictions_never_establish_S2_or_electrical_infeasibility"] = True
        self.save()
        return self.state


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--method", choices=["full_oracle", "fixed_area", "adaptive_geometry", "fixed_rc_product", "f3_calibrated"], required=True)
    p.add_argument("--calibration", type=Path)
    p.add_argument("--pool-id", action="append")
    p.add_argument("--online-six", action="store_true")
    p.add_argument("--workers", type=int, choices=[1, 2], default=1)
    p.add_argument("--formal", action="store_true")
    a = p.parse_args()
    started = time.monotonic()
    before_self = resource.getrusage(resource.RUSAGE_SELF)
    before_children = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        return dispatch(a)
    finally:
        after_self = resource.getrusage(resource.RUSAGE_SELF)
        after_children = resource.getrusage(resource.RUSAGE_CHILDREN)
        if a.output.is_dir():
            write(a.output / "controller_resource_usage.json", {"wall_seconds": time.monotonic()-started,
                "self_user_CPU_seconds": after_self.ru_utime-before_self.ru_utime,
                "self_system_CPU_seconds": after_self.ru_stime-before_self.ru_stime,
                "waited_host_tool_child_user_CPU_seconds": after_children.ru_utime-before_children.ru_utime,
                "waited_host_tool_child_system_CPU_seconds": after_children.ru_stime-before_children.ru_stime,
                "scope": "Actual host controller and its waited mask/patch/docker-client processes. Container simulation CPU is separately recorded by each trusted launcher.",
                "overlapping_components_do_not_add_twice": ["mask-comparison helper CPU belongs to host-tool children", "archive thread CPU belongs to controller self CPU", "SPICE per-analysis child CPU belongs to trusted-container total CPU"]})


def dispatch(a):
    manifest = json.loads(a.manifest.read_text())
    if a.formal and (manifest["status"] != "FROZEN" or not manifest["formal_execution_allowed"]):
        raise ValueError("Formal E2 cannot start from a DRAFT or unapproved contract")
    calibration = None
    if a.method == "f3_calibrated":
        if a.calibration is None:
            raise ValueError("F3 requires the actual independent train/validation calibration artifact")
        from src.promotion_calibration import NominalWorstCalibration
        artifact = json.loads(a.calibration.read_text())
        if a.formal and not artifact["formal_calibration_freeze"]:
            raise ValueError("The real calibration artifact must be frozen before formal promotion")
        calibration = NominalWorstCalibration(artifact)
    if a.method == "full_oracle" and a.online_six:
        raise ValueError("The six online runs are real heuristic executions, not offline oracle replays")
    if a.method != "full_oracle" and not a.online_six and not a.pool_id:
        raise ValueError("Select explicit online tasks")
    pools = [pool for pool in manifest["pools"] if (not a.pool_id or pool["pool_id"] in a.pool_id)
        and (not a.online_six or pool["online_selected"])]
    if a.online_six and len(pools) != 6:
        raise ValueError("Exactly six prospectively assigned online tasks are required")
    a.output.mkdir(parents=True, exist_ok=False)
    write(a.output / "execution.json", {"manifest": str(a.manifest.resolve()), "method": a.method,
        "formal": a.formal, "pool_ids": [pool["pool_id"] for pool in pools], "workers": a.workers,
        "online_runs_are_separate_actual_executions": a.online_six, "oracle_labels_available_to_method": False})
    def run(pool):
        return Pool(manifest, pool, a.output / pool["pool_id"], a.method, a.formal, calibration).run()
    with ThreadPoolExecutor(max_workers=a.workers) as executor:
        results = list(executor.map(run, pools))
    write(a.output / "summary.json", {"formal": a.formal, "method": a.method,
        "pool_results": [{key: row.get(key) for key in ["pool_id", "status", "observed_feasible", "observed_unknown", "best_observed_feasible_ugb_Hz"]} for row in results]})


if __name__ == "__main__":
    main()
