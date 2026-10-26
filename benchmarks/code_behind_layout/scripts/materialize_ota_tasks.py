"""Prepare four private OTA natural-state domains; no generation or physics.

Only public/ may be exported. The two naturally low-PM vendor applications
remain .5pF/10pF. This does not reuse the prospective E2 15pF applications.
"""
import argparse
import ast
import difflib
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
import textwrap
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.measurement import audit_reference_ports, validate_contract

DEFINITIONS = {
    "five_t": {"plan": "phase0_20261019T011122226634Z_e2_development_pilot", "top": "five_t_ota",
        "module": "src.generators.five_t", "function": "build", "bench": "custom_ota_schematic.py", "bench_function": "simulate",
        "family": "single_stage_mirror_load_OTA", "lineage": "research_five_t", "objective": "area",
        "description": "Unmodified research5T source; complete default is feasible. Minimize actual GDS area while preserving every electrical constraint; an improvement witness is pending."},
    "compact_miller": {"plan": "phase0_20261019T012051320824Z_e2_development_pilot", "top": "compact_miller_ota",
        "module": "src.generators.compact_miller", "function": "build", "bench": "custom_ota_miller_schematic.py", "bench_function": "measure",
        "family": "conventional_two_stage_Miller_OTA", "lineage": "research_compact_miller", "objective": "area",
        "description": "Unmodified research compactMiller source with per-configuration cap30 at anchor. Default2pF application is feasible. Minimize area while preserving performance; improvement witness pending."},
    "fvf": {"plan": "phase0_20261019T012053961469Z_e2_development_pilot", "top": "fvf7",
        "module": "glayout.cells.composite.fvf_based_ota.ota", "function": "super_class_AB_OTA", "bench": "fvf_validate.py",
        "family": "FVF_local_feedback_class_AB_OTA", "lineage": "glayout_fvf_ota", "objective": "ugb",
        "description": "Current repaired FVF source at original10pF has SS PM58.59deg against fixed60deg. This is a natural performance shortfall; source-only repairability is unestablished. The separate15pF control never changes this initial state."},
    "legacy_miller": {"plan": "phase0_20261019T012056202713Z_e2_development_pilot", "top": "ota7",
        "module": "glayout.cells.composite.opamp.opamp_twostage", "function": "opamp_twostage", "face": "__add_mimcap_arr", "bench": "ota_postlayout.py",
        "family": "vendor_two_stage_Miller_OTA", "lineage": "glayout_twostage_ota", "objective": "ugb",
        "description": "Current repaired Miller source at original.5pF has post-RC PM26..29deg against fixed60deg. This is a natural performance shortfall. No intrinsic-versus-layout repairability claim is made; the separate15pF load hypothesis does not change this task."},
}


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+"\n")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def full_function(source, node):
    start = min([node.lineno]+[d.lineno for d in node.decorator_list])
    return "".join(source.splitlines(keepends=True)[start-1:node.end_lineno])+"\n", start


