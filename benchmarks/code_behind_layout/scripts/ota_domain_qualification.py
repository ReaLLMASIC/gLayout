"""Private development OTA domain qualification using retained actual GDS.

Uses the shared isolated executor and trusted physical evaluator. Generation
reuse is explicit; the original acquisition remains charged. Hidden GDS and
point-level outcomes remain private. This does not create formal measurements.
"""
import argparse
import ast
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import copy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.candidate_executor import CandidateExecutor
from src.domain_runner import inspect_point, source_contents
from src.measurement import validate_contract

TASK_PREPARATION = ROOT / "runtime/task_preparation/otas_20261019T022816023029Z"
COPY_SOURCE = '''import argparse,shutil
p=argparse.ArgumentParser();p.add_argument('--configuration');p.add_argument('--output');a=p.parse_args()
shutil.copyfile('/source/input.gds',a.output)
'''


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n")


def analysis_contracts(kind, long_window=False):
    if kind in ["five_t", "compact_miller"]:
        from scripts.materialize_e1_packets import ota_analysis_contracts
        return ota_analysis_contracts(kind)
    return {"op": {"kind": "op", "columns": 7, "expected_rows": 1},
        "ac": {"kind": "ac", "columns": 3, "start": 10, "end": 1e9, "points": 241, "scale": "log"},
        "tran": {"kind": "transient", "columns": 4, "start": 0, "end": 20e-6 if long_window else 4e-6,
            "required_windows": [[8.5e-6, 9.9e-6], [13.5e-6, 14.9e-6]] if long_window else [[1.8e-6, 1.99e-6], [2.8e-6, 2.99e-6]]},
        "dc": {"kind": "dc", "columns": 4, "start": .6, "end": 1.2, "points": 7, "scale": "linear"}}


