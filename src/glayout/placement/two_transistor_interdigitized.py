from glayout.pdk.mappedpdk import MappedPDK
from pydantic import validate_arguments
from glayout.backend import Component, clear_cache, rectangle, transformed
from glayout.primitives.fet import nmos, pmos, multiplier
from glayout.util.comp_utils import evaluate_bbox
from typing import Literal, Union
from glayout.util.port_utils import rename_ports_by_orientation, rename_ports_by_list, create_private_ports
from glayout.util.comp_utils import prec_ref_center,evaluate_bbox, prec_center, align_comp_to_port
from glayout.routing.straight_route import straight_route
from glayout.primitives.guardring import tapring
from glayout.util.port_utils import add_ports_perimeter
from typing import Literal, Optional, Union
from glayout.pdk.sky130_mapped import sky130_mapped_pdk
from glayout.pdk.gf180_mapped import gf180_mapped_pdk
from glayout.spice.netlist import Netlist
from glayout.primitives.via_gen import via_stack
from glayout.routing.c_route import c_route
#from glayout.placement.two_transistor_interdigitized import two_nfet_interdigitized; from glayout.pdk.sky130_mapped import sky130_mapped_pdk as pdk; biasParams=[6,2,4]; rmult=2
def add_two_int_labels(two_int_in: Component,
                pdk: MappedPDK 
                ) -> Component:
	
    two_int_in.unlock()

    # list that will contain all port/comp info
    move_info = list()
    # create labels and append to info list
    # vss1
    vss1label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vss1label.add_label(text="VSS1",layer=pdk.get_glayer("met2_label"))
    move_info.append((vss1label,two_int_in.ports["A_source_E"],None))
    # vss2
    vss2label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vss2label.add_label(text="VSS2",layer=pdk.get_glayer("met2_label"))
    move_info.append((vss2label,two_int_in.ports["B_source_E"],None))
    # vdd1
    vdd1label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vdd1label.add_label(text="VDD1",layer=pdk.get_glayer("met2_label"))
    move_info.append((vdd1label,two_int_in.ports["A_drain_N"],None))
    # vdd2
    vdd2label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vdd2label.add_label(text="VDD2",layer=pdk.get_glayer("met2_label"))
    move_info.append((vdd2label,two_int_in.ports["B_drain_N"],None))
    
    # vg1
    vg1label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vg1label.add_label(text="VG1",layer=pdk.get_glayer("met2_label"))
    move_info.append((vg1label,two_int_in.ports["A_gate_S"],None))
    # vg2
    vg2label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vg2label.add_label(text="VG2",layer=pdk.get_glayer("met2_label"))
    move_info.append((vg2label,two_int_in.ports["B_gate_S"],None))
    
    # VB
    vblabel = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.5,0.5),centered=True).copy()
    vblabel.add_label(text="VB",layer=pdk.get_glayer("met2_label"))
    move_info.append((vblabel,two_int_in.ports["welltie_S_top_met_S"], None))
    
    # move everything to position
    for comp, prt, alignment in move_info:
        alignment = ('c','b') if alignment is None else alignment
        compref = align_comp_to_port(comp, prt, alignment=alignment)
        two_int_in.add(compref)
    return two_int_in.flatten() 


TERMINALS = ("A_source", "A_drain", "A_gate", "B_source", "B_drain", "B_gate")


def interdigitized_nets(nets: Optional[dict] = None, shared_gate: bool = False) -> dict:
    """Complete terminal -> net map. Missing terminals get their own net (their
    own name), so ``None`` means six distinct nets: two independent devices."""
    out = {t: t for t in TERMINALS}
    out.update(nets or {})
    unknown = set(out) - set(TERMINALS)
    if unknown:
        raise ValueError(f"unknown terminals {sorted(unknown)}; use {TERMINALS}")
    if shared_gate:
        out["B_gate"] = out["A_gate"]
    for dev in "AB":
        if out[f"{dev}_source"] == out[f"{dev}_drain"]:
            raise ValueError(f"device {dev}: source and drain are the same net {out[dev + '_source']!r}")
    return out


