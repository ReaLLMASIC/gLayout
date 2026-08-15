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

from glayout.cells.composite.diffpair_cmirror_bias import diff_pair_ibias
from glayout.cells.composite.stacked_current_mirror import stacked_nfet_current_mirror
from glayout.cells.composite.differential_to_single_ended_converter import differential_to_single_ended_converter
from glayout.cells.composite.opamp.row_csamplifier_diff_to_single_ended_converter import row_csamplifier_diff_to_single_ended_converter
from glayout.cells.composite.opamp.diff_pair_stackedcmirror import diff_pair_stackedcmirror
from glayout.spice import Netlist
from glayout.cells.elementary.current_mirror import current_mirror_netlist

@validate_arguments
def __create_and_route_pins(
    pdk: MappedPDK,
    opamp_top: Component,
    pmos_comps_ref: ComponentReference,
    halfmultn_drain_routeref: ComponentReference,
    halfmultn_gate_routeref: ComponentReference
) -> tuple:
    _max_metal_seperation_ps = pdk.util_max_metal_seperation()
    # route halfmultp source, drain, and gate together, place vdd pin in the middle
    halfmultp_Lsrcport = opamp_top.ports["commonsource_Pamp_L_multiplier_0_source_con_N"]
    halfmultp_Rsrcport = opamp_top.ports["commonsource_Pamp_R_multiplier_0_source_con_N"]
    opamp_top << c_route(pdk, halfmultp_Lsrcport, halfmultp_Rsrcport, extension=opamp_top.ymax-halfmultp_Lsrcport.center[1], fullbottom=True,viaoffset=(False,False))
    # place vdd pin
    vddpin = opamp_top << rectangle(size=(5,3),layer=pdk.get_glayer("met4"),centered=True)
    vddpin.movey(opamp_top.ymax)
    # route vdd to source of 2L/2R
    opamp_top << straight_route(pdk, opamp_top.ports["pcomps_2L2Rsrcvia_top_met_N"], vddpin.ports["e4"])
    # drain route above vdd pin
    halfmultp_Ldrainport = opamp_top.ports["commonsource_Pamp_L_multiplier_0_drain_con_N"]
    halfmultp_Rdrainport = opamp_top.ports["commonsource_Pamp_R_multiplier_0_drain_con_N"]
    halfmultp_drain_routeref = opamp_top << c_route(pdk, halfmultp_Ldrainport, halfmultp_Rdrainport, extension=opamp_top.ymax-halfmultp_Ldrainport.center[1]+pdk.get_grule("met5")["min_separation"], fullbottom=True)
    halfmultp_Lgateport = opamp_top.ports["commonsource_Pamp_L_multiplier_0_gate_con_S"]
    halfmultp_Rgateport = opamp_top.ports["commonsource_Pamp_R_multiplier_0_gate_con_S"]
    ptop_halfmultp_gate_route = opamp_top << c_route(pdk, halfmultp_Lgateport, halfmultp_Rgateport, extension=abs(pmos_comps_ref.ymin-halfmultp_Lgateport.center[1])+pdk.get_grule("met5")["min_separation"],fullbottom=True,viaoffset=(False,False))
    # halfmultn to halfmultp drain to drain route
    extensionL = min(halfmultn_drain_routeref.ports["con_W"].center[0],halfmultp_drain_routeref.ports["con_W"].center[0])
    extensionR = max(halfmultn_drain_routeref.ports["con_E"].center[0],halfmultp_drain_routeref.ports["con_E"].center[0])
    opamp_top << c_route(pdk, halfmultn_drain_routeref.ports["con_W"], halfmultp_drain_routeref.ports["con_W"],extension=abs(opamp_top.xmin-extensionL)+2,cwidth=2)
    n_to_p_output_route = opamp_top << c_route(pdk, halfmultn_drain_routeref.ports["con_E"], halfmultp_drain_routeref.ports["con_E"],extension=abs(opamp_top.xmax-extensionR)+2,cwidth=2)
    # top nwell taps to vdd, top p substrate taps to gnd. Keep <3um wide so
    # sky130's m1.3ab huge-metal rule isn't tripped (the rail otherwise
    # picks up tiny mcon neighbours at the diff_pair corners <0.28um away).
    opamp_top << straight_route(pdk, opamp_top.ports["commonsource_cmirror_output_L_tie_N_top_met_N"], opamp_top.ports["pcomps_top_ptap_S_top_met_S"], width=2.5)
    opamp_top << straight_route(pdk, opamp_top.ports["commonsource_cmirror_output_R_tie_N_top_met_N"], opamp_top.ports["pcomps_top_ptap_S_top_met_S"], width=2.5)
    L_toptapn_route = opamp_top.ports["commonsource_Pamp_L_tie_N_top_met_N"]
    R_toptapn_route = opamp_top.ports["commonsource_Pamp_R_tie_N_top_met_N"]
    opamp_top << straight_route(pdk, movex(vddpin.ports["e4"],destination=L_toptapn_route.center[0]), L_toptapn_route, glayer1="met3",fullbottom=True)
    opamp_top << straight_route(pdk, movex(vddpin.ports["e4"],destination=R_toptapn_route.center[0]), R_toptapn_route, glayer1="met3",fullbottom=True)
    # bias pins for first two stages
    vbias1 = opamp_top << rectangle(size=(5,3),layer=pdk.get_glayer("met3"),centered=True)
    vbias1.movey(opamp_top.ymin - _max_metal_seperation_ps - vbias1.ymax)
    opamp_top << straight_route(pdk, vbias1.ports["e2"], opamp_top.ports["diffpair_ibias_B_gate_S"],width=1,fullbottom=False)
    vbias2 = opamp_top << rectangle(size=(5,3),layer=pdk.get_glayer("met5"),centered=True)
    vbias2.movex(1+opamp_top.xmax+evaluate_bbox(vbias2)[0]+pdk.util_max_metal_seperation()).movey(opamp_top.ymin+vbias2.ymax)
    opamp_top << L_route(pdk, halfmultn_gate_routeref.ports["con_E"], vbias2.ports["e2"],hwidth=2)
    # route + and - pins (being careful about antenna violations)
    # The cs_bias↔cs_amp drain c_route at line ~58 places a met3 bridge
    # spanning the full width at y ≈ 16. The minus_pin's L_route from the
    # diff_pair MINUS gate (at y ≈ -1) up to the pin (at y ≈ 18) has a
    # VERTICAL leg on met3 (default = N-facing port layer) at x =
    # diffpair_MINUSgateroute_W_con_N.x. That vertical leg crosses the
    # met3 bridge → VN is shorted to GAIN_STAGE.VOUT. Force the vertical
    # leg onto met4 so it can fly OVER the cs_amp drain bridge.
    minusi_pin = opamp_top << rectangle(size=(5,2),layer=pdk.get_glayer("met3"),centered=True)
    minusi_pin.movex(opamp_top.xmin).movey(_max_metal_seperation_ps + minusi_pin.ymax + halfmultn_drain_routeref.ports["con_W"].center[1] + halfmultn_drain_routeref.ports["con_W"].width/2)
    iport_antenna1 = movex(minusi_pin.ports["e3"],destination=opamp_top.ports["diffpair_MINUSgateroute_W_con_N"].center[0]-9*_max_metal_seperation_ps)
    opamp_top << L_route(pdk, opamp_top.ports["diffpair_MINUSgateroute_W_con_N"],iport_antenna1, vglayer="met5")
    iport_antenna2 = movex(iport_antenna1,offsetx=-9*_max_metal_seperation_ps)
    opamp_top << straight_route(pdk, iport_antenna1, iport_antenna2,glayer1="met4",glayer2="met4",via2_alignment=('c','c'),via1_alignment=('c','c'),fullbottom=True)
    iport_antenna2.layer=pdk.get_glayer("met4")
    opamp_top << straight_route(pdk, iport_antenna2, minusi_pin.ports["e3"],glayer1="met3",via2_alignment=('c','c'),via1_alignment=('c','c'),fullbottom=True)
    plusi_pin = opamp_top << rectangle(size=(5,2),layer=pdk.get_glayer("met3"),centered=True)
    plusi_pin.movex(opamp_top.xmin + plusi_pin.xmax).movey(_max_metal_seperation_ps + minusi_pin.ymax + plusi_pin.ymax)
    iport_antenna1 = movex(plusi_pin.ports["e3"],destination=opamp_top.ports["diffpair_PLUSgateroute_E_con_N"].center[0]-9*_max_metal_seperation_ps)
    opamp_top << L_route(pdk, opamp_top.ports["diffpair_PLUSgateroute_E_con_N"],iport_antenna1)
    iport_antenna2 = movex(iport_antenna1,offsetx=-9*_max_metal_seperation_ps)
    opamp_top << straight_route(pdk, iport_antenna1, iport_antenna2, glayer1="met4",glayer2="met4",via2_alignment=('c','c'),via1_alignment=('c','c'),fullbottom=True)
    iport_antenna2.layer=pdk.get_glayer("met4")
    opamp_top << straight_route(pdk, iport_antenna2, plusi_pin.ports["e3"],glayer1="met3",via2_alignment=('c','c'),via1_alignment=('c','c'),fullbottom=True)
    # route top center components to diffpair
    opamp_top << straight_route(pdk,opamp_top.ports["diffpair_tr_multiplier_0_drain_N"], opamp_top.ports["pcomps_pbottomAB_R_gate_S"], glayer1="met5",width=3*pdk.get_grule("met5")["min_width"],via1_alignment_layer="met2",via1_alignment=('c','c'))
    opamp_top << straight_route(pdk,opamp_top.ports["diffpair_tl_multiplier_0_drain_N"], opamp_top.ports["pcomps_minusvia_top_met_S"], glayer1="met5",width=3*pdk.get_grule("met5")["min_width"],via1_alignment_layer="met2",via1_alignment=('c','c'))
    # route minus transistor drain to output
    outputvia_diff_pcomps = opamp_top << via_stack(pdk,"met5","met4")
    outputvia_diff_pcomps.movex(opamp_top.ports["diffpair_tl_multiplier_0_drain_N"].center[0]).movey(ptop_halfmultp_gate_route.ports["con_E"].center[1])
    # add pin ports
    opamp_top.add_ports(vddpin.get_ports_list(), prefix="pin_vdd_")
    opamp_top.add_ports(vbias1.get_ports_list(), prefix="pin_diffpairibias_")
    opamp_top.add_ports(vbias2.get_ports_list(), prefix="pin_commonsourceibias_")
    opamp_top.add_ports(minusi_pin.get_ports_list(), prefix="pin_minus_")
    opamp_top.add_ports(plusi_pin.get_ports_list(), prefix="pin_plus_")
    #opamp_top.add_ports(output.get_ports_list(), prefix="pin_output_")
    return opamp_top, n_to_p_output_route



