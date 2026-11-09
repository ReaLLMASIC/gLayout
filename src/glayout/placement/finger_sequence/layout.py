"""Draw a FingerSequence as one row of fingers with net-based rails.

Unlike ``macro_two_transistor_interdigitized``, which builds every A/B column
as its own multiplier with its own diffusion, this generator draws each
*unbroken segment* of the sequence as one diffusion strip, so fingers of
different devices share a source/drain region wherever the sequence allows.

Routing is assigned by net, not by device:

- every source/drain net gets one horizontal rail above the row (lowest rail
  nearest the diffusion); each contact rises on met1 to its net's rail;
- every gate net gets one rail below the row; consecutive fingers on the same
  gate net in a segment share one poly-to-metal bar;
- a net that has both a source/drain rail and a gate rail (a diode
  connection) is tied with a C route at the row edge.

The geometry reuses the fet primitive's finger macro and copies the rail and
gate-bar spacing of ``multiplier`` / the interdigitized macro, which are
DRC-proven on sky130 and gf180.
"""
from __future__ import annotations

from typing import Literal, Optional, Sequence, Union

import glayout.primitives.fet as _fet
from glayout.backend import Component, rectangle
from glayout.pdk.mappedpdk import MappedPDK
from glayout.placement.finger_sequence.model import FingerSequence
from glayout.primitives.via_gen import via_array, via_stack
from glayout.routing.L_route import L_route
from glayout.routing.c_route import c_route
from glayout.routing.straight_route import straight_route
from glayout.spice.netlist import Netlist
from glayout.util.comp_utils import align_comp_to_port, evaluate_bbox, movey, prec_ref_center
from glayout.util.port_utils import add_ports_perimeter, rename_ports_by_orientation
from glayout.util.process_table import ProcessTable
from glayout.util.snap_to_grid import component_snap_to_grid

_gen_fingers = getattr(_fet, "__gen_fingers_macro")
_comp_min_width = getattr(_fet, "__comp_min_width")


def _normalise_wl(pdk: MappedPDK, width: float, length: Optional[float]) -> tuple[float, float]:
    """Same floors and snapping as ``fet.multiplier``."""
    min_length = pdk.get_grule("poly")["min_width"]
    length = min_length if (length or min_length) <= min_length else length
    min_width = pdk.get_grule("active_diff")["min_width"]
    width = min_width if (width or min_width) <= min_width else width
    return pdk.snap_to_2xgrid(width), pdk.snap_to_2xgrid(length)


def default_sd_rail_order(seq: FingerSequence) -> list[str]:
    """Pure source nets first (nearest the diffusion), then the rest by first use."""
    order: list[str] = []
    for c in seq.contacts():
        if c.net not in order:
            order.append(c.net)
    sources = {d.source for d in seq.devices.values()}
    drains = {d.drain for d in seq.devices.values()}
    return sorted(order, key=lambda n: (not (n in sources and n not in drains), order.index(n)))


def default_gate_rail_order(seq: FingerSequence) -> list[str]:
    order: list[str] = []
    for f in seq.fingers:
        g = seq.devices[f.device].gate
        if g not in order:
            order.append(g)
    return order


def _dummy_finger(pdk: MappedPDK, interfinger_rmult: int, length: float, width: float,
                  poly_height: float, sdlayer: str) -> Component:
    """One finger with gate, source and drain shorted on met1 (as in ``multiplier``)."""
    dummy = _gen_fingers(pdk, rmult=interfinger_rmult, fingers=1, length=length, width=width,
                         poly_height=poly_height, sdlayer=sdlayer, inter_finger_topmet="met1")
    dummyvia = dummy << via_stack(pdk, "poly", "met1", fullbottom=True)
    align_comp_to_port(dummyvia, dummy.ports["row0_col0_gate_S"], layer=pdk.get_glayer("poly"))
    dummy << L_route(pdk, dummyvia.ports["top_met_W"], dummy.ports["leftsd_top_met_S"])
    dummy << L_route(pdk, dummyvia.ports["top_met_E"], dummy.ports["row0_col0_rightsd_top_met_S"])
    dummy.add_ports(dummyvia.get_ports_list(), prefix="gsdcon_")
    return dummy


