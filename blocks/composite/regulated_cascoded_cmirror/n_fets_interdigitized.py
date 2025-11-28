from pathlib import Path
from glayout.pdk.mappedpdk import MappedPDK
from pydantic import validate_arguments
from gdsfactory.component import Component
from glayout.primitives.fet import nmos, pmos, multiplier
from glayout.util.comp_utils import evaluate_bbox
from typing import Literal, Union, List, Tuple
from glayout.util.port_utils import rename_ports_by_orientation, rename_ports_by_list, create_private_ports
from glayout.util.comp_utils import prec_ref_center,evaluate_bbox, prec_center, align_comp_to_port
from glayout.routing.straight_route import straight_route
from gdsfactory.functions import transformed
from glayout.primitives.guardring import tapring
from glayout.util.port_utils import add_ports_perimeter
from gdsfactory.cell import clear_cache
from typing import Literal, Optional, Union
from glayout.pdk.sky130_mapped import sky130_mapped_pdk
from glayout.pdk.gf180_mapped import gf180_mapped_pdk
from glayout.spice.netlist import Netlist
from gdsfactory.components import text_freetype, rectangle
from glayout.primitives.via_gen import via_stack
import re

from glayout import MappedPDK, sky130,gf180

from glayout.util.snap_to_grid import component_snap_to_grid
from glayout.placement.two_transistor_interdigitized import two_nfet_interdigitized, two_pfet_interdigitized

###### Only Required for IIC-OSIC Docker
import os
import subprocess

# Run a shell, source .bashrc, then printenv
cmd = 'bash -c "source ~/.bashrc && printenv"'
result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
env_vars = {}
for line in result.stdout.splitlines():
    if '=' in line:
        key, value = line.split('=', 1)
        env_vars[key] = value

# Now, update os.environ with these
os.environ.update(env_vars)