@validate_arguments
def __add_mimcap_arr(pdk: MappedPDK, opamp_top: Component, mim_cap_size, mim_cap_rows, ymin: float, n_to_p_output_route) -> tuple[Component, Netlist]:
    mim_cap_size = pdk.snap_to_2xgrid(mim_cap_size, return_type="float")
    max_metalsep = pdk.util_max_metal_seperation()
    mimcaps_ref = opamp_top << mimcap_array(pdk,mim_cap_rows,2,size=mim_cap_size,rmult=6)
    if int(mim_cap_rows) < 1:
        raise ValueError("mim_cap_rows should be a positive integer")
    mimcap_netlist = mimcaps_ref.info['netlist']

    displace_fact = max(max_metalsep,pdk.get_grule("capmet")["min_separation"]) + 0.3 # Hack
    mimcaps_ref.movex(pdk.snap_to_2xgrid(opamp_top.xmax + displace_fact + mim_cap_size[0]/2))
    mimcaps_ref.movey(pdk.snap_to_2xgrid(ymin + mim_cap_size[1]/2))
    # connect mimcap. Match OpenFASOC reference: use the cap plates' native
    # routing layers — V2 (cap_metalbottom) is glayout met4, V1 (cap_metaltop)
    # is glayout met5. The c_route to V2 lands on met4 and the L_route to V1
    # lands on met5, so both via stacks contact the cap plates directly.
    port1 = opamp_top.ports["pcomps_mimcap_connection_con_N"]
    port2 = mimcaps_ref.ports["row"+str(int(mim_cap_rows)-1)+"_col0_top_met_N"]
    cref2_extension = max_metalsep + opamp_top.ymax - max(port1.center[1], port2.center[1])
    opamp_top << c_route(pdk,port1,port2, extension=cref2_extension, fullbottom=True, e1glayer="met3", e2glayer="met5", cglayer="met4", width2=5.0) # A Hack
    intermediate_output = set_port_orientation(n_to_p_output_route.ports["con_S"],"N")
    # opamp_top << L_route(pdk, mimcaps_ref.ports["row0_col0_top_met_N"], intermediate_output, hwidth=1, hglayer="met4", vglayer="met4")
    # C route up right up to reach the mimcap port, extension is 
    opamp_top << L_route(pdk, intermediate_output,
                         mimcaps_ref.ports["row0_col0_top_met_E"], fullbottom=True, vglayer="met5", hglayer="met4") 
    opamp_top.add_ports(mimcaps_ref.get_ports_list(),prefix="mimcap_")
    # add the cs output as a port
    opamp_top.add_port(name="commonsource_output_E", port=intermediate_output)
    return opamp_top, mimcap_netlist

