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
from glayout.primitives.guardring import tapring

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
    width: float = 0.8,  # Minimum width per DRC rule PRES.1/LRES.1 (will be validated against grules)
    fingers: int = 1,
    tie_layers: tuple[str,str] = ("met2","met2"),
    is_snake: bool = True,
    n_type: bool = False,
    silicided: bool = False
) -> Component:
    # Validate width against minimum requirements
    min_width = pdk.get_grule("poly", "poly")["min_width"]
    if width < min_width:
        raise ValueError(f"Poly resistor width {width} must be >= {min_width} (minimum from grules)")
    
    #poly_res = (66, 13)
    sab = (49,0)
    res_mk = (110,5)
    p_res = Component()
    contact_length = 2.2
    separation = pdk.get_grule("poly", "poly")["min_separation"] + width  # Use grules for spacing
    #Extend poly for contacts with proper spacing from SAB (use grules for spacing)
    sab_contact_spacing = pdk.get_grule("sab", "mcon")["min_separation"]
    ex_length = length + 2*contact_length + 2*sab_contact_spacing
    for i in range(0,fingers):
        #poly resistor rectangle
        p_rect = rectangle(size=(width,ex_length), layer=pdk.get_glayer("poly"), centered=True)
        p_rect_ref = prec_ref_center(p_rect)
        p_res.add(p_rect_ref)
        movex(p_rect_ref, (i)*separation)
        #Add li layer on top and bottom contacts (positioned outside SAB area)
        li_top = rectangle(size=(width,contact_length), layer=pdk.get_glayer("met1"), centered=True)
        li_top_ref = prec_ref_center(li_top)
        p_res.add(li_top_ref)
        movey(li_top_ref, contact_length/2 + length/2 + sab_contact_spacing)
        movex(li_top_ref, (i)*separation)

        li_bot = rectangle(size=(width,contact_length), layer=pdk.get_glayer("met1"), centered=True)
        li_bot_ref = prec_ref_center(li_bot)
        p_res.add(li_bot_ref)
        movey(li_bot_ref, - contact_length/2 - length/2 - sab_contact_spacing)
        movex(li_bot_ref, (i)*separation)

        # SAB and RES_MK layers will be added after the loop for proper coverage

        #Place poly to li via contact
        licon1 = via_array(pdk, "poly", "met1", size=(width,contact_length))
        licon1_ref = prec_ref_center(licon1)
        #p_res.add(licon1_ref)
        #movey(licon1_ref, contact_length/2 + length/2)

        licon2 = via_array(pdk, "poly", "met1", size=(width,contact_length))
        licon2_ref = prec_ref_center(licon2)
        p_res.add(licon2_ref)
        movey(licon2_ref, - contact_length/2 - length/2 - sab_contact_spacing)
        movex(licon2_ref, (i)*separation)

        licon3 = via_array(pdk, "poly", "met1", size=(width,contact_length))
        licon3_ref = prec_ref_center(licon3)
        p_res.add(licon3_ref)
        movey(licon3_ref, contact_length/2 + length/2 + sab_contact_spacing)
        movex(licon3_ref, (i)*separation)

        # place metal 1 layer on contacts
        met1_top = rectangle(size=(width,contact_length), layer=pdk.get_glayer("met2"), centered=True)
        met1_top_ref = prec_ref_center(met1_top)
        p_res.add(met1_top_ref)
        movey(met1_top_ref, contact_length/2 + length/2 + sab_contact_spacing)
        movex(met1_top_ref, (i)*separation)

        met1_bot = rectangle(size=(width,contact_length), layer=pdk.get_glayer("met2"), centered=True)
        met1_bot_ref = prec_ref_center(met1_bot)
        p_res.add(met1_bot_ref)
        movey(met1_bot_ref, - contact_length/2 - length/2 - sab_contact_spacing)
        movex(met1_bot_ref, (i)*separation)
        #place li to metal vias
        met1con1 = via_array(pdk, "met1", "met2", size=(width,contact_length))
        met1con1_ref = prec_ref_center(met1con1)
        p_res.add(met1con1_ref)
        movey(met1con1_ref, contact_length/2 + length/2 + sab_contact_spacing)
        movex(met1con1_ref, (i)*separation)

        met1con2 = via_array(pdk, "met1", "met2", size=(width,contact_length))
        met1con2_ref = prec_ref_center(met1con2)
        p_res.add(met1con2_ref)
        movey(met1con2_ref, - contact_length/2 - length/2 - sab_contact_spacing)
        movex(met1con2_ref, (i)*separation)

        con_offset = (separation)/2
        if is_snake == True:
            if i > 0:
                met1_connect = rectangle(size=(width+separation,contact_length), layer=pdk.get_glayer("met2"),centered= True)
                met1_con_ref = prec_ref_center(met1_connect)
                p_res.add(met1_con_ref)
                if i%2 == 0:
                    movey(met1_con_ref, - contact_length/2 - length/2 - sab_contact_spacing)
                    movex(met1_con_ref, (i-1)*separation+con_offset)
                else:
                    movey(met1_con_ref, contact_length/2 + length/2 + sab_contact_spacing)
                    movex(met1_con_ref, (i-1)*separation+con_offset)

        if i == 0:
            p_res.add_ports(met1_bot_ref.get_ports_list(), prefix="MINUS_")


    tap_separation = max(
            pdk.util_max_metal_seperation(),
            pdk.get_grule("active_diff", "active_tap")["min_separation"],
        )
    tap_separation += pdk.get_grule("p+s/d", "active_tap")["min_enclosure"]
    tap_encloses = (
            2 * (tap_separation + p_res.xmax),
            2 * (tap_separation + p_res.ymax),
        )
    tiering_ref = p_res << tapring(
            pdk,
            enclosed_rectangle=tap_encloses,
            sdlayer="p+s/d",
            horizontal_glayer=tie_layers[0],
            vertical_glayer=tie_layers[1],
        )
    p_res.add_ports(tiering_ref.get_ports_list(), prefix="tie_")
    
    # Add SAB layer with proper enclosure (use grules for enclosure)
    sab_enclosure = pdk.get_grule("sab", "poly")["min_enclosure"]
    sab_width = width * fingers + 2 * sab_enclosure
    sab_length = length + 2 * sab_enclosure
    sab_rect = rectangle(size=(sab_width, sab_length), layer=sab, centered=True)
    sab_ref = prec_ref_center(sab_rect)
    p_res.add(sab_ref)
    
    # Add RES_MK layer with proper coverage (must cover poly resistor per PRES.9a/LRES.9a)
    res_mk_enclosure = pdk.get_grule("res_mk", "poly")["min_enclosure"]
    res_mk_width = width * fingers + 2 * res_mk_enclosure
    res_mk_length = length + 2 * res_mk_enclosure
    res_mk_rect = rectangle(size=(res_mk_width, res_mk_length), layer=res_mk, centered=True)
    res_mk_ref = prec_ref_center(res_mk_rect)
    p_res.add(res_mk_ref)

    # add pplus or nplus layer according to the polyresistor type
    if n_type:
        plus_layer = pdk.get_glayer("n+s/d")  # N-plus for N-type polyresistor
        plus_enclosure = pdk.get_grule("n+s/d", "poly")["min_enclosure"]
    else:
        plus_layer = pdk.get_glayer("p+s/d")  # P-plus for P-type polyresistor
        plus_enclosure = pdk.get_grule("p+s/d", "poly")["min_enclosure"]
    
    # P+/N+ implant with proper enclosure (use grules for enclosure)
    plus_width = width * fingers + 2 * plus_enclosure
    plus_length = length + 2 * plus_enclosure
    plus = rectangle(size=(plus_width, plus_length), layer=plus_layer, centered=True)
    plus_ref = prec_ref_center(plus)
    p_res.add(plus_ref)
    # add pwell
    #p_res.add_padding(
    #    layers=(pdk.get_glayer("pwell"),),
    #    default=pdk.get_grule("pwell", "active_tap")["min_enclosure"],
    #)
    #p_res = add_ports_perimeter(p_res,layer=pdk.get_glayer("pwell"),prefix="well_")

    #print(i)
    if i%2 == 0:
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

    sub_label = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.5,0.5),centered=True).copy()
    sub_label.add_label(text="VSUBS",layer=pdk.get_glayer("met2_label"))
    move_info.append((sub_label,p_res.ports["tie_N_top_met_N"], None))
    for comp, prt, alignment in move_info:
        alignment = ('c','b') if alignment is None else alignment
        compref = align_comp_to_port(comp, prt, alignment=alignment)
        p_res.add(compref)
    return p_res.flatten()


