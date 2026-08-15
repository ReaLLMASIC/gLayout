from glayout.backend import Component, ComponentReference, cell, clear_cache, copy, rectangle, route_quad
from glayout.pdk.mappedpdk import MappedPDK
from typing import Optional, Union
from glayout.primitives.fet import nmos, pmos, multiplier
from glayout.cells.elementary.diff_pair import diff_pair
from glayout.primitives.guardring import tapring
from glayout.primitives.mimcap import mimcap_array, mimcap
from glayout.routing.L_route import L_route
from glayout.routing.c_route import c_route
from glayout.primitives.via_gen import via_stack, via_array
from glayout.util.comp_utils import evaluate_bbox, prec_ref_center, movex, movey, to_decimal, to_float, move, align_comp_to_port, get_padding_points_cc
from glayout.util.port_utils import rename_ports_by_orientation, rename_ports_by_list, add_ports_perimeter, print_ports, set_port_orientation, rename_component_ports
from glayout.routing.straight_route import straight_route
from glayout.util.snap_to_grid import component_snap_to_grid
from pydantic import validate_arguments
from glayout.placement.two_transistor_interdigitized import two_nfet_interdigitized
from glayout.spice import Netlist

from glayout.cells.composite.opamp.opamp_twostage import opamp_twostage
from glayout.cells.elementary.current_mirror import current_mirror_netlist


def _erase_subcell_pin_labels(opamp_top: Component, label_texts) -> Component:
    """Remove pin labels that propagated up from flattened sub-cells.

    Sub-cells like ``diff_pair_ibias`` and
    ``differential_to_single_ended_converter`` add their OWN labels (VP, VN,
    VDD1, VDD2, IBIAS, VSS, B, …) so they can be exercised standalone against
    their standalone schematics. When those cells are flatten()'d into the
    opamp layout the labels land on the opamp top GDS cell and confuse
    Magic LVS in two ways:

    1. Sub-cell labels named the same as opamp-top labels (e.g. VP, VN) get
       reported as "electrically shorted" synonyms even when the underlying
       metal really IS the same net — noisy.
    2. Sub-cell labels named for nets that are INTERNAL at the opamp level
       (e.g. dpiibias's ``VDD1`` and ``VDD2`` — those are diffpair drains,
       which are mapped to ``GAIN_STAGE.VIN1/VIN2`` inside opamp_twostage,
       not top-level pins) get extracted as extra subckt ports, which then
       fail pin matching.

    The function removes labels by exact text. The opamp top-level labels
    (added by ``add_opamp_labels``) are NOT in ``label_texts`` so they stay
    in place. We touch ``opamp_top._cell.labels`` directly because gdsfactory
    exposes ``.labels`` as a property whose returned list is detached
    (mutating it does nothing); the underlying gdstk Cell's ``remove()``
    method is the only way to actually delete labels.
    """
    opamp_top.unlock()
    targets = set(label_texts)
    # Snapshot first because we mutate the cell during iteration.
    to_remove = [lab for lab in opamp_top._cell.labels if lab.text in targets]
    for lab in to_remove:
        opamp_top._cell.remove(lab)
    return opamp_top


