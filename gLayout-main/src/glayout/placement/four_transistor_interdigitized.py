# 4 transistor placed in two rows (each row is an interdigitized pair of transistors)
# the 4 transistors are labeled top or bottom and transistor A or B
# top_A_, bottom_A, top_B_, bottom_B_

from glayout.pdk.mappedpdk import MappedPDK
from glayout.placement.two_transistor_interdigitized import two_nfet_interdigitized, two_pfet_interdigitized
from typing import Literal, Optional
from gdsfactory import Component
from gdsfactory.component_reference import ComponentReference
from glayout.util.comp_utils import evaluate_bbox, movey, align_comp_to_port
from glayout.primitives.guardring import tapring
from glayout.spice.netlist import Netlist
from gdsfactory.components import text_freetype, rectangle
from glayout.primitives.via_gen import via_stack

#two seperate bulk nodes
def add_four_int_labels1(four_int_in: Component,
                pdk: MappedPDK 
                ) -> Component:
	
    four_int_in.unlock()
    # list that will contain all port/comp info
    move_info = list()
    # create labels and append to info list
    # vss1
    vss1label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vss1label.add_label(text="VSS1",layer=pdk.get_glayer("met2_label"))
    move_info.append((vss1label,four_int_in.ports["top_A_source_E"],None))
    # vss2
    vss2label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vss2label.add_label(text="VSS2",layer=pdk.get_glayer("met2_label"))
    move_info.append((vss2label,four_int_in.ports["top_B_source_E"],None))
    # vss3
    vss3label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vss3label.add_label(text="VSS3",layer=pdk.get_glayer("met2_label"))
    move_info.append((vss3label,four_int_in.ports["bottom_A_source_E"],None))
    # vss4
    vss4label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vss4label.add_label(text="VSS4",layer=pdk.get_glayer("met2_label"))
    move_info.append((vss4label,four_int_in.ports["bottom_B_source_E"],None))
    
    # vdd1
    vdd1label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vdd1label.add_label(text="VDD1",layer=pdk.get_glayer("met2_label"))
    move_info.append((vdd1label,four_int_in.ports["top_A_drain_N"],None))
    # vdd2
    vdd2label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vdd2label.add_label(text="VDD2",layer=pdk.get_glayer("met2_label"))
    move_info.append((vdd2label,four_int_in.ports["top_B_drain_N"],None))
    # vdd3
    vdd3label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vdd3label.add_label(text="VDD3",layer=pdk.get_glayer("met2_label"))
    move_info.append((vdd3label,four_int_in.ports["bottom_A_drain_N"],None))
    # vdd4
    vdd4label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vdd4label.add_label(text="VDD4",layer=pdk.get_glayer("met2_label"))
    move_info.append((vdd4label,four_int_in.ports["bottom_B_drain_N"],None))
    
    # vg1
    vg1label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vg1label.add_label(text="VG1",layer=pdk.get_glayer("met2_label"))
    move_info.append((vg1label,four_int_in.ports["top_A_gate_S"],None))
    # vg2
    vg2label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vg2label.add_label(text="VG2",layer=pdk.get_glayer("met2_label"))
    move_info.append((vg2label,four_int_in.ports["top_B_gate_S"],None))
    # vg3
    vg3label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vg3label.add_label(text="VG3",layer=pdk.get_glayer("met2_label"))
    move_info.append((vg3label,four_int_in.ports["bottom_A_gate_S"],None))
    # vg4
    vg4label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vg4label.add_label(text="VG4",layer=pdk.get_glayer("met2_label"))
    move_info.append((vg4label,four_int_in.ports["bottom_B_gate_S"],None))
    
    # VB1
    vb1label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.5,0.5),centered=True).copy()
    vb1label.add_label(text="VB1",layer=pdk.get_glayer("met2_label"))
    move_info.append((vb1label,four_int_in.ports["top_welltie_S_top_met_S"], None))
    # VB2
    vb2label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.5,0.5),centered=True).copy()
    vb2label.add_label(text="VB2",layer=pdk.get_glayer("met2_label"))
    move_info.append((vb2label,four_int_in.ports["bottom_welltie_S_top_met_S"], None))
    
    # move everything to position
    for comp, prt, alignment in move_info:
        alignment = ('c','b') if alignment is None else alignment
        compref = align_comp_to_port(comp, prt, alignment=alignment)
        four_int_in.add(compref)
    return four_int_in.flatten()

