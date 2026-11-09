"""End-to-end example: floorplan a two-stage OTA from finger-sequence blocks.

    DP    nfet CC diff pair         VINP VINN -> N1 N2, tail VTAIL
    LOAD  pfet CC current mirror    N1 (diode) -> N2, from VDD
    BIAS  nfet 3-device CC bank     IBIAS (diode) -> VTAIL and VOUT sinks
    CS    pfet common source        gate N2, drain VOUT, from VDD

Every block has three variants with the same total W per device (finger
count × finger width), so the annealer trades shape without changing the
circuit. DP and LOAD are self-symmetric about a common vertical axis.
"""
from __future__ import annotations

from typing import Optional

from glayout.backend import Component
from glayout.cells.elementary.finger_sequence import cc_current_mirror, cc_diff_pair, finger_sequence_cell
from glayout.floorplan.anneal import FloorplanResult, FloorplanWeights, anneal_floorplan
from glayout.floorplan.block import Block, build_block, print_blocks
from glayout.floorplan.circuit import Circuit, Instance
from glayout.floorplan.drr import apply_drr
from glayout.floorplan.realize import realize_floorplan
from glayout.pdk.mappedpdk import MappedPDK

# (fingers, finger width) splits of a 12µm device
_SPLITS = [(2, 6.0), (4, 3.0), (8, 1.5)]


def bias_bank(pdk: MappedPDK, scale: int = 1, width: float = 3.0, **kw) -> Component:
    devices = [dict(name="R", source="VSS", drain="IBIAS", gate="IBIAS", fingers=2 * scale),
               dict(name="T", source="VSS", drain="VTAIL", gate="IBIAS", fingers=4 * scale),
               dict(name="K", source="VSS", drain="VOUT", gate="IBIAS", fingers=4 * scale)]
    return finger_sequence_cell(pdk, devices, device="nfet", width=width, pins=["IBIAS", "VTAIL", "VOUT", "VSS", "B"],
                                circuit_name="BIAS_BANK", name=f"biasbank_x{scale}", **kw)


def cs_stage(pdk: MappedPDK, fingers: int = 4, width: float = 3.0, **kw) -> Component:
    devices = [dict(name="M", source="VDD", drain="VOUT", gate="VG", fingers=fingers)]
    return finger_sequence_cell(pdk, devices, device="pfet", width=width, pins=["VG", "VOUT", "VDD", "B"],
                                circuit_name="CS_STAGE", name=f"csstage_f{fingers}", **kw)


def two_stage_ota_blocks(pdk: MappedPDK, labels: bool = True) -> dict[str, Block]:
    """``labels=False`` builds the cells without their own pin labels, as a
    routed composite needs (its labels go on the top level)."""
    import os
    old = os.environ.get("GLAYOUT_NO_PIN_LABELS")
    if not labels:
        os.environ["GLAYOUT_NO_PIN_LABELS"] = "1"
    try:
        return _build_ota_blocks(pdk)
    finally:
        if not labels:
            if old is None:
                os.environ.pop("GLAYOUT_NO_PIN_LABELS", None)
            else:
                os.environ["GLAYOUT_NO_PIN_LABELS"] = old


def _build_ota_blocks(pdk: MappedPDK) -> dict[str, Block]:
    return {
        "DP": build_block(pdk, "DP", "DP", cc_diff_pair,
                          [dict(fingers=f, width=w, device="nfet") for f, w in _SPLITS]),
        "LOAD": build_block(pdk, "LOAD", "CM", cc_current_mirror,
                            [dict(fingers=f, width=w, device="pfet") for f, w in _SPLITS]),
        "BIAS": build_block(pdk, "BIAS", "BIAS", bias_bank,
                            [dict(scale=1, width=3.0), dict(scale=2, width=1.5)]),
        "CS": build_block(pdk, "CS", "CS", cs_stage,
                          [dict(fingers=f, width=w) for f, w in _SPLITS]),
    }


def two_stage_ota_circuit(blocks: dict[str, Block]) -> Circuit:
    return Circuit(
        "two_stage_ota",
        [
            Instance("DP", blocks["DP"], {"VINP": "VINP", "VINN": "VINN", "VOUT1": "N1", "VOUT2": "N2",
                                          "VTAIL": "VTAIL", "B": "VSS"}),
            Instance("LOAD", blocks["LOAD"], {"VREF": "N1", "VOUT": "N2", "VSS": "VDD", "B": "VDD"}),
            Instance("BIAS", blocks["BIAS"], {"IBIAS": "IBIAS", "VTAIL": "VTAIL", "VOUT": "VOUT",
                                              "VSS": "VSS", "B": "VSS"}),
            Instance("CS", blocks["CS"], {"VG": "N2", "VOUT": "VOUT", "VDD": "VDD", "B": "VDD"}),
        ],
        self_symmetric=["DP", "LOAD"],
        ports=["VINP", "VINN", "VOUT", "IBIAS", "VDD", "VSS"],
    )


def two_stage_ota_floorplan(
    pdk: MappedPDK,
    seed: int = 0,
    drr_scale: float = 1.0,
    weights: Optional[dict] = None,
    return_result: bool = False,
    blocks: Optional[dict[str, Block]] = None,
):
    """Build blocks, pad, anneal and realise. Builder-compatible with the DRC runner.

    Pass ``blocks`` (from ``two_stage_ota_blocks``) to reuse built cells across runs.
    """
    blocks = blocks or two_stage_ota_blocks(pdk)
    apply_drr(pdk, blocks.values(), scale=drr_scale)
    print_blocks(list(blocks.values()), "Two-stage OTA blocks (after DRR)")
    circuit = two_stage_ota_circuit(blocks)
    circuit.graph()
    result: FloorplanResult = anneal_floorplan(circuit, FloorplanWeights(**(weights or {})), seed=seed)
    comp = realize_floorplan(pdk, result, name="two_stage_ota_floorplan")
    return (comp, result) if return_result else comp


def two_stage_ota_routed(
    pdk: MappedPDK,
    seed: int = 0,
    mode: str = "closed_loop",
    drr_scale: float = 1.0,
    return_result: bool = False,
    blocks: Optional[dict[str, Block]] = None,
    strict: bool = True,
):
    """Floorplan + route the two-stage OTA. Builder-compatible with the DRC/LVS runner.

    ``strict``: raise if routing fails, so a runner never checks an unrouted layout.

    mode:
      ``closed_loop`` router feedback: start without DRR, router in the annealer's
                      loop, grow padding only around blocks whose nets fail
      ``drr``         paper flow: fixed DRR padding (``drr_scale``), router afterwards
    """
    from glayout.floorplan.route_flow import closed_loop_floorplan, route_floorplan
    from glayout.floorplan.router import RouterTech
    blocks = blocks or two_stage_ota_blocks(pdk, labels=False)
    circuit = two_stage_ota_circuit(blocks)
    tech = RouterTech.from_pdk(pdk)
    if mode == "closed_loop":
        loop = closed_loop_floorplan(pdk, circuit, list(blocks.values()), tech, seed=seed)
        fp = loop.floorplan
    elif mode == "drr":
        apply_drr(pdk, blocks.values(), scale=drr_scale, layers=tech.layers)
        fp = anneal_floorplan(circuit, seed=seed)
        loop = None
    else:
        raise ValueError(f"unknown mode {mode!r}")
    comp, rr = route_floorplan(pdk, circuit, fp, tech, name="two_stage_ota_routed")
    if strict and not rr.success:
        raise RuntimeError(f"routing failed: nets {rr.failed_nets}, unreachable pins {rr.unreachable}")
    return (comp, fp, rr, loop) if return_result else comp
