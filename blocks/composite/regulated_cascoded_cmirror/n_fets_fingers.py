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


# === New: CLUSTERED (non-interdigitized) placement ===

def n_tran_clustered_netlist(
    pdk: MappedPDK,
    width: Optional[float],
    length: Optional[float],
    fingers: int,
    numcols: int,
    with_dummy: bool = True,
    n_or_p_fet: Literal['nfet','pfet'] = 'nfet',
    n_devices: int = 2,
) -> Netlist:
    """
    Build a subcircuit with N clustered transistors (no interdigitation).
    Each Xi has m = fingers * numcols.
    Nodes per device i: VDDi, VGi, VSSi, VB
    """
    if length is None:
        length = pdk.get_grule('poly')['min_width']
    if width is None:
        width = 3.0

    model = pdk.models[n_or_p_fet]
    mtop = fingers * numcols
    N = int(n_devices)

    nodes = (
        [f"VDD{i}" for i in range(1, N+1)] +
        [f"VSS{i}" for i in range(1, N+1)] +
        [f"VG{i}"  for i in range(1, N+1)] +
        ["VB"]
    )

    lines = [f".subckt {{circuit_name}} {' '.join(nodes)} l={length} w={width} m=1"]
    for i in range(1, N+1):
        lines.append(f"X{i} VDD{i} VG{i} VSS{i} VB {model} l={length} w={width} m={mtop}")
    if with_dummy:
        lines.append(f"XDUMMY VB VB VB VB {model} l={length} w={width} m=2")
    lines.append(".ends {circuit_name}")

    return Netlist(
        circuit_name=f"{N}_trans_clustered",
        nodes=nodes,
        source_netlist="\n".join(lines),
        instance_format="X{name} {nodes} {circuit_name} l={length} w={width} m=1",
        parameters={
            'model': model,
            'width': width,
            'length': length,
            'mult': numcols,
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
def macro_n_transistor_clustered(
    pdk: MappedPDK,
    numcols: int,                                 # columns per device block (repeated unit cells)
    devices: Literal["nfet", "pfet"],
    n_devices: int,                                # how many device blocks: A, B, C, ...
    dummy: Union[bool, tuple[bool, bool]] = True,  # left/right edge dummies on the whole row
    **kwargs,
) -> Component:
    """
    Place N device *blocks* side-by-side.
    Each block = numcols repeated 'multiplier(**kwargs)' cells of the SAME device,
    shorted to share gate and S/D rails (clustered fingers, not interdigitized).
    Exposes ports per device block: e.g., A_source_*, A_drain_*, A_gate_*; then B_*, etc.
    """
    if isinstance(dummy, bool):
        dummy = (dummy, dummy)

    # Base kwargs
    k = dict(kwargs)
    k["pdk"] = pdk
    k["sdlayer"] = "n+s/d" if devices == "nfet" else "p+s/d"
    # Keep consistent routes inside a block
    k.setdefault("sd_route_extension", 0)
    k.setdefault("gate_route_extension", 0)
    k.setdefault("dummy", False)

    letters = _letters(n_devices)
    row = Component()

    # Build a single "unit" for this device type (matched extents)
    unit = multiplier(**k)
    u_bbox = evaluate_bbox(unit)
    pitch = pdk.snap_to_2xgrid(u_bbox[0] + pdk.get_grule("active_diff")["min_separation"])

    blocks = []   # list[(L, [cref0..cref{numcols-1}])]
    x = 0.0

    for bi, L in enumerate(letters):
        # For the first and last block, optionally add edge dummies within the block
        left_edge  = (bi == 0)  and dummy[0]
        right_edge = (bi == n_devices - 1) and dummy[1]

        # Build the block
        refs = []

        inter_col = numcols

        if dummy[0]:
            inter_col -= 1
        if dummy[1]:
            inter_col -= 1


        # Left dummy (only if requested for the *row* edge)
        if left_edge:
            kL = dict(k); kL["dummy"] = (True, False)
            dL = row << multiplier(**kL)
            dL.movex(x); refs.append(dL); x += pitch

        # numcols repeated real devices for this block
        kC = dict(k); kC["dummy"] = False
        for ci in range(inter_col):
            c = row << multiplier(**kC)
            c.name = f"{L}_{ci}"
            c.movex(x); refs.append(c); x += pitch

        # Right dummy (only if requested for the *row* edge)
        if right_edge:
            kR = dict(k); kR["dummy"] = (False, True)
            dR = row << multiplier(**kR)
            dR.movex(x); refs.append(dR); x += pitch

        blocks.append((L, refs))

        # Add per-instance ports (scoped under letter for clarity)
        for idx, r in enumerate(refs):
            row.add_ports(r.get_ports_list(), prefix=f"{L}_{idx}_")

        # Add per-instance ports (scoped under letter for clarity)
        # for r in refs:
        #     row.add_ports(r.get_ports_list(), prefix=f"{L}_inst_")

        # Stitch block-internal rails so the block shares S/D and Gate
        # Find first/last *real* cell indices inside refs (skip block-edge dummies)
        start_idx = 1 if left_edge else 0
        end_idx   = (len(refs)-2) if right_edge else (len(refs)-1)

        first = refs[0]; last = refs[-1]

        # Tie S/D top metals across the block
        for r in refs[0:-1]:
            end_layer = pdk.layer_to_glayer(r.ports["row0_col0_rightsd_top_met_N"].layer)
            row << straight_route(pdk, r.ports["row0_col0_rightsd_top_met_N"], last.ports["drain_E"], glayer2=end_layer)
            row << straight_route(pdk, r.ports["leftsd_top_met_N"],              last.ports["drain_E"], glayer2=end_layer)

        # Tie gate poly across the block
        for r in refs[0:-1]:
            row << straight_route(pdk, r.ports["row0_col0_gate_N"], last.ports["gate_E"], glayer1="poly", glayer2="poly")

        # Expose one set of ports per device block (A_*, B_*, ...)
        # Use the first and last real cells to create block-wide W/E bus ports.
        # Source/Drain buses:
        try:
            # West/East ends
            sW = first.ports["source_W"]; sE = last.ports["source_E"]
            dW = first.ports["drain_W"];  dE = last.ports["drain_E"]
            gW = first.ports["gate_W"];   gE = last.ports["gate_E"]

            # Create stitched routes so we can expose neat block ports
            # (no-op if already continuous from the loops above)
            row << straight_route(pdk, sW, sE)
            row << straight_route(pdk, dW, dE)
            row << straight_route(pdk, gW, gE, glayer1="met2", glayer2="met2")

            # Add named block ports
            row.add_port(name=f"{L}_source_W", port=sW)
            row.add_port(name=f"{L}_source_E", port=sE)
            row.add_port(name=f"{L}_drain_W",  port=dW)
            row.add_port(name=f"{L}_drain_E",  port=dE)
            row.add_port(name=f"{L}_gate_W",   port=gW)
            row.add_port(name=f"{L}_gate_E",   port=gE)

            # Also expose the “convenience” N/S ports if present on the last cell
            for pname in ["gate_S","gate_N","diff_N","diff_S"]:
                pp = f"{pname}"
                if pp in last.ports:
                    row.add_port(name=f"{L}_{pp}", port=last.ports[pp])
        except KeyError:
            # Layout variants may name ports slightly differently; adapt here if needed.
            pass

    # Merge doped region along the full row (optional but helpful for DRC/matching)
    first_cell = blocks[0][1][0]
    last_cell  = blocks[-1][1][-1]
    row << straight_route(pdk, first_cell.ports["plusdoped_W"], last_cell.ports["plusdoped_E"])

    row = transformed(prec_ref_center(row))
    row.unlock()
    return row


@validate_arguments
def n_nfet_clustered(
    pdk: MappedPDK,
    numcols: int,
    n_devices: int,
    dummy: Union[bool, tuple[bool, bool]] = True,
    with_substrate_tap: bool = True,
    with_tie: bool = True,
    tie_layers: tuple[str, str] = ("met2", "met1"),
    **kwargs,
) -> Component:
    base = macro_n_transistor_clustered(
        pdk=pdk, numcols=numcols, devices="nfet", n_devices=n_devices, dummy=dummy, **kwargs
    )

    # Well tie ring
    if with_tie:
        tap_sep = max(
            pdk.util_max_metal_seperation(),
            pdk.get_grule("active_diff", "active_tap")["min_separation"],
        )
        tap_sep += pdk.get_grule("p+s/d", "active_tap")["min_enclosure"]
        encl = (2 * (tap_sep + base.xmax), 2 * (tap_sep + base.ymax))
        tr = base << tapring(pdk, enclosed_rectangle=encl, sdlayer="p+s/d",
                             horizontal_glayer=tie_layers[0], vertical_glayer=tie_layers[1])
        base.add_ports(tr.get_ports_list(), prefix="welltie_")

    # pwell padding + perimeter ports
    base.add_padding(layers=(pdk.get_glayer("pwell"),),
                     default=pdk.get_grule("pwell", "active_tap")["min_enclosure"])
    base = add_ports_perimeter(base, layer=pdk.get_glayer("pwell"), prefix="well_")

    # Outer substrate tap
    if with_substrate_tap:
        sep = pdk.get_grule("dnwell", "active_tap")["min_separation"]
        encl = (2 * (sep + base.xmax), 2 * (sep + base.ymax))
        tr = base << tapring(pdk, enclosed_rectangle=encl, sdlayer="p+s/d",
                             horizontal_glayer="met2", vertical_glayer="met1")
        base.add_ports(tr.get_ports_list(), prefix="substratetap_")

    base.info["route_genid"] = "n_transistor_clustered"
    base.info["netlist"] = n_tran_clustered_netlist(
        pdk=pdk,
        width=kwargs.get("width", 3),
        length=kwargs.get("length", 0.15),
        fingers=kwargs.get("fingers", 1),
        numcols=numcols,
        with_dummy=bool(dummy) if isinstance(dummy, bool) else any(dummy),
        n_or_p_fet="nfet",
        n_devices=n_devices,
    )
    return base


@validate_arguments
def n_pfet_clustered(
    pdk: MappedPDK,
    numcols: int,
    n_devices: int,
    dummy: Union[bool, tuple[bool, bool]] = True,
    with_substrate_tap: bool = True,
    with_tie: bool = True,
    tie_layers: tuple[str, str] = ("met2", "met1"),
    **kwargs,
) -> Component:
    base = macro_n_transistor_clustered(
        pdk=pdk, numcols=numcols, devices="pfet", n_devices=n_devices, dummy=dummy, **kwargs
    )

    # Well tie ring
    if with_tie:
        tap_sep = max(
            pdk.util_max_metal_seperation(),
            pdk.get_grule("active_diff", "active_tap")["min_separation"],
        )
        tap_sep += pdk.get_grule("n+s/d", "active_tap")["min_enclosure"]
        encl = (2 * (tap_sep + base.xmax), 2 * (tap_sep + base.ymax))
        tr = base << tapring(pdk, enclosed_rectangle=encl, sdlayer="n+s/d",
                             horizontal_glayer=tie_layers[0], vertical_glayer=tie_layers[1])
        base.add_ports(tr.get_ports_list(), prefix="welltie_")

    # nwell padding + perimeter ports
    base.add_padding(layers=(pdk.get_glayer("nwell"),),
                     default=pdk.get_grule("nwell", "active_tap")["min_enclosure"])
    base = add_ports_perimeter(base, layer=pdk.get_glayer("nwell"), prefix="well_")

    # Outer substrate tap
    if with_substrate_tap:
        sep = pdk.get_grule("dnwell", "active_tap")["min_separation"]
        encl = (2 * (sep + base.xmax), 2 * (sep + base.ymax))
        tr = base << tapring(pdk, enclosed_rectangle=encl, sdlayer="p+s/d",
                             horizontal_glayer="met2", vertical_glayer="met1")
        base.add_ports(tr.get_ports_list(), prefix="substratetap_")

    base.info["route_genid"] = "n_transistor_clustered"
    base.info["netlist"] = n_tran_clustered_netlist(
        pdk=pdk,
        width=kwargs.get("width", 3),
        length=kwargs.get("length", 0.15),
        fingers=kwargs.get("fingers", 1),
        numcols=numcols,
        with_dummy=bool(dummy) if isinstance(dummy, bool) else any(dummy),
        n_or_p_fet="pfet",
        n_devices=n_devices,
    )
    return base


def n_transistor_clustered(
    pdk: MappedPDK,
    device: Literal["nfet", "pfet"],
    numcols: int,
    n_devices: int = 2,
    dummy: Union[bool, Tuple[bool, bool]] = True,
    with_substrate_tap: bool = True,
    with_tie: bool = True,
    tie_layers: tuple[str, str] = ("met2", "met1"),
    **kwargs,
) -> Component:
    """Wrapper for clustered placement (non-interdigitized)."""
    if n_devices < 1:
        raise ValueError("n_devices must be >= 1")
    if device == "nfet":
        return n_nfet_clustered(pdk, numcols, n_devices, dummy, with_substrate_tap, with_tie, tie_layers, **kwargs)
    else:
        return n_pfet_clustered(pdk, numcols, n_devices, dummy, with_substrate_tap, with_tie, tie_layers, **kwargs)
    
def input_stage(
    pdk: MappedPDK,
    Width: float = 1,
    Length: Optional[float] = 1,
    num_cols: int = 1,
    fingers: int = 1,
    multipliers: int = 1,
    device: Optional[str] = "pfet",
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

    currm_bottom = n_transistor_clustered(
        pdk,
        device=device,
        numcols=10,
        n_devices=1,
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
        selected_pdk, num_cols=1, Width=10, Length=2, with_substrate_tap=False, show_netlist=False, with_tie=True, device="pfet"
    )
    # comp = input_stage(selected_pdk, num_cols=1, Width=10, Length=2,with_substrate_tap=True,show_netlist=False)
    #comp.pprint_ports()
    #comp = add_cm_labels(comp, pdk=selected_pdk)
    comp.name = "TEST"
    comp.show()
    ##Write the current mirror layout to a GDS file
    comp.write_gds("GDS/test.gds")
    
    # # #Generate the netlist for the current mirror
    # print("\n...Generating Netlist...")
    #print(comp.info["netlist"].generate_netlist())
    # # #DRC Checks
    drc_result = selected_pdk.drc_magic(comp, comp.name,output_file=Path("DRC/"))