#from glayout.placement.two_transistor_interdigitized import two_nfet_interdigitized; from glayout.pdk.sky130_mapped import sky130_mapped_pdk as pdk; biasParams=[6,2,4]; rmult=2
def add_n_int_labels(
    device_int_in: Component,
    pdk: MappedPDK,
    *,
    n_or_p_fet: Literal["nfet", "pfet"] = "nfet",
    width: Optional[float] = 3.0,
    length: Optional[float] = None,
    fingers: int = 1,
    multipliers: int = 1,
    with_dummy: bool = False,
) -> Component:
    """
    - Auto-detects device prefixes (A_, B_, C_, ...) from the component's ports.
    - Adds labels VSSi / VDDi / VGi next to source / drain / gate ports.
    - Creates and attaches a Netlist with Xi VDDi VGi VSSi VB <model>.
    """

    device_int_in.unlock()

    # -------- 1) Discover device prefixes (A_, B_, C_, ...) --------
    # We detect prefixes by looking for ports named "<PREFIX>_source_*", "<PREFIX>_drain_*", "<PREFIX>_gate_*"
    prefixes = set()
    src_pat  = re.compile(r"^([A-Za-z]+)_source_[A-Z]$")
    drn_pat  = re.compile(r"^([A-Za-z]+)_drain_[A-Z]$")
    gate_pat = re.compile(r"^([A-Za-z]+)_gate_[A-Z]$")

    for pname in device_int_in.ports.keys():
        m = src_pat.match(pname) or drn_pat.match(pname) or gate_pat.match(pname)
        if m:
            prefixes.add(m.group(1))

    # Sort prefixes alphabetically so numbering is deterministic: A,B,C,... → 1,2,3,...
    prefixes = sorted(prefixes)
    if not prefixes:
        raise ValueError("Could not detect any device prefixes (e.g., A_, B_, ...) from ports.")

    # Helper to resolve a port robustly for a given prefix and role
    def _resolve_port(prefix: str, role: str) -> str:
        """
        role ∈ {'source','drain','gate'}
        Prefer specific orientations if available, otherwise any matching role.
        """
        # Try common orientations first
        candidates_ordered = {
            "source": [f"{prefix}_source_E", f"{prefix}_source_W", f"{prefix}_source_N", f"{prefix}_source_S"],
            "drain":  [f"{prefix}_drain_E",  f"{prefix}_drain_W",  f"{prefix}_drain_N",  f"{prefix}_drain_S"],
            "gate":   [f"{prefix}_gate_S",   f"{prefix}_gate_N",   f"{prefix}_gate_E",   f"{prefix}_gate_W"],
        }[role]
        for c in candidates_ordered:
            if c in device_int_in.ports:
                return c
        # Fallback: first any port matching the role
        for pname in device_int_in.ports.keys():
            if pname.startswith(f"{prefix}_{role}_"):
                return pname
        raise KeyError(f"No port found for {prefix} {role}")

    # -------- 2) Add labels for each device i --------
    move_info = []
    for i, prefix in enumerate(prefixes, start=1):
        # VSSi at source
        vss = rectangle(layer=pdk.get_glayer("met2_pin"), size=(0.27, 0.27), centered=True).copy()
        vss.add_label(text=f"VSS{i}", layer=pdk.get_glayer("met2_label"))
        move_info.append((vss, device_int_in.ports[_resolve_port(prefix, "source")], None))

        # VDDi at drain
        vdd = rectangle(layer=pdk.get_glayer("met2_pin"), size=(0.27, 0.27), centered=True).copy()
        vdd.add_label(text=f"VDD{i}", layer=pdk.get_glayer("met2_label"))
        move_info.append((vdd, device_int_in.ports[_resolve_port(prefix, "drain")], None))

        # VGi at gate
        vg = rectangle(layer=pdk.get_glayer("met2_pin"), size=(0.27, 0.27), centered=True).copy()
        vg.add_label(text=f"VG{i}", layer=pdk.get_glayer("met2_label"))
        move_info.append((vg, device_int_in.ports[_resolve_port(prefix, "gate")], None))

    # Bulk (VB) — try a generic well tie port name; if missing, skip label quietly
    try:
        vb_rect = rectangle(layer=pdk.get_glayer("met2_pin"), size=(0.5, 0.5), centered=True).copy()
        vb_rect.add_label(text="VB", layer=pdk.get_glayer("met2_label"))
        move_info.append((vb_rect, device_int_in.ports["welltie_S_top_met_S"], None))
    except KeyError:
        # If your well-tie port is named differently, add another try here or ignore
        pass

    # Place all labels
    for comp, prt, alignment in move_info:
        alignment = ('c', 'b') if alignment is None else alignment
        compref = align_comp_to_port(comp, prt, alignment=alignment)
        device_int_in.add(compref)

    # -------- 3) Generate & attach Netlist with N devices --------
    if length is None:
        length = pdk.get_grule("poly")["min_width"]
    if width is None:
        width = 3.0

    model = pdk.models[n_or_p_fet]
    mtop = fingers * multipliers
    N = len(prefixes)

    # Build .subckt body
    # Nodes order: VDD1..N, VSS1..N, VG1..N, VB  (or any ordering you prefer)
    nodes = (
        [f"VDD{i}" for i in range(1, N + 1)] +
        [f"VSS{i}" for i in range(1, N + 1)] +
        [f"VG{i}"  for i in range(1, N + 1)] +
        ["VB"]
    )

    lines = [f".subckt {{circuit_name}} {' '.join(nodes)} l={length} w={width} m=1"]
    # XAi lines
    for i in range(1, N + 1):
        lines.append(f"X{i} VDD{i} VG{i} VSS{i} VB {model} l={length} w={width} m={mtop}")
    if with_dummy:
        lines.append(f"XDUMMY VB VB VB VB {model} l={length} w={width} m=2")
    lines.append(".ends {circuit_name}")
    source_netlist = "\n".join(lines)

    device_int_in.info["netlist"] = Netlist(
        circuit_name=f"{N}_trans_interdigitized",
        nodes=nodes,
        source_netlist=source_netlist,
        instance_format="X{name} {nodes} {circuit_name} l={length} w={width} m=1",
        parameters={
            "model": model,
            "width": width,
            "length": length,
            "mult": multipliers,
        },
    )

    return device_int_in.flatten()


