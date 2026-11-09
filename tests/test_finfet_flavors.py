"""Threshold flavor coverage against independently extracted physical masks."""

import pytest
import gdstk
from glayout import asap7, nmos, pmos
from glayout.backend import Component
from glayout.spice import Netlist
from glayout.pdk.asap7_mapped.verification import drc, lvs
from asap7_pins import add_pins

FLAVORS = {"rvt": None, "lvt": 98, "slvt": 97, "sram": 110}


def labelled(builder, **kwargs):
    c = builder(asap7, **kwargs)
    return add_pins(c, "nmos_narrow" if builder is nmos else "pmos_narrow", asap7)


def write_device(c, tmp_path, name="device"):
    gds, spice = tmp_path / (name + ".gds"), tmp_path / (name + ".spice")
    c.write_gds(gds)
    spice.write_text(c.info["netlist"].generate_netlist())
    return gds, spice


@pytest.mark.parametrize("builder,polarity", [(nmos, "nmos"), (pmos, "pmos")])
@pytest.mark.parametrize("vt", FLAVORS)
@pytest.mark.parametrize("nfin,fingers,multipliers", [(1, 1, 1), (3, 2, 2)])
def test_all_flavors_extract(
    tmp_path, builder, polarity, vt, nfin, fingers, multipliers
):
    c = labelled(builder, vt=vt, nfin=nfin, fingers=fingers, multipliers=multipliers)
    gds, spice = write_device(c, tmp_path)
    layers = {p.layer for cell in gdstk.read_gds(gds).cells for p in cell.polygons}
    assert layers.intersection({97, 98, 110}) == (
        {FLAVORS[vt]} if FLAVORS[vt] else set()
    )
    assert c.info["finfet"]["vt"] == vt
    assert c.info["finfet"]["model"] == polarity + "_" + vt
    assert polarity + "_" + vt in spice.read_text()
    assert drc(gds) == {}
    report = tmp_path / "lvs"
    assert lvs(gds, spice, report)["match"]
    assert polarity + "_" + vt in (report / "extracted.txt").read_text()


@pytest.mark.parametrize("builder", [nmos, pmos])
@pytest.mark.parametrize("vt", ["lvt", "slvt", "sram"])
def test_removed_marker_and_wrong_model_fail_lvs(tmp_path, builder, vt):
    c = labelled(builder, nfin=3, vt=vt)
    gds, spice = write_device(c, tmp_path)
    assert lvs(gds, spice, tmp_path / "good")["match"]
    text = spice.read_text()
    spice.write_text(text.replace("_" + vt, "_rvt"))
    assert not lvs(gds, spice, tmp_path / "wrong_model")["match"]
    spice.write_text(text)
    lib = gdstk.read_gds(gds)
    for cell in lib.cells:
        for p in list(cell.polygons):
            if p.layer == FLAVORS[vt]:
                cell.remove(p)
    lib.write_gds(tmp_path / "unmarked.gds")
    assert drc(tmp_path / "unmarked.gds") == {}
    assert not lvs(tmp_path / "unmarked.gds", spice, tmp_path / "missing_marker")[
        "match"
    ]


def test_conflicting_and_partial_markers_rejected(tmp_path):
    c = labelled(nmos, vt="lvt", nfin=3)
    gds, spice = write_device(c, tmp_path)
    lib = gdstk.read_gds(gds)
    for cell in lib.cells:
        for p in list(cell.polygons):
            if p.layer == 98:
                q = p.copy()
                q.layer = 97
                cell.add(q)
    overlap = tmp_path / "overlap.gds"
    lib.write_gds(overlap)
    assert "VT.AUX.2" in drc(overlap)
    with pytest.raises(ValueError, match="overlapping threshold"):
        lvs(overlap, spice, tmp_path / "overlap")
    lib = gdstk.read_gds(gds)
    for cell in lib.cells:
        for p in list(cell.polygons):
            if p.layer == 98:
                x0, y0 = p.bounding_box()[0]
                x1, y1 = p.bounding_box()[1]
                cell.remove(p)
                cell.add(gdstk.rectangle(((x0 + x1) / 2, y0), (x1, y1), layer=98))
    partial = tmp_path / "partial.gds"
    lib.write_gds(partial)
    assert "LVT.ACTIVE.EN" in drc(partial)
    with pytest.raises(ValueError, match="partially covers"):
        lvs(partial, spice, tmp_path / "partial")


def test_mixed_flavors_in_one_hierarchy(tmp_path):
    top = Component("all_flavors")
    nl = Netlist(
        circuit_name="ALL_FLAVORS",
        nodes=["B"] + [f"{p}{i}" for i in range(8) for p in "DGS"],
    )
    i = 0
    for builder in (nmos, pmos):
        for vt in FLAVORS:
            c = labelled(builder, vt=vt, nfin=3, fingers=2)
            for label in c._cell.labels:
                if label.text in "DGS":
                    label.text += str(i)
            ref = top << c
            ref.movex(i * 6.048)
            # Child labels name local nets; expose actual parent-level terminals.
            for label in c._cell.labels:
                top.add_label(
                    label.text,
                    position=(
                        label.origin[0] + ref.origin[0],
                        label.origin[1] + ref.origin[1],
                    ),
                    layer=(label.layer, label.texttype),
                )
            nl.connect_netlist(
                c.info["netlist"],
                [(p, f"{p}{i}") for p in "DGS"] + [("B", "B"), ("DUM", "B")],
            )
            i += 1
    top.info["netlist"] = nl
    gds, spice = write_device(top, tmp_path)
    assert drc(gds) == {}
    assert lvs(gds, spice, tmp_path / "lvs")["match"]
    extracted = (tmp_path / "lvs/extracted.txt").read_text()
    for polarity in ("nmos", "pmos"):
        for vt in FLAVORS:
            assert polarity + "_" + vt in extracted


def test_selection_does_not_mutate_default_and_rejects_invalid_flavors():
    original = asap7.models.copy()
    selected = asap7.with_finfet_flavor("SLVT")
    assert selected.models == {"nfet": "nmos_slvt", "pfet": "pmos_slvt"}
    assert selected.finfet_flavor == "slvt"
    assert nmos(selected, nfin=1).info["finfet"]["vt"] == "slvt"
    assert pmos(asap7, nfin=1, vt="sram").info["finfet"]["model"] == "pmos_sram"
    assert asap7.models == original and asap7.finfet_flavor == "rvt"
    for bad in ("hvt", "", None, 3):
        with pytest.raises(ValueError, match="unsupported FinFET flavor"):
            asap7.with_finfet_flavor(bad)
    from glayout.pdk.mappedpdk import MappedPDK

    planar = MappedPDK(
        name="planar", glayers={}, grules={}, pdk_files={}, valid_bjt_sizes={}
    )
    with pytest.raises(ValueError, match="requires a FinFET"):
        nmos(planar, vt="lvt")


@pytest.mark.parametrize("vt", FLAVORS)
def test_original_mirror_accepts_selected_pdk(tmp_path, vt):
    from glayout.cells.elementary import current_mirror

    selected = asap7.with_finfet_flavor(vt)
    c = current_mirror(selected, width=0.081, numcols=2)
    c = add_pins(c, "current_mirror_nfet", selected)
    assert "fet_A_drain_N" in c.ports
    gds, spice = write_device(c, tmp_path)
    assert "nmos_" + vt in spice.read_text()
    assert drc(gds) == {}
    assert lvs(gds, spice, tmp_path / "lvs")["match"]
