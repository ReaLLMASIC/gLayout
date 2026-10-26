"""Fixed engineering E2 candidate pool; development only, no model policy or GPU."""
import argparse
import ast
from datetime import datetime, timezone
import difflib
import fcntl
import hashlib
import importlib.util
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

ROOT = Path("/work")
DEPENDENCY_REVISION = "d092211d7996c99159402451bc7141931d6a93c3"
DEPENDENCY_SOURCE = ROOT / "vendor/glayout-e2-development/src"


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def normalized_polygon_key(layer, datatype, points, origin):
    points = [(int(x)-origin[0], int(y)-origin[1]) for x, y in points]
    while len(points) > 1 and points[-1] == points[0]:
        points.pop()
    start = min(range(len(points)), key=lambda i: points[i])
    forward = points[start:]+points[:start]
    reverse = [forward[0]]+list(reversed(forward[1:]))
    return (int(layer), int(datatype), tuple(min(forward, reverse)))


def geometry(gds):
    import gdstk
    library = gdstk.read_gds(gds)
    top, = library.top_level()
    top.flatten()
    scale_um = library.unit / 1e-6
    grid_um = library.precision / 1e-6
    quantized = [(p.layer, p.datatype,
        [(round(float(x)*scale_um/grid_um), round(float(y)*scale_um/grid_um)) for x, y in p.points])
        for p in top.polygons]
    origin = (min(x for _, _, ps in quantized for x, _ in ps),
              min(y for _, _, ps in quantized for _, y in ps))
    canonical = sorted(normalized_polygon_key(layer, datatype, ps, origin)
                       for layer, datatype, ps in quantized)
    # This digest replaces expensive duplicate DRC/LVS/PEX/SPICE, not provenance.
    digest = hashlib.sha256(json.dumps(canonical, separators=(",", ":")).encode()).hexdigest()
    box = top.bounding_box()
    width, height = (float(box[1][0]-box[0][0])*scale_um,
                     float(box[1][1]-box[0][1])*scale_um)
    metal = [p for p in top.polygons if p.datatype == 20 and p.layer in [67, 68, 69, 70, 71]]
    length = 0.0
    for polygon in metal:
        lower, upper = polygon.bounding_box()
        dx, dy = float(upper[0]-lower[0])*scale_um, float(upper[1]-lower[1])*scale_um
        length += max(dx, dy)-min(dx, dy)
    return {"canonical_polygon_digest": digest, "canonical_grid_um": grid_um,
        "canonicalization": "flatten; ignore labels and cell names; remove common translation; normalize polygon start and winding; sort polygon multiset",
        "polygon_count": len(top.polygons), "bbox_width_um": width, "bbox_height_um": height,
        "footprint_area_um2": width*height,
        "wirelength_rectilinear_proxy_um": length,
        "wirelength_definition": "Sum of abs(bbox_width-bbox_height) over conductive LI/M1/M2/M3/M4 datatype20 polygons; geometric centerline proxy, not net-aware routed length",
        "conductor_area_um2": sum(float(p.area())*scale_um**2 for p in metal)}


def variant_text(before, family, control):
    """Only the explicitly predeclared layout constants may change."""
    if family == "five_t":
        replacements = [
            ("escape_width, drop_width, trunk_width = .2, .6, .8",
             f"escape_width, drop_width, trunk_width = .2, {control['drop_width_um']:g}, {control['trunk_width_um']:g}", 1),
            ("cursor = snap(reference.xmax + 22)", f"cursor = snap(reference.xmax + {control['channel_gap_um']:g})", 1),
            ("y = snap(top_edge + 8 + 3 * index)", f"y = snap(top_edge + 8 + {control['bus_pitch_um']:g} * index)", 1)]
    elif family == "compact_miller":
        replacements = [
            ("def segment(layer, first, last, width=.6, net=None):",
             f"def segment(layer, first, last, width={control['spine_width_um']:g}, net=None):", 1),
            ("width=.8,net=", f"width={control['bus_width_um']:g},net=", before.count("width=.8,net=")),
            ("destination=(130,10)", f"destination=({control['capacitor_center_x_um']:g},10)", 1),
            ("cap.xmax+4", f"cap.xmax+{control['output_landing_clearance_um']:g}", 1)]
    elif family == "fvf":
        replacements = [
            ("p_block_ref.movey(res_1_ref.ymax + evaluate_bbox(pblock)[1]/2 + 8)",
             f"p_block_ref.movey(res_1_ref.ymax + evaluate_bbox(pblock)[1]/2 + {control['pblock_gap_um']:g})", 1),
            ("cwidth=0.6, viaoffset=None, fullbottom=True, extension=8)",
             f"cwidth=0.6, viaoffset=None, fullbottom=True, extension={control['bias_route_extension_um']:g})", 2),
            ("hwidth=0.6, vwidth=0.6)",
             f"hwidth={control['source_tie_width_um']:g}, vwidth={control['source_tie_width_um']:g})", 1),
            ("cwidth=0.9, width2=0.29*3)", f"cwidth={control['lcmfb_route_width_um']:g}, width2=0.29*3)", 2)]
    else:
        replacements = [
            ("pmos_comps_ref.ymax+10)", f"pmos_comps_ref.ymax+{control['stage_gap_um']:g})", 1),
            ("+2,cwidth=2)", f"+{control['output_route_extension_um']:g},cwidth={control['output_route_width_um']:g})", 2),
            ("9*_max_metal_seperation_ps", f"{control['input_antenna_span_multiplier']:g}*_max_metal_seperation_ps", 4)]
    after = before
    for old, new, count in replacements:
        if count < 1 or after.count(old) != count:
            raise ValueError(f"Fixed layout control site changed: {old!r}; expected {count}")
        after = after.replace(old, new)
    return after


