from glayout import MappedPDK, sky130,gf180
from gdsfactory.components import rectangle
from glayout.util.comp_utils import align_comp_to_port
from glayout.primitives.fet import pmos
from glayout.routing.c_route import c_route
from glayout.routing.straight_route import straight_route
from glayout.primitives.guardring import tapring
from glayout.util.comp_utils import evaluate_bbox, add_ports_perimeter
from glayout.pdk.mappedpdk import MappedPDK
from gdsfactory.component import Component
from gdsfactory.cell import cell
from typing import Optional
from glayout.spice.netlist import Netlist
from gdsfactory.component import Component
import time
def add_resistor_labels(res: Component, pdk: MappedPDK) -> Component:
    res.unlock()

    def label(txt):
        r = rectangle(layer=pdk.get_glayer("met2_pin"), size=(0.3, 0.3), centered=True).copy()
        r.add_label(txt, layer=pdk.get_glayer("met2_label"))
        return r

    vres_port = next(p for n, p in res.ports.items() if n.startswith("VRES_"))
    vss_port  = next(p for n, p in res.ports.items() if n.startswith("VSS_"))
    b_port    = next(p for n, p in res.ports.items() if n.startswith("B_"))

    res.add(align_comp_to_port(label("VRES"), vres_port))
    res.add(align_comp_to_port(label("VSS"),  vss_port))
    res.add(align_comp_to_port(label("B"), b_port))

    return res.flatten()

def resistor_netlist(fet: Component) -> Netlist:
    """
    Diode-connected PFET resistor netlist
    """
    resistor_netlist = Netlist(circuit_name="DIODE_RES", nodes=["VRES", "VSS", "B"])
    resistor_netlist.connect_netlist(
        fet.info["netlist"],
        [
            ("D", "VRES"),
            ("G", "VRES"),
            ("S", "VSS"),
            ("B", "B"),
        ],
    )
    return resistor_netlist

@cell
def resistor(
    pdk: MappedPDK,
    width: float = 5,
    length: float = 1,
    num_series: int = 1,
    multipliers: int = 1,
    rmult: Optional[int] = None,
    with_tie: bool = True,
    with_substrate_tap: bool = False,
    tie_layers: tuple[str, str] = ("met2", "met1"),
    substrate_tap_layers: tuple[str, str] = ("met2", "met1"),
) -> Component:
    """
    Diode-connected PFET resistor (CM-style)

    Ports:
      - VRES : drain/gate node
      - VSS  : source
      - B    : bulk
    """
    pdk.activate()
    res = Component("resistor")
    max_sep = pdk.util_max_metal_seperation()
    pfets = []

    # ---- First PFET ----
    pf0 = res << pmos(
        pdk,
        width=width,
        length=length,
        multipliers=multipliers,
        rmult=rmult,
        with_dummy=False,
        with_tie=False,
        with_substrate_tap=False,
    )
    pfets.append(pf0)

    # Diode connect
    diode0 = res << c_route(pdk, pf0.ports["multiplier_0_gate_W"], pf0.ports["multiplier_0_drain_W"])

    # ---- Series stacking ----
    for i in range(1, num_series):
        pf = (res << pmos(
            pdk,
            width=width,
            length=length,
            multipliers=multipliers,
            rmult=rmult,
            with_dummy=False,
            with_tie=False,
            with_substrate_tap=False,
        )).movey(i * (evaluate_bbox(pf0)[1] + max_sep))

        pfets.append(pf)

        # diode connect
        res << c_route(pdk, pf.ports["multiplier_0_gate_W"], pf.ports["multiplier_0_drain_W"])

        # connect previous source → next drain
        res << c_route(pfets[i - 1].ports["multiplier_0_source_E"], pf.ports["multiplier_0_drain_E"])

    # ---- Canonical ports ----
    res.add_ports([pfets[0].ports["multiplier_0_source_E"]], prefix="VSS_")
    res.add_ports(diode0.get_ports_list(), prefix="VRES_")

    # ---- Well / bulk ----
    res.add_padding(layers=(pdk.get_glayer("nwell"),), default=pdk.get_grule("active_tap", "nwell")["min_enclosure"])
    res = add_ports_perimeter(res, layer=pdk.get_glayer("nwell"), prefix="B_")

    # ---- Tie ring ----
    if with_tie:
        tap_encloses = (evaluate_bbox(res)[0] + max_sep, evaluate_bbox(res)[1] + max_sep)
        ring = tapring(pdk, enclosed_rectangle=tap_encloses, sdlayer="n+s/d", horizontal_glayer=tie_layers[0], vertical_glayer=tie_layers[1])
        ringref = res << ring
        res.add_ports(ringref.get_ports_list(), prefix="tie_")

    # ---- Substrate tap ----
    if with_substrate_tap:
        tap_encloses = (evaluate_bbox(res)[0] + max_sep, evaluate_bbox(res)[1] + max_sep)
        ring = tapring(pdk, enclosed_rectangle=tap_encloses, sdlayer="p+s/d", horizontal_glayer=substrate_tap_layers[0], vertical_glayer=substrate_tap_layers[1])
        ringref = res << ring
        res.add_ports(ringref.get_ports_list(), prefix="substrate_")

    # ---- Netlist ----
    res.info["netlist"] = resistor_netlist(pfets[0])

    return res

import time
if __name__ == "__main__":
    comp =resistor(sky130)
    # comp.pprint_ports()
    comp =add_resistor_labels(comp,sky130)
    comp = comp.flatten()
    comp.name = "RS"
    #print(comp.info['netlist'].generate_netlist())
    nl = comp.info["netlist"]
    print(nl)
    print(nl.generate_netlist())
    print("...Running DRC...")
    drc_result = sky130.drc_magic(comp, "RS")
    print(drc_result)
    ## Klayout DRC
    #drc_result = sky130.drc(comp)\n
    time.sleep(5)
    print("...Running LVS...")
    lvs_res=sky130.lvs_netgen(comp, "RS", copy_intermediate_files=True, show_scripts=True)
    print(lvs_res)
    #print("...Saving GDS...")
    #comp.write_gds('out_resistor.gds')
