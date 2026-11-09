"""The 18 textbook topologies: normalised device lists, ports and source provenance.

Device lines follow the AnalogGenie convention (D G S B for MOS, P N for R/C) with
the original net names kept wherever they are meaningful.  Device names are
normalised to M1.. / R1.. / C1.. in order of appearance; the mapping to the
source names is recorded in ``source["device_name_map"]``.  Every modification
of the source netlist is listed in ``source["modifications"]``.
"""
from __future__ import annotations
from .netlist import Circuit, Device

AG = "https://github.com/xz-group/AnalogGenie"
AG_SHA = "efc25358939c6bedd247f28d3df61066964f3a90"
BOOKS = {
    "razavi": "B. Razavi, Design of Analog CMOS Integrated Circuits, 2nd ed., McGraw-Hill, 2017",
    "johns": "T. C. Carusone, D. A. Johns, K. W. Martin, Analog Integrated Circuit Design, 2nd ed., Wiley, 2012",
    "gray": "P. R. Gray, P. J. Hurst, S. H. Lewis, R. G. Meyer, Analysis and Design of Analog Integrated Circuits, 5th ed., Wiley, 2009",
    "allen": "P. E. Allen, D. R. Holberg, CMOS Analog Circuit Design, 3rd ed., Oxford University Press, 2012",
    "camenzind": "H. Camenzind, Designing Analog Chips, Virtualbookworm, 2005",
}


IMAGE_OBS = {726: 'Johns p.305 scan: Q1 diode-connected NMOS, Q2 output NMOS gate tied through a long wire (bias-distribution figure); basic 1:1 mirror', 672: 'Johns p.129 scan: Q1/Q2 bottom pair, Q3/Q4 cascode pair, Q3 and Q1 diode-connected, Iin source on top; cascode mirror', 840: 'Gray p.272 scan: bipolar Wilson mirror Q3 (input), Q1 (diode), Q2 (output, emitter on Q1 collector); MOS form authored with identical graph', 709: 'Johns p.261 scan: Q5 bias diode (W/L)/(n+1)^2, Q4/Q1 cascodes (W/L)/n^2, Q3/Q2 bottom devices W/L; wide-swing cascode mirror with Ibias and Iin sources', 934: 'Allen p.135 scan: M4 1/4-size diode, M5/M2 cascodes, M3/M1 bottom; corroborates the C13 graph', 936: 'Allen p.147 scan: M4 diode (II), M2 mirror, M1 regulating device biased by IREG, M3 output cascode; regulated cascode', 9: 'Razavi p.58 scan: M1 NMOS input, M2 PMOS current-source load biased by Vb', 20: 'Razavi p.72 scan: M1 follower, M2 NMOS current source (Vb), RL load resistor drawn as an external load to ground', 38: 'Razavi p.88 scan: M1/M2 NMOS cascode, M3/M4 PMOS cascode current source (Vb1..Vb3)', 195: 'Razavi p.268 scan: M1 NMOS and M2 PMOS with common gate input and common drain output (inverter amplifier)', 235: 'Razavi p.283 scan (partial): only M1 with an output current Iout is visible in the crop; the resistor R0 (VDD-VOUT1) of the dataset netlist is not visible. Treated as CS stage with resistive load per Razavi Sec. 3.2.1', 192: 'Razavi p.260 scan: M1/M2 pair with ideal tail current source symbol, M3/M4 PMOS current sources (Vb)', 157: 'Razavi p.171 scan: M1/M2 pair, M3 diode / M4 mirror PMOS load, M5 tail (Vb)', 71: 'Razavi p.107 scan: M1/M2 pair, RD1/RD2 loads, ideal tail source ISS', 220: 'Razavi p.272 scan: M1/M2 pair with RS/RS degeneration joined at the tail node, M3 tail (Vb), R1/R1 loads', 296: 'Razavi p.360 scan: M1/M2 pair, M3/M4 cascodes (Vb), M5/M6 PMOS cascodes and M7/M8 PMOS current sources with M5 and M7 diode-connected (X node), ideal tail ISS', 294: 'Razavi p.357 scan: M1/M2 PMOS pair (ISS tail), M5/M6 NMOS current sources (Vb4), M3/M4 NMOS cascodes (Vb1), M7/M8 PMOS cascodes (Vb2), M9/M10 PMOS sources (Vb3), differential Vout', 705: 'Johns p.243 scan: Q8 diode (3) with 20 uA source, Q5 (30) tail, Q1/Q2 (36) PMOS pair, Q3/Q4 (6) NMOS mirror, Q6 (45) PMOS load, Q7 (18) NMOS second stage, RC and CC compensation; W/L ratios annotated', 877: 'Gray p.380 scan: M3 PMOS current source (BIAS), M4 NMOS diode and M5 PMOS diode stack, M1 NMOS and M2 PMOS source followers driving RL, M6 NMOS input device'}


