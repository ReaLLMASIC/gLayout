"""Prepare private 25-point domains for five independent research sources.

This creates prospective development qualification inputs, not formal tasks.
Only public/ may be exported. Hidden parameter values and references stay here.
"""
import argparse
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.measurement import audit_reference_ports, validate_contract

TARGETS = {
    "cascode_mirror": {"reference": "cascode_mirror_reference", "widths": ["width"], "lengths": ["length"],
        "family": "cascode_current_mirror", "evidence": "results/derived/cascode_mirror_independent_development.json",
        "specs": [{"name": "absolute_current_error", "unit": "1", "max": .05}, {"name": "output_resistance", "unit": "ohm", "min": 1e7}]},
    "source_follower": {"reference": "source_follower_reference", "widths": ["input_width", "bias_width"], "lengths": ["input_length", "bias_length"],
        "family": "common_drain_buffer", "evidence": "results/derived/source_follower_independent_development.json",
        "specs": [{"name": "voltage_gain", "unit": "1", "min": .7, "max": 1.05}, {"name": "output_impedance", "unit": "ohm", "max": 10000}, {"name": "power", "unit": "W", "max": 80e-6}]},
    "stacked_switch": {"reference": "stacked_switch_reference", "widths": ["n_width", "p_width"], "lengths": ["length"],
        "family": "complementary_switch", "evidence": "results/derived/stacked_switch_independent_development.json",
        "specs": [{"name": "off_leakage", "unit": "A", "max": 1e-9}, {"name": "settled_tracking_error", "unit": "V", "max": .1}, {"name": "loaded_gain", "unit": "1", "min": .5}]},
    "common_source_stage": {"reference": "common_source_reference", "widths": ["n_width", "p_width"], "lengths": ["length"],
        "family": "common_source_amplifier", "evidence": "results/derived/common_source_independent_development.json",
        "specs": [{"name": "absolute_gain", "unit": "1", "min": 8}, {"name": "power", "unit": "W", "max": 90e-6}, {"name": "bandwidth", "unit": "Hz", "min": 1e6}]},
    "resistive_diff": {"reference": "resistive_diff_reference", "widths": ["input_width", "bias_width"], "lengths": ["input_length", "bias_length"],
        "family": "resistor_loaded_differential_amplifier", "evidence": "results/derived/resistive_diff_independent_development.json",
        "specs": [{"name": "differential_gain", "unit": "1", "min": 8}, {"name": "power", "unit": "W", "max": 90e-6}, {"name": "absolute_imbalance", "unit": "V", "max": .01}, {"name": "bandwidth", "unit": "Hz", "min": 1e6}]}}


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def domain(default, target):
    # Nine visible combinations; eight interpolation combinations, four legal
    # boundary points and four explicitly narrow extrapolation points are hidden.
    visible = [(1., 1.)] + [(w, l) for w in [.97, 1., 1.03] for l in [.97, 1., 1.03] if (w, l) != (1., 1.)]
    interpolation = [(w, l) for w in [.985, 1., 1.015] for l in [.985, 1., 1.015] if (w, l) != (1., 1.)]
    boundary = [(.955, 1.), (1.045, 1.), (1., .955), (1., 1.045)]
    extrapolation = [(.94, .94), (.94, 1.06), (1.06, .94), (1.06, 1.06)]
    rows = []
    for index, (w, l) in enumerate(visible + interpolation + boundary + extrapolation):
        sizing = dict(default)
        for key in target["widths"]:
            sizing[key] = round(round(default[key] * w / .005) * .005, 3)
        for key in target["lengths"]:
            sizing[key] = round(round(default[key] * l / .005) * .005, 3)
        role = "anchor" if index == 0 else "development" if index < 9 else "hidden"
        subtype = "anchor" if index == 0 else "visible_combination" if index < 9 else "interpolation" if index < 17 else "legal_boundary" if index < 21 else "extrapolation"
        rows.append({"configuration_id": "anchor" if index == 0 else ("dev_%02d" % index if index < 9 else "hidden_%02d" % (index - 8)),
                     "role": role, "domain_subtype": subtype, "parameters": sizing})
    if len({json.dumps(row["parameters"], sort_keys=True) for row in rows}) != 25:
        raise ValueError("Every point must be a distinct sizing, not a repeated configuration")
    return rows


