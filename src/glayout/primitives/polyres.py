import numpy as np
np.float_ = np.float64


from gdsfactory.components import rectangle
from gdsfactory import Component
from glayout.pdk.mappedpdk import MappedPDK
from glayout.primitives.via_gen import via_array
from glayout.util.comp_utils import prec_ref_center, movey, align_comp_to_port, movex
from glayout.util.port_utils import add_ports_perimeter
from glayout.pdk.sky130_mapped import sky130_mapped_pdk
from glayout.pdk.gf180_mapped import gf180_mapped_pdk
from glayout.spice import Netlist
# from glayout.primitives.guardring import tapring  # Not needed for polyresistor

def poly_resistor_netlist(
    circuit_name: str,
    model: str,
    width: float,
    length: float,
    multipliers: int
) -> Netlist :

    ltop = (round(length, 2))*(1e-6)
    wtop = (round(width, 2))*(1e-6)
    mtop = multipliers

    #source_netlist=""".subckt {model} r0 r1 """+f'\n l={ltop} w={wtop} '

    #source_netlist += "\n.ends"

    source_netlist="""\n.subckt {circuit_name} {nodes} """+f'l={ltop} w={wtop} m={mtop}'+"""
XMAIN PLUS MINUS VSUBS {model} r_width={{w}} r_length={{l}} m={{m}}"""

    source_netlist += "\n.ends {circuit_name}"



    return Netlist(
        circuit_name=circuit_name,
        nodes=['PLUS', 'MINUS', 'VSUBS'],
        source_netlist=source_netlist,
        instance_format="X{name} {nodes} {circuit_name} l={length} w={width} m={multipliers}}",
        parameters={
            'model': model,
            'length': ltop,
            'width': wtop,
            'multipliers': mtop,
        }
    )

