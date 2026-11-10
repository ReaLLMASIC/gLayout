"""Net-aware interdigitized rows: one rail per net, no shorts left to draw.

Needs a PDK (gf180). Run with pytest, or directly: ``python tests/test_netaware_interdigitized.py``.
"""
import os

os.environ.setdefault("GLAYOUT_TABLES", "0")

from glayout import gf180 as pdk  # noqa: E402
from glayout.backend import Component  # noqa: E402
from glayout.cells.elementary.current_mirror.current_mirror import MIRROR_NETS, current_mirror  # noqa: E402
from glayout.placement.two_transistor_interdigitized import (  # noqa: E402
    interdigitized_nets, two_nfet_interdigitized, two_tran_interdigitized_netlist,
)
from glayout.routing.smart_route import smart_route  # noqa: E402


def test_default_is_six_distinct_nets():
    nets = interdigitized_nets()
    assert len(set(nets.values())) == 6


def test_shared_source_drain_and_gate_rails():
    row = two_nfet_interdigitized(pdk, numcols=2, nets=MIRROR_NETS, with_tie=False, with_substrate_tap=False)
    assert row.info["sd_rails"] == ["VSS", "VREF", "VOUT"]          # three rails, not four
    assert row.info["diode_ties"] == ["VREF"]                       # the one real connection
    for term in ("source", "gate"):
        a, b = row.ports[f"A_{term}_W"], row.ports[f"B_{term}_W"]
        assert tuple(a.center) == tuple(b.center)                   # aliases of one rail


def test_rail_pitch_is_uniform():
    row = two_nfet_interdigitized(pdk, numcols=1, with_tie=False, with_substrate_tap=False)
    ys = sorted(row.ports[f"{t}_W"].center[1] for t in ("A_source", "A_drain", "B_source", "B_drain"))
    gaps = [b - a for a, b in zip(ys, ys[1:])]
    assert max(gaps) - min(gaps) <= 2 * pdk.grid_size + 1e-9      # one pitch, up to grid snapping


def test_rail_order():
    row = two_nfet_interdigitized(pdk, numcols=2, nets=MIRROR_NETS, rail_order=["VREF", "VSS", "VOUT"],
                                  with_tie=False, with_substrate_tap=False)
    assert row.info["sd_rails"] == ["VREF", "VSS", "VOUT"]
    y = {t: row.ports[f"{t}_W"].center[1] for t in ("A_drain", "A_source", "B_drain")}
    assert y["A_drain"] < y["A_source"] < y["B_drain"]


def test_netlist_pins_merge_with_nets():
    nl = two_tran_interdigitized_netlist(pdk, 3, None, 1, 2, True, nets=MIRROR_NETS)
    assert nl.nodes == ["VDD1", "VDD2", "VSS1", "VB"]
    text = nl.source_netlist
    assert "XA VDD1 VDD1 VSS1 VB" in text and "XB VDD2 VDD1 VSS1 VB" in text


def test_smart_route_skips_terminals_already_joined():
    top = Component("t")
    row = top << two_nfet_interdigitized(pdk, numcols=2, nets=MIRROR_NETS, with_substrate_tap=False)
    top.add_ports(row.get_ports_list(), prefix="cm_")
    # both backends wrap a gdstk.Cell; the gdstk backend's Component has no get_polygons()
    r = smart_route(pdk, top.ports["cm_A_source_W"], top.ports["cm_B_source_W"], row, top)
    assert len(r._cell.get_polygons()) == 0
    r = smart_route(pdk, top.ports["cm_A_gate_W"], top.ports["cm_A_drain_W"], row, top)
    assert len(r._cell.get_polygons()) == 0                         # the diode tie is already drawn


def test_current_mirror_has_no_shorts():
    cm = current_mirror(pdk, numcols=2)
    assert not any(p.startswith("purposegndports") for p in cm.ports)
    assert cm.info["netlist"] is not None


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)} passed")