def vendor_closure(pack, target):
    vendor = ROOT / "vendor/glayout/src/glayout"
    common = pack / "glayout"
    common.mkdir()
    for part in ["pdk", "placement", "primitives", "routing", "spice", "util", "provenance"]:
        shutil.copytree(vendor / part, common / part, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copyfile(vendor / "__init__.py", common / "__init__.py")
    pending, seen, retained = [target], set(), set()
    while pending:
        name = pending.pop()
        if name in seen or not name.startswith("glayout."):
            continue
        seen.add(name)
        module_path = Path(*name.split(".")[1:])
        is_package = (vendor / module_path / "__init__.py").is_file()
        relative = module_path / "__init__.py" if is_package else module_path.with_suffix(".py")
        original = vendor / relative
        if not original.is_file():
            continue
        retained.add(name)
        destination = common / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        for parent in destination.parents:
            if parent == common:
                break
            (parent / "__init__.py").touch()
        # A parent's namespace placeholder may already exist. A real package
        # initializer supplies exports/relative imports and must replace it.
        if is_package or not destination.exists():
            shutil.copyfile(original, destination)
        tree = ast.parse(original.read_text())
        package = name if is_package else name.rsplit(".", 1)[0]
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                base = importlib.util.resolve_name("."*node.level+(node.module or ""), package) if node.level else (node.module or "")
                if base.startswith("glayout."):
                    pending.append(base)
                    pending.extend(base+"."+alias.name for alias in node.names if alias.name != "*")
            elif isinstance(node, ast.Import):
                pending.extend(alias.name for alias in node.names if alias.name.startswith("glayout."))
    return sorted(retained)


def domain_scales():
    visible = [(1., 1.)]+[(w, l) for w in [.97, 1., 1.03] for l in [.97, 1., 1.03] if (w, l) != (1., 1.)]
    # Exact hidden values and assignments are produced only on the execution
    # host and are never included in public/context packets.
    inner = [(w, l) for w in [.985, 1., 1.015] for l in [.985, 1., 1.015] if (w, l) != (1., 1.)]
    boundary = [(.955, 1.), (1.045, 1.), (1., .955), (1., 1.045)]
    outer = [(.94, .94), (.94, 1.06), (1.06, .94), (1.06, 1.06)]
    return visible+inner+boundary+outer


def flat_legacy_reference(text):
    """Expand only this literal intended hierarchy, without reading a layout."""
    blocks, current = {}, None
    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0].startswith("*"):
            continue
        if fields[0].lower() == ".subckt":
            pins = [token for token in fields[2:] if "=" not in token]
            current = fields[1]
            blocks[current.casefold()] = (pins, [])
        elif fields[0].lower() == ".ends":
            current = None
        elif current:
            blocks[current.casefold()][1].append(fields)
    ports, _ = blocks["ota7"]
    rows = ["* Independent literal legacy intent flattened before any extraction", ".subckt ota7 "+" ".join(ports)]
    def expand(name, bindings, prefix):
        _, body = blocks[name.casefold()]
        def net(value):
            return bindings.get(value.casefold(), "0" if value == "0" else prefix+"_"+value)
        for fields in body:
            if len(fields) >= 6 and fields[5].startswith("sky130_fd_pr__"):
                count = 4
            elif len(fields) >= 4 and fields[3] == "sky130_fd_pr__cap_mim_m3_1":
                count = 2
            else:
                model_index = next(i for i, value in enumerate(fields[1:], 1) if value.casefold() in blocks)
                pins, _ = blocks[fields[model_index].casefold()]
                if model_index != len(pins)+1:
                    raise ValueError("Literal hierarchy has an unexpected pin binding")
                expand(fields[model_index], {p.casefold(): net(n) for p, n in zip(pins, fields[1:model_index])}, prefix+"_"+fields[0])
                continue
            params = [field.replace("{1}", "1") for field in fields[count+2:]]
            if any("{" in p or "}" in p for p in params):
                raise ValueError("Only literal intended primitive parameters are supported")
            rows.append("X"+prefix+"_"+fields[0]+" "+" ".join(net(n) for n in fields[1:count+1])+" "+fields[count+1]+" "+" ".join(params))
    expand("ota7", {p.casefold(): p for p in ports}, "root")
    return "\n".join(rows+[".ends ota7", ""])


def sizing_and_gold(kind, plan, width_scale, length_scale):
    snap = lambda value, grid=.005: round(round(value/grid)*grid, 3)
    if kind in ["five_t", "compact_miller"]:
        reference = load("ota_task_reference_"+kind, ROOT / "src/generators" / (kind+"_reference.py"))
        sizes = dict(reference.DEFAULT)
        if kind == "compact_miller":
            sizes["cap_size"] = 30.
        sizes["input_width"] = snap(sizes["input_width"]*width_scale)
        sizes["input_length"] = snap(sizes["input_length"]*length_scale)
        return sizes, reference.schematic(sizes), reference.PORTS
    original = (plan / "gold.spice").read_text()
    ports = json.loads((plan / "pool_plan.json").read_text())["fixed_ports"]
    if kind == "fvf":
        width, length = snap(3.76*width_scale, .01), snap(3*length_scale)
        def replace_device(match):
            line = match[0]
            actual_width = width if "dummy" in line.split()[0] else width/2
            line = re.sub(r"\bw=\S+", f"w={actual_width:g}", line)
            return re.sub(r"\bl=\S+", f"l={length:g}", line)
        gold, count = re.subn(r"^Xlocal_p(?:diode|out|dummy)[12]\b.*$", replace_device, original, flags=re.M)
        if count != 6:
            raise ValueError("Independent local PMOS mirror reference binding changed")
        return {"local_current_bias_params": [width, length]}, gold, ports
    width, length = snap(6*width_scale), snap(length_scale)
    def replace_block(match):
        text = re.sub(r"(\bw=)6(?:\.0)?(?=\s|$)", lambda m: m[1]+f"{width:g}", match[0])
        return re.sub(r"(\bl=)1(?:\.0)?(?=\s|$)", lambda m: m[1]+f"{length:g}", text)
    gold, first = re.subn(r"^\.subckt NMOS .*?^\.ends NMOS$", replace_block, original, count=1, flags=re.M|re.S)
    gold, second = re.subn(r"^\.subckt DIFF_PAIR .*?^\.ends DIFF_PAIR$", replace_block, gold, count=1, flags=re.M|re.S)
    if first != 1 or second != 1:
        raise ValueError("Independent legacy input reference blocks changed")
    return {"half_diffpair_params": [width, length, 4], "mim_cap_size": [30, 30], "rmult": 2}, flat_legacy_reference(gold), ports


