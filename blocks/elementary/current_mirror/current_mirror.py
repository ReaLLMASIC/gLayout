from glayout import MappedPDK, sky130,gf180
from glayout import nmos, pmos, tapring,via_stack

from glayout.placement.two_transistor_interdigitized import two_nfet_interdigitized, two_pfet_interdigitized
from gdsfactory import cell
from gdsfactory.component import Component
from gdsfactory.components import text_freetype, rectangle

from glayout.routing import c_route,L_route,straight_route
from glayout.spice.netlist import Netlist

from glayout.util.port_utils import add_ports_perimeter,rename_ports_by_orientation
from glayout.util.comp_utils import evaluate_bbox, prec_center, prec_ref_center, align_comp_to_port
from typing import Optional, Union 

import time

def add_cm_labels(cm_in: Component, pdk: MappedPDK) -> Component:
    cm_in.unlock()

    # list that will contain all port/comp info
    move_info = []

    # VSS
    vsslabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=(0.27, 0.27), centered=True).copy()
    vsslabel.add_label(text="VSS",layer=pdk.get_glayer("met2_label"))
    move_info.append((vsslabel, cm_in.ports["ref_multiplier_0_source_E"]))

    # VREF
    vreflabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=(0.27, 0.27), centered=True).copy()
    vreflabel.add_label(text="VREF",layer=pdk.get_glayer("met2_label"))
    move_info.append((vreflabel, cm_in.ports["ref_multiplier_0_drain_N"]))

    # VCOPY
    vcopylabel = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27, 0.27),  centered=True).copy()
    vcopylabel.add_label(text="VCOPY",layer=pdk.get_glayer("met2_label"))
    move_info.append((vcopylabel, cm_in.ports["out_multiplier_0_drain_N"]))

    # VB (well tie)
    vb_port = next(p for n, p in cm_in.ports.items() if n.startswith("well_"))
    vblabel = rectangle(layer=pdk.get_glayer("met2_pin"), size=(0.5, 0.5), centered=True).copy()
    vblabel.add_label(text="VB",layer=pdk.get_glayer("met2_label"))
    move_info.append((vblabel, vb_port))

    for label, port in move_info:
        cm_in.add(align_comp_to_port(label, port, alignment=("c", "b")))

    return cm_in.flatten()

def current_mirror_netlist(fetL: Component, fetR: Component) -> Netlist:
	current_mirror_netlist = Netlist(circuit_name='CMIRROR', nodes=['VREF', 'VOUT', 'VSS', 'B'])
	current_mirror_netlist.connect_netlist(
		fetL.info['netlist'],
		[('D', 'VREF'), ('G', 'VREF'), ('S', 'VSS'), ('B', 'B')]
	)
	current_mirror_netlist.connect_netlist(
		fetR.info['netlist'],
		[('D', 'VOUT'), ('G', 'VREF'), ('S', 'VSS'), ('B', 'B')]
	)
	return current_mirror_netlist

