"""Cells built from one common-centroid, diffusion-shared finger row.

``finger_sequence_cell`` is the generic form: give it devices (nets + finger
counts) and it searches for the sequence, draws the row, adds the well tie
ring, the well, gf180 pin labels and the LVS reference netlist.
``cc_current_mirror`` and ``cc_diff_pair`` are the two common-source cases
from the notes (§2.4), where common centroid and shared diffusion agree.
"""
from __future__ import annotations

import os
from typing import Literal, Optional, Sequence, Union

from glayout.backend import Component, rectangle
from glayout.pdk.mappedpdk import MappedPDK
from glayout.placement.finger_sequence.layout import finger_sequence_netlist, finger_sequence_row
from glayout.placement.finger_sequence.model import DeviceSpec, FingerSequence
from glayout.placement.finger_sequence.search import SequenceWeights, search_sequences
from glayout.primitives.guardring import tapring
from glayout.routing.straight_route import straight_route
from glayout.util.comp_utils import align_comp_to_port
from glayout.util.port_utils import add_ports_perimeter
from glayout.util.process_table import ProcessTable

DeviceLike = Union[DeviceSpec, dict]


def _specs(devices: Sequence[DeviceLike]) -> list[DeviceSpec]:
    return [d if isinstance(d, DeviceSpec) else DeviceSpec(**d) for d in devices]


def _label(pdk: MappedPDK, top: Component, text: str, port, alignment, size: float = 0.27) -> None:
    pin = rectangle(layer=pdk.get_glayer("met2_pin"), size=(size, size), centered=True).copy()
    pin.add_label(text=text, layer=pdk.get_glayer("met2_label"))
    top.add(align_comp_to_port(pin, port, alignment=alignment))