def two_tran_interdigitized_netlist(
    pdk: MappedPDK,
    width: float,
    length: float,
    fingers: int,
    multipliers: int,
    with_dummy: True,
    n_or_p_fet: Optional[str] = 'nfet',
    subckt_only: Optional[bool] = False,
    dummies_tied_to_bulk: bool = True,
    shared_gate: bool = False,
    nets: Optional[dict] = None,
) -> Netlist:
    # Terminals on one net (``nets``/``shared_gate``, see macro_two_transistor_interdigitized)
    # share one rail in the layout, so they share one pin here: the pin of the first such
    # terminal in VDD1 VDD2 VSS1 VSS2 VG1 VG2 order. E.g. shared_gate drops VG2; a current
    # mirror (shared source, diode-connected A) keeps only VDD1 VDD2 VSS1 VB.
    if length is None:
        length = pdk.get_grule('poly')['min_width']
    if width is None:
        width = 3
    model = pdk.models[n_or_p_fet]
    mtop = fingers * multipliers

    # `dummies_tied_to_bulk` controls where the cmirror's dummies' G/S/D
    # land. The standalone current_mirror cell adds a straight_route from
    # the dummies' gsdcon to the welltie ring, so the layout extracts them
    # on bulk (VB) — pass True (the default). When this same cmirror is
    # built without that routing (e.g. via raw two_nfet_interdigitized in
    # diff_pair_ibias / opamp's cs_bias), the layout leaves the dummies'
    # G/S/D on a per-cmirror floating net; pass False so the schematic
    # uses a local 'cmdum' net that --combine collapses to one device.
    dum_node = "VB" if dummies_tied_to_bulk else "cmdum"
    # X-prefix is sky130's magic+netgen tech expectation; klayout decks
    # that classify primitive MOSFETs by SPICE prefix get their netlist
    # X→M-rewritten by the LVS runner.
    terms = interdigitized_nets(nets, shared_gate)
    canonical = [("A_drain", "VDD1"), ("B_drain", "VDD2"), ("A_source", "VSS1"), ("B_source", "VSS2"),
                 ("A_gate", "VG1"), ("B_gate", "VG2")]
    first = {}
    for t, pin in canonical:
        first.setdefault(terms[t], pin)
    pin = {t: first[terms[t]] for t, _ in canonical}
    pins = [p for _, p in canonical if p in first.values()]
    source_netlist = """.subckt {circuit_name} {nodes} """ + f'l={length} w={width} m={1} '+ f"""
XA {pin['A_drain']} {pin['A_gate']} {pin['A_source']} VB {model} l={length} w={width} m={mtop}
XB {pin['B_drain']} {pin['B_gate']} {pin['B_source']} VB {model} l={length} w={width} m={mtop}"""
    if with_dummy:
        source_netlist += f"\nXDUMMY {dum_node} {dum_node} {dum_node} VB {model} l={length} w={width} m={2}"
    source_netlist += "\n.ends {circuit_name}"

    instance_format = "X{name} {nodes} {circuit_name} l={length} w={width} m={{1}}"

    return Netlist(
        circuit_name='two_trans_interdigitized',
        nodes=pins + ['VB'],
        source_netlist=source_netlist,
        instance_format=instance_format,
        parameters={
            'model': model,
            'width': width,
            'length': length,
            'mult': multipliers
        }
    )