def n_tran_interdigitized_netlist(
    pdk: MappedPDK, 
    width: Optional[float],
    length: Optional[float],
    fingers: int,
    multipliers: int, 
    with_dummy: bool = True,
    n_or_p_fet: Literal['nfet','pfet'] = 'nfet',
    subckt_only: Optional[bool] = False,   # kept for API compatibility
    n_devices: int = 2,                    # NEW: how many transistors to generate
) -> Netlist:
    """
    Build a subcircuit with N interdigitized transistors.
    Nodes: VDD1..N, VSS1..N, VG1..N, VB
    Instances: X1..XN (each m = fingers * multipliers)
    """

    if length is None:
        length = pdk.get_grule('poly')['min_width']
    if width is None:
        width = 3.0

    model = pdk.models[n_or_p_fet]
    mtop = fingers * multipliers
    N = int(n_devices)

    # Node list (order can be adapted if you prefer a different convention)
    nodes = (
        [f"VDD{i}" for i in range(1, N+1)] +
        [f"VSS{i}" for i in range(1, N+1)] +
        [f"VG{i}"  for i in range(1, N+1)] +
        ["VB"]
    )

    # Subckt header
    lines = [f".subckt {{circuit_name}} {' '.join(nodes)} l={length} w={width} m=1"]

    # Instances X1..XN
    for i in range(1, N+1):
        lines.append(f"X{i} VDD{i} VG{i} VSS{i} VB {model} l={length} w={width} m={mtop}")

    # Optional dummy
    if with_dummy:
        lines.append(f"XDUMMY VB VB VB VB {model} l={length} w={width} m=2")

    # End subckt
    lines.append(".ends {circuit_name}")
    source_netlist = "\n".join(lines)

    return Netlist(
        circuit_name=f"{N}_trans_interdigitized",
        nodes=nodes,
        source_netlist=source_netlist,
        instance_format="X{name} {nodes} {circuit_name} l={length} w={width} m=1",
        parameters={
            'model': model,
            'width': width,
            'length': length,   
            'mult': multipliers
        }
    )

def _letters(n: int) -> List[str]:
    """Return ['A','B','C',...] up to n (supports up to 26 cleanly)."""
    if n < 1:
        raise ValueError("n_devices must be >= 1")
    if n > 26:
        # Simple guard; extend to AA/AB... if you need more than 26.
        raise ValueError("This helper supports at most 26 devices (A..Z).")
    import string
    return list(string.ascii_uppercase[:n])

def _find_port(cref, patterns: list[str]) -> str | None:
    """Return first matching port name on cref given a list of regex patterns."""
    for pat in patterns:
        rx = re.compile(pat)
        for pname in cref.ports.keys():
            if rx.fullmatch(pname):
                return pname
    return None