BUILD = '''import importlib,json,sys
from pathlib import Path
import gdstk
from glayout import sky130
KIND={kind!r}
MODULE={module!r}
FACE={face!r}
TOP={top!r}
def build(parameters, output):
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    if KIND in ['five_t','compact_miller']:
        fn=importlib.import_module(MODULE).build
        generated=fn(output.parent/(output.stem+'_generated'),parameters)
        output.write_bytes(Path(generated).read_bytes());return output
    module=importlib.import_module(MODULE)
    # This executes a complete original assembly/helper function in precisely
    # its original module namespace. It is part of the untrusted source->GDS
    # process, never imported by the trusted GDS evaluator.
    face=Path(__file__).parent/FACE
    exec(compile(face.read_text(),str(face),'exec'),module.__dict__)
    kwargs={{k:tuple(v) if isinstance(v,list) else v for k,v in parameters.items()}}
    component=getattr(module,{function!r})(sky130,**kwargs).copy()
    component.write_gds(output)
    lib=gdstk.read_gds(output);top,=lib.top_level();top.flatten();top.name=TOP
{markers}
    lib=gdstk.Library();lib.add(top);lib.write_gds(output);return output
'''

LEGACY_MARKERS = '''    top.remove(*top.labels)
    annotation={(64,44)}|{value for key,value in sky130.glayers.items() if key.endswith(('_label','_pin')) and isinstance(value,tuple)}
    top.remove(*(p for p in top.polygons if (p.layer,p.datatype) in annotation))
    pins={'VDD':'pin_vdd_e4','GND':'pin_gnd_N','DIFFPAIR_BIAS':'diffpair_ibias_A_drain_E','VP':'pin_plus_e3','VN':'pin_minus_e3','CS_BIAS':'pin_commonsourceibias_e2','VOUT':'commonsource_output_E'}
    for label,key in pins.items():
        port=component.ports[key];glayer=sky130.layer_to_glayer(port.layer)
        x,y=map(float,port.center);half=.15 if label=='GND' else .1
        if label=='GND':y-=.15
        layer,datatype=sky130.get_glayer(glayer+'_pin')
        top.add(gdstk.rectangle((x-half,y-half),(x+half,y+half),layer=layer,datatype=datatype))
        layer,datatype=sky130.get_glayer(glayer+'_label')
        top.add(gdstk.Label(label,(x,y),layer=layer,texttype=datatype))'''