def poly_resistor(
    pdk: MappedPDK,
    length: float = 1.65,
    width: float = 0.35,
    fingers: int = 1,
    is_snake: bool = True,
    n_type: bool = False,
    silicided: bool = False
) -> Component:
    #poly_res = (66, 13)
    res_mk = (110,5)
    p_res = Component()
    contact_length = 2.2
    # Add DRC-compliant spacing: poly to poly minimum separation is 0.4μm
    poly_poly_rules = pdk.get_grule("poly", "poly")
    min_poly_sep = poly_poly_rules.get("min_separation", 0.4)  # Default to 0.4μm if not found
    separation = max(0.21 + width, min_poly_sep + width)
    #Extend poly for contacts
    ex_length = length + 2*contact_length
    for i in range(0,fingers):
        #poly resistor rectangle
        p_rect = rectangle(size=(width,ex_length), layer=pdk.get_glayer("poly"), centered=True)
        p_rect_ref = prec_ref_center(p_rect)
        p_res.add(p_rect_ref)
        movex(p_rect_ref, (i)*separation)
        #Add li layer on top and bottom contacts
        li_top = rectangle(size=(width,contact_length), layer=pdk.get_glayer("met1"), centered=True)
        li_top_ref = prec_ref_center(li_top)
        p_res.add(li_top_ref)
        movey(li_top_ref, contact_length/2 + length/2)
        movex(li_top_ref, (i)*separation)

        li_bot = rectangle(size=(width,contact_length), layer=pdk.get_glayer("met1"), centered=True)
        li_bot_ref = prec_ref_center(li_bot)
        p_res.add(li_bot_ref)
        movey(li_bot_ref, - contact_length/2 - length/2)
        movex(li_bot_ref, (i)*separation)

        ##SAB layer removed to comply with SB.16 rule
        ##SAB layer cannot exist on 3.3V/5V CMOS transistors in core circuit
        ##Only allowed on transistors marked by LVS_IO, OTP_MK, ESD_MK layers

        ##Add RES_MK layer
        resmk = rectangle(size=((width*fingers+0.56),(length)), layer=res_mk, centered=True)
        resmk_ref = prec_ref_center(resmk)
        p_res.add(resmk_ref)

        #Place poly to li via contact
        # Use no_exception=True to allow smaller via arrays
        licon1 = via_array(pdk, "poly", "met1", size=(width,contact_length), no_exception=True)
        licon1_ref = prec_ref_center(licon1)
        #p_res.add(licon1_ref)
        #movey(licon1_ref, contact_length/2 + length/2)

        licon2 = via_array(pdk, "poly", "met1", size=(width,contact_length), no_exception=True)
        licon2_ref = prec_ref_center(licon2)
        p_res.add(licon2_ref)
        movey(licon2_ref, - contact_length/2 - length/2)
        movex(licon2_ref, (i)*separation)

        licon3 = via_array(pdk, "poly", "met1", size=(width,contact_length), no_exception=True)
        licon3_ref = prec_ref_center(licon3)
        p_res.add(licon3_ref)
        movey(licon3_ref, contact_length/2 + length/2)
        movex(licon3_ref, (i)*separation)

        # place metal 1 layer on contacts
        met1_top = rectangle(size=(width,contact_length), layer=pdk.get_glayer("met2"), centered=True)
        met1_top_ref = prec_ref_center(met1_top)
        p_res.add(met1_top_ref)
        movey(met1_top_ref, contact_length/2 + length/2)
        movex(met1_top_ref, (i)*separation)

        met1_bot = rectangle(size=(width,contact_length), layer=pdk.get_glayer("met2"), centered=True)
        met1_bot_ref = prec_ref_center(met1_bot)
        p_res.add(met1_bot_ref)
        movey(met1_bot_ref, - contact_length/2 - length/2)
        movex(met1_bot_ref, (i)*separation)
        #place li to metal vias
        met1con1 = via_array(pdk, "met1", "met2", size=(width,contact_length), no_exception=True)
        met1con1_ref = prec_ref_center(met1con1)
        p_res.add(met1con1_ref)
        movey(met1con1_ref, contact_length/2 + length/2)
        movex(met1con1_ref, (i)*separation)

        met1con2 = via_array(pdk, "met1", "met2", size=(width,contact_length), no_exception=True)
        met1con2_ref = prec_ref_center(met1con2)
        p_res.add(met1con2_ref)
        movey(met1con2_ref, - contact_length/2 - length/2)
        movex(met1con2_ref, (i)*separation)

        con_offset = (separation)/2
        if is_snake == True:
            if i > 0:
                met1_connect = rectangle(size=(width+separation,contact_length), layer=pdk.get_glayer("met2"),centered= True)
                met1_con_ref = prec_ref_center(met1_connect)
                p_res.add(met1_con_ref)
                if i%2 == 0:
                    movey(met1_con_ref, - contact_length/2 - length/2)
                    movex(met1_con_ref, (i-1)*separation+con_offset)
                else:
                    movey(met1_con_ref, contact_length/2 + length/2)
                    movex(met1_con_ref, (i-1)*separation+con_offset)

        if i == 0:
            p_res.add_ports(met1_bot_ref.get_ports_list(), prefix="MINUS_")


    # Add P-plus layer for polyresistor (required by GF180MCU DRC rules)
    # Note: SAB layer removed to comply with SB.16 rule
    # SAB layer cannot exist on 3.3V/5V CMOS transistors in core circuit
    plus_layer = pdk.get_glayer("p+s/d")  # Always use P-plus for polyresistor
    plus = rectangle(size=(2*p_res.xmax+2,2*p_res.ymax+2), layer=plus_layer, centered=True)
    plus_ref = prec_ref_center(plus)
    p_res.add(plus_ref)
    # add pwell
    #p_res.add_padding(
    #    layers=(pdk.get_glayer("pwell"),),
    #    default=pdk.get_grule("pwell", "active_tap")["min_enclosure"],
    #)
    #p_res = add_ports_perimeter(p_res,layer=pdk.get_glayer("pwell"),prefix="well_")

    # Add PLUS port from the last finger
    if fingers > 0:
        if (fingers-1)%2 == 0:
            p_res.add_ports(met1_top_ref.get_ports_list(), prefix="PLUS_")
        else:
            p_res.add_ports(met1_bot_ref.get_ports_list(), prefix="PLUS_")

    # Select model based on type and silicidation
    if n_type:
        if silicided:
            model = 'npolyf_s'  # n-type, silicided
        else:
            model = 'npolyf_u'  # n-type, unsalicided
    else:
        if silicided:
            model = 'ppolyf_s'  # p-type, silicided
        else:
            model = 'ppolyf_u'  # p-type, unsalicided
    
    p_res.info['netlist'] = poly_resistor_netlist(
        circuit_name="POLY_RES",
        model=model,
        width=width,
        length=length,
        multipliers=1,
    )
    
    # Add padding to ensure DRC compliance with poly spacing
    poly_poly_rules = pdk.get_grule("poly", "poly")
    min_poly_sep = poly_poly_rules.get("min_separation", 0.4)  # Default to 0.4μm if not found
    p_res.add_padding(
        layers=(pdk.get_glayer("poly"),),
        default=min_poly_sep
    )
    
    #print(p_res.get_ports_list())
    return p_res