@validate_arguments
def macro_n_transistor_interdigitized(
    pdk: MappedPDK,
    numcols: int,
    devices: Literal["nfet", "pfet"],
    n_devices: int,                               # NEW: how many devices per interdigitized row (e.g., 3 → A,B,C)
    dummy: Union[bool, tuple[bool, bool]] = True, # left/right edge dummies
    **kwargs,
) -> Component:
    """
    Place N identical transistors in a single interdigitized row.
    Pattern: A B C ... (N devices) repeated horizontally for `numcols` columns.

    - For matching, per-device metal/poly extents are equalized using PDK spacing.
    - Creates 3*N global buses across the full row: <Letter>_source / _drain / _gate
    - Exposes ports for all buses, + private ports for internal use (like original).
    """

    if isinstance(dummy, bool):
        dummy = (dummy, dummy)

    # ----- common kwargs for all multipliers -----
    kwargs = dict(kwargs)
    kwargs["sd_route_extension"] = 0
    kwargs["gate_route_extension"] = 0
    kwargs["sdlayer"] = "n+s/d" if devices == "nfet" else "p+s/d"
    kwargs["pdk"] = pdk

    # Device letters: A, B, C, ...
    letters = _letters(n_devices)

    # ---- Create a "center" baseline device for reference (letter A) ----
    # leftmost variant (with left dummy if requested)
    kwargs["dummy"] = (True, False) if dummy[0] else False
    leftmost_A = multiplier(**kwargs)

    # center variant (no dummies, base extents)
    kwargs["dummy"] = False
    center_A = multiplier(**kwargs)


    # Compute extensions so other devices align endpoints (parasitic matching).
    # We mimic your original "devB extension" logic, generalized:
    dev_sd_extension = pdk.util_max_metal_seperation() + abs(
        center_A.ports["drain_N"].center[1] - center_A.ports["diff_N"].center[1]
    )
    dev_gate_extension = pdk.util_max_metal_seperation() + abs(
        center_A.ports["row0_col0_gate_S"].center[1] - center_A.ports["gate_S"].center[1]
    )
    kwargs["sd_route_extension"] = pdk.snap_to_2xgrid(dev_sd_extension)
    kwargs["gate_route_extension"] = pdk.snap_to_2xgrid(dev_gate_extension)

    # Build "center" variants for all letters (B..Z), using same matched extensions
    center_by_letter = {"A": center_A}
    for idx, L in enumerate(letters[1:]):

        kwargs["sd_route_extension"] = pdk.snap_to_2xgrid((idx+1)*dev_sd_extension)
        kwargs["gate_route_extension"] = pdk.snap_to_2xgrid((idx+1)*dev_gate_extension)
        # no dummies in the middle cells
        kwargs["dummy"] = False
        center_by_letter[L] = multiplier(**kwargs)

    # Rightmost variant for the last placed device if we put a right dummy:
    kwargs["dummy"] = (False, True) if dummy[1] else False
    rightmost_last = multiplier(**kwargs)  # used at the very end only

    # ----- Placement loop -----
    idplace = Component()
    # pitch: device width + min diff separation (like original)
    dims = evaluate_bbox(center_A)
    xdisp = pdk.snap_to_2xgrid(
        dims[0] + pdk.get_grule("active_diff")["min_separation"]
    )

    refs = []  # placed ComponentReferences (in sequence)
    total_slots = n_devices * numcols  # total instances to place horizontally

    for i in range(total_slots):
        # The device index cycles 0..n_devices-1
        idx = i % n_devices
        L = letters[idx]

        # Which template to use?
        if i == 0:
            # very first instance uses leftmost_A (if left dummy requested), else center_A
            cref = idplace << (leftmost_A if dummy[0] else center_by_letter["A"])
        elif i == (total_slots - 1):
            # very last instance: use rightmost_last (if right dummy requested), else center variant
            cref = idplace << (rightmost_last if dummy[1] else center_by_letter[L])
        else:
            # middle: center variant for that letter
            cref = idplace << center_by_letter[L]

        cref.name = f"{L}_{i // n_devices}"

        # Move to its horizontal slot
        cref.movex(i * xdisp)
        refs.append(cref)

        # Add the placed instance's ports with a per-instance prefix:
        # e.g., A_0_, B_0_, C_0_, A_1_, ...
        prefix = f"{L}_{i // n_devices}_"
        idplace.add_ports(cref.get_ports_list(), prefix=prefix)



    # ----- Equalize extents for each placed device (like original) -----
    # For each placed instance, extend its S/D top metal to the last instance's drain_E,
    # and (for A-like positions) extend gate poly to the last instance's gate_E.
    last = refs[-1]
    for i, r in enumerate(refs):
        # get the "end" metal layer from an existing port on r
        end_layer = pdk.layer_to_glayer(r.ports["row0_col0_rightsd_top_met_N"].layer)

        idplace << straight_route(
            pdk, r.ports["row0_col0_rightsd_top_met_N"], last.ports["drain_E"], glayer2=end_layer
        )
        idplace << straight_route(
            pdk, r.ports["leftsd_top_met_N"], last.ports["drain_E"], glayer2=end_layer
        )

    
    for i, r in enumerate(refs):

        gl = "poly"
        up = straight_route(pdk, r.ports["row0_col0_gate_N"], refs[-1].ports["gate_E"], glayer1=gl, glayer2=gl)
        idplace << up
       

    # ----- Merge doped region across the row (like original) -----
    idplace << straight_route(pdk, refs[0].ports["plusdoped_W"], refs[-1].ports["plusdoped_E"])

    # ----- Build N×3 global buses across the row -----

    bus_roles = ["source","drain","gate"] # or ["source","drain","gate"]
    bus_layer = "met2"       # routing layer for these rails

    N = len(refs)
    for i, r in enumerate(refs):
        for role in bus_roles:
            left_name  = f"{role}_W"
            right_name = f"{role}_E"

            # (1) from this instance to the LAST instance
            if left_name in r.ports and right_name in refs[-1].ports:
                gl = pdk.layer_to_glayer(r.ports[left_name].layer)  # keep on same layer as start
                rr = straight_route(pdk, r.ports[left_name], refs[-1].ports[right_name], glayer2=gl or bus_layer)
                rr = rename_ports_by_orientation(rename_ports_by_list(rr, [("route_", "_")]))
                idplace << rr

            # (2) from this instance back to the FIRST instance
            if right_name in r.ports and left_name in refs[0].ports:
                gl = pdk.layer_to_glayer(r.ports[right_name].layer)
                rr = straight_route(pdk, r.ports[right_name], refs[0].ports[left_name], glayer2=gl or bus_layer)
                rr = rename_ports_by_orientation(rename_ports_by_list(rr, [("route_", "_")]))
                idplace << rr

    # Center + finalize
    idplace = transformed(prec_ref_center(idplace))
    idplace.unlock()
    
    return idplace