def src(ag_id, book, page, names, level, mods=None, extra=None):
    d = {"dataset": "AnalogGenie", "dataset_url": AG, "dataset_sha": AG_SHA, "dataset_license": "MIT (code and dataset repository)",
         "analoggenie_id": ag_id, "files": [f"Dataset/{ag_id}/{ag_id}.cir", f"Dataset/{ag_id}/Port{ag_id}.txt", f"Dataset/{ag_id}/Pagenumber{ag_id}.txt", f"Dataset/{ag_id}/Book{ag_id}.png", f"Dataset/{ag_id}/Cadence{ag_id}.png"] if ag_id else [],
         "book": BOOKS[book], "book_key": book, "page_ref": page, "device_name_map": names,
         "source_verification_level": level, "image_review": {"file": f"Dataset/{ag_id}/Book{ag_id}.png", "observation": IMAGE_OBS.get(ag_id)}, "modifications": mods or [],
         "textbook_image_note": "Book<id>.png (textbook scan) and Cadence<id>.png (schematic capture) ship inside the public AnalogGenie repository; for entries marked 'image_checked' the scan was compared with the netlist when the benchmark was built.  The scans are not redistributed here."}
    if extra: d.update(extra)
    return d


CIRCUITS = {}


def _add(c: Circuit):
    CIRCUITS[c.circuit_id] = c


# ---- current mirrors -------------------------------------------------------
_add(Circuit("C01", "basic_current_mirror", ["VSS", "IB1", "IOUT1"],
             [Device("M1", "nfet", ["IB1", "IB1", "VSS", "VSS"]), Device("M2", "nfet", ["IOUT1", "IB1", "VSS", "VSS"])],
             src(726, "johns", "305", {"M1": "M3", "M2": "M5"}, "netlist_matched_isomorphic+image_checked")))
_add(Circuit("C02", "cascode_current_mirror", ["VSS", "IIN1", "IOUT1"],
             [Device("M1", "nfet", ["IIN1", "IIN1", "net6", "VSS"]), Device("M2", "nfet", ["net6", "net6", "VSS", "VSS"]),
              Device("M3", "nfet", ["IOUT1", "IIN1", "net12", "VSS"]), Device("M4", "nfet", ["net12", "net6", "VSS", "VSS"])],
             src(672, "johns", "129", {"M1": "M3", "M2": "M2", "M3": "M1", "M4": "M0"}, "netlist_matched_isomorphic+image_checked")))
_add(Circuit("C03", "wilson_current_mirror", ["VSS", "IIN1", "IOUT1"],
             [Device("M1", "nfet", ["IIN1", "Y", "VSS", "VSS"]), Device("M2", "nfet", ["Y", "Y", "VSS", "VSS"]), Device("M3", "nfet", ["IOUT1", "IIN1", "Y", "VSS"])],
             src(840, "gray", "272 (bipolar Wilson mirror; MOS form from Gray et al. Sec. 4.2.5 'Wilson current mirror', MOS subsection)",
                 {"M1": "Q0 (npn)", "M2": "Q1 (npn)", "M3": "Q2 (npn)"},
                 "topology_from_textbook_section;netlist_authored (AnalogGenie has no MOS Wilson entry: isomorphism search over 3350 netlists found only bipolar versions #606 and #840)",
                 ["bipolar devices replaced by NMOS with the same connection graph (C->D, B->G, E->S, bulk to VSS)"])))