@validate_arguments
def macro_two_transistor_interdigitized(
    pdk: MappedPDK,
    numcols: int,
    deviceA_and_B: Literal["nfet", "pfet"],
    dummy: Union[bool, tuple[bool, bool]] = True,
    shared_gate: bool = False,
    nets: Optional[dict] = None,
    diode_tie_side: Literal["W", "E"] = "W",
    diode_tie_viaoffset: Optional[bool] = False,
    rail_order: Optional[list] = None,
    **kwargs
) -> Component:
    """place two transistors in a single row with interdigitized placement
    Currently only supports two of the same transistor (same devices)
    Place follows an ABABAB... pattern
    args:
    pdk = MappedPDK to use
    numcols = a single col is actually one col for both transistors (so AB). 2 cols = ABAB ... so on
    deviceA_and_B = the device to place for both transistors (either nfet or pfet)
    dummy = place dummy at the edges of the interdigitized place (true by default). you can specify tuple to place only on one side
    nets = terminal -> net map over A_source, A_drain, A_gate, B_source, B_drain, B_gate (missing
        terminals are distinct nets). Rails are drawn per *net*, not per terminal: terminals on the
        same net share one rail and their ports alias it (e.g. a current mirror has three source/drain
        rails, VSS/VREF/VOUT, and one gate rail). Where a gate net is also a source/drain net (a diode
        connection) the macro draws the one C route that joins the two rails, on ``diode_tie_side``.
    shared_gate = shorthand for nets with B_gate == A_gate. default False
    diode_tie_side = side of the row for diode-connection C routes. default W
    diode_tie_viaoffset = c_route viaoffset for those ties. False (default) suits met2 rails; with
        met3 rails it leaves a ~30nm gap between via and stub (sky130 m2.2, and an open), use None
    rail_order = source/drain nets bottom to top (default: A_source, A_drain, then B's other nets).
        Use it to keep side connections of different nets off adjacent rails when their vias are
        bigger than a rail pitch allows (sky130 met3->met4 vias have a 1.5um met4 pad)
    kwargs = key word arguments for device.
    ****NOTE: These are the same as glayout.flow.primitives.fet.multiplier arguments EXCLUDING dummy, sd_route_extension, and pdk options

    source/drain rails stack above the row one rail pitch (rail height + spacing) apart, in the order
    A_source, A_drain, then B's nets that are not already there; B's gate rail, if B has its own gate
    net, sits one metal spacing below A's.
    """
    nets = interdigitized_nets(nets, shared_gate)
    shared_gate = nets["A_gate"] == nets["B_gate"]
    if isinstance(dummy, bool):
        dummy = (dummy, dummy)
    # override kwargs for needed options
    kwargs["sd_route_extension"] = 0
    kwargs["gate_route_extension"] = 0
    kwargs["sdlayer"] = "n+s/d" if deviceA_and_B == "nfet" else "p+s/d"
    kwargs["pdk"] = pdk
    # create devices dummy l/r and A/B (change extension options)
    kwargs["dummy"] = (True,False) if dummy[0] else False
    lefttmost_devA = multiplier(**kwargs)
    kwargs["dummy"] = False
    center_devA = multiplier(**kwargs)
    # rail levels: one level per distinct source/drain net (default: A's source 0, A's drain 1)
    sd_order = []
    for t in ("A_source", "A_drain", "B_source", "B_drain"):
        if nets[t] not in sd_order:
            sd_order.append(nets[t])
    if rail_order is not None:
        if sorted(rail_order) != sorted(sd_order):
            raise ValueError(f"rail_order {rail_order} must list the source/drain nets {sd_order} once each")
        sd_order = list(rail_order)
    level = {t: sd_order.index(nets[t]) for t in ("A_source", "A_drain", "B_source", "B_drain")}
    # one rail pitch = the distance multiplier already keeps between its source and drain rails
    sd_pitch = center_devA.ports["drain_W"].center[1] - center_devA.ports["source_W"].center[1]
    if (level["A_source"], level["A_drain"]) != (0, 1):
        kwargs["source_route_extension"] = pdk.snap_to_2xgrid(level["A_source"] * sd_pitch)
        kwargs["drain_route_extension"] = pdk.snap_to_2xgrid((level["A_drain"] - 1) * sd_pitch)
        kwargs["dummy"] = (True,False) if dummy[0] else False
        lefttmost_devA = multiplier(**kwargs)
        kwargs["dummy"] = False
        center_devA = multiplier(**kwargs)
    kwargs["source_route_extension"] = pdk.snap_to_2xgrid(level["B_source"] * sd_pitch)
    kwargs["drain_route_extension"] = pdk.snap_to_2xgrid((level["B_drain"] - 1) * sd_pitch)
    # B's own gate rail: its bar top one max metal spacing below A's bar bottom
    devB_gate_extension = abs(center_devA.ports["row0_col0_gate_S"].center[1]-center_devA.ports["gate_S"].center[1])
    kwargs["gate_route_extension"] = 0 if shared_gate else pdk.snap_to_2xgrid(devB_gate_extension)
    center_devB = multiplier(**kwargs)
    kwargs["dummy"] = (False,True) if dummy[1] else False
    rightmost_devB = multiplier(**kwargs)
    # place devices
    idplace = Component()
    dims = evaluate_bbox(center_devA)
    xdisp = pdk.snap_to_2xgrid(dims[0]+pdk.get_grule("active_diff")["min_separation"])
    refs = list()
    for i in range(2*numcols):
        if i==0:
            refs.append(idplace << lefttmost_devA)
        elif i==((2*numcols)-1):
            refs.append(idplace << rightmost_devB)
        elif i%2: # is odd (so device B)
            refs.append(idplace << center_devB)
        else: # not i%2 == i is even (so device A)
            refs.append(idplace << center_devA)
        refs[-1].movex(i*(xdisp))
        devletter = "B" if i%2 else "A"
        prefix=devletter+"_"+str(int(i/2))+"_"
        idplace.add_ports(refs[-1].get_ports_list(), prefix=prefix)
    # owner terminal of each rail: the first terminal on that net; A rails start at the
    # leftmost A, B rails at the rightmost B (as before)
    def _rail_ports(t: str):
        dev, term = t.split("_")
        if dev == "A":
            return refs[0].ports[f"{term}_W"], refs[-1].ports[f"{term}_E"]
        return refs[-1].ports[f"{term}_E"], refs[0].ports[f"{term}_W"]
    sd_owner = {}
    for t in ("A_source", "A_drain", "B_source", "B_drain"):
        sd_owner.setdefault(nets[t], t)
    top_rail = sd_owner[sd_order[-1]]
    top_port = _rail_ports(top_rail)[0]
    # extend s/d risers to the top rail and gate poly to the lowest gate rail, for equal parasitics
    for i in range(2*numcols):
        desired_end_layer = pdk.layer_to_glayer(refs[i].ports["row0_col0_rightsd_top_met_N"].layer)
        idplace << straight_route(pdk, refs[i].ports["row0_col0_rightsd_top_met_N"],top_port,glayer2=desired_end_layer)
        idplace << straight_route(pdk, refs[i].ports["leftsd_top_met_N"],top_port,glayer2=desired_end_layer)
        # with a shared gate rail, A and B gate poly already have equal length
        if not i%2 and not shared_gate:
            desired_gate_end_layer = "poly"
            idplace << straight_route(pdk, refs[i].ports["row0_col0_gate_S"], refs[-1].ports["gate_E"],glayer2=desired_gate_end_layer)
    # merge s/d layer for all transistors
    idplace << straight_route(pdk, refs[0].ports["plusdoped_W"],refs[-1].ports["plusdoped_E"])
    # one row-wide rail per net: source/drain rails above the row, gate rails below
    def _rail(t: str):
        return idplace << rename_ports_by_orientation(rename_ports_by_list(straight_route(pdk, *_rail_ports(t)), [("route_","_")]))
    gate_owner = {}
    for t in ("A_gate", "B_gate"):
        gate_owner.setdefault(nets[t], t)
    rails = {("sd", net): _rail(sd_owner[net]) for net in sd_order}
    rails.update({("gate", net): _rail(t) for net, t in gate_owner.items()})
    def _rail_of(t: str):
        return rails[("gate" if t.endswith("gate") else "sd", nets[t])]
    # add route ports (terminals on the same net alias one rail) and return
    prefixes = ["A_source","B_source","A_drain","B_drain","A_gate","B_gate"]
    for t in prefixes:
        idplace.add_ports(_rail_of(t).get_ports_list(),prefix=t)
    # diode connections: a gate rail (below the row) joined to the source/drain rail (above) of the same net
    maxsep = pdk.util_max_metal_seperation()
    ties = [net for net in gate_owner if net in sd_owner]
    for i, net in enumerate(ties):
        side = diode_tie_side if i % 2 == 0 else ("E" if diode_tie_side == "W" else "W")
        idplace << c_route(pdk, idplace.ports[f"{sd_owner[net]}_{side}"], idplace.ports[f"{gate_owner[net]}_{side}"],
                           extension=(3 + 4 * (i // 2)) * maxsep, viaoffset=diode_tie_viaoffset)
    idplace = transformed(prec_ref_center(idplace))
    idplace.unlock()
    idplace.add_ports(create_private_ports(idplace, prefixes))
    idplace.info["nets"] = dict(nets)
    idplace.info["sd_rails"] = list(sd_order)
    idplace.info["diode_ties"] = ties
    return idplace


@validate_arguments
def two_nfet_interdigitized(
    pdk: MappedPDK,
    numcols: int,
    dummy: Union[bool, tuple[bool, bool]] = True,
    with_substrate_tap: bool = True,
    with_tie: bool = True,
    tie_layers: tuple[str,str]=("met2","met1"),
    **kwargs
) -> Component:
    """Currently only supports two of the same nfet instances. does NOT support multipliers (currently)
    Place follows an ABABAB... pattern
    args:
    pdk = MappedPDK to use
    numcols = a single col is actually one col for both nfets (so AB). 2 cols = ABAB ... so on
    dummy = place dummy at the edges of the interdigitized place (true by default). you can specify tuple to place only on one side
    kwargs = key word arguments for multiplier. 
    ****NOTE: These are the same as glayout.flow.primitives.fet.multiplier arguments EXCLUDING dummy, sd_route_extension, and pdk options
    tie_layers: tuple[str,str] specifying (horizontal glayer, vertical glayer) or well tie ring. default=("met2","met1")
    """
    base_multiplier = macro_two_transistor_interdigitized(pdk, numcols, "nfet", dummy, **kwargs)
    # tie
    if with_tie:
        tap_separation = max(
            pdk.util_max_metal_seperation(),
            pdk.get_grule("active_diff", "active_tap")["min_separation"],
        )
        tap_separation += pdk.get_grule("p+s/d", "active_tap")["min_enclosure"]
        tap_encloses = (
            2 * (tap_separation + base_multiplier.xmax),
            2 * (tap_separation + base_multiplier.ymax),
        )
        tiering_ref = base_multiplier << tapring(
            pdk,
            enclosed_rectangle=tap_encloses,
            sdlayer="p+s/d",
            horizontal_glayer=tie_layers[0],
            vertical_glayer=tie_layers[1],
        )
        base_multiplier.add_ports(tiering_ref.get_ports_list(), prefix="welltie_")
        try:
            base_multiplier<<straight_route(pdk,base_multiplier.ports["A_0_dummy_L_gsdcon_top_met_W"],base_multiplier.ports["welltie_W_top_met_W"],glayer2="met1")
        except KeyError:
            pass
        try:
            base_multiplier<<straight_route(pdk,base_multiplier.ports[f"B_{numcols-1}_dummy_R_gsdcon_top_met_E"],base_multiplier.ports["welltie_E_top_met_E"],glayer2="met1")
        except KeyError:
            pass
    # add pwell
    base_multiplier.add_padding(
        layers=(pdk.get_glayer("pwell"),),
        default=pdk.get_grule("pwell", "active_tap")["min_enclosure"],
    )
    # add substrate tap
    base_multiplier = add_ports_perimeter(base_multiplier,layer=pdk.get_glayer("pwell"),prefix="well_")
    # add substrate tap if with_substrate_tap
    if with_substrate_tap:
        substrate_tap_separation = pdk.get_grule("dnwell", "active_tap")[
            "min_separation"
        ]
        substrate_tap_encloses = (
            2 * (substrate_tap_separation + base_multiplier.xmax),
            2 * (substrate_tap_separation + base_multiplier.ymax),
        )
        ringtoadd = tapring(
            pdk,
            enclosed_rectangle=substrate_tap_encloses,
            sdlayer="p+s/d",
            horizontal_glayer="met2",
            vertical_glayer="met1",
        )
        tapring_ref = base_multiplier << ringtoadd
        base_multiplier.add_ports(tapring_ref.get_ports_list(),prefix="substratetap_")
    base_multiplier.info["route_genid"] = "two_transistor_interdigitized"

    base_multiplier.info['netlist'] = two_tran_interdigitized_netlist(
        pdk,
        width=kwargs.get('width', 3), length=kwargs.get('length'), fingers=kwargs.get('fingers', 1), multipliers=numcols, with_dummy=dummy,
        n_or_p_fet="nfet",
        subckt_only=True,
        shared_gate=kwargs.get('shared_gate', False),
        nets=kwargs.get('nets'),
    )
    return base_multiplier



@validate_arguments
def two_pfet_interdigitized(
    pdk: MappedPDK,
    numcols: int,
    dummy: Union[bool, tuple[bool, bool]] = True,
    with_substrate_tap: bool = True,
    with_tie: bool = True,
    tie_layers: tuple[str,str]=("met2","met1"),
    **kwargs
) -> Component:
    """Currently only supports two of the same nfet instances. does NOT support multipliers (currently)
    Place follows an ABABAB... pattern
    args:
    pdk = MappedPDK to use
    numcols = a single col is actually one col for both nfets (so AB). 2 cols = ABAB ... so on
    dummy = place dummy at the edges of the interdigitized place (true by default). you can specify tuple to place only on one side
    kwargs = key word arguments for multiplier. 
    ****NOTE: These are the same as glayout.flow.primitives.fet.multiplier arguments EXCLUDING dummy, sd_route_extension, and pdk options
    tie_layers: tuple[str,str] specifying (horizontal glayer, vertical glayer) or well tie ring. default=("met2","met1")
    """
    base_multiplier = macro_two_transistor_interdigitized(pdk, numcols, "pfet", dummy, **kwargs)
    # tie
    if with_tie:
        tap_separation = max(
            pdk.util_max_metal_seperation(),
            pdk.get_grule("active_diff", "active_tap")["min_separation"],
        )
        tap_separation += pdk.get_grule("n+s/d", "active_tap")["min_enclosure"] 
        tap_encloses = (
            2 * (tap_separation + base_multiplier.xmax),
            2 * (tap_separation + base_multiplier.ymax),
        )
        tiering_ref = base_multiplier << tapring(
            pdk,
            enclosed_rectangle=tap_encloses,
            sdlayer="n+s/d",
            horizontal_glayer=tie_layers[0],
            vertical_glayer=tie_layers[1],
        )
        base_multiplier.add_ports(tiering_ref.get_ports_list(), prefix="welltie_")
        try:
            base_multiplier<<straight_route(pdk,base_multiplier.ports["A_0_dummy_L_gsdcon_top_met_W"],base_multiplier.ports["welltie_W_top_met_W"],glayer2="met1")
        except KeyError:
            pass
        try:
            base_multiplier<<straight_route(pdk,base_multiplier.ports[f"B_{numcols-1}_dummy_R_gsdcon_top_met_E"],base_multiplier.ports["welltie_E_top_met_E"],glayer2="met1")
        except KeyError:
            pass
    # add pwell
    base_multiplier.add_padding(
        layers=(pdk.get_glayer("nwell"),),
        default=pdk.get_grule("nwell", "active_tap")["min_enclosure"],
    )
    # add substrate tap
    base_multiplier = add_ports_perimeter(base_multiplier,layer=pdk.get_glayer("nwell"),prefix="well_")
    # add substrate tap if with_substrate_tap
    if with_substrate_tap:
        substrate_tap_separation = pdk.get_grule("dnwell", "active_tap")[
            "min_separation"
        ]
        substrate_tap_encloses = (
            2 * (substrate_tap_separation + base_multiplier.xmax),
            2 * (substrate_tap_separation + base_multiplier.ymax),
        )
        ringtoadd = tapring(
            pdk,
            enclosed_rectangle=substrate_tap_encloses,
            sdlayer="p+s/d",
            horizontal_glayer="met2",
            vertical_glayer="met1",
        )
        tapring_ref = base_multiplier << ringtoadd
        base_multiplier.add_ports(tapring_ref.get_ports_list(),prefix="substratetap_")
    base_multiplier.info["route_genid"] = "two_transistor_interdigitized"

    base_multiplier.info['netlist'] = two_tran_interdigitized_netlist(
        pdk,
        width=kwargs.get('width', 3), length=kwargs.get('length'), fingers=kwargs.get('fingers', 1), multipliers=numcols, with_dummy=dummy,
        n_or_p_fet="pfet",
        subckt_only=True,
        shared_gate=kwargs.get('shared_gate', False),
        nets=kwargs.get('nets'),
    )
    return base_multiplier




def two_transistor_interdigitized(
    pdk: MappedPDK,
    device: Literal["nfet","pfet"],
    numcols: int,
    dummy: Union[bool, tuple[bool, bool]] = True,
    with_substrate_tap: bool = True,
    with_tie: bool = True,
    tie_layers: tuple[str,str]=("met2","met1"),
    **kwargs
) -> Component:
    if device=="nfet":
        return two_nfet_interdigitized(pdk=pdk,numcols=numcols,dummy=dummy,with_substrate_tap=with_substrate_tap,with_tie=with_tie,tie_layers=tie_layers,**kwargs)
    else:
        return two_pfet_interdigitized(pdk=pdk,numcols=numcols,dummy=dummy,with_substrate_tap=with_substrate_tap,with_tie=with_tie,tie_layers=tie_layers,**kwargs)

def rail_tap(pdk: MappedPDK, port, extension: float, glayer_up: Optional[str] = None) -> Component:
    """A tap on one rail end: the rail continued by ``extension`` beyond ``port``
    (an E- or W-facing rail port) and a via up to ``glayer_up`` (default: one
    metal above the rail).

    It replaces the C route that used to short two rails of one net only to get
    a tap point: with net-aware rails there is one rail, so only the tap is
    left. Ports ``con_{N,E,S,W}`` are the via's top-metal edges, as on c_route.
    """
    lay = pdk.layer_to_glayer(port.layer)
    up = glayer_up or f"met{int(lay[-1]) + 1}"
    direction = {0: 1, 180: -1}[round(port.orientation) % 360]
    tap = Component("rail_tap")
    via = via_stack(pdk, lay, up, fullbottom=True)
    cx = pdk.snap_to_2xgrid(port.center[0] + direction * (extension + evaluate_bbox(via)[0] / 2))
    x0, x1 = sorted((port.center[0], cx))
    stub = tap << rectangle(size=(x1 - x0, port.width), layer=pdk.get_glayer(lay), centered=True)
    stub.move(((x0 + x1) / 2, port.center[1]))
    vref = tap << via
    vref.move((cx, port.center[1]))
    for p in vref.get_ports_list():
        if p.name.startswith("top_met_"):
            q = p.copy()
            q.name = "con_" + p.name[len("top_met_"):]
            tap.add_port(port=q)
    return tap