@validate_arguments
def n_nfet_interdigitized(
    pdk: MappedPDK,
    numcols: int,
    n_devices: int,                               # NEW: number of devices per row (A..)
    dummy: Union[bool, tuple[bool, bool]] = True,
    with_substrate_tap: bool = True,
    with_tie: bool = True,
    tie_layers: tuple[str, str] = ("met2", "met1"),
    **kwargs,
) -> Component:
    """
    N-NFET interdigitized row: places N identical NFETs repeated across `numcols`.
    - Preserves dummy-at-edges behavior (bool or (left,right) tuple).
    - Adds optional well-tie ring (with_tie) and outer substrate ring (with_substrate_tap).
    - Exposes perimeter well ports and attaches an N-device netlist.
    """

    base_multiplier = macro_n_transistor_interdigitized(
        pdk=pdk,
        numcols=numcols,
        devices="nfet",
        n_devices=n_devices,
        dummy=dummy,
        **kwargs,
    )

    # ---- Well tie ring (like your 2T flow) ----
    if with_tie:
        tap_separation = max(
            pdk.util_max_metal_seperation(),
            pdk.get_grule("active_diff", "active_tap")["min_separation"],
        )
        tap_separation += pdk.get_grule("p+s/d", "active_tap")["min_enclosure"]  # PFET tie uses n+ in nwell

        tap_encloses = (
            2 * (tap_separation + base_multiplier.xmax),
            2 * (tap_separation + base_multiplier.ymax),
        )
        tiering_ref = base_multiplier << tapring(
            pdk,
            enclosed_rectangle=tap_encloses,
            sdlayer="p+s/d",                   # NFET well tie ring
            horizontal_glayer=tie_layers[0],
            vertical_glayer=tie_layers[1],
        )
        base_multiplier.add_ports(tiering_ref.get_ports_list(), prefix="welltie_")

        # Try to hook up left/right dummy gsd contacts to welltie ring if those ports exist.
        # We don’t assume only A/B—scan for any *_dummy_L_gsdcon_top_met_W / *_dummy_R_gsdcon_top_met_E.
        try:
            wtW = base_multiplier.ports["welltie_W_top_met_W"]
        except KeyError:
            wtW = None
        try:
            wtE = base_multiplier.ports["welltie_E_top_met_E"]
        except KeyError:
            wtE = None

        if wtW:
            # Connect any left dummy contact we can find
            left_dummy_keys = [k for k in base_multiplier.ports.keys() if k.endswith("dummy_L_gsdcon_top_met_W")]
            for k in left_dummy_keys:
                try:
                    base_multiplier << straight_route(pdk, base_multiplier.ports[k], wtW, glayer2="met1")
                    break
                except Exception:
                    pass

        if wtE:
            # Connect any right dummy contact we can find
            right_dummy_keys = [k for k in base_multiplier.ports.keys() if k.endswith(f"dummy_R_gsdcon_top_met_E")]
            for k in right_dummy_keys:
                try:
                    base_multiplier << straight_route(pdk, base_multiplier.ports[k], wtE, glayer2="met1")
                    break
                except Exception:
                    pass

    # ---- Add pwell padding + perimeter ports (same as your 2T PFET) ----
    base_multiplier.add_padding(
        layers=(pdk.get_glayer("pwell"),),
        default=pdk.get_grule("pwell", "active_tap")["min_enclosure"],
    )
    base_multiplier = add_ports_perimeter(
        base_multiplier, layer=pdk.get_glayer("pwell"), prefix="well_"
    )

    # ---- Optional outer substrate tap ring ----
    if with_substrate_tap:
        substrate_tap_separation = pdk.get_grule("dnwell", "active_tap")["min_separation"]
        substrate_tap_encloses = (
            2 * (substrate_tap_separation + base_multiplier.xmax),
            2 * (substrate_tap_separation + base_multiplier.ymax),
        )
        ringtoadd = tapring(
            pdk,
            enclosed_rectangle=substrate_tap_encloses,
            sdlayer="p+s/d",                  # outer ring using p+ taps
            horizontal_glayer="met2",
            vertical_glayer="met1",
        )
        tapring_ref = base_multiplier << ringtoadd
        base_multiplier.add_ports(tapring_ref.get_ports_list(), prefix="substratetap_")

    base_multiplier.info["route_genid"] = "n_transistor_interdigitized"

    # ---- Attach N-device netlist ----
    base_multiplier.info["netlist"] = n_tran_interdigitized_netlist(
        pdk=pdk,
        width=kwargs.get("width", 3),
        length=kwargs.get("length", 0.15),
        fingers=kwargs.get("fingers", 1),
        multipliers=numcols,
        with_dummy=bool(dummy) if isinstance(dummy, bool) else any(dummy),
        n_or_p_fet="nfet",
        subckt_only=True,
        n_devices=n_devices,                  # NEW: pass N
    )

    return base_multiplier

