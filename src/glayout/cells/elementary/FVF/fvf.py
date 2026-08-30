from typing import Optional
from glayout.pdk.mappedpdk import MappedPDK
from glayout.pdk.sky130_mapped import sky130_mapped_pdk
from glayout.backend import Component, cell, rectangle
from glayout.primitives.fet import nmos, pmos, multiplier
from glayout.util.comp_utils import evaluate_bbox, prec_center, prec_ref_center, align_comp_to_port
from glayout.util.snap_to_grid import component_snap_to_grid
from glayout.util.port_utils import rename_ports_by_orientation
from glayout.routing.straight_route import straight_route
from glayout.routing.c_route import c_route
from glayout.routing.L_route import L_route
from glayout.primitives.guardring import tapring
from glayout.util.port_utils import add_ports_perimeter
from glayout.spice.netlist import Netlist
from glayout.primitives.via_gen import via_stack
try:
    from glayout.verification.evaluator_wrapper import run_evaluation
except ImportError:
    print("Warning: evaluator_wrapper not found. Evaluation will be skipped.")
    run_evaluation = None

def get_component_netlist(component):
    """Helper function to get netlist object from component info, compatible with all gdsfactory versions"""
    from glayout.spice.netlist import Netlist
    
    # Try to get stored object first (for older gdsfactory versions)
    if 'netlist_obj' in component.info:
        return component.info['netlist_obj']
    
    # Try to reconstruct from netlist_data (for newer gdsfactory versions)
    if 'netlist_data' in component.info:
        data = component.info['netlist_data']
        netlist = Netlist(
            circuit_name=data['circuit_name'],
            nodes=data['nodes']
        )
        netlist.source_netlist = data['source_netlist']
        return netlist
    
    # Fallback: return the string representation (should not happen in normal operation)
    return component.info.get('netlist', '')

def fvf_netlist(fet_1: Component, fet_2: Component) -> Netlist:

         netlist = Netlist(circuit_name='FLIPPED_VOLTAGE_FOLLOWER', nodes=['VIN', 'VBULK', 'VOUT', 'Ib'])

         # Both fets' dummies tie to VBULK:
         # * sky130 magic absorbs floating dummies into the bulk during
         #   parallel-device merging, so DUM=VBULK matches the extraction.
         # * gf180 klayout: add_fvf_labels now stamps VBULK on BOTH fets'
         #   welltie rings, so the dummies' G/S/D (which physically connect
         #   to the welltie metal via the inter-finger diffusion contacts)
         #   end up on the labeled VBULK net.
         fet_1_netlist = get_component_netlist(fet_1)
         fet_2_netlist = get_component_netlist(fet_2)
         netlist.connect_netlist(fet_1_netlist, [('D', 'Ib'), ('G', 'VIN'), ('S', 'VOUT'), ('B', 'VBULK'), ('DUM', 'VBULK')])
         netlist.connect_netlist(fet_2_netlist, [('D', 'VOUT'), ('G', 'Ib'), ('S', 'VBULK'), ('B', 'VBULK'), ('DUM', 'VBULK')])

         return netlist



def sky130_add_fvf_labels(fvf_in: Component) -> Component:

    fvf_in.unlock()
    # define layers`
    met1_pin = (68,16)
    met1_label = (68,5)
    met2_pin = (69,16)
    met2_label = (69,5)
    # list that will contain all port/comp info
    move_info = list()
    # create labels and append to info list
    # gnd
    gnd2label = rectangle(layer=met1_pin,size=(0.5,0.5),centered=True).copy()
    gnd2label.add_label(text="VBULK",layer=met1_label)
    move_info.append((gnd2label,fvf_in.ports["B_tie_N_top_met_N"],None))

    #currentbias
    ibiaslabel = rectangle(layer=met2_pin,size=(0.5,0.5),centered=True).copy()
    ibiaslabel.add_label(text="Ib",layer=met2_label)
    move_info.append((ibiaslabel,fvf_in.ports["A_drain_bottom_met_N"],None))

    # output (3rd stage)
    outputlabel = rectangle(layer=met2_pin,size=(0.5,0.5),centered=True).copy()
    outputlabel.add_label(text="VOUT",layer=met2_label)
    move_info.append((outputlabel,fvf_in.ports["A_source_bottom_met_N"],None))

    # input
    inputlabel = rectangle(layer=met1_pin,size=(0.5,0.5),centered=True).copy()
    inputlabel.add_label(text="VIN",layer=met1_label)
    move_info.append((inputlabel,fvf_in.ports["A_multiplier_0_gate_N"], None))

    # move everything to position
    for comp, prt, alignment in move_info:
        alignment = ('c','b') if alignment is None else alignment
        compref = align_comp_to_port(comp, prt, alignment=alignment)
        fvf_in.add(compref)
    return fvf_in.flatten()