def opamp_gain_stage_netlist(mimcap_netlist: Netlist, diff_cs_netlist: Netlist, cs_bias_netlist: Netlist) -> Netlist:
    netlist = Netlist(
        circuit_name="GAIN_STAGE",
        nodes=['VIN1', 'VIN2', 'VOUT', 'VDD', 'IBIAS', 'GND']
    )

    diff_cs_ref = netlist.connect_netlist(
        diff_cs_netlist,
        [('VSS', 'VDD')]
    )

    netlist.connect_netlist(
        cs_bias_netlist,
        [('VREF', 'IBIAS'), ('VSS', 'GND'), ('VOUT', 'VOUT'), ('B', 'GND')]
    )

    # V1/V2 swapped vs the OpenFASOC reference to match the layout: with
    # the c_route landing on V2 (met4 = cap_metalbottom) tied to the cs_amp
    # output and the L_route landing on V1 (met5 = cap_metaltop) tied to
    # dse VSS2, the cap is symmetric so the schematic just needs to use
    # the same plate assignments.
    mimcap_ref = netlist.connect_netlist(mimcap_netlist, [('V2', 'VOUT'), ('V1', 'VSS2')])

    netlist.connect_subnets(
        mimcap_ref,
        diff_cs_ref,
        [('V1', 'VSS2')]
    )

    return netlist