_add(Circuit("C13", "wide_swing_cascode_current_mirror", ["VSS", "IIN1", "IOUT1", "IB1"],
             [Device("M1", "nfet", ["IB1", "IB1", "VSS", "VSS"]), Device("M2", "nfet", ["IIN1", "IB1", "net15", "VSS"]), Device("M3", "nfet", ["net15", "IIN1", "VSS", "VSS"]),
              Device("M4", "nfet", ["IOUT1", "IB1", "net14", "VSS"]), Device("M5", "nfet", ["net14", "IIN1", "VSS", "VSS"])],
             src(709, "johns", "261", {"M1": "M4", "M2": "M1", "M3": "M0", "M4": "M3", "M5": "M2"}, "netlist_matched_isomorphic+image_checked",
                 extra={"corroborating_entry": {"analoggenie_id": 934, "book": BOOKS["allen"], "page_ref": "135", "note": "same connection graph (IREF1<->IB1, IREF2<->IIN1)"}})))
_add(Circuit("C14", "regulated_cascode_current_mirror", ["VSS", "IIN1", "IOUT1", "IREF1"],
             [Device("M1", "nfet", ["IIN1", "IIN1", "VSS", "VSS"]), Device("M2", "nfet", ["net11", "IIN1", "VSS", "VSS"]),
              Device("M3", "nfet", ["IREF1", "net11", "VSS", "VSS"]), Device("M4", "nfet", ["IOUT1", "IREF1", "net11", "VSS"])],
             src(936, "allen", "147", {"M1": "M3", "M2": "M1", "M3": "M2", "M4": "M0"}, "netlist_matched_isomorphic+image_checked")))
# ---- single-stage amplifiers ------------------------------------------------
_add(Circuit("C04", "cs_amplifier_current_source_load", ["VDD", "VSS", "VIN1", "VOUT1", "VB1"],
             [Device("M1", "pfet", ["VOUT1", "VB1", "VDD", "VDD"]), Device("M2", "nfet", ["VOUT1", "VIN1", "VSS", "VSS"])],
             src(9, "razavi", "58", {"M1": "M0", "M2": "M1"}, "netlist_matched_isomorphic+image_checked")))
_add(Circuit("C05", "source_follower_mos_current_source", ["VDD", "VSS", "VIN1", "VOUT1", "VB1"],
             [Device("M1", "nfet", ["VOUT1", "VB1", "VSS", "VSS"]), Device("M2", "nfet", ["VDD", "VIN1", "VOUT1", "VSS"])],
             src(20, "razavi", "72", {"M1": "M0", "M2": "M1"}, "netlist_matched_isomorphic+image_checked",
                 ["source resistor R0 (VOUT1-VSS) is interpreted as the external load R_L and lives in the testbench, not in the DUT"])))
_add(Circuit("C06", "cascode_amplifier_cascode_load", ["VDD", "VSS", "VIN1", "VOUT1", "VB1", "VB2", "VB3"],
             [Device("M1", "pfet", ["VOUT1", "VB2", "net10", "VDD"]), Device("M2", "pfet", ["net10", "VB3", "VDD", "VDD"]),
              Device("M3", "nfet", ["net9", "VIN1", "VSS", "VSS"]), Device("M4", "nfet", ["VOUT1", "VB1", "net9", "VSS"])],
             src(38, "razavi", "88", {"M1": "M1", "M2": "M0", "M3": "M3", "M4": "M2"}, "netlist_matched_isomorphic+image_checked")))
_add(Circuit("C12", "cmos_inverter_amplifier", ["VDD", "VSS", "VIN1", "VOUT1"],
             [Device("M1", "nfet", ["VOUT1", "VIN1", "VSS", "VSS"]), Device("M2", "pfet", ["VOUT1", "VIN1", "VDD", "VDD"])],
             src(195, "razavi", "268", {"M1": "M0", "M2": "M1"}, "netlist_matched_isomorphic+image_checked")))
_add(Circuit("C15", "cs_amplifier_resistor_load", ["VDD", "VSS", "VIN1", "VOUT1"],
             [Device("M1", "nfet", ["VOUT1", "VIN1", "VSS", "VSS"]), Device("R1", "res", ["VDD", "VOUT1"])],
             src(235, "razavi", "283", {"M1": "M1", "R1": "R0"}, "netlist_matched_isomorphic+image_partial (resistor not visible in crop)")))
