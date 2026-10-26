"""Draft editing states made from complete, real target modules.

The parameter renderer changes only declared layout sites. Device sizing and
the independent reference are outside this interface. No policy or EDA runs
when this module is imported.
"""
import ast
import copy
import json
import re

TARGETS = ("mirror", "cascode_mirror", "source_follower", "stacked_switch",
           "common_source_stage", "resistive_diff", "five_t", "compact_miller")

EDITABLE = {target: "src/generators/"+target+".py" for target in TARGETS}
EDITABLE["mirror"] = "glayout/cells/elementary/current_mirror/current_mirror.py"

# These are layout controls, never transistor/MIM dimensions. Existing E2 level
# sets are kept in full, including their observed physically failing values.
LEVELS = {
    "mirror": {"route_extension_multiplier": [1, 2, 3, 4, 5, 6, 7, 8]},
    "cascode_mirror": {"external_rail_offset_um": [0, 10, 20, 30],
                       "stack_width_um": [.6, .8, 1., 1.2, 1.4]},
    "source_follower": {"output_collector_x_um": [70, 85, 100],
                        "ground_floor_y_um": [-45, -50, -55],
                        "output_width_um": [.6, .8, 1., 1.2]},
    "stacked_switch": {"separation_um": [12, 18, 24, 30, 36, 42, 48],
                       "signal_width_um": [.6, .8, 1., 1.2]},
    "common_source_stage": {"pair_gap_um": [24, 30, 36, 42, 48, 54, 60],
                            "stage_gap_um": [16, 24, 32, 40],
                            "output_width_um": [.6, .8, 1., 1.2]},
    "resistive_diff": {"input_gap_um": [36, 48, 60, 72],
                       "row_gap_um": [24, 28, 36, 44],
                       "collector_width_um": [.6, .8, 1., 1.2]},
    "five_t": {"channel_gap_um": [22, 30], "drop_width_um": [.6, 1.],
               "trunk_width_um": [.8, 1.4], "bus_pitch_um": [3, 4]},
    "compact_miller": {"spine_width_um": [.6, .9], "bus_width_um": [.8, 1.2],
                       "capacitor_center_x_um": [130, 146],
                       "output_landing_clearance_um": [4, 8]},
}

DEFAULTS = {
    "mirror": {"route_extension_multiplier": 3},
    "cascode_mirror": {"external_rail_offset_um": 0, "stack_width_um": .8},
    "source_follower": {"output_collector_x_um": 70, "ground_floor_y_um": -45,
                        "output_width_um": .8},
    "stacked_switch": {"separation_um": 24, "signal_width_um": .8},
    "common_source_stage": {"pair_gap_um": 36, "stage_gap_um": 24, "output_width_um": .8},
    "resistive_diff": {"input_gap_um": 48, "row_gap_um": 28, "collector_width_um": .8},
    "five_t": {"channel_gap_um": 22, "drop_width_um": .6, "trunk_width_um": .8, "bus_pitch_um": 3},
    "compact_miller": {"spine_width_um": .6, "bus_width_um": .8,
                       "capacitor_center_x_um": 130, "output_landing_clearance_um": 4},
}