def retained_bench(original, family):
    """Reuse the same verified PEX; preserve all SPICE and integrity code."""
    if family == "fvf":
        start = original.index("if not a.skip_physical:")
        marker = "for fidelity in (["
        end = original.index(marker, start)
        transport = "\n".join([
            "physical = json.loads((source / 'validation.json').read_text())",
            "if not physical['physical_connectivity_and_positive_RC']: raise SystemExit('Retained physical admission required')",
            "record['DRC'], record['LVS'], record['RC'] = physical['DRC'], physical['LVS'], physical['RC']",
            "(out / 'fvf7_pex.spice').write_text((source / 'fvf7_pex.spice').read_text())", ""])
        adapted = original[:start]+transport+original[end:]
    elif family == "legacy_miller":
        original_drc = 'drc = check_gds(source/"ota7.gds", out/"drc_full")'
        if original.count(original_drc) != 1:
            raise ValueError("Legacy retained DRC transport site changed")
        adapted = original.replace(original_drc, 'drc = validation["DRC"]')
        start = adapted.index('if args.fidelity in ["post_rc","both"]:')
        marker = "for fidelity, netlist in ["
        end = adapted.index(marker, start)
        adapted = adapted[:start]+"pex.write_text((source / 'ota7_pex.spice').read_text())\nrecord['pex_returncode'] = 0\n"+adapted[end:]
    else:
        return original, {"adapted": False, "SPICE_and_integrity_source_identical": True}
    assert original[original.index(marker):] == adapted[adapted.index(marker):]
    return adapted, {"adapted": True, "analysis_suffix_marker": marker,
        "SPICE_and_integrity_source_identical": True,
        "change": "Only repeated physical verification/extraction replaced by already admitted actual PEX transport",
        "cost_disclosure": "Exactly one actual DRC/LVS/PEX acquisition per candidate; redundant benchmark extraction is omitted for every candidate in this source pool. No omitted cost is called a measurement."}


def generate_layout(generator, family, manifest, sky130, out):
    if family in ["five_t", "compact_miller"]:
        write(out / "sizing.json", manifest["fixed_sizing"])
        return generator.build(out, manifest["fixed_sizing"])
    import gdstk
    if family == "fvf":
        component = generator.super_class_AB_OTA(sky130).copy()
    else:
        component = generator.opamp_twostage(sky130, mim_cap_size=(30, 30), rmult=2,
                                            half_diffpair_params=(6, 1, 4))
    name = manifest["cell_name"]
    path = out / (name+".gds")
    component.write_gds(path)
    library = gdstk.read_gds(path)
    top, = library.top_level()
    top.flatten(); top.name = name
    if family == "legacy_miller":
        # Same independent seven-port binding used by the qualified physical
        # probe, including its in-metal GND marker placement.
        top.remove(*top.labels)
        annotation = {(64, 44)} | {value for key, value in sky130.glayers.items()
            if key.endswith(("_label", "_pin")) and isinstance(value, tuple)}
        top.remove(*(polygon for polygon in top.polygons if (polygon.layer, polygon.datatype) in annotation))
        pin_ports = {"VDD": "pin_vdd_e4", "GND": "pin_gnd_N",
            "DIFFPAIR_BIAS": "diffpair_ibias_A_drain_E", "VP": "pin_plus_e3", "VN": "pin_minus_e3",
            "CS_BIAS": "pin_commonsourceibias_e2", "VOUT": "commonsource_output_E"}
        pins = {}
        for label, key in pin_ports.items():
            port = component.ports[key]
            glayer = sky130.layer_to_glayer(port.layer)
            x, y = map(float, port.center)
            half = .15 if label == "GND" else .1
            if label == "GND":
                y -= .15
            layer, datatype = sky130.get_glayer(glayer+"_pin")
            top.add(gdstk.rectangle((x-half, y-half), (x+half, y+half), layer=layer, datatype=datatype))
            layer, datatype = sky130.get_glayer(glayer+"_label")
            top.add(gdstk.Label(label, (x, y), layer=layer, texttype=datatype))
            pins[label] = {"port": key, "label_center_um": [x, y]}
        write(out / "pin_bindings.json", pins)
    clean = gdstk.Library(unit=library.unit, precision=library.precision)
    clean.add(top); clean.write_gds(path)
    return path


