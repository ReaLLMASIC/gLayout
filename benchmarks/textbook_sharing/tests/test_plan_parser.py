"""The restricted program format: accepted constructs expand into SharingPlans, anything else is rejected."""
import pytest
from textbook_sharing.llm.plan_parser import parse_program, to_sharing_plan, ParseError
from textbook_sharing import paths
from textbook_sharing.run_case import load_case_dir
from textbook_sharing.circuits import CIRCUITS
from textbook_sharing.layout import device_specs, sharing_groups
from textbook_sharing.pdk import pdk_obj

PROGRAM = '''plans = {
 0: axis_plan(arrangement="block", orientation="seek_SD", diffusion="all_legal", gate="per_device",
              strap_start="bottom", contact_end="left"),
 1: SharingPlan(finger_order=[("M4",0),("M4",1),("M4",2),("M4",3),("M5",0),("M5",1),("M5",2),("M5",3)],
                orientations=["SD","DS"]*4, diffusion_joins=[True]*7,
                gate_groups=[GateGroup(fingers=tuple(range(8)), side="top", pad_end="right")])}'''


def groups():
    case, _ = load_case_dir(paths.CASES / "C08" / "sky130" / "sW1_sL1")
    return sharing_groups(device_specs(CIRCUITS["C08"], case.sizing))


def test_program_expands_to_plans():
    g = groups(); pdk = pdk_obj("sky130"); calls = parse_program(PROGRAM)
    p0 = to_sharing_plan(calls[0], g[0], pdk); p1 = to_sharing_plan(calls[1], g[1], pdk)
    assert all(p0.diffusion_joins) and p0.orientations[16] == "DS"       # M3 turned so that net23 meets net23
    assert p1.summary()["cross_device_gate_groups"] == 1 and p1.summary()["islands"] == 1


@pytest.mark.parametrize("code", ["import os\nplans = {}", "plans = {0: __import__('os')}", "x = 1"])
def test_anything_else_is_rejected(code):
    with pytest.raises(ParseError):
        parse_program(code)