def add_polyres_labels(pdk: MappedPDK, p_res: Component, length, width, fingers):
    p_res.unlock()
    #met1_label = (68, 5)
    #met1_pin = (68, 16)
    move_info = list()
    separation = 0.21 + width
    contact_length = 2.2
    p_pin = p_res << rectangle(size=(0.1,0.1),layer=pdk.get_glayer("met2"),centered=True)
    if fingers%2 == 0:
        movey(p_pin, -contact_length/2 - length/2)
        movex(p_pin, (fingers-1)*separation)
    else:
        movey(p_pin, contact_length/2 + length/2)
        movex(p_pin, (fingers-1)*separation)

    m_pin = p_res << rectangle(size=(0.1,0.1),layer=pdk.get_glayer("met2"),centered=True)
    movey(m_pin, -contact_length/2 - length/2)

    #plus label
    p_label = rectangle(layer=pdk.get_glayer("met2_pin"), size=(0.1,0.1), centered=True).copy()
    p_label.add_label(text="PLUS",layer=pdk.get_glayer("met2_label"))
    move_info.append((p_label,p_pin.ports["e1"],None))

    m_label = rectangle(layer=pdk.get_glayer("met2_pin"), size=(0.1,0.1), centered=True).copy()
    m_label.add_label(text="MINUS",layer=pdk.get_glayer("met2_label"))
    move_info.append((m_label,m_pin.ports["e1"],None))

    # Create a simple substrate connection point (no tapring needed for polyresistor)
    sub_pin = p_res << rectangle(size=(0.1,0.1),layer=pdk.get_glayer("met2"),centered=True)
    movey(sub_pin, contact_length/2 + length/2 + 1.0)  # Place above the resistor
    
    sub_label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.5,0.5),centered=True).copy()
    sub_label.add_label(text="VSUBS",layer=pdk.get_glayer("met2_label"))
    move_info.append((sub_label,sub_pin.ports["e1"], None))
    for comp, prt, alignment in move_info:
        alignment = ('c','b') if alignment is None else alignment
        compref = align_comp_to_port(comp, prt, alignment=alignment)
        p_res.add(compref)
    return p_res.flatten()


# Test different configurations
if __name__ == "__main__":
    print("Testing P-type, unsilicided polyresistor...")
    resistor = add_polyres_labels(gf180_mapped_pdk, poly_resistor(gf180_mapped_pdk, width=0.8, fingers=1, is_snake=True, n_type=False, silicided=False), 1.65, 0.8, 1) 
    resistor.show()
    resistor.name = "POLY_RES_P_UNSAL"
    
    # Generate GDS file
    resistor.write_gds("polyres_test.gds")
    print("✓ GDS file saved: polyres_test.gds")
    
    # Print netlist
    print("P-type, unsilicided netlist:")
    print(resistor.info['netlist'].generate_netlist())

    # Test N-type, silicided
    print("\nTesting N-type, silicided polyresistor...")
    resistor_n_sal = add_polyres_labels(gf180_mapped_pdk, poly_resistor(gf180_mapped_pdk, width=0.8, fingers=1, is_snake=True, n_type=True, silicided=True), 1.65, 0.8, 1)
    resistor_n_sal.show()
    resistor_n_sal.name = "POLY_RES_N_SAL"
    
    # Generate GDS file
    resistor_n_sal.write_gds("polyres_n_sal_test.gds")
    print("✓ GDS file saved: polyres_n_sal_test.gds")
    
    print("N-type, silicided netlist:")
    print(resistor_n_sal.info['netlist'].generate_netlist())