# ---- differential ----------------------------------------------------------
_add(Circuit("C07", "diff_pair_current_source_loads", ["VDD", "VSS", "VIN1", "VIN2", "VOUT1", "VOUT2", "VB1", "IB1"],
             [Device("M1", "nfet", ["VOUT1", "VIN1", "IB1", "VSS"]), Device("M2", "nfet", ["VOUT2", "VIN2", "IB1", "VSS"]),
              Device("M3", "pfet", ["VOUT1", "VB1", "VDD", "VDD"]), Device("M4", "pfet", ["VOUT2", "VB1", "VDD", "VDD"])],
             src(192, "razavi", "260", {"M1": "M0", "M2": "M1", "M3": "M2", "M4": "M3"}, "netlist_matched_isomorphic+image_checked",
                 ["tail node IB1 is a port: the tail current source is an ideal (disclosed) testbench source"])))
_add(Circuit("C08", "five_transistor_ota", ["VDD", "VSS", "VIN1", "VIN2", "VOUT1", "VB1"],
             [Device("M1", "nfet", ["net22", "VIN1", "net23", "VSS"]), Device("M2", "nfet", ["VOUT1", "VIN2", "net23", "VSS"]), Device("M3", "nfet", ["net23", "VB1", "VSS", "VSS"]),
              Device("M4", "pfet", ["net22", "net22", "VDD", "VDD"]), Device("M5", "pfet", ["VOUT1", "net22", "VDD", "VDD"])],
             src(157, "razavi", "171", {"M1": "M2", "M2": "M3", "M3": "M4", "M4": "M0", "M5": "M1"}, "netlist_matched_isomorphic+image_checked")))
_add(Circuit("C16", "diff_pair_resistor_loads", ["VDD", "VSS", "VIN1", "VIN2", "VOUT1", "VOUT2", "IB1"],
             [Device("M1", "nfet", ["VOUT1", "VIN1", "IB1", "VSS"]), Device("M2", "nfet", ["VOUT2", "VIN2", "IB1", "VSS"]),
              Device("R1", "res", ["VDD", "VOUT1"]), Device("R2", "res", ["VDD", "VOUT2"])],
             src(71, "razavi", "107", {"M1": "M0", "M2": "M1", "R1": "R0", "R2": "R1"}, "netlist_matched_isomorphic+image_checked",
                 ["tail node IB1 is a port: ideal (disclosed) testbench current source"])))
_add(Circuit("C17", "degenerated_diff_pair", ["VDD", "VSS", "VIN1", "VIN2", "VOUT1", "VOUT2", "VB1"],
             [Device("M1", "nfet", ["VOUT1", "VIN1", "net07", "VSS"]), Device("M2", "nfet", ["VOUT2", "VIN2", "net09", "VSS"]), Device("M3", "nfet", ["net06", "VB1", "VSS", "VSS"]),
              Device("R1", "res", ["VDD", "VOUT1"]), Device("R2", "res", ["VDD", "VOUT2"]), Device("R3", "res", ["net07", "net06"]), Device("R4", "res", ["net09", "net06"])],
             src(220, "razavi", "272", {"M1": "M0", "M2": "M2", "M3": "M1", "R1": "R0", "R2": "R1", "R3": "R2", "R4": "R3"}, "netlist_matched_isomorphic+image_checked")))
# ---- op amps ---------------------------------------------------------------
_add(Circuit("C09", "telescopic_ota_single_ended", ["VDD", "VSS", "VIN1", "VIN2", "VOUT1", "VB1", "IB1"],
             [Device("M1", "nfet", ["net018", "VIN1", "IB1", "VSS"]), Device("M2", "nfet", ["net016", "VIN2", "IB1", "VSS"]),
              Device("M3", "nfet", ["net04", "VB1", "net018", "VSS"]), Device("M4", "nfet", ["VOUT1", "VB1", "net016", "VSS"]),
              Device("M5", "pfet", ["net04", "net04", "net019", "VDD"]), Device("M6", "pfet", ["VOUT1", "net04", "net017", "VDD"]),
              Device("M7", "pfet", ["net019", "net019", "VDD", "VDD"]), Device("M8", "pfet", ["net017", "net019", "VDD", "VDD"])],
             src(296, "razavi", "360", {"M1": "M1", "M2": "M3", "M3": "M4", "M4": "M5", "M5": "M6", "M6": "M7", "M7": "M8", "M8": "M9"}, "netlist_matched_isomorphic+image_checked",
                 ["tail node IB1 is a port: ideal (disclosed) testbench current source"])))