def finger_sequence_row(
    pdk: MappedPDK,
    sequence: FingerSequence,
    device: Literal["nfet", "pfet"] = "nfet",
    width: float = 3,
    length: Optional[float] = None,
    with_dummy: Union[bool, tuple[bool, bool]] = True,
    rmult: Optional[int] = None,
    sd_rail_order: Optional[Sequence[str]] = None,
    gate_rail_order: Optional[Sequence[str]] = None,
    tie_gate_to_sd: bool = True,
    sd_route_topmet: str = "met2",
    gate_route_topmet: str = "met2",
    title: str = "Finger-sequence row",
) -> Component:
    """Build one row of fingers for ``sequence``.

    Ports (``<net>`` is the net name as given in the DeviceSpecs):
      ``<net>_sd_{N,E,S,W}``    source/drain rail of that net
      ``<net>_gate_{N,E,S,W}``  gate rail of that net
      ``dummy_{L,R}_gsdcon_*``  dummy gate/source/drain tie (met1)
      ``plusdoped_*``, ``diff_*`` row implant / diffusion extent
    ``info``: sequence, rails, measured centroids (µm) and centroid error.
    """
    if device not in ("nfet", "pfet"):
        raise ValueError("device must be 'nfet' or 'pfet'")
    sdlayer = "n+s/d" if device == "nfet" else "p+s/d"
    dummy_l, dummy_r = (with_dummy, with_dummy) if isinstance(with_dummy, bool) else with_dummy
    sd_rmult, gate_rmult, interfinger_rmult = 1, 1, 1
    if rmult:
        sd_rmult, interfinger_rmult = rmult, ((rmult - 1) or 1)
    pdk.activate()
    with ProcessTable(title, f"{device} {sequence.labels()}") as pt:
        with pt.stage("Normalise W/L") as st:
            width, length = _normalise_wl(pdk, width, length)
            poly_height = max(width, _comp_min_width(pdk)) + 2 * pdk.get_grule("poly", "active_diff")["overhang"]
            st.detail(f"W={width}µm L={length}µm per finger, poly height {poly_height:.3f}µm")
        row = Component("finger_sequence_row")
        with pt.stage("Diffusion segments") as st:
            segments = sequence.segments()
            sep = pdk.get_grule("active_diff")["min_separation"]
            seg_refs = []
            cursor = None
            for idxs in segments:
                seg = _gen_fingers(pdk, rmult=interfinger_rmult, fingers=len(idxs), length=length, width=width,
                                   poly_height=poly_height, sdlayer=sdlayer, inter_finger_topmet="met2")
                half = pdk.snap_to_2xgrid(evaluate_bbox(seg)[0] / 2)
                centre = 0.0 if cursor is None else pdk.snap_to_2xgrid(cursor + sep + half)
                ref = row << seg
                ref.movex(centre)
                cursor = centre + half
                seg_refs.append((ref, idxs))
            st.detail(f"{len(segments)} strip(s) {[len(s) for s in segments]}, {sequence.breaks} break(s)")
        # collect contact and gate ports in sequence order
        contacts = sequence.contacts()
        contact_ports, gate_ports = [], {}
        for ref, idxs in seg_refs:
            contact_ports.append(ref.ports["leftsd_top_met_N"])
            for j, fidx in enumerate(idxs):
                contact_ports.append(ref.ports[f"row0_col{j}_rightsd_top_met_N"])
                gate_ports[fidx] = ref.ports[f"row0_col{j}_gate_S"]
        assert len(contact_ports) == len(contacts)
        row_xmin = min(ref.xmin for ref, _ in seg_refs)
        row_xmax = max(ref.xmax for ref, _ in seg_refs)

        with pt.stage("Source/drain rails") as st:
            sd_order = list(sd_rail_order or default_sd_rail_order(sequence))
            missing = {c.net for c in contacts} - set(sd_order)
            if missing:
                raise ValueError(f"sd_rail_order is missing nets {sorted(missing)}")
            sdvia = via_stack(pdk, "met1", sd_route_topmet)
            sd_h = sd_rmult * evaluate_bbox(sdvia)[1]
            sd_sep = pdk.get_grule(sd_route_topmet)["min_separation"]
            rail_y = {}
            for c, port in zip(contacts, contact_ports):
                k = sd_order.index(c.net)
                diff_top = movey(port, destination=width / 2)
                ext = sd_sep + sd_h / 2 + k * (sd_h + sd_sep)
                via = align_comp_to_port(sdvia, diff_top, alignment=("c", "t"))
                row.add(via.movey(pdk.snap_to_2xgrid(ext)))
                row << straight_route(pdk, diff_top, via.ports["bottom_met_N"])
                rail_y[c.net] = via.ports["top_met_W"].center[1]
            for net in sd_order:
                if net not in rail_y:
                    continue
                rail = Component(f"rail_{net}")
                rail << rectangle(size=(row_xmax - row_xmin, sd_h), layer=pdk.get_glayer(sd_route_topmet), centered=True)
                rail = add_ports_perimeter(rail, layer=pdk.get_glayer(sd_route_topmet), prefix=f"{net}_sd_")
                rref = row << rail
                rref.move(((row_xmin + row_xmax) / 2, rail_y[net]))
                row.add_ports(rref.get_ports_list())
            st.detail(f"{len(rail_y)} rail(s) bottom→top {[n for n in sd_order if n in rail_y]}, {len(contacts)} contacts")

        with pt.stage("Gate bars + rails") as st:
            g_order = list(gate_rail_order or default_gate_rail_order(sequence))
            metal_sep = pdk.util_max_metal_seperation()
            probe = via_array(pdk, "poly", gate_route_topmet, size=(length, None), num_vias=(None, gate_rmult),
                              no_exception=True, fullbottom=True)
            bar_h = evaluate_bbox(probe)[1]
            level_pitch = bar_h + 2 * metal_sep
            groups = []   # (gate net, [finger idx]) consecutive within one segment
            for _, idxs in seg_refs:
                for fidx in idxs:
                    g = sequence.devices[sequence.fingers[fidx].device].gate
                    if groups and groups[-1][0] == g and groups[-1][2] is idxs and groups[-1][1][-1] == fidx - 1:
                        groups[-1][1].append(fidx)
                    else:
                        groups.append((g, [fidx], idxs))
            gate_rails = {}
            for g, fidxs, _ in groups:
                level = g_order.index(g)
                ends = []
                for fidx in fidxs:
                    gp = gate_ports[fidx]
                    stub_end = movey(gp.copy(), 0 - metal_sep - level * level_pitch)
                    stub_end.y = pdk.snap_to_2xgrid(stub_end.y)
                    row << straight_route(pdk, gp, stub_end)
                    ends.append(stub_end)
                first, last = gate_ports[fidxs[0]], gate_ports[fidxs[-1]]
                bar_w = last.center[0] - first.center[0] + last.width
                bar = rename_ports_by_orientation(via_array(pdk, "poly", gate_route_topmet, size=(bar_w, None),
                                                            num_vias=(None, gate_rmult), no_exception=True,
                                                            fullbottom=True))
                bref = align_comp_to_port(bar.copy(), ends[-1], alignment=(None, "b"), layer=pdk.get_glayer("poly"))
                bref.movex((first.center[0] + last.center[0]) / 2 - bref.center[0])
                row.add(bref)
                gate_rails.setdefault(g, (bref.ports["top_met_E"].center[1], bref.ports["top_met_E"].width))
            for g in g_order:
                if g not in gate_rails:
                    continue
                y, h = gate_rails[g]
                rail = Component(f"grail_{g}")
                rail << rectangle(size=(row_xmax - row_xmin, h), layer=pdk.get_glayer(gate_route_topmet), centered=True)
                rail = add_ports_perimeter(rail, layer=pdk.get_glayer(gate_route_topmet), prefix=f"{g}_gate_")
                rref = row << rail
                rref.move(((row_xmin + row_xmax) / 2, y))
                row.add_ports(rref.get_ports_list())
            st.detail(f"{len(gate_rails)} gate rail(s) {list(gate_rails)}, {len(groups)} poly bar(s)")

        with pt.stage("Dummies + implant") as st:
            placed = []
            if dummy_l or dummy_r:
                dummy = _dummy_finger(pdk, interfinger_rmult, length, width, poly_height, sdlayer)
                dsep = pdk.get_grule(sdlayer)["min_separation"]
                for on, side, name, edge in ((dummy_l, -1, "dummy_L_", row_xmin), (dummy_r, 1, "dummy_R_", row_xmax)):
                    if not on:
                        continue
                    dref = row << dummy
                    dref.movex(pdk.snap_to_2xgrid(edge + side * (dsep + dummy.xmax)))
                    row.add_ports(dref.get_ports_list(), prefix=name)
                    placed.append(name.strip("_"))
            pd_layer = pdk.get_glayer(sdlayer)
            pd_bbox = row.extract(layers=(pd_layer,)).bbox
            implant = row << rectangle(size=(pd_bbox[1][0] - pd_bbox[0][0], pd_bbox[1][1] - pd_bbox[0][1]),
                                       layer=pd_layer, centered=True)
            implant.move(((pd_bbox[0][0] + pd_bbox[1][0]) / 2, (pd_bbox[0][1] + pd_bbox[1][1]) / 2))
            row.add_ports(implant.get_ports_list(), prefix="plusdoped_")
            st.detail(f"dummies {placed or 'none'}")

        with pt.stage("Gate↔S/D ties") as st:
            ties = [n for n in gate_rails if f"{n}_sd_W" in row.ports] if tie_gate_to_sd else []
            maxsep = pdk.util_max_metal_seperation()
            tie_sides = {}
            for i, net in enumerate(ties):
                side = "W" if i % 2 == 0 else "E"
                tie_sides[net] = side
                ext = (3 + 4 * (i // 2)) * maxsep
                row << c_route(pdk, row.ports[f"{net}_sd_{side}"], row.ports[f"{net}_gate_{side}"],
                               extension=ext, viaoffset=False)
            st.detail(f"{ties or 'none'}")

        with pt.stage("Measure") as st:
            by_dev: dict[str, list[float]] = {}
            for fidx, gp in gate_ports.items():
                by_dev.setdefault(sequence.fingers[fidx].device, []).append(gp.center[0])
            row_cx = (row_xmin + row_xmax) / 2
            centroids = {d: sum(v) / len(v) - row_cx for d, v in by_dev.items()}
            cerr = max(centroids.values()) - min(centroids.values())
            dims = evaluate_bbox(row)
            st.detail("centroids µm " + ", ".join(f"{d}={x:.4f}" for d, x in sorted(centroids.items())))
            if cerr > 1e-6:
                st.warn(f"centroid error {cerr:.4f}µm")
        pt.result("size_um", f"{dims[0]:.2f}x{dims[1]:.2f}")
        pt.result("area_um2", f"{dims[0] * dims[1]:.2f}")
        pt.result("centroid_err_um", f"{cerr:.2g}")
    centred = Component("finger_sequence_row")
    cref = centred << row
    prec_ref_center(cref, snapmov2grid=True)
    centred.add_ports(cref.get_ports_list())
    out = component_snap_to_grid(rename_ports_by_orientation(centred))
    out.info["sequence"] = sequence.compact()
    out.info["diagram"] = sequence.diagram()
    out.info["sd_rails"] = [n for n in sd_order if n in rail_y]
    out.info["gate_rails"] = list(gate_rails)
    out.info["centroids_um"] = {d: round(x, 4) for d, x in centroids.items()}
    out.info["tie_sides"] = tie_sides            # net -> row side its gate/S-D tie leaves from
    out.info["centroid_error_um"] = round(cerr, 6)
    return out


def finger_sequence_netlist(
    pdk: MappedPDK,
    sequence: FingerSequence,
    device: Literal["nfet", "pfet"],
    width: float,
    length: Optional[float],
    with_dummy: Union[bool, tuple[bool, bool]] = True,
    bulk: str = "B",
    dummy_net: Optional[str] = None,
    circuit_name: str = "FSROW",
    pins: Optional[Sequence[str]] = None,
) -> Netlist:
    """One device line per logical transistor (``m`` = its finger count).

    Dummies sit on ``dummy_net`` (default: the bulk, which is what a cell that
    ties them to the well ring extracts).
    """
    width, length = _normalise_wl(pdk, width, length)
    model = pdk.models[device]
    nets: list[str] = []
    for d in sequence.devices.values():
        for n in (d.drain, d.gate, d.source):
            if n not in nets:
                nets.append(n)
    nodes = list(pins) if pins else nets + [bulk]
    # no parameters on the .subckt line: klayout then fails to match a top cell
    lines = [".subckt {circuit_name} {nodes}"]
    for d in sequence.devices.values():
        lines.append(f"X{d.name} {d.drain} {d.gate} {d.source} {bulk} {model} l={length} w={width} m={d.fingers}")
    n_dum = sum(with_dummy) if isinstance(with_dummy, tuple) else 2 * bool(with_dummy)
    if n_dum:
        dn = dummy_net or bulk
        lines.append(f"XDUMMY {dn} {dn} {dn} {bulk} {model} l={length} w={width} m={n_dum}")
    lines.append(".ends {circuit_name}")
    return Netlist(circuit_name=circuit_name, nodes=nodes, source_netlist="\n".join(lines))