def add_opamp_labels(opamp_in: Component, pdk: MappedPDK, add_output_stage: bool = False) -> Component:
    """Drop pin/label rectangles on the top-level signals so netgen LVS can
    match them to the schematic's named pins. Without these, magic extracts
    auto-named nodes and netgen can't disambiguate by connectivity alone.

    Two label sets, depending on the topology:
      * ``add_output_stage=False`` -> opamp_twostage_netlist ports (uppercase
        VDD, GND, DIFFPAIR_BIAS, VP, VN, CS_BIAS, VOUT).
      * ``add_output_stage=True``  -> opamp_netlist ports (lowercase vdd, gnd,
        plus, minus, diffpairibias, commonsourceibias + outputibias, output,
        CSoutput introduced by the wrapper netlist).

    Each label is anchored at an existing port on the matching metal layer.
    """
    opamp_in.unlock()

    # Pin glayer must match the pin rectangle's actual layer in opamp_twostage,
    # otherwise magic associates the label with the wrong (or no) metal:
    #   vddpin: met4, vbias1 (DIFFPAIR_BIAS): met3, vbias2 (CS_BIAS): met5,
    #   minusi_pin: met3, plusi_pin: met3, gndpin: met4 (in diff_pair_stackedcmirror).
    # commonsource_output_E sits on the c_route's met2 connector.
    #
    # Anchor at the GEOMETRIC CENTER of each pin rectangle (computed from two
    # opposite-edge ports) rather than an edge port. Edge anchors put half of
    # the label rect outside the metal, which causes magic to associate the
    # label with whichever neighboring metal it happened to overlap.
    # The pin_minus / pin_plus / commonsource_output rectangles in
    # opamp_twostage are placed at the LEFT edge (x ≈ opamp_top.xmin) and
    # near the cs_amp drain c_route's WEST extension. Centering a label rect
    # on those metals makes Magic associate VN/VP/VOUT with the cs_amp drain
    # (= GAIN_STAGE.VOUT) instead of the diffpair gate / output node, which
    # extracts as a 3-way short between VN, VOUT, and the cs_bias drain.
    # Anchor VP/VN on the diffpair multiplier gate ports themselves (deep
    # inside the diffpair area, on met2 — same metal as dpiibias used to
    # label internally before _erase_subcell_pin_labels stripped them).
    if not add_output_stage:
        placements = [
            # (port_a, port_b, label_text, glayer)
            ("pin_vdd_e1",               "pin_vdd_e3",               "VDD",           "met4"),
            ("pin_diffpairibias_e1",     "pin_diffpairibias_e3",     "DIFFPAIR_BIAS", "met3"),
            ("pin_commonsourceibias_e1", "pin_commonsourceibias_e3", "CS_BIAS",       "met5"),
            # diff_pair places: tl=fetL, tr=fetR, bl=fetL, br=fetR (lines
            # 155-162 of diff_pair.py — a_topl=fetL, b_topr=fetR, a_botr=fetR,
            # b_botl=fetL, with the bl/br port-prefix swap because b_botl
            # gets the "bl_" prefix and a_botr gets "br_"). So VP (fetL)
            # gates live on bl_*, and VN (fetR) gates on br_*.
            ("diffpair_bl_multiplier_0_gate_S", None,                "VP",            "met2"),
            ("diffpair_br_multiplier_0_gate_S", None,                "VN",            "met2"),
            ("pin_gnd_W",                "pin_gnd_E",                "GND",           "met4"),
            # commonsource_output_E is the n_to_p_output_route c_route's con_S
            # port — that bridge sits on met4 (cglayer = e1+1 = met3+1). A
            # met2 label rect there has no underlying met2 polygon, so Magic
            # auto-names a floating fragment instead of pinning the bridge.
            ("commonsource_output_E",    None,                       "VOUT",          "met4"),
        ]
    else:
        # add_output_stage=True -> opamp_netlist's lowercase top-level nodes.
        # The two_stage VDD/GND/VP/VN/DIFFPAIR_BIAS/CS_BIAS get re-mapped to
        # vdd/gnd/plus/minus/diffpairibias/commonsourceibias, and VOUT becomes
        # CSoutput (the gain-stage output that drives the output stage). The
        # output stage adds the outputibias and output top-level pins.
        placements = [
            ("pin_vdd_e1",               "pin_vdd_e3",               "vdd",              "met4"),
            ("pin_diffpairibias_e1",     "pin_diffpairibias_e3",     "diffpairibias",    "met3"),
            ("pin_commonsourceibias_e1", "pin_commonsourceibias_e3", "commonsourceibias","met5"),
            ("diffpair_bl_multiplier_0_gate_S", None,                "plus",             "met2"),
            ("diffpair_br_multiplier_0_gate_S", None,                "minus",            "met2"),
            ("pin_gnd_W",                "pin_gnd_E",                "gnd",              "met4"),
            # CSoutput is the gain-stage's output node, named VOUT inside two_stage.
            ("commonsource_output_E",    None,                       "CSoutput",         "met2"),
            # Output stage ibias pin (added by __add_output_stage as pin_outputibias_).
            ("pin_outputibias_e1",       "pin_outputibias_e3",       "outputibias",      "met3"),
            # Output pin (rectangle from output_pin straight_route, prefix pin_output_).
            ("pin_output_route_E",       "pin_output_route_W",       "output",           "met3"),
        ]
    for port_a, port_b, text, glayer in placements:
        if port_a not in opamp_in.ports:
            continue
        try:
            pin_layer = pdk.get_glayer(f"{glayer}_pin")
            label_layer = pdk.get_glayer(f"{glayer}_label")
        except (NotImplementedError, KeyError):
            continue
        a = opamp_in.ports[port_a].center
        if port_b and port_b in opamp_in.ports:
            b = opamp_in.ports[port_b].center
            cx, cy = (float(a[0]) + float(b[0])) / 2.0, (float(a[1]) + float(b[1])) / 2.0
        else:
            cx, cy = float(a[0]), float(a[1])
        # Tiny label rect, fully inside the metal. Build fresh per call so the
        # gdsfactory rectangle cache doesn't mix labels across cells.
        # 0.15 half-side (0.3x0.3) clears sky130 m1 min-width (0.14) and
        # min-area (0.083um²) when the anchor lands on a met1 layer.
        s = 0.15
        rect = Component(name=f"opamp_pin_{text}")
        rect.add_polygon([(-s, -s), (s, -s), (s, s), (-s, s)], layer=pin_layer)
        rect.add_label(text=text, layer=label_layer, position=(0.0, 0.0))
        ref = rect.ref(position=(cx, cy))
        opamp_in.add(ref)
    return opamp_in.flatten()