_add(Circuit("C10", "folded_cascode_ota_fully_differential", ["VDD", "VSS", "VIN1", "VIN2", "VOUT1", "VOUT2", "VB1", "VB2", "VB3", "VB4", "IB1"],
             [Device("M1", "pfet", ["net022", "VIN1", "IB1", "VDD"]), Device("M2", "pfet", ["net018", "VIN2", "IB1", "VDD"]),
              Device("M3", "nfet", ["net022", "VB4", "VSS", "VSS"]), Device("M4", "nfet", ["net018", "VB4", "VSS", "VSS"]),
              Device("M5", "nfet", ["VOUT1", "VB1", "net022", "VSS"]), Device("M6", "nfet", ["VOUT2", "VB1", "net018", "VSS"]),
              Device("M7", "pfet", ["VOUT1", "VB2", "net023", "VDD"]), Device("M8", "pfet", ["VOUT2", "VB2", "net021", "VDD"]),
              Device("M9", "pfet", ["net023", "VB3", "VDD", "VDD"]), Device("M10", "pfet", ["net021", "VB3", "VDD", "VDD"])],
             src(294, "razavi", "357", {"M1": "M0", "M2": "M2", "M3": "M1", "M4": "M3", "M5": "M4", "M6": "M5", "M7": "M6", "M8": "M7", "M9": "M8", "M10": "M9"}, "netlist_matched_isomorphic+image_checked",
                 ["tail node IB1 is a port: ideal (disclosed) testbench current source", "output common mode is set by a disclosed ideal common-mode feedback in the testbench acting on VB4"])))
_add(Circuit("C11", "two_stage_miller_opamp", ["VDD", "VSS", "VIN1", "VIN2", "VOUT1", "IB1"],
             [Device("M1", "pfet", ["IB1", "IB1", "VDD", "VDD"]), Device("M2", "pfet", ["net97", "IB1", "VDD", "VDD"]),
              Device("M3", "pfet", ["net014", "VIN1", "net97", "VDD"]), Device("M4", "pfet", ["net016", "VIN2", "net97", "VDD"]),
              Device("M5", "nfet", ["net014", "net014", "VSS", "VSS"]), Device("M6", "nfet", ["net016", "net014", "VSS", "VSS"]),
              Device("M7", "pfet", ["VOUT1", "IB1", "VDD", "VDD"]), Device("M8", "nfet", ["VOUT1", "net016", "VSS", "VSS"]),
              Device("R1", "res", ["net016", "net022"]), Device("C1", "cap", ["net022", "VOUT1"])],
             src(705, "johns", "243", {"M1": "M10", "M2": "M12", "M3": "M14", "M4": "M13", "M5": "M15", "M6": "M16", "M7": "M17", "M8": "M18", "R1": "R0", "C1": "C0"}, "netlist_matched_isomorphic+image_checked",
                 ["input-pair bodies (source net023, floating in the dataset) tied to VDD", "compensation resistor R1 and capacitor C1 are DUT elements realised with PDK devices"])))
_add(Circuit("C18", "class_ab_output_buffer", ["VDD", "VSS", "VIN1", "VOUT1", "VB1"],
             [Device("M1", "nfet", ["net13", "VIN1", "VSS", "VSS"]), Device("M2", "pfet", ["net9", "VB1", "VDD", "VDD"]),
              Device("M3", "nfet", ["net9", "net9", "net22", "VSS"]), Device("M4", "pfet", ["net13", "net13", "net22", "VDD"]),
              Device("M5", "nfet", ["VDD", "net9", "VOUT1", "VSS"]), Device("M6", "pfet", ["VSS", "net13", "VOUT1", "VDD"])],
             src(877, "gray", "380", {"M1": "M5", "M2": "M4", "M3": "M0", "M4": "M2", "M5": "M1", "M6": "M3"}, "netlist_matched_isomorphic+image_checked",
                 ["load resistor R0 (VOUT1-VSS) is the external load R_L in the testbench", "bias network (M2 current source, M3/M4 diode stack) is part of the DUT"])))

ORDER = sorted(CIRCUITS)
DEV_SPLIT = ["C01", "C04", "C05", "C07", "C13", "C15"]          # development topologies (6)
TEST_SPLIT = [c for c in ORDER if c not in DEV_SPLIT]            # 12 test topologies
E3_CIRCUITS = ["C02", "C08", "C09", "C11", "C16", "C18"]        # E3 selection: mirrors, differential structures, amplifiers
E4_CIRCUITS = ["C02", "C08", "C11", "C17"]                      # E4 hold-out circuits