@validate_arguments
def n_pfet_interdigitized(
    pdk: MappedPDK,
    numcols: int,
    n_devices: int,                               # NEW: number of devices per row (A..)
    dummy: Union[bool, tuple[bool, bool]] = True,
    with_substrate_tap: bool = True,
    with_tie: bool = True,
    tie_layers: tuple[str, str] = ("met2", "met1"),
    **kwargs,
) -> Component:
    """
    N-PFET interdigitized row: places N identical PFETs repeated across `numcols`.
    - Preserves dummy-at-edges behavior (bool or (left,right) tuple).
    - Adds optional well-tie ring (with_tie) and outer substrate ring (with_substrate_tap).
    - Exposes perimeter well ports and attaches an N-device netlist.
    """

    base_multiplier = macro_n_transistor_interdigitized(
        pdk=pdk,
        numcols=numcols,
        devices="pfet",
        n_devices=n_devices,
        dummy=dummy,
        **kwargs,
    )

    # ---- Well tie ring (like your 2T flow) ----
    if with_tie:
        tap_separation = max(
            pdk.util_max_metal_seperation(),
            pdk.get_grule("active_diff", "active_tap")["min_separation"],
        )
        tap_separation += pdk.get_grule("n+s/d", "active_tap")["min_enclosure"]  # PFET tie uses n+ in nwell

        tap_encloses = (
            2 * (tap_separation + base_multiplier.xmax),
            2 * (tap_separation + base_multiplier.ymax),
        )
        tiering_ref = base_multiplier << tapring(
            pdk,
            enclosed_rectangle=tap_encloses,
            sdlayer="n+s/d",                   # PFET well tie ring
            horizontal_glayer=tie_layers[0],
            vertical_glayer=tie_layers[1],
        )
        base_multiplier.add_ports(tiering_ref.get_ports_list(), prefix="welltie_")

        # Try to hook up left/right dummy gsd contacts to welltie ring if those ports exist.
        # We don’t assume only A/B—scan for any *_dummy_L_gsdcon_top_met_W / *_dummy_R_gsdcon_top_met_E.
        try:
            wtW = base_multiplier.ports["welltie_W_top_met_W"]
        except KeyError:
            wtW = None
        try:
            wtE = base_multiplier.ports["welltie_E_top_met_E"]
        except KeyError:
            wtE = None

        if wtW:
            # Connect any left dummy contact we can find
            left_dummy_keys = [k for k in base_multiplier.ports.keys() if k.endswith("dummy_L_gsdcon_top_met_W")]
            for k in left_dummy_keys:
                try:
                    base_multiplier << straight_route(pdk, base_multiplier.ports[k], wtW, glayer2="met1")
                    break
                except Exception:
                    pass

        if wtE:
            # Connect any right dummy contact we can find
            right_dummy_keys = [k for k in base_multiplier.ports.keys() if k.endswith(f"dummy_R_gsdcon_top_met_E")]
            for k in right_dummy_keys:
                try:
                    base_multiplier << straight_route(pdk, base_multiplier.ports[k], wtE, glayer2="met1")
                    break
                except Exception:
                    pass

    # ---- Add nwell padding + perimeter ports (same as your 2T PFET) ----
    base_multiplier.add_padding(
        layers=(pdk.get_glayer("nwell"),),
        default=pdk.get_grule("nwell", "active_tap")["min_enclosure"],
    )
    base_multiplier = add_ports_perimeter(
        base_multiplier, layer=pdk.get_glayer("nwell"), prefix="well_"
    )

    # ---- Optional outer substrate tap ring ----
    if with_substrate_tap:
        substrate_tap_separation = pdk.get_grule("dnwell", "active_tap")["min_separation"]
        substrate_tap_encloses = (
            2 * (substrate_tap_separation + base_multiplier.xmax),
            2 * (substrate_tap_separation + base_multiplier.ymax),
        )
        ringtoadd = tapring(
            pdk,
            enclosed_rectangle=substrate_tap_encloses,
            sdlayer="p+s/d",                  # outer ring using p+ taps
            horizontal_glayer="met2",
            vertical_glayer="met1",
        )
        tapring_ref = base_multiplier << ringtoadd
        base_multiplier.add_ports(tapring_ref.get_ports_list(), prefix="substratetap_")

    base_multiplier.info["route_genid"] = "n_transistor_interdigitized"

    # ---- Attach N-device netlist ----
    base_multiplier.info["netlist"] = n_tran_interdigitized_netlist(
        pdk=pdk,
        width=kwargs.get("width", 3),
        length=kwargs.get("length", 0.15),
        fingers=kwargs.get("fingers", 1),
        multipliers=numcols,
        with_dummy=bool(dummy) if isinstance(dummy, bool) else any(dummy),
        n_or_p_fet="pfet",
        subckt_only=True,
        n_devices=n_devices,                  # NEW: pass N
    )

    return base_multiplier
    