def prepare():
    if not (ROOT / "runtime/GLdev").is_dir():
        raise ValueError("Private task tables may only be materialized on the execution host")
    began = time.monotonic()
    out = ROOT / "runtime/task_preparation" / ("otas_"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    (out / "private").mkdir(parents=True, mode=0o700)
    (out / "public").mkdir()
    base_packet = json.loads((ROOT / "runtime/task_preparation/components_20261019T012723731624Z/public/mirror/task_packet.json").read_text())
    index = []
    for kind, definition in DEFINITIONS.items():
        plan = ROOT / "runs/phase0" / definition["plan"]
        legacy = json.loads((plan / "pool_plan.json").read_text())
        directory = out / "private" / kind
        pack = directory / "source_pack"
        pack.mkdir(parents=True)
        closure = vendor_closure(pack, definition["module"] if kind not in ["five_t", "compact_miller"] else "glayout")
        if kind in ["five_t", "compact_miller"]:
            editable = "src/generators/"+kind+".py"
            folder = pack / "src/generators"
            folder.mkdir(parents=True)
            (pack / "src/__init__.py").write_text("")
            (folder / "__init__.py").write_text("")
            shutil.copyfile(ROOT / editable, pack / editable)
            reference = load("ota_task_constants_"+kind, ROOT / "src/generators" / (kind+"_reference.py"))
            constants = {**reference.DEFAULT, **({"cap_size": 30.} if kind == "compact_miller" else {})}
            (folder / (kind+"_reference.py")).write_text("DEFAULT="+repr(constants)+"\nPORTS="+repr(reference.PORTS)+"\n")
            window = {"scope": "complete unchanged current module", "origin": str(ROOT / editable), "algorithm_preserved_verbatim": True}
        else:
            original = ROOT / "vendor/glayout/src" / Path(*definition["module"].split(".")).with_suffix(".py")
            source = original.read_text()
            face_name = definition.get("face", definition["function"])
            tree = ast.parse(source)
            node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == face_name)
            function, first = full_function(source, node)
            verbatim = True
            if kind == "fvf":
                # A complete local-bias assembly is hoisted from the original
                # constructor. Its placement/routing statements stay verbatim;
                # the rest of the OTA is a frozen own-circuit API.
                block = node.body[6:25]
                if (not isinstance(block[0], ast.Assign) or ast.unparse(block[0].targets[0]) != "local_c_bias"
                        or not ast.unparse(block[-1]).startswith("top_level.add_ports(local_c_bias_2_ref")):
                    raise ValueError("FVF local-bias semantic window changed")
                assigned = {n.id for statement in block for n in ast.walk(statement)
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
                read_later = {n.id for statement in node.body[25:] for n in ast.walk(statement)
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
                if assigned & read_later != {"local_c_bias_1_ref", "local_c_bias_2_ref"}:
                    raise ValueError("FVF helper output dataflow changed")
                first, last = block[0].lineno, block[-1].end_lineno
                lines = source.splitlines(keepends=True)
                body = "".join(lines[first-1:last])
                face_name = "place_and_route_local_bias"
                function = "def "+face_name+"(pdk, top_level, n_block_ref, local_current_bias_params):\n"+body+"    return local_c_bias_1_ref, local_c_bias_2_ref\n"
                replacement = ast.parse(function).body[0]
                if [ast.dump(s) for s in replacement.body[:-1]] != [ast.dump(s) for s in block]:
                    raise ValueError("FVF semantic extraction changed original statements")
                refactored = "".join(lines[:first-1])+"    local_c_bias_1_ref, local_c_bias_2_ref = place_and_route_local_bias(pdk, top_level, n_block_ref, local_current_bias_params)\n"+"".join(lines[last:])
                frozen_module = pack / Path(*definition["module"].split(".")).with_suffix(".py")
                frozen_module.write_text(refactored)
                ast.parse(refactored)
            imports = "\n".join(ast.get_source_segment(source, n) for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)))
            editable = kind+"_layout_face.py"
            (pack / editable).write_text(imports+"\n\n"+function)
            ast.parse((pack / editable).read_text())
            window = {"scope": "complete original semantic function plus complete import declarations", "function": face_name,
                "origin": str(original), "original_line_window": [first, last if kind == "fvf" else node.end_lineno],
                "algorithm_preserved_verbatim": verbatim and function in source,
                "algorithm_AST_preserved": True,
                "presentation": "verbatim local-bias block hoisted to complete helper; constructor calls it in the same statement position; original whole module retained privately" if kind == "fvf" else "unchanged original function",
                "binding": "frozen launcher executes complete face into original module namespace; original helpers/decorators/import namespace are frozen APIs",
                "not_parameter_wrapper": "Editable body contains actual placement/routing/assembly control flow and geometry operations; immutable sizing remains an independent input."}
            if kind == "fvf":
                window["scope"] = "complete semantically extracted local-bias placement/routing helper plus complete imports"
                shutil.copyfile(original, directory / "original_current_ota.py")
        (pack / "component_build.py").write_text(BUILD.format(kind=kind, module=definition["module"], face=editable,
            top=definition["top"], function=definition["function"], markers=LEGACY_MARKERS if kind == "legacy_miller" else ""))
        (pack / "generator.py").write_text('import argparse,json\nfrom pathlib import Path\nfrom component_build import build\np=argparse.ArgumentParser();p.add_argument("--configuration");p.add_argument("--output");a=p.parse_args()\nbuild(json.loads(Path(a.configuration).read_text()),Path(a.output))\n')
        trusted = directory / "trusted_bench"
        trusted.mkdir()
        bench_source = (plan / "testbench_snapshot.py").read_text()
        (trusted / "original_retained_bench.py").write_text(bench_source)
        bench_tree = ast.parse(bench_source)
        if "bench_function" in definition:
            node = next(n for n in bench_tree.body if isinstance(n, ast.FunctionDef) and n.name == definition["bench_function"])
            bench_body = ast.get_source_segment(bench_source, node)
            body_kind = "exact AST function source segment"
        else:
            node = next(n for n in bench_tree.body if isinstance(n, ast.For) and isinstance(n.target, (ast.Name, ast.Tuple)))
            bench_body = "def run_exact_analysis_loop():\n"+textwrap.indent(ast.get_source_segment(bench_source, node), "    ")+"\n"
            body_kind = "complete original analysis loop wrapped as a function by indentation only"
        (trusted / "analysis_function.py").write_text(bench_body+"\n")
        ast.parse(bench_body)
        (directory / "references").mkdir()
        objective = {"id": kind+"_"+("area_min" if definition["objective"] == "area" else "ugb_max"),
            "metric": definition["objective"], "unit": "um2" if definition["objective"] == "area" else "Hz",
            "direction": "min" if definition["objective"] == "area" else "max", "corner_aggregation": "worst"}
        feasibility = legacy["contract"]["existing_development_feasibility"]
        constraints = [{"name": "gain", "unit": "dB", "min": feasibility["gain_10Hz_dB_min"]},
            {"name": "phase_margin", "unit": "deg", "min": 60., "max": 180.},
            {"name": "ugb", "unit": "Hz", "min": 1e6},
            {"name": "nominal_tracking_error", "unit": "V", "max": feasibility["nominal_tracking_abs_V_lt"]},
            {"name": "settled_tracking_error", "unit": "V", "max": .005 if kind == "compact_miller" else .01}]
        if "power_W_max" in feasibility:
            constraints.append({"name": "power", "unit": "W", "max": feasibility["power_W_max"]})
        points = []
        for i, scales in enumerate(domain_scales()):
            ident = "anchor" if i == 0 else "dev_%02d" % i if i < 9 else "hidden_%02d" % (i-8)
            parameters, gold, ports = sizing_and_gold(kind, plan, *scales)
            if audit_reference_ports(gold, definition["top"], ports)["status"] != "PASS":
                raise ValueError("Independent sizing gold has an unused declared port")
            ref = directory / "references" / (ident+".spice")
            ref.write_text(gold)
            contract = {"task_id": "draft_"+kind+"_natural_source", "configuration_id": ident,
                "reference_id": "independent_"+kind+"_"+ident, "required_corners": ["tt", "ss", "ff"],
                "specifications": constraints, "objective": objective, "scope": "DRAFT_NOT_FROZEN_NOT_MEASURED",
                "immutable_parameters": parameters, "strict_development_predicate": feasibility,
                "numeric_options": legacy["contract"]["numerics"]}
            validate_contract(contract)
            points.append({"configuration_id": ident, "role": "anchor" if i == 0 else "development" if i < 9 else "hidden",
                "parameters": parameters, "reference_id": contract["reference_id"], "reference_file": str(ref), "contract": contract})
        if len({json.dumps(p["parameters"], sort_keys=True) for p in points}) != 25:
            raise ValueError("Expected25 distinct intended circuits")
        bench = {"original_application": legacy["contract"], "body_reuse": body_kind,
            "snapshot": str(trusted / "original_retained_bench.py"), "callable_source": str(trusted / "analysis_function.py"),
            "SPICE_stimuli_numeric_formulas_and_completion_source_unchanged": True,
            "transport": legacy.get("bench_transport", {"adapted": False}), "no_load15_substitution": True}
        task = {"status": "DRAFT_REAL_OTA_NATURAL_INITIAL_STATE", "task_id": points[0]["contract"]["task_id"],
            "initial_state_id": kind+"__natural_current_source", "parent_lineage": definition["lineage"], "origin": "natural",
            "topology_family": definition["family"], "source_pack": str(pack), "editable_paths": [editable], "entrypoint": "generator.py",
            "representation": "G2", "source_files": sorted(str(p.relative_to(pack)) for p in pack.rglob("*") if p.is_file()),
            "source_snapshot": {editable: (pack / editable).read_text()}, "source_face": window, "frozen_dependency_modules": closure,
            "configurations": points, "ports": ports, "cell_name": definition["top"], "bench": bench,
            "natural_shortfall": definition["description"], "source_dependency_group": "vendor_connected_closure" if kind in ["fvf", "legacy_miller"] else definition["lineage"],
            "domain_note": "Declared narrow width/length domain; FVF local total width snapped.01um to preserve each parallel-finger width on.005um grid. Circuit multiplicities/topology and cap30 remain fixed within each configuration.",
            "qualification": {"generation_preflight": None, "anchor_geometry_equivalence": None, "full_domain_baseline": None,
                "isolated_evaluator_adapter": None, "model_context_tokens": None, "feasible_edit_witness": None},
            "formal_admission": False, "formal_trials": 0, "training_examples": 0, "new_physical_calls": 0}
        save(directory / "task.json", task)
        destination = out / "public" / kind
        destination.mkdir()
        public = {k: v for k, v in task.items() if k not in ["configurations", "source_files", "frozen_dependency_modules"]}
        public["visible_configurations"] = [{k: v for k, v in p.items() if k != "reference_file"} for p in points[:9]]
        public["hidden_configuration_count"] = 16
        save(destination / "task.json", public)
        packet = {"task_id": task["task_id"], "goal": "Improve the declared objective by one shared actual source edit across the visible domain, preserving immutable devices, intended connectivity, all constraints and exact fullRC analysis. Naturally infeasible points remain failures; an objective is ranked only after feasibility.",
            "contract": points[0]["contract"], "allowed_paths": [editable], "visible_sources": {editable: "Use read_source to obtain the complete editable semantic module"},
            "documents": {"PDK": base_packet["documents"]["PDK"],
                "configuration_defaults": points[0]["parameters"],
                "configurations": [{"configuration_id": p["configuration_id"], "reference_id": p["reference_id"],
                    "parameter_overrides": {k: v for k, v in p["parameters"].items() if v != points[0]["parameters"].get(k)}} for p in points[:9]],
                "configuration_reconstruction": "Each visible configuration is exactly configuration_defaults updated by its complete parameter_overrides. No sizing value is omitted or inferred from hidden data.",
                "bench": {k: legacy["contract"][k] for k in ["supply_V", "load_F", "common_mode_V", "temperature_C", "analysis_coverage", "reference_current_A", "n_reference_current_A", "p_reference_current_A", "bias_currents_A"] if k in legacy["contract"]},
                "API": {"module": definition["module"], "editable_function": window.get("function", definition["function"]),
                    "source_scope": window["scope"], "helpers": "All retained imported primitive/router and own-circuit helpers are frozen APIs. The complete actual assembly/helper body is editable; this is not an immutable generator behind an editable sizing wrapper."},
                "natural_shortfall": definition["description"]},
            "visible_configurations": [p["configuration_id"] for p in points[:9]],
            "budget": {"decisions": 10, "physical_evaluations": 9, "context_tokens": 8192, "reserved_output_tokens": 1024, "status": "DRAFT_CALIBRATION_PENDING"}}
        save(destination / "task_packet.json", packet)
        index.append({"kind": kind, "initial_state_id": task["initial_state_id"], "parent_lineage": task["parent_lineage"],
            "public_task": str(destination / "task.json"), "private_task": str(directory / "task.json"), "editable_paths": [editable],
            "source_bytes": len((pack / editable).read_bytes()), "points": 25, "objective": objective,
            "natural_application_load_F": legacy["contract"]["load_F"]})
    save(out / "public/index.json", {"status": "DRAFT_NOT_FORMAL", "preparation": str(out), "tasks": index,
        "task_count": 4, "formal_trials": 0, "new_physical_calls": 0, "hidden_tables_exportable": False,
        "materialization_wall_seconds": time.monotonic()-began})
    print(json.dumps({"preparation": str(out), "tasks": 4, "references": 100, "status": "DRAFT", "new_physical_calls": 0}), flush=True)