INITIALS = {
    "mirror": [DEFAULTS["mirror"], {"route_extension_multiplier": 5}, {"route_extension_multiplier": 7}],
    "cascode_mirror": [DEFAULTS["cascode_mirror"],
        {"external_rail_offset_um": 10, "stack_width_um": 1.},
        {"external_rail_offset_um": 20, "stack_width_um": 1.2}],
    "source_follower": [DEFAULTS["source_follower"],
        {"output_collector_x_um": 85, "ground_floor_y_um": -50, "output_width_um": 1.},
        {"output_collector_x_um": 100, "ground_floor_y_um": -55, "output_width_um": 1.2}],
    "stacked_switch": [DEFAULTS["stacked_switch"],
        {"separation_um": 36, "signal_width_um": 1.},
        {"separation_um": 48, "signal_width_um": 1.2}],
    "common_source_stage": [DEFAULTS["common_source_stage"],
        {"pair_gap_um": 48, "stage_gap_um": 32, "output_width_um": 1.},
        {"pair_gap_um": 60, "stage_gap_um": 40, "output_width_um": 1.2}],
    "resistive_diff": [DEFAULTS["resistive_diff"],
        {"input_gap_um": 60, "row_gap_um": 36, "collector_width_um": 1.},
        {"input_gap_um": 72, "row_gap_um": 44, "collector_width_um": 1.2}],
    # Actual E2 c00/c07/c15 and c00/c02/c08, not newly injected bugs.
    "five_t": [DEFAULTS["five_t"],
        {"channel_gap_um": 22, "drop_width_um": 1., "trunk_width_um": 1.4, "bus_pitch_um": 4},
        {"channel_gap_um": 30, "drop_width_um": 1., "trunk_width_um": 1.4, "bus_pitch_um": 4}],
    "compact_miller": [DEFAULTS["compact_miller"],
        {"spine_width_um": .6, "bus_width_um": .8, "capacitor_center_x_um": 146, "output_landing_clearance_um": 4},
        {"spine_width_um": .9, "bus_width_um": .8, "capacitor_center_x_um": 130, "output_landing_clearance_um": 4}],
}


def render_parameters(target, before, controls):
    """Render P's complete declared layout family from its immutable source."""
    if target not in TARGETS or set(controls) != set(LEVELS[target]):
        raise ValueError("Controls do not match the declared target interface")
    if any(value not in LEVELS[target][key] for key, value in controls.items()):
        raise ValueError("Undeclared layout parameter value")
    return render_layout_sites(target, before, controls)


def render_layout_sites(target, before, controls):
    """Shared literal-site renderer; public callers validate their own domain."""
    ast.parse(before)
    if controls == DEFAULTS[target]:
        return before  # exact original bytes, not a reformatted baseline
    c = controls
    replacements = []
    if target == "mirror":
        replacements = [("extension=3*maxmet_sep", "extension=%g*maxmet_sep" % c["route_extension_multiplier"], 2)]
    elif target == "cascode_mirror":
        shift = c["external_rail_offset_um"]
        # Explicit macro rail coordinates only; primitive/access coordinates stay fixed.
        for value in (70, 82, 94, -65):
            pattern = r"(?<![\w.])"+str(value)+r"(?![\w.])"
            count = len(re.findall(pattern, before))
            if count < (2 if value in (70, -65) else 1):
                raise ValueError("Cascode external rail site changed")
        # One substitution pass: a new rail coordinate can equal another old
        # coordinate (e.g.70+12==82), and must not be shifted a second time.
        before = re.sub(r"(?<![\w.])(?:-65|70|82|94)(?![\w.])",
            lambda match: "%g" % (int(match.group())+(shift if int(match.group()) > 0 else -shift)), before)
        replacements = [('segment("met4",(x,min(ys)),(x,max(ys)),.8)',
                         'segment("met4",(x,min(ys)),(x,max(ys)),%g)' % c["stack_width_um"], 1)]
    elif target == "source_follower":
        for old, value in [("70", c["output_collector_x_um"]), ("-45", c["ground_floor_y_um"])]:
            pattern = r"(?<![\w.])"+old+r"(?![\w.])"
            if len(re.findall(pattern, before)) < 2:
                raise ValueError("Follower macro route coordinate changed")
            before = re.sub(pattern, "%g" % value, before)
        replacements = [('line("met4",(70,min(q[1]for q in ends)),(70,max(q[1]for q in ends)),.8)'.replace("70", "%g" % c["output_collector_x_um"]),
            'line("met4",(%g,min(q[1]for q in ends)),(%g,max(q[1]for q in ends)),%g)' %
            (c["output_collector_x_um"], c["output_collector_x_um"], c["output_width_um"]), 1)]
    elif target == "stacked_switch":
        replacements = [('separation=24., signal_width=.8', 'separation=%g, signal_width=%g' %
                         (c["separation_um"], c["signal_width_um"]), 1)]
    elif target == "common_source_stage":
        replacements = [('pair_gap=36.,stage_gap=24.,output_width=.8',
            'pair_gap=%g,stage_gap=%g,output_width=%g' % (c["pair_gap_um"], c["stage_gap_um"], c["output_width_um"]), 1)]
    elif target == "resistive_diff":
        replacements = [('input_gap=48., row_gap=28., collector_width=.8',
            'input_gap=%g, row_gap=%g, collector_width=%g' % (c["input_gap_um"], c["row_gap_um"], c["collector_width_um"]), 1)]
    elif target == "five_t":
        replacements = [('escape_width, drop_width, trunk_width = .2, .6, .8',
            'escape_width, drop_width, trunk_width = .2, %g, %g' % (c["drop_width_um"], c["trunk_width_um"]), 1),
            ('cursor = snap(reference.xmax + 22)', 'cursor = snap(reference.xmax + %g)' % c["channel_gap_um"], 1),
            ('y = snap(top_edge + 8 + 3 * index)', 'y = snap(top_edge + 8 + %g * index)' % c["bus_pitch_um"], 1)]
    else:
        replacements = [('def segment(layer, first, last, width=.6, net=None):',
            'def segment(layer, first, last, width=%g, net=None):' % c["spine_width_um"], 1),
            ('width=.8,net=', 'width=%g,net=' % c["bus_width_um"], before.count('width=.8,net=')),
            ('destination=(130,10)', 'destination=(%g,10)' % c["capacitor_center_x_um"], 1),
            ('cap.xmax+4', 'cap.xmax+%g' % c["output_landing_clearance_um"], 1)]
    for old, new, count in replacements:
        if count < 1 or before.count(old) != count:
            raise ValueError("Declared layout control site changed: "+old)
        before = before.replace(old, new)
    ast.parse(before)
    return before