def electrical_summary(measures, family):
    if family in ["five_t", "compact_miller"]:
        corners = measures["results"]
        op_field = "operating_point_integrity" if family == "five_t" else "op_integrity"
        complete = (len(corners) == 3 and {x["corner"] for x in corners.values()} == {"tt", "ss", "ff"}
            and all(x.get(op_field, {}).get("complete") and
                all(x.get("analyses", {}).get(k, {}).get("integrity", {}).get("complete") for k in ["ac", "tran", "dc"])
                for x in corners.values()))
        feasible_field = "development_all_corners_feasible" if family == "five_t" else "all_corners_nominal_feasible"
        feasible = bool(complete and measures.get(feasible_field))
        metrics = {c: x for c, x in corners.items()}
    else:
        corners = measures["results"].get("post_rc", {})
        complete_field = "simulation_flow_complete" if family == "fvf" else "flow_complete"
        integrity_field = "analysis_validation" if family == "fvf" else "analysis_evidence"
        complete = bool(set(corners) == {"tt", "ss", "ff"} and measures.get(complete_field) and all(
            all(x["complete"] for x in row[integrity_field].values()) for row in corners.values()))
        metrics = {}
        for corner, row in corners.items():
            original = row["metrics"]
            m = {"gain_10Hz_dB": original.get("gain_at_10Hz_dB"), "ugb_Hz": original.get("ugb_Hz"),
                "phase_margin_deg": original.get("phase_margin_deg"), "power_W": original.get("power_W"),
                "output_V": original.get("output_bias_V"), "positive_low_frequency_gain": original.get("gain_at_10Hz_real", 0)>0}
            if row[integrity_field].get("transient", {}).get("complete"):
                import numpy as np
                trace_path = Path(row[integrity_field]["transient"]["data_path"])
                trace = np.loadtxt(trace_path, skiprows=1, ndmin=2)
                high = (trace[:, 0] > 1.8e-6) & (trace[:, 0] < 1.99e-6)
                low = (trace[:, 0] > 2.8e-6) & (trace[:, 0] < 2.99e-6)
                m["settled_tracking_error_V"] = float(max(abs(np.mean(trace[high, 2]-trace[high, 1])),
                                                            abs(np.mean(trace[low, 2]-trace[low, 1]))))
            if row[integrity_field].get("dc", {}).get("complete"):
                import numpy as np
                trace = np.loadtxt(Path(row[integrity_field]["dc"]["data_path"]), skiprows=1, ndmin=2)
                m["maximum_dc_tracking_error_V"] = float(max(abs(trace[:, 2]-trace[:, 1])))
            metrics[corner] = m
        feasible = bool(complete and all(x.get("gain_10Hz_dB") is not None and x["gain_10Hz_dB"]>=30
            and x.get("ugb_Hz") is not None and x["ugb_Hz"]>=1e6
            and x.get("phase_margin_deg") is not None and 60 <= x["phase_margin_deg"] <= 180 and x["positive_low_frequency_gain"]
            and abs(x["output_V"]-.9)<.01 and x.get("settled_tracking_error_V", 1)<.01
            and 0 < x["power_W"] <= .001 for x in metrics.values()))
    worst = None
    if complete:
        minimum = lambda key: min(x[key] for x in metrics.values()) if all(x.get(key) is not None for x in metrics.values()) else None
        worst = {"ugb_Hz": minimum("ugb_Hz"),
            "gain_10Hz_dB": min(x["gain_10Hz_dB"] for x in metrics.values()),
            "phase_margin_deg": minimum("phase_margin_deg"),
            "power_W": max(x["power_W"] for x in metrics.values()),
            "settled_tracking_error_V": max(x["settled_tracking_error_V"] for x in metrics.values()),
            "maximum_dc_tracking_error_V": max(x["maximum_dc_tracking_error_V"] for x in metrics.values())}
    return complete, feasible, worst


