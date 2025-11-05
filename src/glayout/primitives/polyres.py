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
    width: float = 0.35,
    fingers: int = 1,
    tie_layers: tuple[str,str] = ("met2","met2"),
    is_snake: bool = True,
    n_type: bool = False,
    silicided: bool = False
) -> Component:
    #poly_res = (66, 13)
    sab = (49,0)
    res_mk = (110,5)
    p_res = Component()
    contact_length = 2.2
    # Calculate separation to ensure all spacing rules are met
    # Get minimum spacing requirements from PDK rules
    poly_min_sep = pdk.get_grule("poly", "poly").get("min_separation", 0.4)
    # PRES.4 requires 0.6µm spacing from poly2 resistor to unrelated poly2
    # Use the more strict requirement for poly2 resistors
    poly2_resistor_min_sep = 0.6
    met1_min_sep = pdk.get_grule("met1", "met1").get("min_separation", 0.23)
    # Separation must satisfy all: spacing = center_to_center - width >= min_separation
    # So: center_to_center >= width + min_separation
    # Use the maximum requirement to satisfy all rules (PRES.4 is most strict for poly2 resistors)
    separation = width + max(poly2_resistor_min_sep, met1_min_sep)
    # Snap to grid for proper alignment
    separation = pdk.snap_to_2xgrid(separation)
    #Extend poly for contacts
    ex_length = length + 2*contact_length

    # Calculate SAB layer width: account for finger spacing (separation between fingers)
    # SB.5a requires 0.3µm spacing from SAB to unrelated poly2, but for related poly2 
    # (same resistor fingers), SAB should cover all fingers with proper overlap
    if fingers > 1:
        # Total width = first finger + spacing*(fingers-1) + last finger width
        sab_width = width + (fingers - 1) * separation + 0.56  # 0.56 for overlap/extensions
    else:
        sab_width = width + 0.56  # Single finger case

    ##Add unsalicide layer, if not silicided, use this block, otherwise skip
    # SAB layer should cover all fingers (only create once, outside the loop)
    unsal = rectangle(size=(sab_width, length), layer=sab, centered=True)
    unsal_ref = prec_ref_center(unsal)
    p_res.add(unsal_ref)

    ##Add RES_MK layer
    # RES_MK should match SAB dimensions (only create once, outside the loop)
    resmk = rectangle(size=(sab_width, length), layer=res_mk, centered=True)
    resmk_ref = prec_ref_center(resmk)
    p_res.add(resmk_ref)

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

        #Place poly to li via contact
        licon1 = via_array(pdk, "poly", "met1", size=(width,contact_length))
        licon1_ref = prec_ref_center(licon1)
        #p_res.add(licon1_ref)
        #movey(licon1_ref, contact_length/2 + length/2)

        licon2 = via_array(pdk, "poly", "met1", size=(width,contact_length))
        licon2_ref = prec_ref_center(licon2)
        p_res.add(licon2_ref)
        movey(licon2_ref, - contact_length/2 - length/2)
        movex(licon2_ref, (i)*separation)

        licon3 = via_array(pdk, "poly", "met1", size=(width,contact_length))
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
        met1con1 = via_array(pdk, "met1", "met2", size=(width,contact_length))
        met1con1_ref = prec_ref_center(met1con1)
        p_res.add(met1con1_ref)
        movey(met1con1_ref, contact_length/2 + length/2)
        movex(met1con1_ref, (i)*separation)

        met1con2 = via_array(pdk, "met1", "met2", size=(width,contact_length))
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


    # Calculate tap_separation to ensure proper spacing from poly resistor to COMP (active_diff)
    # tapring creates COMP layer via active_tap, so we need to ensure poly-to-COMP spacing (0.6µm minimum for PRES.3)
    poly_to_comp_sep = pdk.get_grule("poly", "active_diff").get("min_separation", 0.6)

    # tap_separation_base for other spacing requirements (metal, tap spacing, etc.)
    tap_separation_base = max(
            pdk.util_max_metal_seperation(),
            pdk.get_grule("active_diff", "active_tap")["min_separation"],
        )
    tap_separation_base += pdk.get_grule("p+s/d", "active_tap")["min_enclosure"]

    # tap_encloses is the internal rectangle size that tapring will enclose
    # The tapring creates a ring around this rectangle with active_tap (which contains COMP)
    # To ensure PRES.3: poly edge to COMP edge >= 0.6µm
    # The ring's inner edge is at enclosed_rectangle edge, so COMP edge is at that edge
    # Since p_res.xmax is half-width from center (poly edge distance), tapring internal rectangle half-width should be:
    # p_res.xmax + poly_to_comp_sep to ensure poly-to-COMP spacing
    # Add tap_separation_base for other requirements
    # Ensure minimum 0.6µm spacing from poly to COMP (PRES.3 requirement)
    # Current spacing is 0.56µm, need at least 0.04µm more to reach 0.6µm
    # Add safety margin (0.15µm) to account for rounding, grid snapping, and ensure >= 0.6µm
    safety_margin = 0.15  # Add safety margin to ensure >= 0.6µm even after grid snapping
    total_separation = poly_to_comp_sep + tap_separation_base + safety_margin
    # Snap to grid to ensure proper alignment
    total_separation = pdk.snap_to_2xgrid(total_separation)
    # Ensure minimum: poly_to_comp_sep (0.6µm) must be met
    # total_separation should be at least poly_to_comp_sep + tap_separation_base
    min_required_separation = poly_to_comp_sep + tap_separation_base
    min_required_separation = pdk.snap_to_2xgrid(min_required_separation)
    if total_separation < min_required_separation:
        total_separation = min_required_separation + 0.15  # Add extra margin if below minimum
        total_separation = pdk.snap_to_2xgrid(total_separation)
    tap_encloses = (
            2 * (p_res.xmax + total_separation),
            2 * (p_res.ymax + total_separation),
        )
    tiering_ref = p_res << tapring(
            pdk,
            enclosed_rectangle=tap_encloses,
            sdlayer="p+s/d",
            horizontal_glayer=tie_layers[0],
            vertical_glayer=tie_layers[1],
        )
    p_res.add_ports(tiering_ref.get_ports_list(), prefix="tie_")

    # add pplus or nplus layer according to the polyresistor type
    if n_type:
        plus_layer = pdk.get_glayer("n+s/d")  # N-plus for N-type polyresistor
    else:
        plus_layer = pdk.get_glayer("p+s/d")  # P-plus for P-type polyresistor

    plus = rectangle(size=(2*p_res.xmax+2,2*p_res.ymax+2), layer=plus_layer, centered=True)
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
    # Calculate separation the same way as in poly_resistor() to ensure consistency
    # PRES.4 requires 0.6µm spacing from poly2 resistor to unrelated poly2
    poly2_resistor_min_sep = 0.6
    met1_min_sep = pdk.get_grule("met1", "met1").get("min_separation", 0.23)
    separation = width + max(poly2_resistor_min_sep, met1_min_sep)
    separation = pdk.snap_to_2xgrid(separation)
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

# # Test multi-finger configuration (M1.2a spacing fix)
print("\nTesting multi-finger polyresistor (width=0.8, fingers=5)...")
resistor_multi = add_polyres_labels(
     gf180_mapped_pdk, 
     poly_resistor(gf180_mapped_pdk, width=0.8, length=1.5, fingers=5, is_snake=True, n_type=False, silicided=False), 
     1.5, 0.8, 5
 )
resistor_multi.name = "polyres_multifinger_w0.8_f5"
print(f"Created resistor with {5} fingers, width=0.8µm")
print(f"GDS file will be saved as: {resistor_multi.name}.gds")
resistor_multi.show()
print("Running DRC check...")
drc_result = gf180_mapped_pdk.drc(resistor_multi)
print(f"DRC Result: {drc_result}")