def objective(target):
    if target in ("five_t", "compact_miller"):
        return {"id": target+"_ugb_per_area_max", "metric": "ugb_per_area", "unit": "Hz/um2",
                "direction": "max", "corner_aggregation": "worst"}
    return {"id": target+"_area_min", "metric": "area", "unit": "um2",
            "direction": "min", "corner_aggregation": "worst"}


def generator_wrapper(target):
    """Frozen export transport: immutable sizing envelope, one output GDS."""
    if target not in TARGETS:
        raise ValueError("Unknown target")
    prefix = ('import argparse,json,shutil,tempfile\nfrom pathlib import Path\n'
        'p=argparse.ArgumentParser();p.add_argument("--configuration");p.add_argument("--output");a=p.parse_args()\n'
        'parameters=json.loads(Path(a.configuration).read_text())["parameters"]\n'
        'with tempfile.TemporaryDirectory(prefix="e3_build_",dir="/tmp") as temporary:\n'
        '    directory=Path(temporary)\n')
    if target in ("mirror", "five_t", "compact_miller"):
        call = '    from component_build import build\n    generated=directory/"candidate.gds"\n    build(parameters,generated)\n'
    else:
        call = '    from src.generators.'+target+' import build\n    generated=build(directory/"generated",parameters)\n'
    return prefix+call+'    shutil.copyfile(generated,Path(a.output))\n'


def compact_pdk(pdk):
    """Lossless grouped text of every effective rule, without repeated keys."""
    rows = {}
    for first, pairs in pdk["rules"].items():
        for second, rules in pairs.items():
            for field, value in rules.items():
                rows.setdefault(field, []).append(first+" "+second+" "+json.dumps(value, separators=(",", ":")))
    result = {key: copy.deepcopy(value) for key, value in pdk.items() if key != "rules"}
    result.update(rule_row="layer1 layer2 JSON_value; one rule per line", rules={key: "\n".join(values) for key, values in rows.items()})
    reconstructed = {}
    for field, values in result["rules"].items():
        for row in values.splitlines():
            first, second, value = row.split(" ", 2)
            reconstructed.setdefault(first, {}).setdefault(second, {})[field] = json.loads(value)
    if reconstructed != pdk["rules"]:
        raise ValueError("PDK table lost an effective rule")
    return result