def context(preparation):
    from transformers import AutoTokenizer
    from src.local_model_adapter import decision_prompt
    cache = json.loads((ROOT / "configs/training/backbone_cache.json").read_text())
    tokenizer = AutoTokenizer.from_pretrained(cache["snapshot"], local_files_only=True, trust_remote_code=False)
    rows = []
    for kind in DEFINITIONS:
        folder = preparation / "public" / kind
        public = json.loads((folder / "task.json").read_text())
        packet = json.loads((folder / "task_packet.json").read_text())
        packet["visible_sources"] = public["source_snapshot"]
        request = {"task_packet": packet, "visible_history": [{"observation": {"source_scope": "complete actual editable source included once; no physical outcomes yet"}}]}
        prompt = decision_prompt(request)
        encoded = tokenizer.apply_chat_template([{"role": "user", "content": prompt}], tokenize=True, add_generation_prompt=True, return_dict=True)
        count = len(encoded["input_ids"])
        row = {"kind": kind, "input_tokens_with_complete_source": count, "reserved_output_tokens": 1024,
            "max_context_tokens": 8192, "fits_initial_complete_source_context": count+1024 <= 8192,
            "source_bytes": sum(len(s.encode()) for s in public["source_snapshot"].values()),
            "history_scope": "Initial complete source+all9visibleparameters+anchorcontract+PDK+documents. Later physical history is not measured; runtime must budget each complete episode turn without truncation.",
            "GPT_native_token_count": None}
        public["qualification"]["model_context_tokens"] = row
        save(folder / "task.json", public)
        private_task = preparation / "private" / kind / "task.json"
        task = json.loads(private_task.read_text())
        task["qualification"]["model_context_tokens"] = row
        save(private_task, task)
        rows.append(row)
    report = {"scope": "actual_pinned_Qwen_tokenizer_DRAFT_context_preflight_no_inference_no_physics", "tokenizer_revision": cache["revision"],
        "full_editable_source_preserved": True, "records": rows, "all_initial_contexts_fit": all(r["fits_initial_complete_source_context"] for r in rows),
        "formal_tasks": 0, "new_physical_calls": 0}
    save(preparation / "public/context_calibration.json", report)
    print(json.dumps(report), flush=True)


