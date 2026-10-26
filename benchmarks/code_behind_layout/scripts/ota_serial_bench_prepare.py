"""Bind a prospective serial-corner OTA bench after bounded real calibration.

Only ThreadPoolExecutor's corner worker count changes. Measurement functions,
stimuli, numerical options, analysis limits, references and old snapshots do not.
"""
import argparse
import ast
from datetime import datetime, timezone
import difflib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prepare(kind, calibration, output):
    calibration, output = Path(calibration).resolve(), Path(output).resolve()
    result = json.loads(calibration.read_text())
    if result["conclusion"] != "ORIGINAL_SERIAL_DECKS_COMPLETE_SCHEDULING_BUDGET_CALIBRATION":
        raise ValueError("This transport is only justified by complete original serial decks")
    if not result["results"]["original"]["ff"]["saved_FF_equivalence_passed"]:
        raise ValueError("Saved complete FF waveform failed the predeclared tolerance")
    original_task = ROOT / "runtime/task_preparation/otas_20261019T022816023029Z/private" / kind / "task.json"
    task = json.loads(original_task.read_text())
    original = (original_task.parent / "trusted_bench/original_retained_bench.py").read_text()
    tree = ast.parse(original)
    worker_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "ThreadPoolExecutor"]
    if len(worker_calls) != 1:
        raise ValueError("Expected one original corner scheduler")
    call = worker_calls[0]
    worker = next(kw.value for kw in call.keywords if kw.arg == "max_workers")
    if not isinstance(worker, ast.Constant) or not isinstance(worker.value, int) or worker.value < 1:
        raise ValueError("Original scheduler is not a literal bounded worker count")
    lines = original.splitlines(True)
    if worker.lineno != worker.end_lineno:
        raise ValueError("Unexpected multiline worker count")
    line = lines[worker.lineno-1]
    lines[worker.lineno-1] = line[:worker.col_offset]+"1"+line[worker.end_col_offset:]
    serial = "".join(lines)
    function = "simulate" if kind == "five_t" else "measure"
    def body(text):
        node = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == function)
        return ast.get_source_segment(text, node)
    if body(original) != body(serial):
        raise ValueError("The actual electrical measurement function changed")
    output.mkdir(parents=True, exist_ok=False)
    bench = output / "trusted_bench"
    bench.mkdir()
    (bench / "original_retained_bench.py").write_text(serial)
    (bench / "original_parallel_bench.py").write_text(original)
    (bench / "corner_schedule.patch").write_text("".join(difflib.unified_diff(original.splitlines(True), serial.splitlines(True),
        fromfile="retained_original_parallel_bench", tofile="prospective_serial_corner_bench")))
    binding = {"scope": "prospective_DRAFT_serial_corner_scheduling_NOT_OLD_RESULT_REGRADING", "kind": kind,
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "calibration": str(calibration),
        "calibration_run_id": result["actual_execution_run_id"], "source_template": str(output / "task.json"),
        "bench_snapshot": str(bench / "original_retained_bench.py"), "original_task": str(original_task),
        "old_corner_workers": worker.value, "new_corner_workers": 1, "measurement_function_source_identical": True,
        "analysis_timeouts_stimuli_solver_physical_RC_reference_specs_unchanged": True,
        "complete_FF_max_difference_V": result["results"]["original"]["ff"]["max_output_difference_from_saved_FF_V"],
        "actual_new_full_scheduled_bench_control_required_before_freeze": True}
    task["prospective_execution_schedule"] = binding
    task["bench"]["snapshot"] = binding["bench_snapshot"]
    (output / "task.json").write_text(json.dumps(task, indent=2)+"\n")
    (output / "binding.json").write_text(json.dumps(binding, indent=2)+"\n")
    print(json.dumps(binding), flush=True)
    return binding


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--kind", choices=["five_t", "compact_miller"], required=True)
    p.add_argument("--calibration", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    prepare(a.kind, a.calibration, a.output)