def packet(e1_packet, task, source):
    """Model-facing editing contract; ancestry and all hidden rows stay backend-only."""
    result = copy.deepcopy(e1_packet)
    result["task_id"] = task["task_id"]
    result["goal"] = ("Edit the complete existing "+task["target"]+" layout program across its declared family. "
        "Preserve the independent circuit and every electrical constraint; optimize the feasible-first declared objective.")
    result["contract"] = task["configurations"][0]["contract"]
    # Same public fields as E1; no ancestry or private measurements.
    from src.e1_packets import PUBLIC_CONTRACT_FIELDS
    result["contract"] = {key: result["contract"][key] for key in PUBLIC_CONTRACT_FIELDS if key in result["contract"]}
    editable = task["editable_paths"][0]
    result["allowed_paths"] = [editable]
    result["visible_sources"] = {editable: source}
    docs = result["documents"]
    docs["PDK"] = compact_pdk(docs["PDK"])
    for key in ("stratum", "primitive_interface", "composition_boundary", "reuse_blocks", "knowledge_benefit", "routing_API"):
        docs.pop(key, None)
    docs["status"] = "DRAFT_E3_COMPLETE_SOURCE_EDITING_NOT_ADMITTED"
    docs["family_relationship"] = {"shared_domain_id": task["shared_domain_id"],
        "note": "Three distinct complete editing programs share one target logic and the same fixed 1+8+16 role assignment. States/configurations do not increase independent target counts."}
    docs["API"] = "The complete editable module and its existing frozen primitive/routing dependencies are mounted. Only the declared full module may be patched. The frozen generator.py exports the named actual top."
    docs["patch_format"] = "Ordinary unified diff for a/"+editable+" and b/"+editable+"; preserve accurate hunk counts and final newline."
    docs["CLI"] = "Frozen generator.py --configuration PATH --output PATH receives the immutable per-z sizing dictionary and exports candidate.gds; edit the full declared module, not the wrapper or N(z)."
    docs["parameter_baseline"] = {"kind": "predeclared_layout_literal_sites", "levels": LEVELS[task["target"]],
        "current_values": task["parameter_controls"], "scope": "P changes only these layout sites. Code editing may express additional layout changes; all device dimensions and electrical intent are immutable."}
    docs["objective_definition"] = ("Actual full recursive GDS bbox area in um2. For OTA, each corner's measured UGB is divided by that same area and the minimum corner value is maximized. Feasibility requires all original electrical limits; unknown analyses are never feasible.")
    # Repeated interface prose is not physical/source information. Keep the
    # complete rules, graph, application values, all nine sizes and full module.
    for key in ("geometry_units", "fidelity", "API", "family_relationship", "objective_definition"):
        docs.pop(key, None)
    docs["history_policy"] = {"version": "current_source_and_feedback_v1", "full_current_source": True,
        "all_feedback_and_errors_retained": True}
    docs["CLI"] = "Frozen generator.py reads configuration.parameters, builds in /tmp, exports only candidate.gds; edit only allowed_paths."
    application = docs.get("application", {})
    if application.get("corners") == result["contract"]["required_corners"]:
        application.pop("corners")
    if task["target"] in ("five_t", "compact_miller") and "analysis_coverage" in application:
        analyses = result["contract"]["analysis_contracts"]
        duplicate = {"OP_rows": analyses["op"]["expected_rows"], "AC_rows": analyses["ac"]["points"],
            "AC_Hz": [analyses["ac"]["start"], analyses["ac"]["end"]],
            "transient_s": [analyses["tran"]["start"], analyses["tran"]["end"]],
            "DC_points": analyses["dc"]["points"], "DC_V": [analyses["dc"]["start"], analyses["dc"]["end"]]}
        if application["analysis_coverage"] != duplicate:
            raise ValueError("Application coverage differs from the full physical analysis contract")
        application.pop("analysis_coverage")
    return result
