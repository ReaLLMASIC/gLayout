from glayout.backend import Component, ComponentReference, cell, clear_cache, copy, rectangle, route_quad
from glayout import MappedPDK, sky130,gf180
from glayout.routing import c_route,L_route,straight_route
from typing import Optional, Union
from glayout.cells.elementary.diff_pair import diff_pair
from glayout.primitives.fet import nmos, pmos, multiplier
from glayout.primitives.guardring import tapring
from glayout.primitives.mimcap import mimcap_array, mimcap
from glayout.primitives.via_gen import via_stack, via_array
from glayout.util.comp_utils import (
    evaluate_bbox,
    prec_ref_center,
    movex,
    movey,
    to_decimal,
    to_float,
    move,
    align_comp_to_port,
    get_padding_points_cc,
)
from glayout.util.port_utils import (
    rename_ports_by_orientation,
    rename_ports_by_list,
    add_ports_perimeter,
    print_ports,
    set_port_orientation,
    rename_component_ports,
)
from glayout.util.snap_to_grid import component_snap_to_grid
from pydantic import validate_arguments
from glayout.placement.two_transistor_interdigitized import two_nfet_interdigitized
from glayout.spice import Netlist
from glayout.cells.elementary.current_mirror import current_mirror_netlist

def diff_pair_ibias_netlist(center_diffpair: Component, current_mirror: Component, antenna_diode: Optional[Component] = None) -> Netlist:
    netlist = Netlist(
        circuit_name="DIFFPAIR_CMIRROR_BIAS",
        nodes=['VP', 'VN', 'VDD1', 'VDD2', 'IBIAS', 'VSS', 'B']
    )

    diffpair_ref = netlist.connect_netlist(
        center_diffpair.info['netlist'],
        []
    )

    # Cmirror bulk tied to the top-level B port (NOT VSS): in the layout the
    # cmirror's tap ring connects to the global substrate, which is the same
    # net as the diff_pair's substrate-tap ring (top-level B). Mapping it to
    # VSS instead would split the dummies' bulks across two schematic nets
    # while the layout has them all on one — that single-group difference
    # is the only Magic LVS mismatch on this cell.
    cmirror_ref = netlist.connect_netlist(
        current_mirror.info['netlist'],
        [('VREF', 'IBIAS'), ('B', 'B')]
    )

    netlist.connect_subnets(
        cmirror_ref,
        diffpair_ref,
        [('VOUT', 'VTAIL')]
    )

    if antenna_diode is not None:
        netlist.connect_netlist(
            antenna_diode.info['netlist'],
            [('D', 'VSS'), ('G', 'VSS'), ('B', 'VSS'), ('S', 'VP')]
        )

        netlist.connect_netlist(
            antenna_diode.info['netlist'],
            [('D', 'VSS'), ('G', 'VSS'), ('B', 'VSS'), ('S', 'VN')]
        )

    return netlist