def opamp_output_stage_netlist(pdk: MappedPDK, output_amp_fet_ref: ComponentReference, biasParams: list) -> Netlist:
    bias_netlist = current_mirror_netlist(pdk, biasParams[0], biasParams[1], 1, biasParams[2])

    output_stage_netlist = Netlist(
        circuit_name="OUTPUT_STAGE",
        nodes=['VDD', 'GND', 'IBIAS', 'VIN', 'VOUT']
    )

    output_stage_netlist.connect_netlist(
        output_amp_fet_ref.info['netlist'],
        [('D', 'VDD'), ('G', 'VIN'), ('B', 'GND'), ('S', 'VOUT'), ('DUM', 'GND')]
    )

    output_stage_netlist.connect_netlist(
        bias_netlist,
        [('VREF', 'IBIAS'), ('VSS', 'GND'), ('VOUT', 'VOUT'), ('B', 'GND')]
    )

    return output_stage_netlist

@validate_arguments
def __add_output_stage(
    pdk: MappedPDK,
    opamp_top: Component,
    amplifierParams: tuple[float, float, int],
    biasParams: list,
    rmult: int,
) -> tuple[Component, Netlist]:
    '''add output stage to opamp_top, args:
    pdk = pdk to use
    opamp_top = component to add output stage to
    amplifierParams = [width,length,fingers,mults] for amplifying FET
    biasParams = [width,length,fingers,mults] for bias FET
    '''
    # Instantiate output amplifier
    amp_fet_ref = opamp_top << nmos(
        pdk,
        width=amplifierParams[0],
        length=amplifierParams[1],
        fingers=amplifierParams[2],
        multipliers=1,
        sd_route_topmet="met3",
        gate_route_topmet="met3",
        rmult=rmult,
        with_dnwell=False,
        with_tie=True,
        with_substrate_tap=False,
        tie_layers=("met2","met2")
    )
    # Instantiate bias FET
    cmirror_ibias = opamp_top << two_nfet_interdigitized(
        pdk,
        numcols=biasParams[2],
        width=biasParams[0],
        length=biasParams[1],
        fingers=1,
        gate_route_topmet="met3",
        sd_route_topmet="met3",
        rmult=rmult,
        with_substrate_tap=False,
        tie_layers=("met2","met2")
    )

    metal_sep = pdk.util_max_metal_seperation()
    # Locate output stage relative position
    # x-coordinate: Center of SW capacitor in array
    # y-coordinate: Top of NMOS blocks
    xref_port = opamp_top.ports["mimcap_row0_col0_top_met_S"]
    x_cord = xref_port.center[0] - xref_port.width/2
    y_cord = opamp_top.ports["commonsource_cmirror_output_R_tie_N_top_met_N"].center[1]
    dims = evaluate_bbox(amp_fet_ref)
    center = [x_cord + dims[0]/2, y_cord - dims[1]/2]
    amp_fet_ref.move(center)
    amp_fet_ref.movey(pdk.get_grule("active_tap", "p+s/d")["min_enclosure"])
    dims = evaluate_bbox(cmirror_ibias)
    cmirror_ibias.movex(amp_fet_ref.xmin + dims[0]/2)
    cmirror_ibias.movey(amp_fet_ref.ymin - dims[1]/2 - metal_sep)
    # route input of output_stage to output of previous stage
    n_to_p_output_route = opamp_top.ports["special_con_npr_con_S"]
    opamp_top << L_route(pdk, n_to_p_output_route, amp_fet_ref.ports["multiplier_0_gate_W"])
    # route drain of amplifier to vdd
    vdd_route_extension = opamp_top.ymax-opamp_top.ports["pin_vdd_e4"].center[1]+metal_sep
    # widths capped under sky130's "huge" threshold (3um). The c_route's stubs
    # land on the FET drain sd-bar (~0.86um tall, non-huge) and on the pin_vdd
    # rectangle, and merge with them on met2/met3. If the c_route stub is
    # itself "huge" (>=3um in min dim) the merge creates a huge/non-huge
    # boundary that trips m{1,2,3}.3ab even though everything is electrically
    # one net. Keeping widths at 2.5 keeps the stubs non-huge so the rule
    # never fires.
    opamp_top << c_route(pdk,amp_fet_ref.ports["multiplier_0_drain_N"],set_port_orientation(opamp_top.ports["pin_vdd_e4"],"N"),width1=2.5,width2=2.5,extension=vdd_route_extension,e2glayer="met3")
    vddvia = opamp_top << via_stack(pdk,"met3","met4",fullbottom=True)
    align_comp_to_port(vddvia,opamp_top.ports["pin_vdd_e4"],('c','t'))
    # route drain of cmirror to source of amplifier
    opamp_top << c_route(pdk, cmirror_ibias.ports["B_drain_E"],amp_fet_ref.ports["multiplier_0_source_E"],extension=metal_sep)
    # route cmirror: A gate, B gate and A drain together. Then A source and B source to ground
    gate_short = opamp_top << c_route(pdk, cmirror_ibias.ports["A_gate_E"],cmirror_ibias.ports["B_gate_E"],extension=3*metal_sep,viaoffset=None)
    opamp_top << L_route(pdk, gate_short.ports["con_N"],cmirror_ibias.ports["A_drain_E"],viaoffset=False,fullbottom=False)
    srcshort = opamp_top << c_route(pdk, cmirror_ibias.ports["A_source_W"],cmirror_ibias.ports["B_source_W"],extension=metal_sep)
    opamp_top << straight_route(pdk, srcshort.ports["con_N"], cmirror_ibias.ports["welltie_N_top_met_S"],via2_alignment_layer="met2")
    # Route all tap rings together and ground them
    opamp_top << straight_route(pdk, cmirror_ibias.ports["welltie_N_top_met_N"],amp_fet_ref.ports["tie_S_top_met_S"])
    # hwidth capped at 2.5 (under sky130's 3um huge_m1 threshold). The L_route's
    # vertical leg lands on the cmirror_ibias welltie ring (a thin frame on
    # met2, non-huge). With hwidth>=3 the leg is "huge" and merging into the
    # welltie creates a huge/non-huge boundary that trips m1.3ab even though
    # both pieces are the same GND net. Same family of rules m{2,3}.3ab forced
    # the c_route widths above.
    opamp_top << L_route(pdk, cmirror_ibias.ports["welltie_S_top_met_S"], opamp_top.ports["pin_gnd_E"],hwidth=2.5)
    # add ports, add bias/output pin, and return
    psuedo_out_port = movex(amp_fet_ref.ports["multiplier_0_source_E"].copy(),6*metal_sep)
    output_pin = opamp_top << straight_route(pdk, amp_fet_ref.ports["multiplier_0_source_E"], psuedo_out_port)
    opamp_top.add_ports(amp_fet_ref.get_ports_list(),prefix="outputstage_amp_")
    opamp_top.add_ports(cmirror_ibias.get_ports_list(),prefix="outputstage_bias_")
    opamp_top.add_ports(output_pin.get_ports_list(),prefix="pin_output_")
    bias_pin = opamp_top << rectangle(size=(5,3),layer=pdk.get_glayer("met3"),centered=True)
    bias_pin.movex(cmirror_ibias.center[0]).movey(cmirror_ibias.ports["B_gate_S"].center[1]-bias_pin.ymax-5*metal_sep)
    opamp_top << straight_route(pdk, bias_pin.ports["e2"], cmirror_ibias.ports["B_gate_S"],width=1)
    opamp_top.add_ports(bias_pin.get_ports_list(),prefix="pin_outputibias_")

    output_stage_netlist = opamp_output_stage_netlist(pdk, amp_fet_ref, biasParams)
    return opamp_top, output_stage_netlist