def finger_sequence_cell(
    pdk: MappedPDK,
    devices: Sequence[DeviceLike],
    sequence: Optional[str] = None,
    device: Literal["nfet", "pfet"] = "nfet",
    width: float = 3,
    length: Optional[float] = None,
    with_dummy: Union[bool, tuple[bool, bool]] = True,
    with_tie: bool = True,
    tie_layers: tuple[str, str] = ("met2", "met1"),
    rmult: Optional[int] = None,
    pins: Optional[Sequence[str]] = None,
    circuit_name: str = "FSCELL",
    weights: Optional[SequenceWeights] = None,
    name: str = "finger_sequence_cell",
    bulk_net: Optional[str] = None,
) -> Component:
    """Generic one-row cell. ``sequence`` (e.g. ``"A+ A- B+ B-"``) skips the search.

    ``pins`` lists the external nets (default: every net plus ``B``, the bulk).
    ``bulk_net``: a source/drain net that is also the bulk (e.g. the VSS source rail of an NMOS
    mirror). Its rail is tied to the tie ring inside the cell on metal 2 (along the rail to the
    ring's side, then down to the ring's south side), on a side no gate/S-D tie uses, so
    the net and the bulk are one pin (``bulk_net``, reachable from every side of the ring) and one
    netlist node; ``B`` is dropped. Without a free side the cell keeps ``B`` separate
    (``info["bulk_tied"]`` says which happened).
    """
    specs = _specs(devices)
    if isinstance(with_dummy, list):
        with_dummy = tuple(with_dummy)
    nets = []
    for d in specs:
        for n in (d.drain, d.gate, d.source):
            if n not in nets:
                nets.append(n)
    pins = list(pins) if pins else nets + ["B"]
    with ProcessTable(f"{name}: cell", f"{device}, pins {pins}") as pt:
        with pt.stage("Sequence") as st:
            if sequence is None:
                seq = search_sequences(specs, weights=weights, title=f"{name}: sequence search").best.sequence
                st.detail(f"searched: {seq.compact()}")
            else:
                seq = FingerSequence.from_compact({d.name: d for d in specs}, sequence)
                st.detail(f"given: {seq.compact()}")
        with pt.stage("Row") as st:
            row = finger_sequence_row(pdk, seq, device=device, width=width, length=length, with_dummy=with_dummy,
                                      rmult=rmult, title=f"{name}: row")
            st.detail(f"{row.xsize:.2f}x{row.ysize:.2f}µm, centroid error {row.info['centroid_error_um']}µm")
        # the final name goes on the flattened cell; gdsfactory suffixes "$1"
        # to any name assigned twice, which hides the cell from magic and LVS
        top = Component(f"{name}_hier")
        rref = top << row
        top.add_ports(rref.get_ports_list(), prefix="row_")
        tap_layer = "p+s/d" if device == "nfet" else "n+s/d"
        well = "pwell" if device == "nfet" else "nwell"
        with pt.stage("Tie ring") as st:
            if with_tie:
                tap_sep = max(float(pdk.util_max_metal_seperation()),
                              float(pdk.get_grule("active_diff", "active_tap")["min_separation"]))
                tap_sep += float(pdk.get_grule(tap_layer, "active_tap")["min_enclosure"])
                enc = (2 * (tap_sep + row.xmax), 2 * (tap_sep + row.ymax))
                tie = top << tapring(pdk, enclosed_rectangle=enc, sdlayer=tap_layer,
                                     horizontal_glayer=tie_layers[0], vertical_glayer=tie_layers[1])
                top.add_ports(tie.get_ports_list(), prefix="welltie_")
                tied = []
                for side, ring in (("L", "W"), ("R", "E")):
                    p = f"row_dummy_{side}_gsdcon_top_met_{ring}"
                    if p in top.ports:
                        top << straight_route(pdk, top.ports[p], top.ports[f"welltie_{ring}_top_met_{ring}"], glayer2="met1")
                        tied.append(side)
                st.detail(f"enclosing {enc[0]:.2f}x{enc[1]:.2f}µm, dummies tied {tied or 'none'}")
            else:
                st.status = "skip"
        with pt.stage("Bulk tie") as st:
            bulk_tied = False
            if bulk_net is not None and with_tie:
                used = set(row.info.get("tie_sides", {}).values())
                side = next((s for s in ("E", "W") if s not in used and f"row_{bulk_net}_sd_{s}" in top.ports), None)
                if side is not None:
                    # all on metal 2, no via: the rails and the ring's N/S sides are metal 2. Along the rail
                    # to the middle of the ring's side, then down over that side to the ring's south side.
                    # The drop lies over the ring, outside every rail end, and this side carries no
                    # gate/S-D tie, so it crosses no other net.
                    inner = "W" if side == "E" else "E"
                    rail = top.ports[f"row_{bulk_net}_sd_{side}"]
                    bar_x = (top.ports[f"welltie_{side}_top_met_{side}"].center[0]
                             + top.ports[f"welltie_{side}_top_met_{inner}"].center[0]) / 2
                    south_y = (top.ports["welltie_S_top_met_S"].center[1] + top.ports["welltie_S_top_met_N"].center[1]) / 2
                    h, (xr, yr) = rail.width, rail.center
                    if side == "E":
                        hx0, hx1 = xr - h, bar_x + h / 2           # overlap the rail end by a full rail height
                    else:
                        hx0, hx1 = bar_x - h / 2, xr + h
                    # nearest grid point, not snap_to_2xgrid: that rounds up to 2x the grid and moved a
                    # 5 nm rail edge, leaving a sliver gap beside the rail (sky130 m1.2)
                    grid = pdk.grid_size
                    for x0, y0, x1, y1 in ((hx0, yr - h / 2, hx1, yr + h / 2),
                                           (bar_x - h / 2, south_y - h / 2, bar_x + h / 2, yr + h / 2)):
                        x0, y0, x1, y1 = (round(round(v / grid) * grid, 6) for v in (x0, y0, x1, y1))
                        r = top << rectangle(size=(x1 - x0, y1 - y0), layer=pdk.get_glayer("met2"))
                        r.move((x0, y0))
                    bulk_tied = True
                    pins = [p for p in pins if p != "B"]
                    if bulk_net not in pins:
                        pins.append(bulk_net)
                    st.detail(f"{bulk_net} rail tied to the ring on {side}")
                else:
                    st.warn(f"no free side to tie {bulk_net} to the ring; bulk stays a separate pin")
            if bulk_net is not None and not bulk_tied and "B" not in pins:
                pins.append("B")
            if bulk_net is None:
                st.status = "skip"
            bulk = bulk_net if bulk_tied else "B"
        with pt.stage("Well") as st:
            top.add_padding(layers=(pdk.get_glayer(well),), default=pdk.get_grule(well, "active_tap")["min_enclosure"])
            top = add_ports_perimeter(top, layer=pdk.get_glayer(well), prefix="well_")
            st.detail(well)
        with pt.stage("Pin labels") as st:
            if pdk.name.lower() == "gf180" and with_tie and not os.environ.get("GLAYOUT_NO_PIN_LABELS"):
                placed = []
                for net in pins:
                    if net == "B":
                        _label(pdk, top, "B", top.ports["welltie_S_top_met_S"], ("c", "c"), size=0.5)
                    elif f"row_{net}_sd_N" in top.ports:
                        _label(pdk, top, net, top.ports[f"row_{net}_sd_N"], ("c", "b"))
                    elif f"row_{net}_gate_S" in top.ports:
                        _label(pdk, top, net, top.ports[f"row_{net}_gate_S"], ("c", "t"))
                    else:
                        st.warn(f"no rail for pin {net}")
                        continue
                    placed.append(net)
                st.detail(f"{placed}")
            else:
                st.status = "skip"
                st.detail("gf180 only (klayout LVS needs named labels)")
        with pt.stage("Netlist") as st:
            # dummies sit on the bulk when tied to the ring, else on a local net
            dummy_net = bulk if with_tie else "DUM"
            nl = finger_sequence_netlist(pdk, seq, device, width, length, with_dummy=with_dummy, bulk=bulk,
                                         dummy_net=dummy_net, circuit_name=circuit_name, pins=pins)
            top.info["netlist"] = nl
            st.detail(f"{circuit_name}({', '.join(pins)})")
        with pt.stage("Flatten") as st:
            # magic types devices per GDS cell: a pfet row in a subcell, with the
            # nwell drawn in the parent, reads as p+ substrate taps (P-Ohmic)
            top = top.flatten()
            top.name = name
            top.info["netlist"] = nl
            st.detail(f"{len(top.get_polygons())} polygons")
        pt.result("sequence", seq.labels())
        pt.result("size_um", f"{top.xsize:.2f}x{top.ysize:.2f}")
    top.info["sequence"] = seq.compact()
    top.info["diagram"] = seq.diagram()
    top.info["centroid_error_um"] = row.info["centroid_error_um"]
    # per device, x relative to the row centre, which is the cell's origin (the ring and well are centred on it)
    top.info["centroids_um"] = dict(row.info["centroids_um"])
    top.info["bulk_tied"] = bulk_tied
    # external pins for the floorplanner: both ends of each net's rail; the
    # bulk is reachable from every side of the tie ring
    pin_ports = {}
    for net in pins:
        if net == "B" or (bulk_tied and net == bulk_net):
            ring = [f"welltie_{s}_top_met_{s}" for s in "NESW"] if with_tie else [f"well_{s}" for s in "NESW"]
            pin_ports[net] = [p for p in ring if p in top.ports]
            continue
        for kind in ("sd", "gate"):
            ends = [f"row_{net}_{kind}_W", f"row_{net}_{kind}_E"]
            if all(p in top.ports for p in ends):
                pin_ports[net] = ends
                break
    top.info["pins"] = pin_ports
    return top