def add_fvf_labels(fvf_in: Component, pdk: MappedPDK) -> Component:
    """PDK-aware FVF label adder. Welltie ring & gate sit on glayout met2;
    drain/source via tops sit on glayout met3 (via_stack(met2,met3))."""
    fvf_in.unlock()
    move_info = list()

    # VBULK — stamp on BOTH fets' welltie rings so klayout's gf180 deck
    # binds both pwells (fet_1 + fet_2) to the same VBULK net. Without
    # the fet_1-side stamp, the input fet's dummies and other floating
    # diffusion areas land on a per-cell auto-named net, which breaks the
    # schematic-vs-layout dummy match (the schematic puts both fets'
    # dummies on the bulk via the welltie ring's own substrate contact).
    for _portname in ("A_tie_N_top_met_N", "B_tie_N_top_met_N"):
        if _portname not in fvf_in.ports:
            continue
        vbulklabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=(0.5,0.5), centered=True).copy()
        vbulklabel.add_label(text="VBULK", layer=pdk.get_glayer("met2_label"))
        # ('c','c') keeps the label inside the welltie metal regardless of
        # port orientation (south-facing ports + 'b' default would land
        # the rectangle below the ring with no underlying metal).
        move_info.append((vbulklabel, fvf_in.ports[_portname], ('c','c')))

    # Ib — drain via top (glayout met3)
    ibiaslabel = rectangle(layer=pdk.get_glayer("met3_pin"), size=(0.5,0.5), centered=True).copy()
    ibiaslabel.add_label(text="Ib", layer=pdk.get_glayer("met3_label"))
    move_info.append((ibiaslabel, fvf_in.ports["A_drain_bottom_met_N"], None))

    # VOUT — source via top (glayout met3)
    voutlabel = rectangle(layer=pdk.get_glayer("met3_pin"), size=(0.5,0.5), centered=True).copy()
    voutlabel.add_label(text="VOUT", layer=pdk.get_glayer("met3_label"))
    move_info.append((voutlabel, fvf_in.ports["A_source_bottom_met_N"], None))

    # VIN — gate (glayout met2)
    vinlabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=(0.5,0.5), centered=True).copy()
    vinlabel.add_label(text="VIN", layer=pdk.get_glayer("met2_label"))
    move_info.append((vinlabel, fvf_in.ports["A_multiplier_0_gate_N"], None))

    for comp, prt, alignment in move_info:
        alignment = ('c','b') if alignment is None else alignment
        compref = align_comp_to_port(comp, prt, alignment=alignment)
        fvf_in.add(compref)
    return fvf_in.flatten()