def prepare(kind, generation_run, load_pf):
    original = TASK_PREPARATION / "private" / kind
    task = json.loads((original / "task.json").read_text())
    if kind not in ["fvf", "legacy_miller"] or load_pf != 15.:
        raise ValueError("Only the two separately declared prospective15pF vendor applications are owned here")
    if kind == "legacy_miller":
        control = ROOT / "runs/phase0/phase0_20261019T024226699014Z_independent_legacy_domain/domain_result.json"
        if not control.is_file() or not json.loads(control.read_text())["all_corner_development_feasible"]:
            raise ValueError("Legacy15 application requires its single actual complete positive control; no load search")
    out = ROOT / "runs/development/ota_domain_qualification" / (kind+"_"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ_" )+uuid.uuid4().hex[:8])
    (out / "private/references").mkdir(parents=True, mode=0o700)
    (out / "public").mkdir()
    trusted = out / "private/trusted_common"
    (trusted / "src").mkdir(parents=True)
    (trusted / "src/__init__.py").write_text("")
    for name in ["physical_drc.py", "report_parsers.py", "device_intent.py", "measurement.py", "spice_validation.py", "corpus_metrics.py"]:
        shutil.copy2(ROOT / "src" / name, trusted / "src" / name)
    shutil.copy2(ROOT / "scripts/e1_trusted_evaluator.py", trusted / "evaluate.py")
    shutil.copy2(ROOT / "scripts/ota_frozen_bench.py", trusted / "ota_frozen_bench.py")
    bench = original / "trusted_bench/original_retained_bench.py"
    if kind == "legacy_miller":
        bench = ROOT / "runs/phase0/phase0_20261019T024226699014Z_independent_legacy_domain/testbench_load15_long_window.py"
    text = bench.read_text()
    (trusted / "original_bench.py").write_text(text)
    if kind in ["fvf", "legacy_miller"]:
        import textwrap
        loop = next(n for n in ast.parse(text).body if isinstance(n, ast.For))
        (trusted / "analysis_function.py").write_text("def run_exact_analysis_loop():\n"+textwrap.indent(ast.get_source_segment(text, loop), "    ")+"\n")
    meta = {"bench_kind": "vendor_ota" if kind in ["fvf", "legacy_miller"] else "ota",
        "circuit": kind, "top_cell": task["cell_name"], "ports": task["ports"]}
    write(trusted / "meta.json", meta)
    task["prepared_source_task_origin"] = str(original / "task.json")
    task["old_task_file_modified"] = False
    task["source_family"] = kind
    task["source_generation_run"] = generation_run
    task["application_is_new_development_informed_version"] = True
    task["task_id"] = "draft_"+kind+"_load15_10nm_application"
    task["initial_state_id"] += "_load15_10nm_application"
    task["old_task_natural_shortfall_for_provenance"] = task["natural_shortfall"]
    task["natural_shortfall"] = "New15pF application chosen from a complete development positive control; full25-domain and shared-source improvement remain to be established. Old10pF/.5pF performance failures are separate retained task versions."
    task["application_parameters"] = {"supply_V": 1.8, "temperature_C": 27, "common_mode_V": .9,
        "bias_currents_A": [1e-5, 1e-5], "load_F": load_pf*1e-12}
    task["pdk_revision"] = "0fe599b2afb6708d281543108caf8310912f54af"
    shutil.copytree(original / "source_pack", out / "private/source_pack")
    task["source_pack"] = str(out / "private/source_pack")
    def quantize(value, grid):
        return float((Decimal(str(value))/Decimal(str(grid))).quantize(Decimal(1), rounding=ROUND_HALF_UP)*Decimal(str(grid)))
    if kind == "fvf":
        import importlib.util
        path = ROOT / "scripts/fvf_intent_reference.py"
        spec = importlib.util.spec_from_file_location("independent_FVF_v3", path)
        reference = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reference)
        shutil.copyfile(path, out / "private/independent_reference.py")
    else:
        from scripts.materialize_ota_tasks import sizing_and_gold, DEFINITIONS
    for point in task["configurations"]:
        point["old_nominal_parameters_for_provenance_only"] = copy.deepcopy(point["parameters"])
        if kind == "fvf":
            width, length = point["parameters"]["local_current_bias_params"]
            point["parameters"]["local_current_bias_params"] = [quantize(width, .02), quantize(length, .01)]
            gold = reference.intended_reference(point["parameters"]["local_current_bias_params"])
        else:
            width, length, fingers = point["parameters"]["half_diffpair_params"]
            width, length = quantize(width, .01), quantize(length, .01)
            point["parameters"], gold, _ = sizing_and_gold(kind, ROOT / "runs/phase0" / DEFINITIONS[kind]["plan"], width/6, length)
            if point["parameters"]["half_diffpair_params"] != [width, length, fingers]:
                raise ValueError("Prospective independent legacy dimension binding disagrees with the declared10nm grid")
        ref = out / "private/references" / (point["configuration_id"]+".spice")
        ref.write_text(gold)
        point["reference_file"] = str(ref)
        point["reference_id"] = "independent_"+kind+"_10nm_"+point["configuration_id"]
        point["contract"].update(task_id=task["task_id"], analysis_contracts=analysis_contracts(kind, kind == "legacy_miller"),
            scope="DRAFT_DEVELOPMENT_DOMAIN_QUALIFICATION_NOT_FORMAL", immutable_parameters=point["parameters"], reference_id=point["reference_id"])
        point["contract"]["bench_parameters"] = task["application_parameters"]
        point["contract"]["specifications"].append({"name": "original_development_predicate", "unit": "1", "min": 1., "max": 1.})
        validate_contract(point["contract"])
    if len({json.dumps(p["parameters"], sort_keys=True) for p in task["configurations"]}) != 25:
        raise ValueError("Nearest-grid prospective domain has fewer than25 distinct N(z); no hidden outcome filtering is permitted")
    task["parameter_grid"] = {"per_finger_width_um": .01, "length_um": .01, "FVF_total_local_width_um": .02,
        "rounding": "nearest, ties half-up, before source generation and independent gold", "development_reason": "Actual symmetric primitive geometry cannot express every5nm nominal W/L input exactly; old inputs/results remain retained."}
    task["intent_reference_version"] = "FVF_v3_source_derived_per_finger_dummies" if kind == "fvf" else "original_independent_flat_legacy_reference"
    task["bench"]["original_application"] = {**task["bench"]["original_application"], "load_F": 15e-12}
    if kind == "legacy_miller":
        task["bench"]["original_application"]["analysis_coverage"]["transient_s"] = [0, 20e-6]
    task["bench"]["no_load15_substitution"] = False
    task["bench"]["snapshot"] = str(trusted / "original_bench.py")
    task["bench"]["callable_source"] = str(trusted / "analysis_function.py")
    task["bench"]["application_provenance"] = "New prospective task version, not a modification or regrading of old10pF/.5pF tasks"
    write(out / "private/task.json", task)
    public = {k: v for k, v in task.items() if k not in ["configurations", "source_files", "frozen_dependency_modules"]}
    public["visible_configurations"] = [{k: v for k, v in point.items() if k != "reference_file"} for point in task["configurations"][:9]]
    public["hidden_configuration_count"] = 16
    write(out / "public/task.json", public)
    packet = json.loads((TASK_PREPARATION / "public" / kind / "task_packet.json").read_text())
    packet.update(task_id=task["task_id"], contract=task["configurations"][0]["contract"],
        goal="Improve the declared worst-corner UGB by one shared source edit across the fixed15pF application domain, preserving the immutable per-finger devices, connectivity and every fixed constraint.")
    defaults = task["configurations"][0]["parameters"]
    packet["documents"].update(configuration_defaults=defaults, bench=task["application_parameters"],
        natural_shortfall=task["natural_shortfall"], parameter_grid=task["parameter_grid"])
    packet["documents"]["configurations"] = [{"configuration_id": point["configuration_id"], "reference_id": point["reference_id"],
        "parameter_overrides": {k: v for k, v in point["parameters"].items() if v != defaults.get(k)}} for point in task["configurations"][:9]]
    write(out / "public/task_packet.json", packet)
    write(out / "private/state.json", {"scope": "development_OTA_domain_qualification_NOT_FORMAL_NOT_TRAINING",
        "status": "PREPARED_NO_PHYSICS", "created_at_utc": datetime.now(timezone.utc).isoformat(), "points": {},
        "source_generation_acquisition": str(ROOT / "runs/phase0" / generation_run) if generation_run else None,
        "generation_cost_policy": "Actual source->GDS generation is charged at its recorded origin. Its total CPU belongs to the entire25-point batch; per-point generation wall exists, per-point CPU is not invented.",
        "source_applications": "Old10pF/.5pF task versions and all their results remain unchanged. New15pF qualification never fills their missing labels.",
        "formal_trials": 0, "training_examples": 0})
    print(json.dumps({"prepared": str(out), "kind": kind, "points": 25, "new_physical_calls": 0}), flush=True)
    return out


