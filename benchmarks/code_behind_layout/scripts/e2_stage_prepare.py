"""Build explicitly scoped E2 geometry/PEX/full trusted capsules."""
import argparse
import ast
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def cached(output, *, point, full_trusted, physical_run, nominal=False):
    """Build an electrical capsule tied to one actual admitted GDS/PEX pair."""
    output, physical_run = Path(output), Path(physical_run)
    evidence = physical_run / "evidence"
    prior = json.loads((evidence / "validation.json").read_text())
    if not prior["assessment"]["S1"] or not prior["requested_fidelity_complete"]:
        raise ValueError("Only an actually completed physical/PEX acquisition can be reused")
    paths = build("pex_spice", output, top="unused", point=point, full_trusted=full_trusted)
    shutil.copyfile(output / "evaluate.py", output / "original_full_evaluator.py")
    shutil.copyfile(ROOT / "scripts/e2_cached_evaluator.py", output / "evaluate.py")
    shutil.copyfile(ROOT / "scripts/e2_spice_process_profile.py", output / "e2_spice_process_profile.py")
    if nominal:
        text = (output / "evaluate.py").read_text()
        boundary = "measure = ota_frozen_bench.run_vendor_post_rc"
        if text.count(boundary) != 1:
            raise ValueError("The trusted E2 cached physical/electrical boundary changed")
        prefix = text[:text.index(boundary)]
        tail = "\n".join([
            "from e2_nominal_bench import run_nominal",
            "nominal=run_nominal(out,pex,cell,inventory['ports'],configuration['parameters'],contract,kind=meta['circuit'],bench_snapshot=trusted/'original_bench.py',reference_path=trusted/'reference.spice')",
            "record={'scope':'E2_actual_nominal_only_on_admitted_PEX','requested_fidelity':'nominal_op_ac','requested_fidelity_complete':nominal['complete'],'nominal':nominal,'S1':True,'S2':False,'point_evaluation_complete':False,'physical_tool_calls':{'DRC':0,'LVS':0,'PEX':0,'SPICE':1},'physical_acquisition':meta['physical_acquisition'],'calibrated_UGB_prediction':None}",
            "(out/'validation.json').write_text(json.dumps(record,indent=2,allow_nan=False)+'\\n')",
            "print(json.dumps(record),flush=True)",
            "raise SystemExit(0 if nominal['complete'] else 2)", ""])
        (output / "evaluate.py").write_text(prefix+tail)
        shutil.copyfile(ROOT / "scripts/e2_nominal_bench.py", output / "e2_nominal_bench.py")
    cache = output / "cached"
    cache.mkdir()
    for name in ["validation.json", "extracted_lvs.spice"]:
        shutil.copyfile(evidence / name, cache / name)
    for relative in [prior["artifacts"]["drc"]["report"], prior["artifacts"]["drc"]["metadata"], prior["artifacts"]["lvs"]["report"]]:
        destination = cache / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(evidence / relative, destination)
    shutil.copyfile(physical_run / "accepted/candidate.gds", cache / "candidate.gds")
    shutil.copyfile(evidence / prior["artifacts"]["pex"]["netlist"], cache / "physical_rc.spice")
    meta = json.loads((output / "meta.json").read_text())
    meta["physical_acquisition"] = str(physical_run)
    meta["physical_cost_policy"] = "Charge the real acquisition at its origin; this run performs no repeated DRC/LVS/PEX"
    (output / "meta.json").write_text(json.dumps(meta, indent=2)+"\n")
    return sorted(str(p.relative_to(output)) for p in output.rglob("*") if p.is_file())


def build(stage, output, *, top, point=None, full_trusted=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    if stage == "geometry":
        layer = json.loads((ROOT / "results/derived/e2_development_mask_layer_binding.json").read_text())
        exclusions = layer["pin_and_label_layer_datatypes"]+layer["additional_nonmanufacturing_annotation"]
        shutil.copy2(ROOT / "scripts/e2_geometry_evaluator.py", output / "evaluate.py")
        shutil.copy2(ROOT / "src/e2_mask_geometry.py", output / "e2_mask_geometry.py")
        (output / "meta.json").write_text(json.dumps({"top_cell": top, "excluded_layer_datatypes": exclusions}, indent=2)+"\n")
    elif stage in ["pex", "pex_spice"]:
        if full_trusted is None or point is None:
            raise ValueError("The physical stages require frozen independent reference and full trusted template")
        for path in Path(full_trusted).rglob("*"):
            if path.is_file():
                destination = output / path.relative_to(full_trusted)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        shutil.copyfile(point["reference_file"], output / "reference.spice")
        (output / "contract.json").write_text(json.dumps(point["contract"], indent=2)+"\n")
        if stage == "pex":
            original = (output / "evaluate.py").read_text()
            tree = ast.parse(original)
            boundary = next(n for n in tree.body if isinstance(n, ast.If) and "meta['bench_kind']" in ast.unparse(n.test))
            prefix = "".join(original.splitlines(True)[:boundary.lineno-1])
            # The complete physical core is retained. Omit every benchmark
            # branch before execution, so PEX cannot run an electrical analysis.
            save_node = next(n for n in ast.parse(prefix).body if isinstance(n, ast.FunctionDef) and n.name == "save")
            lines = prefix.splitlines(True)
            wrapper = "\n".join([
                "_physical_save=save",
                "def save():",
                "    result=_physical_save()",
                "    requested_complete=bool(rejected or globals().get('real',False))",
                "    result.update(scope='E2_PEX_only_no_SPICE',requested_fidelity='pex',requested_fidelity_complete=requested_complete,analysis_complete=False)",
                "    result['point_evaluation_complete']=bool(rejected)",
                "    result['execution_integrity']='valid' if requested_complete else 'incomplete'",
                "    result['failure_class']='candidate' if rejected else None if requested_complete else 'unknown'",
                "    result['physical_tool_calls']={'DRC':int((out/'drc').exists()),'LVS':int((out/'netgen.log').exists()),'PEX':int((out/'rc_extract.tcl').exists()),'SPICE':0}",
                "    (out/'validation.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\\n')",
                "    return result", ""])
            prefix = "".join(lines[:save_node.end_lineno])+"\n"+wrapper+"\n"+"".join(lines[save_node.end_lineno:])
            adapted = prefix+"\nprint(json.dumps(save()),flush=True)\nraise SystemExit(0)\n"
            ast.parse(adapted)
            (output / "original_full_evaluator.py").write_text(original)
            (output / "evaluate.py").write_text(adapted)
            for name in ["original_bench.py", "analysis_function.py", "ota_frozen_bench.py", "bench.py"]:
                (output / name).unlink(missing_ok=True)
    else:
        raise ValueError("Unknown E2 stage")
    return sorted(str(p.relative_to(output)) for p in output.rglob("*") if p.is_file())


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stage", choices=["geometry", "pex", "pex_spice"], required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--top", required=True)
    p.add_argument("--point", type=Path)
    p.add_argument("--full-trusted", type=Path)
    a = p.parse_args()
    point = json.loads(a.point.read_text()) if a.point else None
    print(json.dumps({"trusted_paths": build(a.stage, a.output, top=a.top, point=point, full_trusted=a.full_trusted)}))