# Test different configurations - commented out to avoid execution during import
# Uncomment the following lines to run tests manually:
if __name__ == "__main__":
    print("Testing P-type, unsilicided polyresistor...")
    resistor = add_polyres_labels(gf180_mapped_pdk, poly_resistor(gf180_mapped_pdk, width=0.8, fingers=1, is_snake=True, n_type=False, silicided=False), 1.65, 0.8, 1) 
    resistor.show()
    resistor.name = "POLY_RES_P_UNSAL"
    magic_drc_result = gf180_mapped_pdk.drc_magic(resistor, resistor.name)
    lvs_result = gf180_mapped_pdk.lvs_netgen(resistor,resistor.name,copy_intermediate_files=True)
    print("P-type, unsilicided netlist:")
    print(resistor.info['netlist'].generate_netlist())
    
    # Test N-type, silicided
    print("\nTesting N-type, silicided polyresistor...")
    resistor_n_sal = add_polyres_labels(gf180_mapped_pdk, poly_resistor(gf180_mapped_pdk, width=0.8, fingers=1, is_snake=True, n_type=True, silicided=True), 1.65, 0.8, 1)
    resistor_n_sal.show()
    resistor_n_sal.name = "POLY_RES_N_SAL"
    print("N-type, silicided netlist:")
    print(resistor_n_sal.info['netlist'].generate_netlist())