# @validate_arguments
def n_transistor_interdigitized(
    pdk: MappedPDK,
    device: Literal["nfet", "pfet"],
    numcols: int,
    n_devices: int = 2,                         # NEW: how many devices per row
    dummy: Union[bool, Tuple[bool, bool]] = True,
    with_substrate_tap: bool = True,
    with_tie: bool = True,
    tie_layers: tuple[str, str] = ("met2", "met1"),
    **kwargs,
) -> Component:
    """
    Wrapper that builds an interdigitized row of `n_devices` transistors of type `device`.

    - If n_devices == 2 → calls the original two_*_interdigitized for full backward compatibility.
    - If n_devices  > 2 → calls the generalized n_*_interdigitized(..., n_devices=n_devices).

    Args mirror the 2-device API; extra kwargs are forwarded to the underlying builders.
    """
    if n_devices < 1:
        raise ValueError("n_devices must be >= 1")

    if device == "nfet":
        return n_nfet_interdigitized(
            pdk=pdk,
            numcols=numcols,
            n_devices=n_devices,
            dummy=dummy,
            with_substrate_tap=with_substrate_tap,
            with_tie=with_tie,
            tie_layers=tie_layers,
            **kwargs,
        )
    else:  # pfet
        # N-device PFET
        return n_pfet_interdigitized(
            pdk=pdk,
            numcols=numcols,
            n_devices=n_devices,
            dummy=dummy,
            with_substrate_tap=with_substrate_tap,
            with_tie=with_tie,
            tie_layers=tie_layers,
            **kwargs,
        )
    