@cell
def  flipped_voltage_follower(
    pdk: MappedPDK,
    device_type: str = "nmos", 
    placement: str = "horizontal",
    width: tuple[float,float] = (6.605703928526579, 3.713220935212418),
    length: tuple[float,float] = (2.3659471990041707, 1.9639325665440608),
    fingers: tuple[int,int] = (1, 1),
    multipliers: tuple[int,int] = (2, 2),
        dummy_1: tuple[bool,bool] = (True,True),
        dummy_2: tuple[bool,bool] = (True,True),
        tie_layers1: tuple[str,str] = ("met1","met1"),
        tie_layers2: tuple[str,str] = ("met1","met1"),
        sd_rmult: int=1,
        **kwargs
        ) -> Component:
    """
    creates a Flipped Voltage Follower
    pdk: pdk to use
    device_type: either "nmos" or "pmos"
    placement: either "horizontal" or "vertical"
    width: (input fet, feedback fet)
    length: (input fet, feedback fet)
    fingers: (input fet, feedback fet)
    multipliers: (input fet, feedback fet)
    dummy_1: dummy for input fet
    dummy_2: dummy for feedback fet
    tie_layers1: tie layers for input fet
    tie_layers2: tie layers for feedback fet
    sd_rmult: sd_rmult for both fets
    **kwargs: any kwarg that is supported by nmos and pmos
    """
   
    #top level component
    top_level = Component()

    #two fets
    device_map = {
            "nmos": nmos,
            "pmos": pmos,
            }
    device = device_map.get(device_type)

    if device_type == "nmos":
        kwargs["with_dnwell"] = False  # Set the parameter dynamically

    
    fet_1 = device(pdk, width=width[0], fingers=fingers[0], multipliers=multipliers[0], with_dummy=dummy_1, with_substrate_tap=False, length=length[0], tie_layers=tie_layers1, sd_rmult=sd_rmult, **kwargs)
    fet_2 = device(pdk, width=width[1], fingers=fingers[1], multipliers=multipliers[1], with_dummy=dummy_2, with_substrate_tap=False, length=length[1], tie_layers=tie_layers2, sd_rmult=sd_rmult, **kwargs)
    well = "pwell" if device == nmos else "nwell"
    sd_layer = "p+s/d" if device == nmos else "n+s/d"
    fet_1_ref = top_level << fet_1
    fet_2_ref = top_level << fet_2

    #Relative move
    ref_dimensions = evaluate_bbox(fet_2)
    if placement == "horizontal":
        # Legacy formula `metal_sep - 0.5` overlaps the two fet bboxes so their
        # pwells merge. Trim the overlap slightly (-0.46 instead of -0.5) so the
        # fets' inner S/D m2 finger contacts respect the strictest PDK m2
        # spacing — gf180 M2.2a (0.28um). Sky130 m2 spacing (0.14um) is well
        # under the resulting gap either way.
        fet_2_ref.movex(fet_1_ref.xmax + ref_dimensions[0]/2 + pdk.util_max_metal_seperation()-0.46)
        # The two fets' welltie tap-implant rings end up `2*well_enc - bbox_overlap`
        # apart at their inner edges. On stricter PDKs (gf180 PP.2 = 0.4um) that
        # gap trips a min-spacing rule. Bridge the implants with a thin rectangle
        # so they merge into one polygon — geometrically inert (it sits inside
        # the merged pwell, on top of existing tap diffusion area), DRC-clean.
        well_enc = pdk.get_grule(well, "active_tap")["min_enclosure"]
        fet1_pp_right = fet_1_ref.xmax - well_enc
        fet2_pp_left = fet_2_ref.xmin + well_enc
        if fet2_pp_left > fet1_pp_right:
            bridge_x = (fet1_pp_right + fet2_pp_left) / 2
            bridge_w = (fet2_pp_left - fet1_pp_right) + 0.04
            bridge_h = (fet_1_ref.ymax - fet_1_ref.ymin) - 2 * well_enc
            bridge_y = (fet_1_ref.ymax + fet_1_ref.ymin) / 2
            bridge = top_level << rectangle(
                size=(bridge_w, bridge_h),
                layer=pdk.get_glayer(sd_layer),
                centered=True,
            )
            bridge.movex(bridge_x).movey(bridge_y)
    if placement == "vertical":
        fet_2_ref.movey(fet_1_ref.ymin - ref_dimensions[1]/2 - pdk.util_max_metal_seperation()-1)
    
    #Routing
    viam2m3 = via_stack(pdk, "met2", "met3", centered=True)
    drain_1_via = top_level << viam2m3
    source_1_via = top_level << viam2m3
    drain_2_via = top_level << viam2m3
    gate_2_via = top_level << viam2m3
    drain_1_via.move(fet_1_ref.ports["multiplier_0_drain_W"].center).movex(-0.5*evaluate_bbox(fet_1)[1])
    source_1_via.move(fet_1_ref.ports["multiplier_0_source_E"].center).movex(1.5)
    drain_2_via.move(fet_2_ref.ports["multiplier_0_drain_W"].center).movex(-1.5)
    gate_2_via.move(fet_2_ref.ports["multiplier_0_gate_E"].center).movex(1)

    top_level << straight_route(pdk, fet_1_ref.ports["multiplier_0_source_E"], source_1_via.ports["bottom_met_W"])
    top_level << straight_route(pdk, fet_2_ref.ports["multiplier_0_drain_W"], drain_2_via.ports["bottom_met_E"])
    top_level << c_route(pdk, source_1_via.ports["top_met_N"], drain_2_via.ports["top_met_N"], extension=1.2*max(width[0],width[1]), e1glayer="met3", e2glayer="met3", cglayer="met2")
    top_level << straight_route(pdk, fet_1_ref.ports["multiplier_0_drain_W"], drain_1_via.ports["bottom_met_E"])
    top_level << c_route(pdk, drain_1_via.ports["top_met_S"], gate_2_via.ports["top_met_S"], extension=1.2*max(width[0],width[1]), cglayer="met2")
    top_level << straight_route(pdk, fet_2_ref.ports["multiplier_0_gate_E"], gate_2_via.ports["bottom_met_W"])
    try:
        # Use the PDK's own min_width for the tie route layer rather than a
        # hardcoded 0.2um (gf180's met1 min_width is 0.23um, so 0.2 trips M1.1).
        _tie_width = max(0.2 * sd_rmult, pdk.get_grule(tie_layers2[1])["min_width"])
        top_level << straight_route(pdk, fet_2_ref.ports["multiplier_0_source_W"], fet_2_ref.ports["tie_W_top_met_W"], glayer1=tie_layers2[1], width=_tie_width, fullbottom=True)
    except:
        pass
    #Renaming Ports
    top_level.add_ports(fet_1_ref.get_ports_list(), prefix="A_")
    top_level.add_ports(fet_2_ref.get_ports_list(), prefix="B_")
    top_level.add_ports(drain_1_via.get_ports_list(), prefix="A_drain_")
    top_level.add_ports(source_1_via.get_ports_list(), prefix="A_source_")
    top_level.add_ports(drain_2_via.get_ports_list(), prefix="B_drain_")
    top_level.add_ports(gate_2_via.get_ports_list(), prefix="B_gate_")
    #add nwell
    if well == "nwell": 
        top_level.add_padding(layers=(pdk.get_glayer("nwell"),),default= 1 )
 
    component = component_snap_to_grid(rename_ports_by_orientation(top_level))
    #component = rename_ports_by_orientation(top_level)

    # Store netlist as string for LVS (avoids gymnasium info dict type restrictions)
    # Compatible with both gdsfactory 7.7.0 and 7.16.0+ strict Pydantic validation
    netlist_obj = fvf_netlist(fet_1, fet_2)
    component.info['netlist'] = netlist_obj.generate_netlist()
    # Store the Netlist object for hierarchical netlist building (used by lvcm.py etc.)
    component.info['netlist_obj'] = netlist_obj
    # Store serialized netlist data for reconstruction if needed
    component.info['netlist_data'] = {
        'circuit_name': netlist_obj.circuit_name,
        'nodes': netlist_obj.nodes,
        'source_netlist': netlist_obj.source_netlist
    }

    # gf180 LVS uses klayout's official deck which strictly requires named
    # pin labels on met*_label layers. sky130 magic+netgen tolerates missing
    # labels, so we only stamp them for gf180. Composite cells (LVCM, opamp)
    # set GLAYOUT_NO_PIN_LABELS=1 around their sub-cell builds so the inner
    # FVF labels don't leak into the parent cell's GDS and confuse top-level
    # pin extraction.
    import os
    if pdk.name.lower() == "gf180" and not os.environ.get("GLAYOUT_NO_PIN_LABELS"):
        try:
            component = add_fvf_labels(component, pdk)
        except KeyError:
            pass

    return component

if __name__=="__main__":
    fvf = sky130_add_fvf_labels(flipped_voltage_follower(sky130_mapped_pdk, width=(2,1), sd_rmult=3))
    fvf.show()
    fvf.name = "fvf"
    fvf_gds = fvf.write_gds("fvf.gds")
    result = run_evaluation("fvf.gds",fvf.name,fvf)
    print(result)