# one common bulk node
def add_four_int_labels2(four_int_in: Component,
                pdk: MappedPDK 
                ) -> Component:
	
    four_int_in.unlock()
    # list that will contain all port/comp info
    move_info = list()
    # create labels and append to info list
    # vss1
    vss1label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vss1label.add_label(text="VSS1",layer=pdk.get_glayer("met2_label"))
    move_info.append((vss1label,four_int_in.ports["top_A_source_E"],None))
    # vss2
    vss2label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vss2label.add_label(text="VSS2",layer=pdk.get_glayer("met2_label"))
    move_info.append((vss2label,four_int_in.ports["top_B_source_E"],None))
    # vss3
    vss3label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vss3label.add_label(text="VSS3",layer=pdk.get_glayer("met2_label"))
    move_info.append((vss3label,four_int_in.ports["bottom_A_source_E"],None))
    # vss4
    vss4label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vss4label.add_label(text="VSS4",layer=pdk.get_glayer("met2_label"))
    move_info.append((vss4label,four_int_in.ports["bottom_B_source_E"],None))
    
    # vdd1
    vdd1label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vdd1label.add_label(text="VDD1",layer=pdk.get_glayer("met2_label"))
    move_info.append((vdd1label,four_int_in.ports["top_A_drain_N"],None))
    # vdd2
    vdd2label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vdd2label.add_label(text="VDD2",layer=pdk.get_glayer("met2_label"))
    move_info.append((vdd2label,four_int_in.ports["top_B_drain_N"],None))
    # vdd3
    vdd3label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vdd3label.add_label(text="VDD3",layer=pdk.get_glayer("met2_label"))
    move_info.append((vdd3label,four_int_in.ports["bottom_A_drain_N"],None))
    # vdd4
    vdd4label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vdd4label.add_label(text="VDD4",layer=pdk.get_glayer("met2_label"))
    move_info.append((vdd4label,four_int_in.ports["bottom_B_drain_N"],None))
    
    # vg1
    vg1label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vg1label.add_label(text="VG1",layer=pdk.get_glayer("met2_label"))
    move_info.append((vg1label,four_int_in.ports["top_A_gate_S"],None))
    # vg2
    vg2label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vg2label.add_label(text="VG2",layer=pdk.get_glayer("met2_label"))
    move_info.append((vg2label,four_int_in.ports["top_B_gate_S"],None))
    # vg3
    vg3label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vg3label.add_label(text="VG3",layer=pdk.get_glayer("met2_label"))
    move_info.append((vg3label,four_int_in.ports["bottom_A_gate_S"],None))
    # vg4
    vg4label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vg4label.add_label(text="VG4",layer=pdk.get_glayer("met2_label"))
    move_info.append((vg4label,four_int_in.ports["bottom_B_gate_S"],None))
    
    # VB
    vblabel = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.5,0.5),centered=True).copy()
    vblabel.add_label(text="VB",layer=pdk.get_glayer("met2_label"))
    move_info.append((vblabel,four_int_in.ports["top_welltie_S_top_met_S"], None))
    
    # move everything to position
    for comp, prt, alignment in move_info:
        alignment = ('c','b') if alignment is None else alignment
        compref = align_comp_to_port(comp, prt, alignment=alignment)
        four_int_in.add(compref)
    return four_int_in.flatten()