@validate_arguments
def diff_pair_ibias(
    pdk: MappedPDK,
    half_diffpair_params: tuple[float, float, int],
    diffpair_bias: tuple[float, float, int],
    rmult: int = 1,
    with_antenna_diode_on_diffinputs: int = 0,
) -> Component:
    # create and center diffpair
    diffpair_i_ = Component("temp diffpair and current source")
    # `dum_net='B'` overrides the standalone gf180 diff_pair convention
    # (which puts dummies on a local floating 'dum' net): inside this
    # composite, the diff_pair's pwell merges with the surrounding tap
    # rings so klayout extracts the dummies' G/S/D on bulk (B). sky130
    # always wants 'B' too — passing it unconditionally is correct on
    # both PDKs because it matches the magic-merged extraction.
    center_diffpair_comp = diff_pair(
        pdk,
        width=half_diffpair_params[0],
        length=half_diffpair_params[1],
        fingers=half_diffpair_params[2],
        rmult=rmult,
        dum_net='B',
        with_pin_labels=False,
    )
    # add antenna diodes if that option was specified
    diffpair_centered_ref = prec_ref_center(center_diffpair_comp)
    diffpair_i_.add(diffpair_centered_ref)
    diffpair_i_.add_ports(diffpair_centered_ref.get_ports_list())
    antenna_diode_comp = None
    if with_antenna_diode_on_diffinputs:
        antenna_diode_comp = nmos(
            pdk,
            1,
            with_antenna_diode_on_diffinputs,
            1,
            with_dummy=False,
            with_tie=False,
            with_substrate_tap=False,
            with_dnwell=False,
            length=0.5,
            sd_route_topmet="met2",
            gate_route_topmet="met1",
        ).copy()
        antenna_diode_comp << straight_route(
            pdk,
            antenna_diode_comp.ports["multiplier_0_row0_col0_rightsd_top_met_S"],
            antenna_diode_comp.ports["multiplier_0_gate_N"],
        )
        antenna_diode_refL = diffpair_i_ << antenna_diode_comp
        antenna_diode_refR = diffpair_i_ << antenna_diode_comp
        align_comp_to_port(
            antenna_diode_refL, diffpair_i_.ports["MINUSgateroute_W_con_N"], ("r", "t")
        )
        antenna_diode_refL.movex(pdk.util_max_metal_seperation())
        align_comp_to_port(
            antenna_diode_refR, diffpair_i_.ports["MINUSgateroute_E_con_N"], ("L", "t")
        )
        antenna_diode_refR.movex(0 - pdk.util_max_metal_seperation())
        # route the antenna diodes to gnd and
        Lgndcon = diffpair_i_.ports["tap_W_top_met_N"]
        Lgndcon.layer = pdk.get_glayer("met1")
        Rgndcon = diffpair_i_.ports["tap_E_top_met_N"]
        Rgndcon.layer = pdk.get_glayer("met1")
        diffpair_i_ << L_route(
            pdk, antenna_diode_refL.ports["multiplier_0_gate_E"], Lgndcon
        )
        diffpair_i_ << L_route(
            pdk, antenna_diode_refR.ports["multiplier_0_gate_W"], Rgndcon
        )
        diffpair_i_ << straight_route(
            pdk,
            antenna_diode_refL.ports["multiplier_0_source_W"],
            diffpair_i_.ports["MINUSgateroute_W_con_N"],
        )
        diffpair_i_ << straight_route(
            pdk,
            antenna_diode_refR.ports["multiplier_0_source_W"],
            diffpair_i_.ports["PLUSgateroute_E_con_N"],
        )
    # create and position tail current source
    cmirror = two_nfet_interdigitized(
        pdk,
        width=diffpair_bias[0],
        length=diffpair_bias[1],
        numcols=diffpair_bias[2],
        with_tie=True,
        with_substrate_tap=False,
        gate_route_topmet="met3",
        sd_route_topmet="met3",
        rmult=rmult,
        tie_layers=("met2", "met2"),
    )
    # cmirror routing
    metal_sep = pdk.util_max_metal_seperation()
    gate_short = cmirror << c_route(
        pdk,
        cmirror.ports["A_gate_E"],
        cmirror.ports["B_gate_E"],
        extension=3 * metal_sep,
        viaoffset=None,
    )
    cmirror << L_route(
        pdk,
        gate_short.ports["con_N"],
        cmirror.ports["A_drain_E"],
        viaoffset=False,
        fullbottom=False,
    )
    # Match gate_short's `extension=3*metal_sep` for breathing room, and
    # `viaoffset=None` to keep the via stack flush with the e1_extension stub.
    # Original `viaoffset=False` negates the flush amount, leaving a ~30nm gap
    # between the W-side via and its met3 stub on the smaller rmult layouts —
    # which trips m2.2 (met2 spacing in the sky130 deck = met3 in glayout).
    srcshort = cmirror << c_route(
        pdk,
        cmirror.ports["A_source_W"],
        cmirror.ports["B_source_W"],
        extension=3 * metal_sep,
        viaoffset=None,
    )
    cmirror.add_ports(srcshort.get_ports_list(), prefix="purposegndports")
    # current mirror netlist — gf180 needs `dummies_tied_to_bulk=False`
    # because here we use raw two_nfet_interdigitized + custom routing,
    # NOT current_mirror, so the standalone-cell's straight_route from
    # dummy gsdcon to welltie never gets drawn; klayout extracts the
    # cmirror dummies on a per-cell floating net. sky130 magic merges
    # the floating dummies into the bulk so the schematic must keep
    # them tied to VB or magic counts an extra net.
    # Extraction shows the merged cmirror dummy as `B B B B` on gf180 too:
    # with_tie=True draws a welltie ring that IS the bulk net, and the dummy
    # contacts land on it. The old sky130-only condition described a difference
    # that does not exist.
    cmirror.info['netlist'] = current_mirror_netlist(
        pdk,
        width=diffpair_bias[0],
        length=diffpair_bias[1],
        fingers=1,
        multipliers=diffpair_bias[2],
        dummies_tied_to_bulk=True,
    )

    # add cmirror — bump y-offset enough that the LVPWELL paddings of the
    # diffpair and cmirror don't end up with a sub-min_separation gap (gf180
    # LPW.2a/b: min 0.86um). sky130's pwell self-rule is empty so fall back.
    try:
        _pwell_sep = pdk.get_grule("pwell").get("min_separation", 0)
    except NotImplementedError:
        _pwell_sep = 0
    _pwell_clear = max(metal_sep, _pwell_sep)
    tailcurrent_ref = diffpair_i_ << cmirror
    tailcurrent_ref.movey(
        pdk.snap_to_2xgrid(
            -0.5 * (center_diffpair_comp.ymax - center_diffpair_comp.ymin)
            - abs(tailcurrent_ref.ymax)
            - _pwell_clear
        )
    )
    purposegndPort = tailcurrent_ref.ports["purposegndportscon_S"].copy()
    purposegndPort.name = "ibias_purposegndport"
    diffpair_i_.add_ports([purposegndPort])
    diffpair_i_.add_ports(tailcurrent_ref.get_ports_list(), prefix="ibias_")

    # VTAIL connection: schematic ties the diff_pair sources (VTAIL) to the
    # cmirror's B-side drain (VOUT). Without this metal the two halves are
    # electrically isolated and LVS sees a topology mismatch. Route from the
    # source-bar bottom (con_S) to the cmirror drain on each side so the
    # wire stays in the gap below the diffpair. Width is left to default
    # (= port width) so the route inherits the rmult-scaled width of the
    # surrounding diff_pair / cmirror routing.
    diffpair_i_ << L_route(
        pdk,
        diffpair_i_.ports["source_routeW_con_S"],
        diffpair_i_.ports["ibias_B_drain_W"],
    )
    diffpair_i_ << L_route(
        pdk,
        diffpair_i_.ports["source_routeE_con_S"],
        diffpair_i_.ports["ibias_B_drain_E"],
    )

    # Pin labels for the seven top-level nets so klayout/magic LVS can pair
    # them with the schematic ports. align_comp_to_port's alignment letters
    # describe which edge of the label rect lines up with the port (e.g.
    # yalign="b" puts the rect's bottom under the port — i.e. the rect
    # extends DOWN from a port). For an N-facing port whose metal lies
    # BELOW the port, we therefore want yalign="b" so the label sits INSIDE
    # the metal; using the default ("c","t") leaves the label floating
    # above the metal where it can't pin a net.
    _orient_to_align = {
        90:  ("c", "b"),  # N-facing: metal below → label below
        270: ("c", "t"),  # S-facing: metal above → label above
        0:   ("l", "c"),  # E-facing: metal west  → label west
        180: ("r", "c"),  # W-facing: metal east  → label east
    }
    _pin_specs = [
        ("VP",    "br_multiplier_0_gate_S",  "met2"),
        ("VN",    "bl_multiplier_0_gate_S",  "met2"),
        ("VDD1",  "tl_multiplier_0_drain_N", "met2"),
        ("VDD2",  "tr_multiplier_0_drain_N", "met2"),
        ("IBIAS", "ibias_A_drain_E",         "met3"),
        # The cmirror's source short is a c_route on top of met3 sd-bars, so
        # its conducting c-bar is on met4 (cglayer = e1glayer+1 in c_route).
        ("VSS",   "ibias_purposegndport",    "met4"),
        ("B",     "tap_N_top_met_S",         "met1"),
    ]
    for _text, _portname, _glayer in _pin_specs:
        _port = diffpair_i_.ports[_portname]
        _alignment = _orient_to_align[round(_port.orientation) % 360]
        _label = rectangle(
            layer=pdk.get_glayer(f"{_glayer}_pin"),
            size=(0.27, 0.27),
            centered=True,
        ).copy()
        _label.add_label(text=_text, layer=pdk.get_glayer(f"{_glayer}_label"))
        diffpair_i_.add(align_comp_to_port(_label, _port, alignment=_alignment))

    # Flatten so the pin labels live at this cell's top level. Without
    # flattening, prec_ref_center would wrap the labels inside a child
    # reference, and Magic LVS's `subcircuit top on` extraction wouldn't
    # promote them to top-level pins (klayout LVS does, but Magic doesn't).
    # The result keeps the same ports + netlist that callers expect.
    diffpair_i_flat = diffpair_i_.flatten()
    diffpair_i_flat.info['netlist'] = diff_pair_ibias_netlist(center_diffpair_comp, cmirror, antenna_diode_comp)
    return diffpair_i_flat