def opamp_netlist(two_stage_netlist: Netlist, output_stage_netlist: Netlist) -> Netlist:
    top_level_netlist = Netlist(
        circuit_name="opamp",
        nodes=["CSoutput", "vdd", "plus", "minus", "commonsourceibias", "outputibias", "diffpairibias", "gnd", "output"]
    )

    top_level_netlist.connect_netlist(
        two_stage_netlist,
        [('VDD', 'vdd'), ('GND', 'gnd'), ('DIFFPAIR_BIAS', 'diffpairibias'), ('VP', 'plus'), ('VN', 'minus'), ('CS_BIAS', 'commonsourceibias'), ('VOUT', 'CSoutput')]
    )

    top_level_netlist.connect_netlist(
        output_stage_netlist,
        [('VDD', 'vdd'), ('GND', 'gnd'), ('IBIAS', 'outputibias'), ('VIN', 'CSoutput'), ('VOUT', 'output')]
    )

    return top_level_netlist

@cell
def opamp(
    pdk: MappedPDK,
    half_diffpair_params: tuple[float, float, int] = (6, 1, 4),
    diffpair_bias: tuple[float, float, int] = (6, 2, 4),
    half_common_source_params: tuple[float, float, int, int] = (7, 1, 10, 3),
    half_common_source_bias: tuple[float, float, int, int] = (6, 2, 8, 2),
    output_stage_params: tuple[float, float, int] = (5, 1, 16),
    output_stage_bias: tuple[float, float, int] = (6, 2, 4),
    half_pload: tuple[float,float,int] = (6,1,6),
    mim_cap_size=(12, 12),
    mim_cap_rows=3,
    rmult: int = 2,
    with_antenna_diode_on_diffinputs: int=5, 
    add_output_stage: Optional[bool] = False
) -> Component:
    """
    create a two stage opamp with an output buffer, args->
    pdk: pdk to use
    half_diffpair_params: diffpair (width,length,fingers)
    diffpair_bias: bias transistor for diffpair nmos (width,length,fingers). The ref and output of the cmirror are identical
    half_common_source_params: pmos top component amp (width,length,fingers,mults)
    half_common_source_bias: bottom L/R large nmos current mirror (width,length,fingers,mults). The ref of the cmirror always has 1 multplier. multiplier must be >=2
    ****NOTE: change the multiplier option to change the relative sizing of the current mirror ref/output
    output_stage_amp_params: output amplifier transistor params (width, length, fingers)
    output_stage_bias: output amplifier current mirror params (width, length, fingers). The ref and output of the cmirror are identical
    half_pload: all 4 pmos load transistors of first stage (width,length,...). The last element in the tuple is the fingers of the bottom two pmos.
    mim_cap_size: width,length of individual mim_cap
    mim_cap_rows: number of rows in the mimcap array (always 2 cols)
    rmult: routing multiplier (larger = wider routes)
    with_antenna_diode_on_diffinputs: adds antenna diodes with_antenna_diode_on_diffinputs*(1um/0.5um) on the positive and negative inputs to the opamp
    """
    opamp_top = opamp_twostage(
        pdk,
        half_diffpair_params,
        diffpair_bias,
        half_common_source_params,
        half_common_source_bias,
        half_pload,
        mim_cap_size,
        mim_cap_rows,
        rmult,
        with_antenna_diode_on_diffinputs
    )
    # add output amplfier stage
    if add_output_stage:
        opamp_top, output_stage_netlist = __add_output_stage(pdk, opamp_top, output_stage_params, output_stage_bias, rmult)
        opamp_top.info['netlist'] = opamp_netlist(opamp_top.info['netlist'], output_stage_netlist)

    # Strip pin labels that propagated up from sub-cells (dpiibias, dse,
    # ...). They were added so each sub-cell can be LVS'd standalone, but
    # at the opamp top level they collide with the opamp's own pin labels
    # and create extra subckt ports for nets that are internal here.
    opamp_top = _erase_subcell_pin_labels(
        opamp_top,
        # diff_pair_ibias labels (see _pin_specs in
        # diff_pair_cmirrorbias.py): every name except those that happen to
        # already match an opamp top-level pin. We purge them all because
        # the opamp's add_opamp_labels below re-emits the right set on
        # the right metal.
        ["VP", "VN", "VDD1", "VDD2", "IBIAS", "VSS", "B"],
    )
    # add LVS pin/label rects so netgen can name-match the top-level signals
    opamp_top = add_opamp_labels(opamp_top, pdk, add_output_stage=add_output_stage)
    return rename_ports_by_orientation(component_snap_to_grid(opamp_top))