def four_tran_interdigitized_netlist(toprow: ComponentReference, bottomrow: ComponentReference, same_bulk: bool) -> Netlist:

    if same_bulk:
        netlist = Netlist(circuit_name='four_trans_interdigitized', nodes=['VDD1', 'VDD2', 'VSS1', 'VSS2', 'VG1', 'VG2', 'VDD3', 'VDD4', 'VSS3', 'VSS4', 'VG3', 'VG4', 'VB'])
        netlist.connect_netlist(toprow.info['netlist'], [('VDD1', 'VDD1'), ('VDD2', 'VDD2'), ('VSS1', 'VSS1'), ('VSS2', 'VSS2'), ('VG1','VG1'), ('VG2','VG2'), ('VB','VB')])
        netlist.connect_netlist(bottomrow.info['netlist'], [('VDD1', 'VDD3'), ('VDD2', 'VDD4'), ('VSS1', 'VSS3'), ('VSS2', 'VSS4'), ('VG1','VG3'), ('VG2','VG4'), ('VB','VB')])
    else:
        netlist = Netlist(circuit_name='four_trans_interdigitized', nodes=['VDD1', 'VDD2', 'VSS1', 'VSS2', 'VG1', 'VG2', 'VDD3', 'VDD4', 'VSS3', 'VSS4', 'VG3', 'VG4', 'VB1', 'VB2'])
        netlist.connect_netlist(toprow.info['netlist'], [('VDD1', 'VDD1'), ('VDD2', 'VDD2'), ('VSS1', 'VSS1'), ('VSS2', 'VSS2'), ('VG1','VG1'), ('VG2','VG2'), ('VB','VB1')])
        netlist.connect_netlist(bottomrow.info['netlist'], [('VDD1', 'VDD3'), ('VDD2', 'VDD4'), ('VSS1', 'VSS3'), ('VSS2', 'VSS4'), ('VG1','VG3'), ('VG2','VG4'), ('VB','VB2')])
    return netlist
        
def generic_4T_interdigitzed(
    pdk: MappedPDK,
    top_row_device: Literal["nfet", "pfet"]="pfet",
    bottom_row_device: Literal["nfet", "pfet"]="nfet",
    numcols: int=3,
    length: float=None,
    with_substrate_tap: bool = True,
    top_kwargs: Optional[dict]=None,
    bottom_kwargs: Optional[dict]=None
):
    if top_kwargs is None:
        top_kwargs = dict()
    if bottom_kwargs is None:
        bottom_kwargs = dict()
    # place
    toplvl = Component()
    if top_row_device=="nfet":
        toprow = toplvl << two_nfet_interdigitized(pdk,numcols,with_substrate_tap=False,length=length,**top_kwargs)
    else:
        toprow = toplvl << two_pfet_interdigitized(pdk,numcols,with_substrate_tap=False,length=length,**top_kwargs)
    if bottom_row_device=="nfet":
        bottomrow = toplvl << two_nfet_interdigitized(pdk,numcols,with_substrate_tap=False,length=length,**bottom_kwargs)
    else:
        bottomrow = toplvl << two_pfet_interdigitized(pdk,numcols,with_substrate_tap=False,length=length,**bottom_kwargs)
    # move
    toprow.movey(pdk.snap_to_2xgrid((evaluate_bbox(bottomrow)[1]/2 + evaluate_bbox(toprow)[1]/2 + pdk.util_max_metal_seperation())))
    # add substrate tap
    if with_substrate_tap:
        substrate_tap = tapring(pdk, enclosed_rectangle=pdk.snap_to_2xgrid(evaluate_bbox(toplvl.flatten(),padding=0.34)))
        substrate_tap_ref = toplvl << movey(substrate_tap,destination=pdk.snap_to_2xgrid(toplvl.flatten().center[1],snap4=True))
    # add ports
    toplvl.add_ports(substrate_tap_ref.get_ports_list(),prefix="substratetap_")
    toplvl.add_ports(toprow.get_ports_list(),prefix="top_")
    toplvl.add_ports(bottomrow.get_ports_list(),prefix="bottom_")
    # flag for smart route
    toplvl.info["route_genid"] = "four_transistor_interdigitized"
    if top_row_device==bottom_row_device and top_row_device=="nfet":
        same_bulk = True
    else:
        same_bulk = False
    toplvl.info['netlist'] = four_tran_interdigitized_netlist(toprow, bottomrow, same_bulk)
    
    return toplvl