def plan(out, family="five_t"):
    # The complete stream and all sources are retained before any GDS is built.
    out.mkdir(exist_ok=True)
    sources = {
        "five_t": (ROOT / "src/generators/five_t.py", ROOT / "src/generators/five_t_reference.py", ROOT / "scripts/custom_ota_schematic.py"),
        "compact_miller": (ROOT / "runs/phase0/phase0_20261018T234425820562Z_custom_ota_miller_build/compact_miller.py",
            ROOT / "runs/phase0/phase0_20261018T234425820562Z_custom_ota_miller_build/compact_miller_reference.py", ROOT / "scripts/custom_ota_miller_schematic.py"),
        "fvf": (DEPENDENCY_SOURCE / "glayout/cells/composite/fvf_based_ota/ota.py", ROOT / "scripts/fvf_reference.py", ROOT / "scripts/fvf_validate.py"),
        "legacy_miller": (DEPENDENCY_SOURCE / "glayout/cells/composite/opamp/opamp_twostage.py", None, ROOT / "scripts/ota_postlayout.py")}
    generator_path, reference_path, bench_path = sources[family]
    (out / "generator_snapshot.py").write_text(generator_path.read_text())
    original_bench = bench_path.read_text()
    adapted_bench, adaptation = retained_bench(original_bench, family)
    (out / "testbench_original.py").write_text(original_bench)
    (out / "testbench_snapshot.py").write_text(adapted_bench)
    (out / "bench_transport.patch").write_text("".join(difflib.unified_diff(original_bench.splitlines(True), adapted_bench.splitlines(True), fromfile=str(bench_path), tofile="testbench_snapshot.py")))
    write(out / "bench_transport_validation.json", adaptation)
    if reference_path:
        (out / "reference_snapshot.py").write_text(reference_path.read_text())
        reference = load_module("e2_fixed_reference", out / "reference_snapshot.py")
    if family in ["five_t", "compact_miller"]:
        sizing = dict(reference.DEFAULT)
        if family == "compact_miller":
            sizing = json.loads((generator_path.parent / "sizing.json").read_text())
            if sizing["cap_size"] != 30:
                raise ValueError("Qualified compact physical reference unexpectedly changed")
        gold = reference.schematic(sizing)
        fixed_ports = reference.PORTS
    elif family == "fvf":
        sizing = {"generator_arguments": "unchanged source defaults", "actual_main_finger_widths": "explicit in frozen independent reference"}
        gold = reference.intended_reference()
        fixed_ports = reference.PORTS
    else:
        sizing = {"mim_cap_size": [30, 30], "rmult": 2, "half_diffpair_params": [6, 1, 4], "other_arguments": "unchanged source defaults"}
        fixed_ports = ["VDD", "GND", "DIFFPAIR_BIAS", "VP", "VN", "CS_BIAS", "VOUT"]
        reference_path = ROOT / "runs/phase0/phase0_20261018T232822611862Z_ota_reference_probe/ota7.spice"
        gold = reference_path.read_text()
        (out / "reference_snapshot.py").write_text("# Fixed independent gold copied before candidate generation\nPORTS = "+repr(fixed_ports)+"\n")
    frozen = out / "frozen_src/src"
    (frozen / "generators").mkdir(parents=True)
    (frozen / "__init__.py").write_text("")
    (frozen / "generators/__init__.py").write_text("")
    if family in ["five_t", "compact_miller"]:
        shutil.copy2(out / "reference_snapshot.py", frozen / "generators" / (family+"_reference.py"))
    for name in ["report_parsers.py", "spice_validation.py", "physical_drc.py"]:
        shutil.copy2(ROOT / "src" / name, frozen / name)
    (out / "gold.spice").write_text(gold)
    controls = {"five_t": {"channel_gap_um": [22, 30], "drop_width_um": [.6, 1.0],
                "trunk_width_um": [.8, 1.4], "bus_pitch_um": [3, 4]},
        "compact_miller": {"spine_width_um": [.6, .9], "bus_width_um": [.8, 1.2],
            "capacitor_center_x_um": [130, 146], "output_landing_clearance_um": [4, 8]},
        "fvf": {"pblock_gap_um": [8, 12], "bias_route_extension_um": [8, 12],
            "source_tie_width_um": [.6, .9], "lcmfb_route_width_um": [.9, 1.2]},
        "legacy_miller": {"stage_gap_um": [10, 14], "output_route_width_um": [2, 3],
            "output_route_extension_um": [2, 6], "input_antenna_span_multiplier": [9, 13]}}[family]
    candidates = [{"candidate_id": f"c{i:02d}", "stream_index": i,
        "baseline": i == 0, "controls": dict(zip(controls, values))}
        for i, values in enumerate(itertools.product(*controls.values()))]
    for item in candidates:
        ast.parse(variant_text(generator_path.read_text(), family, item["controls"]))
    contract = {"supply_V": 1.8, "load_F": 2e-12, "common_mode_V": 1.1,
        "reference_current_A": 20e-6, "temperature_C": 27, "corners": ["tt", "ss", "ff"],
        "bench_source_unchanged": "testbench_snapshot.py",
        "numerics": {"reltol": 1e-6, "abstol": 1e-14, "vntol": 1e-8, "chgtol": 1e-16},
        "analysis_coverage": {"OP_rows": 1, "AC_rows": 401, "AC_Hz": [10, 1e9],
            "transient_s": [0, 4e-6], "DC_points": 9, "DC_V": [.9, 1.3]},
        "existing_development_feasibility": {"tail_V_open_interval": [.15, .8],
            "mirror_V_open_interval": [.4, 1.6], "nominal_tracking_abs_V_lt": .01,
            "supply_current_A_open_interval": [20e-6, 80e-6], "phase_margin_deg_closed_interval": [60, 180],
            "positive_low_frequency_gain": True, "gain_10Hz_dB_min": 30, "ugb_Hz_min": 1e6,
            "settled_tracking_error_V_lt": .01},
        "DC_sweep_interpretation": "The complete broad tracking sweep is retained; no extra output-swing or maximum-DC-error constraint is added."}
    if family == "compact_miller":
        contract.update(load_F=2e-12, common_mode_V=1.05, n_reference_current_A=20e-6, p_reference_current_A=10e-6,
            analysis_coverage={"OP_rows": 1, "AC_rows": 401, "AC_Hz": [10, 1e9], "transient_s": [0, 4e-6], "DC_points": 5, "DC_V": [.95, 1.15]},
            existing_development_feasibility={"gain_10Hz_dB_min": 55, "phase_margin_deg_closed_interval": [60, 180],
                "ugb_Hz_min": 1e6, "nominal_tracking_abs_V_lt": .005, "settled_tracking_error_V_lt": .005,
                "tail_V_open_interval": [.15, .8], "stage1_V_open_interval": [.3, 1.2], "supply_current_A_open_interval": [50e-6, 160e-6]})
        contract.pop("reference_current_A")
        bench_arguments = ["--post-rc", "--load-pf", "2", "--vcm", "1.05", "--cap-size", "30", "--n-bias-ua", "20", "--p-bias-ua", "10"]
    elif family in ["fvf", "legacy_miller"]:
        contract.update(load_F=(10e-12 if family == "fvf" else .5e-12), common_mode_V=.9, bias_currents_A=[1e-5, 1e-5],
            analysis_coverage={"OP_rows": 1, "AC_rows": 241, "AC_Hz": [10, 1e9], "transient_s": [0, 4e-6], "DC_points": 7, "DC_V": [.6, 1.2]},
            existing_development_feasibility={"gain_10Hz_dB_min": 30, "phase_margin_deg_closed_interval": [60, 180],
                "ugb_Hz_min": 1e6, "nominal_tracking_abs_V_lt": .01, "settled_plateau_mean_tracking_abs_V_lt": .01,
                "positive_low_frequency_gain": True, "power_W_max": .001})
        contract.pop("reference_current_A")
        bench_arguments = ["--fidelity", "post_rc", "--load-pf", "10" if family == "fvf" else ".5"]
        if family == "fvf":
            bench_arguments += ["--gds-relative", "fvf7.gds"]
    else:
        bench_arguments = ["--post-rc", "--load-pf", "2", "--vcm", "1.1", "--bias-ua", "20"]
    manifest = {"scope": "E2_fixed_engineering_development_pool_not_formal_or_training", "source_family": family,
        "pool_id": out.name, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "fixed_generator": "generator_snapshot.py", "fixed_reference": "gold.spice",
        "fixed_sizing": sizing, "fixed_ports": fixed_ports,
        "source_origin": str(generator_path), "reference_origin": str(reference_path), "bench_origin": str(bench_path),
        "bench_arguments": bench_arguments, "bench_transport": adaptation,
        "cell_name": {"five_t": "five_t_ota", "compact_miller": "compact_miller_ota", "fvf": "fvf7", "legacy_miller": "ota7"}[family],
        "dependency_revision": DEPENDENCY_REVISION, "dependency_source": str(DEPENDENCY_SOURCE),
        "unchanged_escape_width_um": .2 if family == "five_t" else None,
        "device_or_compensation_capacitor_sizing_changes_allowed": False,
        "control_levels": controls, "candidates": candidates,
        "candidate_count": 16, "order_rule": "lexicographic product in listed control order; baseline first; no outcome filtering",
        "contract": contract, "primary_objective": {"metric": "worst_corner_ugb_Hz", "direction": "maximize", "requires_all_corner_feasibility": True},
        "proxy_directions": {"footprint_area_um2": "minimize", "wirelength_rectilinear_proxy_um": "minimize", "R_sum_ohm": "minimize", "C_sum_F": "minimize"},
        "feature_fidelities": {"footprint_area_um2": "GDS_geometry", "wirelength_rectilinear_proxy_um": "GDS_geometry",
            "R_sum_ohm": "actual_full_RC_PEX", "C_sum_F": "actual_full_RC_PEX"},
        "feature_interpretation": "Descriptive associations only; these are not calibrated predictions of UGB. RC features require actual PEX acquisition cost.",
        "deduplication": "Translation-normalized, winding/start/order-invariant full polygon multiset; geometry digest skips duplicated expensive physical evaluations. All attempts and duplicate costs retained.",
        "execution_role": "trusted engineering constant sampler; not an untrusted model patch execution interface"}
    write(out / "pool_plan.json", manifest)
    # Bounded test of the de-dup transform that determines expensive next action.
    rectangle = [(0, 0), (10, 0), (10, 2), (0, 2)]
    first = normalized_polygon_key(69, 20, rectangle, (0, 0))
    shifted = [(x+7, y-4) for x, y in rectangle]
    assert first == normalized_polygon_key(69, 20, list(reversed(shifted[1:]+shifted[:1])), (7, -4))
    assert first != normalized_polygon_key(69, 20, [(0, 0), (11, 0), (11, 2), (0, 2)], (0, 0))
    write(out / "dedup_smoke.json", {"translation_rotation_winding_invariance": True, "distinct_dimensions_remain_distinct": True})
    for path in [out / "generator_snapshot.py", out / "reference_snapshot.py", out / "testbench_snapshot.py", out / "gold.spice"]:
        path.chmod(0o444)
    print(json.dumps({"pool_id": out.name, "candidate_count": 16, "manifest": str(out / "pool_plan.json")}), flush=True)


