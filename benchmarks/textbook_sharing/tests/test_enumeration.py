"""Six-axis enumeration of the five-transistor OTA at its nominal size (SKY130): 256 raw tuples per group, 10 distinct
legal plans for the NMOS group and 101 for the PMOS group, i.e. 1010 plans for the circuit."""
from glayout.sharing import group_candidates, named_plans, RAW_PER_GROUP
from textbook_sharing import paths
from textbook_sharing.run_case import load_case_dir
from textbook_sharing.circuits import CIRCUITS
from textbook_sharing.layout import device_specs, sharing_groups
from textbook_sharing.pdk import pdk_obj


def test_ota_plan_space():
    case, _ = load_case_dir(paths.CASES / "C08" / "sky130" / "sW1_sL1")
    groups = sharing_groups(device_specs(CIRCUITS["C08"], case.sizing))
    assert [[d.logical_id for d in g] for g in groups] == [["M1", "M2", "M3"], ["M4", "M5"]]
    pdk = pdk_obj("sky130")
    counts = [group_candidates(pdk, g)["counts"] for g in groups]
    assert all(c["raw"] == RAW_PER_GROUP == 256 for c in counts)
    assert [c["unique"] for c in counts] == [10, 101]
    named = named_plans(pdk, groups[0])
    assert named["gate_only"] is None and named["combined"] is None   # M1, M2, M3 have three different gate nets
