"""SharingPlan legality, construction and the sharing evidence recomputed from the drawn geometry (the PMOS mirror
M4/M5 of the five-transistor OTA, SKY130, nominal size)."""
from glayout.sharing import DeviceSpec, SharingPlan, FingerRef, GateGroup, validate_plan, build_mos_group, rules_for, independent_plan
from textbook_sharing.pdk import pdk_obj

M4 = DeviceSpec("M4", "pfet", d="net22", g="net22", s="VDD", b="VDD", width_total=2.0, length=0.3, nf=4)
M5 = DeviceSpec("M5", "pfet", d="VOUT1", g="net22", s="VDD", b="VDD", width_total=2.0, length=0.3, nf=4)


def shared_plan():
    return SharingPlan(finger_order=[FingerRef("M4", k) for k in range(4)] + [FingerRef("M5", k) for k in range(4)],
                       orientations=["SD", "DS"] * 4, diffusion_joins=[True] * 7,
                       gate_groups=[GateGroup(tuple(range(8)), "top", "right")])


def test_independent_plan_is_legal():
    pdk = pdk_obj("sky130")
    assert validate_plan(rules_for(pdk), [M4, M5], independent_plan([M4, M5])).ok


def test_join_across_different_nets_is_rejected():
    pdk = pdk_obj("sky130"); plan = shared_plan()
    plan.orientations[4] = "DS"                      # M5's first finger now shows its drain (VOUT1) to M4's source (VDD)
    rep = validate_plan(rules_for(pdk), [M4, M5], plan)
    assert not rep.ok and rep.errors[0]["code"] == "join_net_mismatch"


def test_shared_plan_builds_and_evidence_is_recomputed():
    pdk = pdk_obj("sky130")
    res = build_mos_group(pdk, [M4, M5], plan=shared_plan(), name="test_pmos_mirror")
    ev = res.physical_sharing_evidence
    assert ev["active_islands"] == 1                         # VDD shared at the M4|M5 boundary
    assert ev["n_cross_device_shared_nodes"] == 1
    assert ev["n_cross_device_gate_conductors"] == 1         # one net22 strap for both gates
    assert ev["consistency"]["cross_device_nodes_found"] == ev["consistency"]["cross_device_joins_requested"]
