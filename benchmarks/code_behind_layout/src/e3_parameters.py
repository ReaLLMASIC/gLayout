"""Prospective stronger P family over the same existing layout knobs.

The wider ranges are declared before new physical qualification. Physically
bad endpoints remain valid parameter proposals and consume real evaluations.
No device sizing, intended graph, or simulation setting can be changed here.
"""
from decimal import Decimal
import math

from src.e3_task_prepare import LEVELS, render_layout_sites

BOUNDS = {
    "mirror": {"route_extension_multiplier": [.5, 12]},
    "cascode_mirror": {"external_rail_offset_um": [-20, 60]},
    "source_follower": {"output_collector_x_um": [40, 140], "ground_floor_y_um": [-80, -25]},
    "stacked_switch": {"separation_um": [8, 72]},
    "common_source_stage": {"pair_gap_um": [12, 90], "stage_gap_um": [8, 60]},
    "resistive_diff": {"input_gap_um": [18, 108], "row_gap_um": [12, 66]},
    "five_t": {"channel_gap_um": [8, 60], "bus_pitch_um": [1.2, 8]},
    "compact_miller": {"capacitor_center_x_um": [90, 190], "output_landing_clearance_um": [1, 16]},
}
WIDTH_LAYERS = {
    "cascode_mirror": {"stack_width_um": ["met4"]},
    "source_follower": {"output_width_um": ["met4"]},
    "stacked_switch": {"signal_width_um": ["met3", "met4"]},
    "common_source_stage": {"output_width_um": ["met3", "met4"]},
    "resistive_diff": {"collector_width_um": ["met4", "met5"]},
    "five_t": {"drop_width_um": ["met3"], "trunk_width_um": ["met4"]},
    "compact_miller": {"spine_width_um": ["met3"], "bus_width_um": ["met4", "met5"]},
}


def interface(target, pdk):
    """Bind macro width minima to the complete actual frozen PDK rule table."""
    if target not in BOUNDS:
        raise ValueError("Unknown target")
    parameters = {key: {"min": bounds[0], "max": bounds[1],
        "step": .05 if key == "route_extension_multiplier" else .005,
        "unit": "1" if key == "route_extension_multiplier" else "um"} for key, bounds in BOUNDS[target].items()}
    for key, layers in WIDTH_LAYERS.get(target, {}).items():
        rules = [{"layer": layer, "rule": "min_width", "value": pdk["rules"][layer][layer]["min_width"]} for layer in layers]
        minimum = max(rule["value"] for rule in rules)
        parameters[key] = {"min": minimum, "max": 2.5, "step": .005, "unit": "um", "bound_rules": rules}
    if set(parameters) != set(LEVELS[target]):
        raise ValueError("Expanded P interface must expose every original finite-family knob")
    return {"version": "prospective_expanded_layout_grid_v1", "parameters": parameters,
        "finite_levels_sensitivity": LEVELS[target], "geometry_grid_um": .005,
        "cascode_offset_binding": "All original external rail coordinates70/82/94 and-65; includes IREF right endpoint70" if target == "cascode_mirror" else None,
        "source_sizing_or_bench_edits": False,
        "endpoint_policy": "No physical-result filtering; DRC/LVS/specification failures remain evaluated parameter outcomes"}


def render(target, original_source, controls, pdk):
    domain = interface(target, pdk)["parameters"]
    if set(controls) != set(domain):
        raise ValueError("Supply every declared existing layout knob")
    values = {}
    for key, value in controls.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Parameter must be finite numeric")
        definition = domain[key]
        if not definition["min"] <= value <= definition["max"]:
            raise ValueError("Parameter lies outside its prospectively declared range")
        number, step = Decimal(str(value)), Decimal(str(definition["step"]))
        if number % step:
            raise ValueError("Parameter must lie on the declared common physical grid")
        values[key] = value
    return render_layout_sites(target, original_source, values)