def input_stage(
    pdk: MappedPDK,
    Width: float = 1,
    Length: Optional[float] = 1,
    num_cols: int = 1,
    fingers: int = 1,
    multipliers: int = 1,
    type: Optional[str] = "pfet",
    with_substrate_tap: Optional[bool] = False,
    with_tie: Optional[bool] = True,
    with_dummy: Optional[bool] = False,
    tie_layers: tuple[str, str] = ("met2", "met1"),
    show_netlist: Optional[bool] = False,
    add_labels = True,
    **kwargs,
) -> Component:
    """An instantiable self biased casoded current mirror that returns a Component object."""

    pdk.activate()
    maxmet_sep = pdk.util_max_metal_seperation()
    n_well_sep = maxmet_sep
    psize = (0.35, 0.35)

    # Create the current mirror component
    top_level = Component(name="input_stage")
    top_level.name = "input_stage"
    Length = Length if Length is not None else pdk.get_grule("poly")["min_width"]
    top_ref = prec_ref_center(top_level)

    # ------------------------------------------------------------------------------------------------------------------------------------------------------------
    # BOTTOM CURRENT MIRRORS
    # ------------------------------------------------------------------------------------------------------------------------------------------------------------

    currm_bottom = n_transistor_interdigitized(
        pdk,
        device="pfet",
        numcols=1,
        n_devices=4,
        with_substrate_tap=False,
        with_tie=with_tie,
        width=Width,
        length=Length,
    )

    currm_bottom = top_level << currm_bottom
    currm_bottom.name = "currm_bottom"

    currm_bottom_ref = prec_ref_center(currm_bottom)
    currm_bottom_ref.move(top_ref.center)
    top_level.add(currm_bottom_ref)

    top_level.add_ports(currm_bottom_ref.get_ports_list(), prefix="currm_bottom_")

    top_level = component_snap_to_grid(rename_ports_by_orientation(top_level))

    return top_level
    

if __name__ == "__main__":
    selected_pdk=gf180 
    
    comp = input_stage(
        selected_pdk, num_cols=1, Width=10, Length=2, with_substrate_tap=False, show_netlist=False, with_tie=True
    )
    #comp.pprint_ports()
    #comp = add_cm_labels(comp, pdk=selected_pdk)
    comp.name = "TEST2"
    comp.show()
    ##Write the current mirror layout to a GDS file
    comp.write_gds("GDS/test2.gds")
    
    # # #Generate the netlist for the current mirror
    # print("\n...Generating Netlist...")
    #print(comp.info["netlist"].generate_netlist())
    # # #DRC Checks
    drc_result = selected_pdk.drc_magic(comp, comp.name,output_file=Path("DRC/"))