def bind_legacy_export(preparation):
    directory = preparation / "private/legacy_miller"
    task = json.loads((directory / "task.json").read_text())
    path = Path(task["source_pack"]) / "component_build.py"
    before = path.read_text()
    definition = DEFINITIONS["legacy_miller"]
    after = BUILD.format(kind="legacy_miller", module=definition["module"], face=task["editable_paths"][0],
        top=definition["top"], function=definition["function"], markers=LEGACY_MARKERS)
    ast.parse(after)
    (directory / "component_build_before_marker_binding.py").write_text(before)
    (directory / "frozen_export_binding.patch").write_text("".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile="prepared_export.py", tofile="qualified_seven_pin_export.py")))
    path.write_text(after)
    task["frozen_export_binding"] = {"reason": "Reuse exactly the already qualified seven-pin marker positions and remove nonphysical64/44 annotation; editable logic, N(z), gold and bench unchanged",
        "origin": "scripts/e2_development_pilot.py generate_layout legacy branch", "raw_before_and_patch_retained": True, "new_physical_calls": 0}
    save(directory / "task.json", task)
    public = preparation / "public/legacy_miller/task.json"
    view = json.loads(public.read_text())
    view["frozen_export_binding"] = task["frozen_export_binding"]
    save(public, view)
    print(json.dumps(task["frozen_export_binding"]), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context-preparation", type=Path)
    parser.add_argument("--bind-legacy-export", type=Path)
    args = parser.parse_args()
    if args.bind_legacy_export:
        bind_legacy_export(args.bind_legacy_export.resolve())
    elif args.context_preparation:
        context(args.context_preparation.resolve())
    else:
        prepare()