@cell
def current_mirror(
    pdk: MappedPDK, 
    numcols: int = 3,
    device: str = 'nfet',
    width: float = 3,
    fingers: int = 1,
    length: Optional[float] = None,
    rmult: int = 1,
    dummy: Union[bool, tuple[bool, bool]] = True,
    with_substrate_tap: Optional[bool] = False,
    with_tie: Optional[bool] = True,
    tie_layers: tuple[str, str] = ("met2", "met1"),
    subckt_only: Optional[bool] = True,
    **kwargs
) -> Component:
    """
    An instantiable current mirror that returns a Component object.

    The current mirror is a two-transistor structure with shorted
    source and gate. It can be instantiated with either NMOS or PMOS
    devices. Optional dummy devices, substrate tap, and tie ring
    are supported. The layout is centered at the origin.

    Transistor A acts as the reference device,
    Transistor B acts as the mirror device.

    Args:
        pdk (MappedPDK): Process design kit
        numcols (int): Number of columns
        device (str): 'nfet' or 'pfet'
        width (float): Device width
        fingers (int): Number of fingers
        length (float): Channel length
        rmult (int): Multiplier
        dummy (bool | tuple): Dummy devices
        with_substrate_tap (bool): Add substrate tap
        with_tie (bool): Add well tie
        tie_layers (tuple): Tie metal layers
        subckt_only (bool): Netlist control
        **kwargs: Passed to device generator

    Returns:
        Component: Current mirror layout
    """
    pdk.activate()
    cmirror = Component("current_mirror")

    # Handle dummy specification
    if isinstance(dummy, bool):
        dummy = (dummy, dummy)
    well = None
    if device.lower() in ["nmos", "nfet"]:
        fetL = nmos(pdk, width=width, fingers=fingers, length=length, multipliers=1, with_tie=False, with_dummy=(dummy[0], False), with_dnwell=False, with_substrate_tap=False, rmult=rmult)
        fetR = nmos(pdk, width=width, fingers=fingers, length=length, multipliers=1, with_tie=False, with_dummy=(False, dummy[1]), with_dnwell=False, with_substrate_tap=False, rmult=rmult)
        min_spacing_x = (pdk.get_grule("n+s/d")["min_separation"] - 2 * (fetL.xmax - fetL.ports["multiplier_0_plusdoped_E"].center[0]))
        well = "pwell"

    elif device.lower() in ["pmos", "pfet"]:
        fetL = pmos(pdk, width=width, fingers=fingers, length=length, multipliers=1, with_tie=False, with_dummy=(dummy[0], False), dnwell=False, with_substrate_tap=False, rmult=rmult)
        fetR = pmos(pdk, width=width, fingers=fingers, length=length, multipliers=1, with_tie=False, with_dummy=(False, dummy[1]), dnwell=False, with_substrate_tap=False, rmult=rmult)
        min_spacing_x = (pdk.get_grule("p+s/d")["min_separation"] - 2 * (fetL.xmax - fetL.ports["multiplier_0_plusdoped_E"].center[0]))
        well = "nwell"

    else:
        raise ValueError(f"device must be either 'nmos' or 'pmos', got {device}")

    viam2m3 = via_stack(pdk, "met2", "met3", centered=True)
    metal_min_dim = max(pdk.get_grule("met2")["min_width"], pdk.get_grule("met3")["min_width"])
    metal_space = max(pdk.get_grule("met2")["min_separation"], pdk.get_grule("met3")["min_separation"], metal_min_dim)
    gate_route_os = (evaluate_bbox(viam2m3)[0] - fetL.ports["multiplier_0_gate_W"].width + metal_space)
    min_spacing_y = metal_space + 2 * gate_route_os 
    min_spacing_y -= 2 * abs(fetL.ports["well_S"].center[1] - fetL.ports["multiplier_0_gate_S"].center[1])
    ref_top = (cmirror << fetL).movey(fetL.ymax + min_spacing_y / 2).movex(-fetL.xmax)
    # Output device (bottom, mirrored)
    out_bot = (cmirror << fetR)
    out_bot.mirror_y()
    out_bot.movey(-fetR.ymax - min_spacing_y / 2).movex(-fetR.xmax)
    cmirror.add_ports(ref_top.get_ports_list(), prefix="ref_")
    cmirror.add_ports(out_bot.get_ports_list(), prefix="out_")
    if with_substrate_tap:
        tapref = cmirror << tapring(pdk, evaluate_bbox(cmirror, padding=1), horizontal_glayer="met1")
        cmirror.add_ports(tapref.get_ports_list(), prefix="tap_")

        for inst in [ref_top, out_bot]:
            try:
                cmirror << straight_route(pdk, inst.ports["multiplier_0_dummy_L_gsdcon_top_met_W"], cmirror.ports["tap_W_top_met_W"],glayer2="met1")
            except KeyError:
                pass
    source_bar = cmirror << c_route(pdk, ref_top.ports["multiplier_0_source_E"], out_bot.ports["multiplier_0_source_E"], viaoffset=False)
    cmirror.add_ports(source_bar.get_ports_list(), prefix="VSS_")
    gate_bar = cmirror << c_route(pdk, ref_top.ports["multiplier_0_gate_W"], out_bot.ports["multiplier_0_gate_W"], viaoffset=False)
    ref_drain = (ref_top.ports.get("multiplier_0_drain_W") or ref_top.ports.get("multiplier_0_drain_E"))
    cmirror << L_route(pdk, ref_drain, gate_bar.ports["con_N"], viaoffset=False, fullbottom=False)
    cmirror.add_ports([out_bot.ports["multiplier_0_drain_N"]], prefix="VOUT_")

    # add a pwell 
    if device.lower() in ['nmos','nfet']:
        cmirror.add_padding(layers = (pdk.get_glayer("pwell"),), default = pdk.get_grule("pwell", "active_tap")["min_enclosure"], )
        cmirror = add_ports_perimeter(cmirror, layer = pdk.get_glayer("pwell"), prefix="well_")
    elif device.lower() in ['pmos','pfet']:
        cmirror.add_padding(layers = (pdk.get_glayer("nwell"),), default = pdk.get_grule("nwell", "active_tap")["min_enclosure"], )
        cmirror = add_ports_perimeter(cmirror, layer = pdk.get_glayer("nwell"), prefix="well_")
    else:
        raise ValueError(f"Device type {device} not recognized. Use 'nfet' or 'pfet'.")
    cmirror.info['netlist'] = current_mirror_netlist(fetL, fetR)
    return cmirror

import time
if __name__ == "__main__":
    comp =current_mirror(sky130)
    # comp.pprint_ports()
    comp =add_cm_labels(comp,sky130)
    comp.name = "CM"
    #print(comp.info['netlist'].generate_netlist())
    print("...Running DRC...")
    drc_result = sky130.drc_magic(comp, "CM")
    print(drc_result)
    ## Klayout DRC
    #drc_result = sky130.drc(comp)\n
    time.sleep(5)
    print("...Running LVS...")
    lvs_res=sky130.lvs_netgen(comp, "CM", copy_intermediate_files=True, show_scripts=True)
    print(lvs_res)
    #print("...Saving GDS...")
    #comp.write_gds('out_current_mirror,.gds')
