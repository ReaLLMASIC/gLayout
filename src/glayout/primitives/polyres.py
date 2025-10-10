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

    # Create proper SPICE subcircuit definition
    source_netlist = f""".subckt {circuit_name} PLUS MINUS VSUBS
XMAIN PLUS MINUS VSUBS {model} r_width={wtop} r_length={ltop} m={mtop}
.ends {circuit_name}"""

    return Netlist(
        circuit_name=circuit_name,
        nodes=['PLUS', 'MINUS', 'VSUBS'],
        source_netlist=source_netlist,
        instance_format="X{name} {nodes} {circuit_name}",
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
        print(f"Warning: Poly resistor width {width} is less than minimum {min_width}, adjusting to minimum width")
        width = min_width
    
    # Define layers based on PDK
    if pdk.name == 'sky130':
        poly_rs = (66, 13)  # poly resistor layer
        rpm = (86, 20)      # resistor poly mask
        res_mk = None       # SKY130 doesn't use res_mk
    else:
        # GF180 layers
        poly_rs = None
        rpm = None
        res_mk = (110,5)
    p_res = Component()
    contact_length = 2.2
    # Use larger separation to meet PRES/LRES.4 rule (0.6μm spacing to unrelated poly)
    min_poly_separation = pdk.get_grule("poly", "poly")["min_separation"]
    unrelated_poly_separation = 0.6  # PRES/LRES.4 rule
    separation = max(min_poly_separation, unrelated_poly_separation) + width
    #Extend poly for contacts with proper spacing (use grules for spacing)
    if pdk.name == 'sky130':
        # SKY130 uses poly_rs layer for spacing
        contact_spacing = 0.2  # Default spacing for SKY130
    else:
        # GF180 uses SAB layer
        contact_spacing = pdk.get_grule("sab", "mcon")["min_separation"]
    ex_length = length + 2*contact_length + 2*contact_spacing
    for i in range(0,fingers):
        #poly resistor rectangle - ensure minimum width
        poly_width = max(width, pdk.get_grule("poly", "poly")["min_width"])
        p_rect = rectangle(size=(poly_width,ex_length), layer=pdk.get_glayer("poly"), centered=True)
        p_rect_ref = prec_ref_center(p_rect)
        p_res.add(p_rect_ref)
        movex(p_rect_ref, (i)*separation)
        #Add li layer on top and bottom contacts (positioned outside SAB area)
        # Use poly_width to ensure consistency
        li_top = rectangle(size=(poly_width,contact_length), layer=pdk.get_glayer("met1"), centered=True)
        li_top_ref = prec_ref_center(li_top)
        p_res.add(li_top_ref)
        movey(li_top_ref, contact_length/2 + length/2 + contact_spacing)
        movex(li_top_ref, (i)*separation)

        li_bot = rectangle(size=(poly_width,contact_length), layer=pdk.get_glayer("met1"), centered=True)
        li_bot_ref = prec_ref_center(li_bot)
        p_res.add(li_bot_ref)
        movey(li_bot_ref, - contact_length/2 - length/2 - contact_spacing)
        movex(li_bot_ref, (i)*separation)

        # SAB and RES_MK layers will be added after the loop for proper coverage

        #Place poly to met1 contacts with proper overlap (CO.3 rule: 0.07μm poly overlap)
        # Create contacts directly to ensure proper overlap
        contact_size = 0.22  # Standard contact size
        poly_overlap = 0.07  # CO.3 rule requirement
        
        # Top contact
        top_contact = rectangle(size=(contact_size, contact_size), layer=pdk.get_glayer("mcon"), centered=True)
        top_contact_ref = prec_ref_center(top_contact)
        p_res.add(top_contact_ref)
        movey(top_contact_ref, contact_length/2 + length/2 + contact_spacing)
        movex(top_contact_ref, (i)*separation)
        
        # Bottom contact
        bot_contact = rectangle(size=(contact_size, contact_size), layer=pdk.get_glayer("mcon"), centered=True)
        bot_contact_ref = prec_ref_center(bot_contact)
        p_res.add(bot_contact_ref)
        movey(bot_contact_ref, - contact_length/2 - length/2 - contact_spacing)
        movex(bot_contact_ref, (i)*separation)
        
        # Extend poly to ensure proper overlap with contacts
        # Ensure poly extension width meets minimum width requirement
        poly_extension = poly_overlap + contact_size/2
        # Use the same poly_width as the main resistor for consistency
        ext_width = poly_width
        # Ensure extension height also meets minimum width requirement
        ext_height = max(2*poly_extension, pdk.get_grule("poly", "poly")["min_width"])
        top_poly_ext = rectangle(size=(ext_width + 2*poly_extension, ext_height), layer=pdk.get_glayer("poly"), centered=True)
        top_poly_ext_ref = prec_ref_center(top_poly_ext)
        p_res.add(top_poly_ext_ref)
        movey(top_poly_ext_ref, contact_length/2 + length/2 + contact_spacing)
        movex(top_poly_ext_ref, (i)*separation)
        
        bot_poly_ext = rectangle(size=(ext_width + 2*poly_extension, ext_height), layer=pdk.get_glayer("poly"), centered=True)
        bot_poly_ext_ref = prec_ref_center(bot_poly_ext)
        p_res.add(bot_poly_ext_ref)
        movey(bot_poly_ext_ref, - contact_length/2 - length/2 - contact_spacing)
        movex(bot_poly_ext_ref, (i)*separation)

        # place metal 1 layer on contacts with proper overlap (CO.6 rule: 0.005μm metal overlap)
        metal_overlap = 0.12  # CO.6 rule requirement
        met1_size = contact_size + 2 * metal_overlap
        
        met1_top = rectangle(size=(met1_size, met1_size), layer=pdk.get_glayer("met1"), centered=True)
        met1_top_ref = prec_ref_center(met1_top)
        p_res.add(met1_top_ref)
        movey(met1_top_ref, contact_length/2 + length/2 + contact_spacing)
        movex(met1_top_ref, (i)*separation)

        met1_bot = rectangle(size=(met1_size, met1_size), layer=pdk.get_glayer("met1"), centered=True)
        met1_bot_ref = prec_ref_center(met1_bot)
        p_res.add(met1_bot_ref)
        movey(met1_bot_ref, - contact_length/2 - length/2 - contact_spacing)
        movex(met1_bot_ref, (i)*separation)
        #place met1 to met2 vias
        via_size = 0.26  # Standard via size
        via_overlap = 0.12  # Via enclosure requirement
        
        # Top via
        top_via = rectangle(size=(via_size, via_size), layer=pdk.get_glayer("via1"), centered=True)
        top_via_ref = prec_ref_center(top_via)
        p_res.add(top_via_ref)
        movey(top_via_ref, contact_length/2 + length/2 + contact_spacing)
        movex(top_via_ref, (i)*separation)

        # Bottom via
        bot_via = rectangle(size=(via_size, via_size), layer=pdk.get_glayer("via1"), centered=True)
        bot_via_ref = prec_ref_center(bot_via)
        p_res.add(bot_via_ref)
        movey(bot_via_ref, - contact_length/2 - length/2 - contact_spacing)
        movex(bot_via_ref, (i)*separation)
        
        # Extend met1 to ensure proper overlap with vias
        met1_via_ext = via_size + 2 * via_overlap
        top_met1_ext = rectangle(size=(met1_via_ext, met1_via_ext), layer=pdk.get_glayer("met1"), centered=True)
        top_met1_ext_ref = prec_ref_center(top_met1_ext)
        p_res.add(top_met1_ext_ref)
        movey(top_met1_ext_ref, contact_length/2 + length/2 + contact_spacing)
        movex(top_met1_ext_ref, (i)*separation)
        
        bot_met1_ext = rectangle(size=(met1_via_ext, met1_via_ext), layer=pdk.get_glayer("met1"), centered=True)
        bot_met1_ext_ref = prec_ref_center(bot_met1_ext)
        p_res.add(bot_met1_ext_ref)
        movey(bot_met1_ext_ref, - contact_length/2 - length/2 - contact_spacing)
        movex(bot_met1_ext_ref, (i)*separation)

        # Add met2 layer for top-level routing
        met2_size = via_size + 2 * via_overlap
        met2_top = rectangle(size=(met2_size, met2_size), layer=pdk.get_glayer("met2"), centered=True)
        met2_top_ref = prec_ref_center(met2_top)
        p_res.add(met2_top_ref)
        movey(met2_top_ref, contact_length/2 + length/2 + contact_spacing)
        movex(met2_top_ref, (i)*separation)

        met2_bot = rectangle(size=(met2_size, met2_size), layer=pdk.get_glayer("met2"), centered=True)
        met2_bot_ref = prec_ref_center(met2_bot)
        p_res.add(met2_bot_ref)
        movey(met2_bot_ref, - contact_length/2 - length/2 - contact_spacing)
        movex(met2_bot_ref, (i)*separation)

        con_offset = (separation)/2
        if is_snake == True:
            if i > 0:
                met2_connect = rectangle(size=(width+separation,contact_length), layer=pdk.get_glayer("met2"),centered= True)
                met2_con_ref = prec_ref_center(met2_connect)
                p_res.add(met2_con_ref)
                if i%2 == 0:
                    movey(met2_con_ref, - contact_length/2 - length/2 - contact_spacing)
                    movex(met2_con_ref, (i-1)*separation+con_offset)
                else:
                    movey(met2_con_ref, contact_length/2 + length/2 + contact_spacing)
                    movex(met2_con_ref, (i-1)*separation+con_offset)

        if i == 0:
            p_res.add_ports(met2_bot_ref.get_ports_list(), prefix="MINUS_")


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
    
    # Add poly resistor layers based on PDK
    if pdk.name == 'sky130':
        # SKY130 uses poly_rs and rpm layers
        poly_rs_enclosure = 0.2  # Default enclosure for SKY130
        poly_rs_width = width * fingers + 2 * poly_rs_enclosure
        poly_rs_length = length + 2 * poly_rs_enclosure
        poly_rs_rect = rectangle(size=(poly_rs_width, poly_rs_length), layer=poly_rs, centered=True)
        poly_rs_ref = prec_ref_center(poly_rs_rect)
        p_res.add(poly_rs_ref)
        
        # Add rpm layer
        rpm_enclosure = 0.2  # Default enclosure for SKY130
        rpm_width = width * fingers + 2 * rpm_enclosure
        rpm_length = length + 2 * rpm_enclosure
        rpm_rect = rectangle(size=(rpm_width, rpm_length), layer=rpm, centered=True)
        rpm_ref = prec_ref_center(rpm_rect)
        p_res.add(rpm_ref)
    else:
        # GF180 uses SAB and RES_MK layers
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
        if pdk.name == 'sky130':
            plus_enclosure = 0.11  # Default enclosure for SKY130
        else:
            plus_enclosure = pdk.get_grule("n+s/d", "poly")["min_enclosure"]
    else:
        plus_layer = pdk.get_glayer("p+s/d")  # P-plus for P-type polyresistor
        if pdk.name == 'sky130':
            plus_enclosure = 0.11  # Default enclosure for SKY130
        else:
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
        p_res.add_ports(met2_top_ref.get_ports_list(), prefix="PLUS_")
    else:
        p_res.add_ports(met2_bot_ref.get_ports_list(), prefix="PLUS_")

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
    resistor = add_polyres_labels(sky130_mapped_pdk, poly_resistor(sky130_mapped_pdk, width=0.8, fingers=1, is_snake=True, n_type=False, silicided=False), 1.65, 0.8, 1) 
    resistor.show()
    resistor.name = "POLY_RES_P_UNSAL"
    magic_drc_result = sky130_mapped_pdk.drc_magic(resistor, resistor.name)
    lvs_result = sky130_mapped_pdk.lvs_netgen(resistor,resistor.name,copy_intermediate_files=True)
    print("P-type, unsilicided netlist:")
    print(resistor.info['netlist'].generate_netlist())
    
    # Test N-type, silicided
    print("\nTesting N-type, silicided polyresistor...")
    resistor_n_sal = add_polyres_labels(sky130_mapped_pdk, poly_resistor(sky130_mapped_pdk, width=0.8, fingers=1, is_snake=True, n_type=True, silicided=True), 1.65, 0.8, 1)
    resistor_n_sal.show()
    resistor_n_sal.name = "POLY_RES_N_SAL"
    print("N-type, silicided netlist:")
    print(resistor_n_sal.info['netlist'].generate_netlist())