def materialize(names):
    if not (ROOT / "runtime/GLdev").is_dir():
        raise ValueError("Private domains must be created on the execution host")
    output = ROOT / "runtime/task_preparation" / ("independent_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    output.mkdir(mode=0o700)
    (output / "private").mkdir(mode=0o700)
    (output / "public").mkdir()
    for name in names:
        target = TARGETS[name]
        ref = importlib.import_module("src.generators." + target["reference"])
        folder = output / "private" / name
        folder.mkdir()
        pack = folder / "source_pack"
        pack.mkdir()
        common = pack / "glayout"
        common.mkdir()
        vendor = ROOT / "vendor/glayout/src/glayout"
        for part in ["pdk", "placement", "primitives", "routing", "spice", "util", "provenance"]:
            shutil.copytree(vendor / part, common / part, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copyfile(vendor / "__init__.py", common / "__init__.py")
        generator_dir = pack / "src/generators"
        generator_dir.mkdir(parents=True)
        (pack / "src/__init__.py").write_text("")
        (generator_dir / "__init__.py").write_text("")
        editable = "src/generators/" + name + ".py"
        shutil.copyfile(ROOT / editable, pack / editable)
        # Generation receives constants only; the independent graph stays on the trusted side.
        (generator_dir / (target["reference"] + ".py")).write_text("DEFAULT=" + repr(ref.DEFAULT) + "\n")
        if "src.generators.terminal_access" in (pack / editable).read_text():
            shutil.copyfile(ROOT / "src/generators/terminal_access.py", generator_dir / "terminal_access.py")
        (pack / "generator.py").write_text('''import argparse,json,shutil
from pathlib import Path
from src.generators.NAME import build
p=argparse.ArgumentParser();p.add_argument("--configuration");p.add_argument("--output");a=p.parse_args()
output=Path(a.output)
generated=build(output.parent/"generated",json.loads(Path(a.configuration).read_text()))
shutil.copyfile(generated,output)
'''.replace("NAME", name))
        references = folder / "references"
        references.mkdir()
        rows = domain(ref.DEFAULT, target)
        objective = {"id": name + "_area_min", "metric": "area", "unit": "um2", "direction": "min", "corner_aggregation": "worst"}
        for row in rows:
            ident = row["configuration_id"]
            text = ref.schematic(row["parameters"])
            if audit_reference_ports(text, name, ref.PORTS)["status"] != "PASS":
                raise ValueError("Independent reference has an unused declared port")
            reference = references / (ident + ".spice")
            reference.write_text(text)
            row["reference_file"] = str(reference)
            row["reference_id"] = "independent_" + name + "_" + ident
            row["contract"] = {"task_id": "draft_" + name + "_area", "configuration_id": ident,
                "reference_id": row["reference_id"], "required_corners": ["tt", "ss", "ff"],
                "specifications": target["specs"], "objective": objective,
                "scope": "DRAFT_QUALIFICATION_NOT_FORMAL"}
            validate_contract(row["contract"])
        task = {"status": "DRAFT_INDEPENDENT_SOURCE_DOMAIN", "task_id": "draft_" + name + "_area",
            "parent_lineage": "research_" + name, "topology_family": target["family"],
            "source_pack": str(pack), "editable_paths": [editable], "entrypoint": "generator.py",
            "source_files": sorted(str(p.relative_to(pack)) for p in pack.rglob("*") if p.is_file()),
            "representation": "G2", "configurations": rows, "ports": ref.PORTS,
            "scope": "Sizing changes only through immutable configuration; source edits preserve all intent and device multiplicities.",
            "domain_note": "Width/length scale combinations snapped to the .005um PDK grid before reference generation; visible scale .97..1.03, declared legal .955..1.045 boundary and narrow .94..1.06 extrapolation. Exact snapped device values remain immutable per point.",
            "default_qualification": target["evidence"], "formal_admission": False, "formal_trials": 0,
            "training_examples": 0, "full25_baseline": None, "feasible_edit_witness": None}
        save(folder / "task.json", task)
        view = {k: v for k, v in task.items() if k not in ["configurations", "source_files"]}
        view.update(visible_configurations=rows[:9], hidden_configuration_count=16,
                    source_snapshot={editable: (pack / editable).read_text()})
        save(output / "public" / (name + ".json"), view)
    save(output / "summary.json", {"status": "DRAFT", "targets": names, "points_per_target": 25,
        "private_details_exportable": False, "formal_trials": 0, "training_examples": 0})
    return {"preparation": str(output), "targets": names, "status": "DRAFT_NOT_GENERATED_OR_PHYSICALLY_QUALIFIED"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", nargs="+", choices=list(TARGETS), default=list(TARGETS))
    print(json.dumps(materialize(parser.parse_args().targets)))