def cc_current_mirror(
    pdk: MappedPDK,
    fingers: int = 4,
    ratio: int = 1,
    device: Literal["nfet", "pfet"] = "nfet",
    width: float = 3,
    length: Optional[float] = None,
    with_dummy: Union[bool, tuple[bool, bool]] = True,
    with_tie: bool = True,
    sequence: Optional[str] = None,
    **kwargs,
) -> Component:
    """Common-centroid current mirror in one diffusion-shared row.

    A is the diode-connected reference (``fingers`` fingers), B the output
    (``fingers * ratio``). Pins: VREF, VOUT, VSS, B — the same as ``current_mirror``.
    """
    devices = [DeviceSpec("A", "VSS", "VREF", "VREF", fingers),
               DeviceSpec("B", "VSS", "VOUT", "VREF", fingers * ratio)]
    return finger_sequence_cell(pdk, devices, sequence=sequence, device=device, width=width, length=length,
                                with_dummy=with_dummy, with_tie=with_tie, pins=["VREF", "VOUT", "VSS", "B"],
                                circuit_name="CC_CMIRROR", name=f"cc_cmirror_{device}", **kwargs)


def cc_diff_pair(
    pdk: MappedPDK,
    fingers: int = 4,
    device: Literal["nfet", "pfet"] = "nfet",
    width: float = 3,
    length: Optional[float] = None,
    with_dummy: Union[bool, tuple[bool, bool]] = True,
    with_tie: bool = True,
    sequence: Optional[str] = None,
    **kwargs,
) -> Component:
    """Common-centroid differential pair in one row with a shared tail diffusion.

    Pins: VINP, VINN, VOUT1 (A drain), VOUT2 (B drain), VTAIL, B.
    """
    devices = [DeviceSpec("A", "VTAIL", "VOUT1", "VINP", fingers),
               DeviceSpec("B", "VTAIL", "VOUT2", "VINN", fingers)]
    return finger_sequence_cell(pdk, devices, sequence=sequence, device=device, width=width, length=length,
                                with_dummy=with_dummy, with_tie=with_tie,
                                pins=["VINP", "VINN", "VOUT1", "VOUT2", "VTAIL", "B"],
                                circuit_name="CC_DIFFPAIR", name=f"cc_diffpair_{device}", **kwargs)