def candidate(out, inputs, index):
    started = time.monotonic()
    manifest = json.loads((inputs / "pool_plan.json").read_text())
    selected = manifest["candidates"][index]
    family = manifest.get("source_family", "five_t")
    cell_name = manifest.get("cell_name", "five_t_ota")
    result = {"scope": manifest["scope"], "pool_id": manifest["pool_id"],
        "attempt_id": out.name, "source_family": family, **selected, "status": "STARTING", "stage_wall_seconds": {},
        "full_flow_complete": False, "all_corner_development_feasible": False}
    write(out / "candidate_manifest.json", {**result, "plan_path": str(inputs / "pool_plan.json"),
        "fixed_sizing": manifest["fixed_sizing"], "contract": manifest["contract"],
        "dependency_revision": manifest["dependency_revision"]})

    def save():
        result["wall_seconds"] = time.monotonic()-started
        write(out / "candidate_result.json", result)

    try:
        sys.path[:0] = [str(inputs / "frozen_src"), manifest["dependency_source"]]
        from src.physical_drc import check_gds
        from src.report_parsers import netgen_lvs_report, rc_netlist_inventory, spice_literal
        from glayout import sky130
        shutil.copy2(inputs / "gold.spice", out / "gold.spice")
        shutil.copy2(inputs / "gold.spice", out / (cell_name+".spice"))
        before = (inputs / "generator_snapshot.py").read_text()
        after = variant_text(before, family, selected["controls"])
        (out / "candidate_source.py").write_text(after)
        (out / "candidate.patch").write_text("".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
            fromfile="a/"+family+"_generator.py", tofile="b/"+family+"_generator.py")))
        t = time.monotonic()
        generator = load_module("e2_"+selected["candidate_id"], out / "candidate_source.py")
        gds = generate_layout(generator, family, manifest, sky130, out)
        result["stage_wall_seconds"]["generation"] = time.monotonic()-t
        t = time.monotonic()
        result["L0"] = geometry(gds)
        result["stage_wall_seconds"]["geometry"] = time.monotonic()-t
        digest = result["L0"]["canonical_polygon_digest"]
        with (inputs / "geometry_registry.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            registry_path = inputs / "geometry_registry.json"
            registry = json.loads(registry_path.read_text()) if registry_path.exists() else {}
            previous = registry.get(digest)
            if previous and previous["candidate_id"] != selected["candidate_id"]:
                result.update(status="GEOMETRY_DUPLICATE", duplicate_of=previous)
                save()
                return 0
            registry.setdefault(digest, {"candidate_id": selected["candidate_id"], "attempt_id": out.name})
            write(registry_path, registry)
        save()
        t = time.monotonic()
        result["DRC"] = check_gds(gds, out / "drc_full")
        result["stage_wall_seconds"]["DRC"] = time.monotonic()-t
        t = time.monotonic()
        sky130.lvs_netgen(gds, cell_name, pdk_root="/foss/pdks",
            magic_drc_file="/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc",
            lvs_setup_tcl_file="/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl",
            lvs_schematic_ref_file=str(Path(manifest["dependency_source"]) / "glayout/pdk/sky130_mapped/sky130_fd_sc_hd.spice"),
            netlist=out / "gold.spice", output_file_path=out / "lvs", copy_intermediate_files=True)
        result["LVS"] = netgen_lvs_report(next((out / "lvs").rglob("*_lvs.rpt")).read_text())
        result["stage_wall_seconds"]["LVS"] = time.monotonic()-t
        if not result["DRC"]["is_clean"] or not result["LVS"]["is_clean"]:
            result["status"] = "PHYSICAL_CORRECTNESS_FAILURE"; save(); return 2
        t = time.monotonic()
        with (out / "pex.log").open("w") as log:
            pex = subprocess.run(["bash", str(Path(manifest["dependency_source"]) / "glayout/verification/run_pex.sh"),
                str(gds), cell_name], stdout=log, stderr=subprocess.STDOUT, timeout=240)
        result["stage_wall_seconds"]["PEX"] = time.monotonic()-t
        extracted = out / (cell_name+"_pex.spice")
        result["pex_returncode"] = pex.returncode
        result["RC"] = rc_netlist_inventory(extracted.read_text(), cell_name+"_rc", manifest["fixed_ports"]) if extracted.exists() else None
        if pex.returncode or not result["RC"] or not result["RC"]["has_real_RC"]:
            result["status"] = "RC_ADMISSION_FAILURE"; save(); return 2
        rc_values = {kind: [spice_literal(line.split()[3]) for line in extracted.read_text().splitlines()
            if line.split() and line[0].upper() == kind] for kind in ["R", "C"]}
        result["post_PEX_features"] = {"R_sum_ohm": sum(rc_values["R"]), "C_sum_F": sum(rc_values["C"]),
            "R_max_ohm": max(rc_values["R"]), "C_max_F": max(rc_values["C"])}
        result["post_PEX_feature_acquisition"] = {"fidelity": "actual_full_RC_PEX",
            "wall_seconds": result["stage_wall_seconds"]["PEX"],
            "interpretation": "Descriptive features requiring actual PEX; not cheap L1 or calibrated UGB predictions"}
        write(out / "validation.json", {"physical_connectivity_and_positive_RC": True, "LVS_match": True,
            "DRC": result["DRC"], "LVS": result["LVS"], "RC": result["RC"]})
        work = out / "electrical"; work.mkdir()
        launcher = work / "run_fixed_bench.py"
        preloads = ["import src.report_parsers, src.spice_validation, src.physical_drc"]
        if family in ["five_t", "compact_miller"]:
            preloads += ["import src.generators."+family+"_reference"]
        if family == "fvf":
            preloads += ["import importlib.util", "spec=importlib.util.spec_from_file_location('fvf_reference', "+repr(str(inputs / "reference_snapshot.py"))+")",
                "module=importlib.util.module_from_spec(spec);sys.modules['fvf_reference']=module;spec.loader.exec_module(module)"]
        launcher.write_text("\n".join(["import os, sys, runpy",
            "sys.path[:0] = " + repr([str(inputs / "frozen_src"), manifest["dependency_source"]]),
            *preloads,
            "os.environ['PROBE_INPUT'] = " + repr(str(out)),
            "sys.argv = " + repr([str(inputs / "testbench_snapshot.py")]+manifest.get("bench_arguments", ["--post-rc", "--load-pf", "2", "--vcm", "1.1", "--bias-ua", "20"])),
            "runpy.run_path(" + repr(str(inputs / "testbench_snapshot.py")) + ", run_name='__main__')", ""]))
        t = time.monotonic()
        with (work / "bench_console.log").open("w") as log:
            simulation = subprocess.run([sys.executable, str(launcher)], cwd=work,
                stdout=log, stderr=subprocess.STDOUT, timeout=2160 if family == "legacy_miller" else 1200)
        result["stage_wall_seconds"]["electrical"] = time.monotonic()-t
        result["bench_returncode"] = simulation.returncode
        measures = json.loads((work / "measurements.json").read_text())
        result["electrical"] = measures
        complete, feasible, worst = electrical_summary(measures, family)
        result["full_flow_complete"] = bool(complete)
        result["all_corner_development_feasible"] = feasible
        if complete:
            result["worst_corner_metrics"] = worst
        result["status"] = ("COMPLETE_FEASIBLE" if result["all_corner_development_feasible"] else
                            "COMPLETE_INFEASIBLE" if complete else "INCOMPLETE_SIMULATION")
        save()
        return 0 if result["all_corner_development_feasible"] else 2
    except Exception as error:
        result.update(status="EXCEPTION", exception=str(error), traceback=traceback.format_exc())
        save()
        return 2


def collect(out, inputs):
    manifest = json.loads((inputs / "pool_plan.json").read_text())
    family = manifest.get("source_family", "five_t")
    attempts = []
    for path in sorted((ROOT / "runs/phase0").glob("*_e2_development_pilot/candidate_manifest.json")):
        info = json.loads(path.read_text())
        if info["pool_id"] != manifest["pool_id"]:
            continue
        folder = path.parent
        result_path = folder / "candidate_result.json"
        result = json.loads(result_path.read_text()) if result_path.exists() else {"status": "MISSING_RESULT"}
        outer = json.loads((folder / "pilot_manifest.json").read_text())
        resource_path = folder / "resource_usage.json"
        resources = json.loads(resource_path.read_text()) if resource_path.exists() else None
        attempts.append({"run_id": folder.name, "candidate_id": info["candidate_id"],
            "stream_index": info["stream_index"], "controls": info["controls"], "result": result,
            "runner_manifest": outer, "resource_usage": resources})
    table = [{"source_family": family, "candidate_id": a["candidate_id"], "stream_index": a["stream_index"],
        "run_id": a["run_id"], **a["controls"], "status": a["result"]["status"],
        "runner_status": a["runner_manifest"]["status"],
        "full_flow_complete": a["result"].get("full_flow_complete", False),
        "all_corner_development_feasible": a["result"].get("all_corner_development_feasible", False),
        **{k: v for k, v in a["result"].get("L0", {}).items() if k in ["footprint_area_um2", "wirelength_rectilinear_proxy_um", "canonical_polygon_digest"]},
        **a["result"].get("post_PEX_features", a["result"].get("L1", {})),
        "RC_feature_fidelity": "actual_full_RC_PEX",
        "RC_feature_acquisition_wall_seconds": a["result"].get("stage_wall_seconds", {}).get("PEX"),
        **{"worst_corner_"+k: v for k, v in a["result"].get("worst_corner_metrics", {}).items()},
        "wall_seconds": a["result"].get("wall_seconds"),
        "stage_wall_seconds": a["result"].get("stage_wall_seconds"),
        "resource_usage": a["resource_usage"]} for a in attempts]
    observed = {x["candidate_id"] for x in attempts}
    feasible_candidates = {a["candidate_id"] for a in attempts if a["result"].get("all_corner_development_feasible")}
    summary = {"scope": manifest["scope"], "pool_id": manifest["pool_id"], "source_family": family, "plan": manifest,
        "development_concurrency_adjustment": json.loads((inputs / "concurrency_adjustment.json").read_text()) if (inputs / "concurrency_adjustment.json").exists() else None,
        "dispatch_cost_records": [name for name in ["dispatch_events.jsonl", "dispatch_events_v2.jsonl", "resource_guard_events.jsonl"] if (inputs / name).exists()],
        "feature_interpretation": "Descriptive associations, not calibrated UGB predictions. R/C aggregates require actual full-RC PEX and its recorded acquisition cost.",
        "raw_field_normalization": "Initial raw attempts used legacy key L1 for post-PEX aggregates; raw JSON is preserved. The derived pool table explicitly marks these as actual_full_RC_PEX, never cheap L1.",
        "planned_candidate_count": 16, "attempt_count": len(attempts),
        "observed_distinct_planned_candidates": len(observed),
        "missing_candidates": [x["candidate_id"] for x in manifest["candidates"] if x["candidate_id"] not in observed],
        "all_candidate_attempts_terminal": len(observed) == 16 and all(a["runner_manifest"]["status"] != "RUNNING" for a in attempts),
        "geometry_unique_count": len({a["result"]["L0"]["canonical_polygon_digest"] for a in attempts if "L0" in a["result"]}),
        "full_flow_complete_attempts": sum(a["result"].get("full_flow_complete", False) for a in attempts),
        "all_corner_feasible_attempts": sum(a["result"].get("all_corner_development_feasible", False) for a in attempts),
        "all_corner_feasible_distinct_candidates": len(feasible_candidates),
        "no_feasible_oracle": len(feasible_candidates) == 0,
        "nonfeasible_fraction_of_fixed_stream": (16-len(feasible_candidates))/16,
        "nonfeasible_fraction_interpretation": "Fraction not establishing all-corner feasibility within the fixed flow and budgets, including physical failures, incomplete simulations and timeouts; not a claim of intrinsic electrical infeasibility.",
        "complete_electrically_infeasible_attempts": sum(a["result"].get("status") == "COMPLETE_INFEASIBLE" for a in attempts),
        "incomplete_simulation_attempts": sum(a["result"].get("status") == "INCOMPLETE_SIMULATION" for a in attempts),
        "physical_correctness_failure_attempts": sum(a["result"].get("status") == "PHYSICAL_CORRECTNESS_FAILURE" for a in attempts),
        "geometry_duplicate_attempts": sum(a["result"].get("status") == "GEOMETRY_DUPLICATE" for a in attempts),
        "regret": None,
        "regret_reason": "no_feasible_oracle" if not feasible_candidates else "not_computed_in_development_pool_collection",
        "pool_table": table, "attempts": attempts}
    write(out / "e2_development_pool.json", summary)
    write(ROOT / "results/derived" / ("e2_development_"+family+"_pool.json"), summary)
    if family == "five_t":
        write(ROOT / "results/derived/e2_development_pool.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k not in ["plan", "pool_table", "attempts"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["plan", "candidate", "collect"], required=True)
    parser.add_argument("--candidate-index", type=int)
    parser.add_argument("--source-family", choices=["five_t", "compact_miller", "fvf", "legacy_miller"], default="five_t")
    args = parser.parse_args()
    out = Path.cwd()
    if args.mode == "plan":
        plan(out, args.source_family)
        return 0
    inputs = Path(os.environ["PROBE_INPUT"])
    if args.mode == "collect":
        collect(out, inputs)
        return 0
    if args.candidate_index not in range(16):
        parser.error("candidate index must refer to the predeclared 0..15 stream")
    return candidate(out, inputs, args.candidate_index)


if __name__ == "__main__":
    raise SystemExit(main())