def machine_sample():
    def cpu():
        values = list(map(int, Path("/proc/stat").read_text().splitlines()[0].split()[1:9]))
        return sum(values), values[3]+values[4]
    first = cpu()
    time.sleep(1)
    second = cpu()
    busy = (1-(second[1]-first[1])/(second[0]-first[0]))*os.cpu_count()
    memory = {line.split()[0].rstrip(":"): int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()}
    return busy, (memory["MemTotal"]-memory["MemAvailable"])/1024**2


class Qualification:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.task = json.loads((self.directory / "private/task.json").read_text())
        self.state = json.loads((self.directory / "private/state.json").read_text())
        if not self.task["source_generation_run"]:
            binding = json.loads((self.directory / "private/generation_binding.json").read_text())
            self.task["source_generation_run"] = binding["run_id"]
            self.state["source_generation_acquisition"] = str(ROOT / "runs/phase0" / binding["run_id"])
        self.lock = threading.Lock()
        self.executor = CandidateExecutor(ROOT / "runtime/GLdev", self.directory / "private/physical", ROOT / "runtime/magic-8.3.685", timeout=1800)

    def save(self):
        write(self.directory / "private/state.json", self.state)
        rows = list(self.state["points"].values())
        groups = {}
        for role in ["anchor", "development", "hidden"]:
            values = [row for row in rows if row["role"] == role]
            groups[role] = {"evaluated": len(values), "S1": sum(v["S1"] for v in values), "S2": sum(v["S2"] for v in values),
                "unknown": sum(not v["point_evaluation_complete"] for v in values)}
        write(self.directory / "public/summary.json", {"scope": self.state["scope"], "status": self.state["status"],
            "task_id": self.task["task_id"], "groups": groups, "physical_calls": len(rows),
            "complete25_domain": len(rows) == 25 and all(v["point_evaluation_complete"] for v in rows),
            "cost": {"stage_wall_seconds": sum(v["cost"]["stage_wall_seconds"] for v in rows),
                "waited_child_CPU_seconds": sum(v["cost"]["waited_child_CPU_seconds"] for v in rows),
                "missing_CPU_records": sum(v["cost"]["missing_CPU_records"] for v in rows)},
            "generation_cost_origin": self.state["source_generation_acquisition"],
            "hidden_details_exported": False, "formal_trials": 0, "training_examples": 0})

    def evaluate(self, point):
        ident = point["configuration_id"]
        origin = ROOT / "runs/phase0" / self.task["source_generation_run"]
        generation = json.loads((origin / "generation.json").read_text())
        if generation["task"] != self.task["task_id"]:
            raise ValueError("Generation came from a different source task")
        row = next(p for p in generation["rows"] if p["configuration_id"] == ident)
        if not row["generation_passed"]:
            raise ValueError("No actual generated GDS exists for this point")
        work = self.directory / "private/point_inputs" / ident
        (work / "source").mkdir(parents=True)
        source = work / "source"
        (source / "generator.py").write_text(COPY_SOURCE)
        shutil.copyfile(origin / (ident+".gds"), source / "input.gds")
        trusted = work / "trusted"
        shutil.copytree(self.directory / "private/trusted_common", trusted)
        shutil.copyfile(point["reference_file"], trusted / "reference.spice")
        write(trusted / "contract.json", point["contract"])
        files = sorted(str(p.relative_to(trusted)) for p in trusted.rglob("*") if p.is_file())
        configuration = {"parameters": point["parameters"]}
        result = self.executor.execute(source_dir=source, source_paths=["generator.py", "input.gds"], entrypoint="generator.py",
            representation="G0", configuration=configuration, trusted_dir=trusted, trusted_paths=files,
            fidelity="pex_spice", phase="development_OTA_domain_qualification",
            context={"source_role": "trusted_evaluator_control", "configuration_id": ident, "reference_id": point["reference_id"],
                "source_generation_origin": str(origin / (ident+".gds")), "generation_wall_seconds": row["generation_wall_seconds"],
                "initial_state_id": self.task["initial_state_id"], "parent_lineage": self.task["parent_lineage"]},
            generation_timeout_seconds=30, evaluator_timeout_seconds=5400 if self.task["cell_name"] == "ota7" else 2100)
        run = Path(result["run_directory"])
        manifest = json.loads((run / "manifest.json").read_text())
        try:
            if (run / "accepted/candidate.gds").read_bytes() != (source / "input.gds").read_bytes():
                raise ValueError("Retained baseline GDS bytes changed at handoff")
            checked = inspect_point(result, point, source_contents(source, ["generator.py", "input.gds"], binary=True), configuration, gold_control_check=False)
        except (OSError, KeyError, TypeError, ValueError) as error:
            checked = {"S0": False, "S1": False, "S2": False, "execution_integrity": "incomplete", "failure_class": "unknown",
                "reason": type(error).__name__+": "+str(error), "run_directory": str(run)}
        cost = {"stage_wall_seconds": 0., "waited_child_CPU_seconds": 0., "missing_CPU_records": 0}
        for stage in ["candidate", "trusted"]:
            if stage not in manifest:
                continue
            cost["stage_wall_seconds"] += manifest[stage]["wall_seconds"]
            usage = run / (stage+"_stage/resource_usage.json")
            if usage.is_file():
                d = json.loads(usage.read_text())
                cost["waited_child_CPU_seconds"] += d["child_user_cpu_seconds"]+d["child_system_cpu_seconds"]
            else:
                cost["missing_CPU_records"] += 1
        complete = checked["execution_integrity"] == "valid" and checked["failure_class"] in [None, "candidate"]
        record = {**checked, "configuration_id": ident, "role": point["role"], "cost": cost,
            "point_evaluation_complete": complete}
        with self.lock:
            self.state["points"][ident] = record
            if not complete:
                self.state["status"] = "PAUSED_UNKNOWN_CONTROL_NOT_AGENT_FAILURE"
            self.save()
        print(json.dumps({"point": ident, "S1": record["S1"], "S2": record["S2"], "complete": complete, "run_directory": str(run)}), flush=True)

    def run(self, mode, workers):
        if self.state["status"].startswith("PAUSED"):
            raise ValueError("Resolve the retained unknown control; do not turn it into an agent failure or retry silently")
        anchor = self.state["points"].get("anchor")
        if mode == "remaining" and (not anchor or not anchor["point_evaluation_complete"]):
            raise ValueError("Actual anchor must calibrate the shared adapter before remaining25-domain points")
        points = [p for p in self.task["configurations"] if p["configuration_id"] not in self.state["points"] and (mode != "anchor" or p["role"] == "anchor")]
        self.state["status"] = "RUNNING"
        self.save()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            active = {}
            while points or active:
                if points and len(active) < workers and not self.state["status"].startswith("PAUSED"):
                    busy, memory = machine_sample()
                    external = subprocess.run(["docker", "ps", "--format", "{{.Names}} {{.Status}}"], capture_output=True, text=True, check=True)
                    # The obsolete10pF batch may be administratively paused
                    # at a saved-GDS boundary. It consumes no CPU slot; its
                    # unstarted/censored points remain recorded separately.
                    external_gds = sum(line.split()[0].endswith("ota-task-preflight") and "(Paused)" not in line
                        for line in external.stdout.splitlines())
                    if len(active)+external_gds < 2 and busy+2 <= 24 and memory <= 190:
                        point = points.pop(0)
                        with (self.directory / "private/dispatch_events.jsonl").open("a") as log:
                            log.write(json.dumps({"utc": datetime.now(timezone.utc).isoformat(), "configuration_id": point["configuration_id"],
                                "busy_cores": busy, "used_RAM_GiB": memory, "external_OTA_GDS_workers": external_gds})+"\n")
                        active[pool.submit(self.evaluate, point)] = point
                if active:
                    done, _ = wait(active, timeout=5, return_when=FIRST_COMPLETED)
                    for future in done:
                        future.result()
                        del active[future]
                elif points and not self.state["status"].startswith("PAUSED"):
                    time.sleep(5)
                if self.state["status"].startswith("PAUSED"):
                    points = []
        if not self.state["status"].startswith("PAUSED"):
            self.state["status"] = "COMPLETE25" if len(self.state["points"]) == 25 else "ANCHOR_COMPLETE"
        self.save()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--kind", choices=["fvf", "legacy_miller"])
    p.add_argument("--generation-run")
    p.add_argument("--load-pf", type=float)
    p.add_argument("--resume", type=Path)
    p.add_argument("--mode", choices=["prepare", "anchor", "remaining"], default="prepare")
    p.add_argument("--workers", type=int, choices=[1, 2], default=1)
    a = p.parse_args()
    folder = a.resume or prepare(a.kind, a.generation_run, a.load_pf)
    if a.mode != "prepare":
        Qualification(folder).run(a.mode, a.workers)
