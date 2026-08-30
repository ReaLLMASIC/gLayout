from glayout import MappedPDK, sky130,gf180
from glayout.backend import Component, cell, rectangle
from glayout.primitives.fet import nmos, pmos, multiplier
from glayout.util.comp_utils import evaluate_bbox, prec_center, align_comp_to_port, movex, movey
from glayout.util.snap_to_grid import component_snap_to_grid
from glayout.util.port_utils import rename_ports_by_orientation
from glayout.routing.straight_route import straight_route
from glayout.routing.c_route import c_route
from glayout.routing.L_route import L_route
from glayout.primitives.guardring import tapring
from glayout.util.port_utils import add_ports_perimeter
from glayout.spice.netlist import Netlist
from glayout.primitives.via_gen import via_stack
from glayout.util.label_utils import add_pin_labels, LabelSpec
try:
    from glayout.verification.evaluator_wrapper import run_evaluation
except ImportError:
    print("Warning: evaluator_wrapper not found. Evaluation will be skipped.")
    run_evaluation = None


_TG_LABELS = [
    LabelSpec("VIN", "N_multiplier_0_source_E", size=0.27),
    LabelSpec("VOUT", "P_multiplier_0_drain_W", size=0.27),
    LabelSpec("VCC", "P_tie_S_top_met_S", size=0.5),
    LabelSpec("VSS", "N_tie_S_top_met_N", size=0.5),
    LabelSpec("VGP", "P_multiplier_0_gate_E", size=0.27),
    LabelSpec("VGN", "N_multiplier_0_gate_E", size=0.27),
]


def add_tg_labels(tg_in: Component, pdk: MappedPDK) -> Component:
    """Add LVS pin rectangles + text labels to a transmission gate (PDK-agnostic)."""
    return add_pin_labels(tg_in, pdk, _TG_LABELS)


def tg_netlist(nfet: Component, pfet: Component) -> Netlist:
    netlist = Netlist(
        circuit_name="Transmission_Gate",
        nodes=["VIN", "VSS", "VOUT", "VCC", "VGP", "VGN"],
    )
    # Each fet's dummies physically tie to that fet's own welltie ring (NMOS bulk
    # = VSS, PMOS bulk = VCC), so DUM maps to the same bulk net and the schematic
    # matches the layout extraction. DUM is a real port of the subckt:
    # `.subckt NMOS D G S B DUM`.
    netlist.connect_netlist(
        nfet.info["netlist"],
        [("D", "VOUT"), ("G", "VGN"), ("S", "VIN"), ("B", "VSS"), ("DUM", "VSS")],
    )
    netlist.connect_netlist(
        pfet.info["netlist"],
        [("D", "VOUT"), ("G", "VGP"), ("S", "VIN"), ("B", "VCC"), ("DUM", "VCC")],
    )

    return netlist


@cell
def  transmission_gate(
        pdk: MappedPDK,
        width: tuple[float,float] = (1,1),
        length: tuple[float,float] = (None,None),
        fingers: tuple[int,int] = (1,1),
        multipliers: tuple[int,int] = (1,1),
        substrate_tap: bool = False,
        tie_layers: tuple[str,str] = ("met2","met1"),
        **kwargs
        ) -> Component:
    """
    creates a transmission gate
    tuples are in (NMOS,PMOS) order
    **kwargs are any kwarg that is supported by nmos and pmos
    """
   
    #top level component
    top_level = Component()

    #two fets
    nfet = nmos(pdk, width=width[0], fingers=fingers[0], multipliers=multipliers[0], with_dummy=True, with_dnwell=False,  with_substrate_tap=False, length=length[0], **kwargs)
    pfet = pmos(pdk, width=width[1], fingers=fingers[1], multipliers=multipliers[1], with_dummy=True, with_substrate_tap=False, length=length[1], **kwargs)
    nfet_ref = top_level << nfet
    pfet_ref = top_level << pfet 
    pfet_ref = rename_ports_by_orientation(pfet_ref.mirror_y())

    #Relative move
    pfet_ref.movey(nfet_ref.ymax + evaluate_bbox(pfet_ref)[1]/2 + pdk.util_max_metal_seperation())
    
    #Routing
    top_level << c_route(pdk, nfet_ref.ports["multiplier_0_source_E"], pfet_ref.ports["multiplier_0_source_E"])
    top_level << c_route(pdk, nfet_ref.ports["multiplier_0_drain_W"], pfet_ref.ports["multiplier_0_drain_W"], viaoffset=False)
    
    #Renaming Ports
    top_level.add_ports(nfet_ref.get_ports_list(), prefix="N_")
    top_level.add_ports(pfet_ref.get_ports_list(), prefix="P_")

    #substrate tap
    if substrate_tap:
            substrate_tap_encloses =((evaluate_bbox(top_level)[0]+pdk.util_max_metal_seperation()), (evaluate_bbox(top_level)[1]+pdk.util_max_metal_seperation()))
            guardring_ref = top_level << tapring(
            pdk,
            enclosed_rectangle=substrate_tap_encloses,
            sdlayer="p+s/d",
            horizontal_glayer='met2',
            vertical_glayer='met1',
        )
            guardring_ref.move(nfet_ref.center).movey(evaluate_bbox(pfet_ref)[1]/2 + pdk.util_max_metal_seperation()/2)
            top_level.add_ports(guardring_ref.get_ports_list(),prefix="tap_")
    
    component = component_snap_to_grid(rename_ports_by_orientation(top_level))
    # Store netlist as string to avoid gymnasium info dict type restrictions
    # Compatible with both gdsfactory 7.7.0 and 7.16.0+ strict Pydantic validation
    netlist_obj = tg_netlist(nfet, pfet)
    component.info['netlist'] = netlist_obj.generate_netlist()
    # Store the Netlist object for hierarchical netlist building
    component.info['netlist_obj'] = netlist_obj
    # Store serialized netlist data for reconstruction if needed
    component.info['netlist_data'] = {
        'circuit_name': netlist_obj.circuit_name,
        'nodes': netlist_obj.nodes,
        'source_netlist': netlist_obj.source_netlist
    }

    # gf180 LVS uses klayout's official deck which strictly requires named
    # pin labels on met*_label layers. sky130 magic+netgen tolerates missing
    # labels, so we only stamp them for gf180. Composite cells suppress with
    # GLAYOUT_NO_PIN_LABELS so inner labels don't leak into the parent's GDS.
    import os
    if pdk.name.lower() == "gf180" and not os.environ.get("GLAYOUT_NO_PIN_LABELS"):
        try:
            component = add_tg_labels(component, pdk)
        except KeyError:
            pass

    return component


if __name__ == "__main__":
    # NEW EVAL CODE
    #transmission_gate = transmission_gate(sky130_mapped_pdk)
    transmission_gate = add_tg_labels(transmission_gate(sky130),sky130)
    transmission_gate.show()
    transmission_gate.name = "Transmission_Gate"
    #magic_drc_result = sky130_mapped_pdk.drc_magic(transmission_gate, transmission_gate.name)
    #netgen_lvs_result = sky130_mapped_pdk.lvs_netgen(transmission_gate, transmission_gate.name)
    transmission_gate_gds = transmission_gate.write_gds("transmission_gate.gds")
    res = run_evaluation("transmission_gate.gds", transmission_gate.name, transmission_gate)