def opamp_twostage_netlist(input_stage_netlist: Netlist, gain_stage_netlist: Netlist) -> Netlist:
    two_stage_netlist = Netlist(
        circuit_name="OPAMP_TWO_STAGE",
        nodes=['VDD', 'GND', 'DIFFPAIR_BIAS', 'VP', 'VN', 'CS_BIAS', 'VOUT']
    )

    input_stage_ref = two_stage_netlist.connect_netlist(
        input_stage_netlist,
        [('IBIAS', 'DIFFPAIR_BIAS'), ('VSS', 'GND'), ('B', 'GND')]
    )

    gain_stage_ref = two_stage_netlist.connect_netlist(
        gain_stage_netlist,
        [('IBIAS', 'CS_BIAS')]
    )

    two_stage_netlist.connect_subnets(
        input_stage_ref,
        gain_stage_ref,
        [('VDD1', 'VIN1'), ('VDD2', 'VIN2')]
    )

    return two_stage_netlist

def opamp_twostage(
    pdk: MappedPDK,
    half_diffpair_params: tuple[float, float, int] = (6, 1, 4),
    diffpair_bias: tuple[float, float, int] = (6, 2, 4),
    half_common_source_params: tuple[float, float, int, int] = (7, 1, 10, 3),
    half_common_source_bias: tuple[float, float, int, int] = (6, 2, 8, 2),
    half_pload: tuple[float,float,int] = (6,1,6),
    mim_cap_size=(12, 12),
    mim_cap_rows=3,
    rmult: int = 2,
    with_antenna_diode_on_diffinputs: int=5
) -> Component:
    """
    create a two stage opamp, args->
    pdk: pdk to use
    half_diffpair_params: diffpair (width,length,fingers)
    diffpair_bias: bias transistor for diffpair nmos (width,length,fingers). The ref and output of the cmirror are identical
    half_common_source_params: pmos top component amp (width,length,fingers,mults)
    half_common_source_bias: bottom L/R large nmos current mirror (width,length,fingers,mults). The ref of the cmirror always has 1 multplier. multiplier must be >=2
    ****NOTE: change the multiplier option to change the relative sizing of the current mirror ref/output
    half_pload: all 4 pmos load transistors of first stage (width,length,...). The last element in the tuple is the fingers of the bottom two pmos.
    mim_cap_size: width,length of individual mim_cap
    mim_cap_rows: number of rows in the mimcap array (always 2 cols)
    rmult: routing multiplier (larger = wider routes)
    with_antenna_diode_on_diffinputs: adds antenna diodes with_antenna_diode_on_diffinputs*(1um/0.5um) on the positive and negative inputs to the opamp
    """
    # error checks
    if with_antenna_diode_on_diffinputs!=0 and with_antenna_diode_on_diffinputs<2:
        raise ValueError("number of antenna diodes should be at least 2 (or 0 to specify no diodes)")
    if half_common_source_bias[3] < 2:
        raise ValueError("half_common_source_bias num multiplier must be >= 2")
    opamp_top, halfmultn_drain_routeref, halfmultn_gate_routeref, _cref = diff_pair_stackedcmirror(pdk, half_diffpair_params, diffpair_bias, half_common_source_bias, rmult, with_antenna_diode_on_diffinputs)

    opamp_top.info['netlist'].circuit_name = "INPUT_STAGE"

    # place pmos components
    pmos_comps = differential_to_single_ended_converter(pdk, rmult, half_pload, opamp_top.ports["diffpair_tl_multiplier_0_drain_N"].center[0])
    clear_cache()

    pmos_comps = row_csamplifier_diff_to_single_ended_converter(pdk, pmos_comps, half_common_source_params, rmult)

    # The cs_bias layout is __add_common_source_nbias_transistors: per side
    # (L,R) one stacked_nfet_current_mirror call which returns two SEPARATE
    # nmos refs — cmirror_ref (multipliers=1) and cmirror_output (multipliers=
    # half_common_source_bias[3]). With fingers=N and `with_dummy=True`,
    # fet_netlist emits one XMAIN per finger×multiplier and one XDUMMY per
    # side×multiplier; Magic merges parallel devices by connectivity, so the
    # extracted cs_bias has three classes:
    #   ref-class    D=G=IBIAS, S=GND, B=GND  →  m = 2 * fingers
    #   out-class    D=VOUT,    G=IBIAS, S=GND, B=GND  →  m = 2 * fingers * mult
    #   dummy-class  D=G=S=B=GND               →  m = 4 + 4*mult
    # The previous current_mirror_netlist call produced a single flat CMIRROR
    # with the wrong dimensions (diffpair_bias instead of half_common_source_
    # bias) and only ~10 NMOS, leaving ~50 unmatched devices. Hand-build a
    # CMIRROR subckt that mirrors the layout's stacked structure on each side.
    _csb_w = half_common_source_bias[0]
    _csb_l = half_common_source_bias[1]
    _csb_f = half_common_source_bias[2]
    _csb_m = half_common_source_bias[3]
    _nfet_model = pdk.models['nfet']
    # X-prefix at the leaf: sky130's magic+netgen tech setup expects
    # X-instances of `sky130_fd_pr__nfet_01v8`. klayout decks that classify
    # primitive MOSFETs by SPICE prefix (e.g. gf180mcu) get their netlist
    # X→M-rewritten by the LVS runner before extraction — keeps this
    # generator PDK-agnostic.
    cs_bias_netlist = Netlist(
        circuit_name="CMIRROR",
        nodes=['VREF', 'VOUT', 'VSS', 'B'],
        # The body uses Spice subckt-parameter substitution `l={l} w={w}`,
        # which means the `.subckt` header must declare those defaults.
        # In Python str.format() that requires `{{l}}` so the braces survive
        # as literals — see DIFF_TO_SINGLE's netlist for the same pattern.
        source_netlist=(
            ".subckt {circuit_name} {nodes} "
            + f"l={_csb_l} w={_csb_w} mr={_csb_f} mo={_csb_f * _csb_m} "
            + f"dr={2} do={2 * _csb_m}\n"
            + "XREFL VREF VREF VSS B {model} l={{l}} w={{w}} m={{mr}}\n"
            + "XREFR VREF VREF VSS B {model} l={{l}} w={{w}} m={{mr}}\n"
            + "XOUTL VOUT VREF VSS B {model} l={{l}} w={{w}} m={{mo}}\n"
            + "XOUTR VOUT VREF VSS B {model} l={{l}} w={{w}} m={{mo}}\n"
            + "XDREFL B B B B {model} l={{l}} w={{w}} m={{dr}}\n"
            + "XDREFR B B B B {model} l={{l}} w={{w}} m={{dr}}\n"
            + "XDOUTL B B B B {model} l={{l}} w={{w}} m={{do}}\n"
            + "XDOUTR B B B B {model} l={{l}} w={{w}} m={{do}}\n"
            + ".ends {circuit_name}"
        ),
        instance_format=(
            "X{name} {nodes} {circuit_name} l={length} w={width} "
            "mr={mr} mo={mo} dr={dr} do={do}"
        ),
        parameters={
            'model': _nfet_model,
            'width': _csb_w,
            'length': _csb_l,
            'mr': _csb_f,
            'mo': _csb_f * _csb_m,
            'dr': 2,
            'do': 2 * _csb_m,
        }
    )

    ydim_ncomps = opamp_top.ymax
    pmos_comps_ref = opamp_top << pmos_comps
    pmos_comps_ref.movey(round(ydim_ncomps + pmos_comps_ref.ymax+10))
    opamp_top.add_ports(pmos_comps_ref.get_ports_list(),prefix="pcomps_")
    rename_func = lambda name_, port_ : name_.replace("pcomps_halfpspecialmarker","commonsource_Pamp") if name_.startswith("pcomps_halfpspecialmarker") else name_
    opamp_top = rename_component_ports(opamp_top, rename_function=rename_func)
    # create pins and route
    clear_cache()
    opamp_top, n_to_p_output_route = __create_and_route_pins(pdk, opamp_top, pmos_comps_ref, halfmultn_drain_routeref, halfmultn_gate_routeref)
    # place mimcaps and route
    clear_cache()
    opamp_top, mimcap_netlist = __add_mimcap_arr(pdk, opamp_top, mim_cap_size, mim_cap_rows, pmos_comps_ref.ymin, n_to_p_output_route)
    opamp_top.add_ports(n_to_p_output_route.get_ports_list(),"special_con_npr_")
    # return
    opamp_top.add_ports(_cref.get_ports_list(), prefix="gnd_route_")

    pmos_comps.info['netlist'] = opamp_gain_stage_netlist(mimcap_netlist, pmos_comps.info['netlist'], cs_bias_netlist)
    opamp_top.info['netlist'] = opamp_twostage_netlist(opamp_top.info['netlist'], pmos_comps.info['netlist'])

    return opamp_top

