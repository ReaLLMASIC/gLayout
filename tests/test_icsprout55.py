"""Comprehensive test suite for ICsprout55 portable PDK support."""
from __future__ import annotations

import shutil
import tempfile
import unittest
import warnings
from pathlib import Path

import gdstk

from glayout import (
    MappedPDK,
    common_centroid_ab_ba,
    generic_4T_interdigitzed,
    icsprout55,
    mimcap,
    mimcap_array,
    multiplier,
    nmos,
    pmos,
    resistor,
    tapring,
    two_nfet_interdigitized,
    two_pfet_interdigitized,
    via_array,
    via_stack,
)
from glayout.cells.composite import (
    diff_pair_ibias,
    differential_to_single_ended_converter,
    low_voltage_cmirror,
    opamp,
)
from glayout.cells.elementary import (
    current_mirror,
    diff_pair,
    flipped_voltage_follower,
    transmission_gate,
)
from glayout.cells.elementary.current_mirror.current_mirror import add_cm_labels
from glayout.cells.elementary.finger_sequence import cc_current_mirror, cc_diff_pair
from glayout.floorplan.examples import bias_bank, cs_stage
from glayout.pdk.icsprout55_mapped import (
    ICSPROUT55_NGSPICE_DIR,
    ICSPROUT55_SPICE_LIB,
    ICSPROUT55_SPICE_MODELS,
    icsprout55_mapped_pdk,
)
from glayout.primitives.bjt import draw_bjt


class ICsprout55Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.pdk = icsprout55_mapped_pdk
        self.pdk.activate()

    def test_pdk_registration_and_metadata(self) -> None:
        self.assertIsNotNone(icsprout55)
        self.assertIs(icsprout55, icsprout55_mapped_pdk)
        self.assertIsInstance(self.pdk, MappedPDK)
        self.assertEqual(self.pdk.name, "icsprout55")
        self.assertAlmostEqual(self.pdk.gds_write_settings.precision, 1e-9)
        self.assertAlmostEqual(self.pdk.grid_size, 0.001)
        self.assertEqual(
            self.pdk.models,
            {
                "nfet": "nm1p2_svt_lp",
                "pfet": "pm1p2_svt_lp",
                "mimcap": "cap_mim_2f0fF",
            },
        )
        self.assertTrue(Path(self.pdk.pdk_files["klayout_drc_file"]).is_file())
        self.assertTrue(Path(self.pdk.pdk_files["lvs_schematic_ref_file"]).is_file())
        self.assertTrue(Path(self.pdk.pdk_files["lvs_setup_tcl_file"]).is_file())
        self.assertTrue(Path(self.pdk.pdk_files["magic_drc_file"]).is_file())

    def test_simulation_models_and_spice_deck(self) -> None:
        self.assertTrue(ICSPROUT55_NGSPICE_DIR.is_dir())
        self.assertTrue(ICSPROUT55_SPICE_LIB.is_file())
        self.assertTrue((ICSPROUT55_NGSPICE_DIR / "model_wrapper1_hsp.lib").is_file())
        self.assertTrue((ICSPROUT55_NGSPICE_DIR / "model_wrapper2_hsp.lib").is_file())
        self.assertEqual(ICSPROUT55_SPICE_MODELS["mos"]["nfet_svt"], "nm1p2_svt_lp")
        self.assertEqual(ICSPROUT55_SPICE_MODELS["mos"]["pfet_svt"], "pm1p2_svt_lp")
        self.assertIn("tt_mos", ICSPROUT55_SPICE_MODELS["corners"]["mos"])
        for subdir in ("mos", "bjt", "dio", "res", "mom", "var"):
            self.assertTrue((ICSPROUT55_NGSPICE_DIR / subdir).is_dir())

    def test_layer_mapping_and_grules(self) -> None:
        for glayer in self.pdk.glayers:
            gds_layer = self.pdk.get_glayer(glayer)
            self.assertIsInstance(gds_layer, tuple)
            self.assertEqual(len(gds_layer), 2)
        self.assertEqual(self.pdk.get_glayer("active_diff"), (2, 1))
        self.assertEqual(self.pdk.get_glayer("poly"), (41, 1))
        self.assertEqual(self.pdk.get_glayer("mcon"), (72, 1))
        self.assertEqual(self.pdk.get_glayer("met1"), (81, 1))
        self.assertEqual(self.pdk.get_glayer("met5"), (85, 1))
        self.assertEqual(self.pdk.get_glayer("capmet"), (140, 1))
        self.assertIn("fusetop", self.pdk.layers)
        self.assertIn("MIM_L_MK", self.pdk.layers)
        self.assertEqual(self.pdk.get_grule("poly")["min_width"], 0.06)
        self.assertEqual(self.pdk.get_grule("active_diff")["min_width"], 0.12)
        self.assertGreater(self.pdk.util_max_metal_seperation(), 0.0)

    def test_grid_snapping_and_gds_precision(self) -> None:
        self.assertAlmostEqual(float(self.pdk.snap_to_2xgrid(0.06)), 0.06, places=6)
        self.assertAlmostEqual(float(self.pdk.snap_to_2xgrid(0.12)), 0.12, places=6)
        snapped = self.pdk.snap_to_2xgrid(0.283)
        self.assertAlmostEqual(float(snapped), 0.284, places=6)
        comp = via_stack(self.pdk, "met1", "met3")
        with tempfile.TemporaryDirectory() as tmp:
            gds_path = Path(tmp) / "via_stack.gds"
            comp.write_gds(str(gds_path))
            lib = gdstk.read_gds(str(gds_path))
            self.assertAlmostEqual(lib.precision, 1e-9)

    def test_primitives_build(self) -> None:
        nfet_comp = nmos(self.pdk, width=1.5, length=0.06, fingers=2, multipliers=1)
        pfet_comp = pmos(self.pdk, width=1.5, length=0.06, fingers=2, multipliers=1)
        self.assertTrue(nfet_comp.get_ports_list())
        self.assertTrue(pfet_comp.get_ports_list())
        self.assertIn("nm1p2_svt_lp", nfet_comp.info["netlist"].generate_netlist())
        self.assertIn("pm1p2_svt_lp", pfet_comp.info["netlist"].generate_netlist())

        # Minimum-sized (W=0.12, L=0.06) and sub-minimum dogbone FETs
        for length in (0.06, 0.08):
            for width in (0.12, 0.08):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    narrow_n = nmos(self.pdk, width=width, length=length)
                    narrow_p = pmos(self.pdk, width=width, length=length)
                self.assertTrue(narrow_n.get_ports_list())
                self.assertTrue(narrow_p.get_ports_list())

        # Multiplier, tapring, via_stack, via_array
        mult = multiplier(self.pdk, "n+s/d", width=1.5, length=0.06, fingers=2)
        ring = tapring(self.pdk, enclosed_rectangle=(4.0, 4.0))
        vstack = via_stack(self.pdk, "active_diff", "met5")
        varr = via_array(self.pdk, "met1", "met2", size=(2.0, 2.0))
        for c in (mult, ring, vstack, varr):
            self.assertTrue(c.get_ports_list())

        # MIM cap (options A and B) and array
        for opt in ("A", "B"):
            cap = mimcap(self.pdk, size=(6.0, 6.0), option=opt)
            self.assertTrue(cap.get_ports_list())
        cap_arr = mimcap_array(self.pdk, rows=2, columns=2, size=(6.0, 6.0))
        self.assertTrue(cap_arr.get_ports_list())
        self.assertIn("cap_mim_2f0fF", cap_arr.info["netlist"].generate_netlist())

        # Resistor and BJT
        res = resistor(self.pdk)
        self.assertTrue(res.get_ports_list())
        npn_comp = draw_bjt(self.pdk, bjt_type="npn", active_area=(0.54, 2.0))
        pnp_comp = draw_bjt(self.pdk, bjt_type="pnp", active_area=(0.42, 5.0))
        self.assertTrue(npn_comp.get_ports_list())
        self.assertTrue(pnp_comp.get_ports_list())

    def test_placements_and_elementary_cells_build(self) -> None:
        inter_n = two_nfet_interdigitized(self.pdk, numcols=2, width=1.5, length=0.06, fingers=1)
        inter_p = two_pfet_interdigitized(self.pdk, numcols=2, width=1.5, length=0.06, fingers=1)
        cc_abba = common_centroid_ab_ba(self.pdk, width=1.5, length=0.06, fingers=2)
        four_t = generic_4T_interdigitzed(self.pdk, numcols=2, length=0.06)
        cm_n = current_mirror(self.pdk, numcols=2, width=3.0, length=0.06, device="nfet")
        cm_p = current_mirror(self.pdk, numcols=2, width=3.0, length=0.06, device="pfet")
        dp = diff_pair(self.pdk, width=3.0, length=0.06, fingers=2)
        fvf = flipped_voltage_follower(self.pdk, width=(3.0, 3.0), length=(0.06, 0.06), fingers=(2, 2))
        tg = transmission_gate(self.pdk, width=(1.5, 1.5), length=(0.06, 0.06), fingers=(2, 2))
        cc_cm = cc_current_mirror(self.pdk, width=1.5, length=0.06, fingers=2, device="nfet")
        cc_dp = cc_diff_pair(self.pdk, width=1.5, length=0.06, fingers=2)

        for comp in (inter_n, inter_p, cc_abba, four_t, cm_n, cm_p, dp, fvf, tg, cc_cm, cc_dp):
            self.assertTrue(comp.get_ports_list())
            self.assertGreater(len(comp.get_polygons()), 0)

    def test_composite_and_floorplan_cells_build(self) -> None:
        dse = differential_to_single_ended_converter(self.pdk, rmult=1, half_pload=(2.0, 0.06, 2), via_xlocation=0.0)
        dpi = diff_pair_ibias(self.pdk, half_diffpair_params=(3.0, 0.06, 2), diffpair_bias=(3.0, 0.06, 2))
        lvcm = low_voltage_cmirror(self.pdk, width=(2.0, 1.0), length=0.06, fingers=(2, 1))
        oa = opamp(
            self.pdk,
            half_diffpair_params=(5.0, 0.06, 1),
            diffpair_bias=(5.0, 0.06, 1),
            half_common_source_params=(7.0, 0.06, 10, 5),
            half_common_source_bias=(6.0, 0.06, 8, 4),
            half_pload=(6.0, 0.06, 5),
        )
        bb = bias_bank(self.pdk, scale=1, width=1.5, length=0.06)
        cs = cs_stage(self.pdk, width=2.0, length=0.06, fingers=4)
        for comp in (dse, dpi, lvcm, oa, bb, cs):
            self.assertTrue(comp.get_ports_list())
            self.assertGreater(len(comp.get_polygons()), 0)

    @unittest.skipUnless(shutil.which("klayout"), "klayout binary not on PATH")
    def test_klayout_drc_and_lvs_smoke(self) -> None:
        import sys
        lvs_dir = Path(__file__).resolve().parent / "lvs"
        if str(lvs_dir) not in sys.path:
            sys.path.insert(0, str(lvs_dir))
        from klayout_gf180 import run_lvs_klayout_gf180
        from run_cell_lvs import _parse_lvs_report

        cell_comp = current_mirror(self.pdk, numcols=2, width=3.0, length=0.06, device="nfet")
        cell_comp.name = "current_mirror_nfet_icsprout55"
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            gds_path = tmpdir / "current_mirror_nfet_icsprout55.gds"
            spice_path = tmpdir / "current_mirror_nfet_icsprout55.spice"
            cell_comp.write_gds(str(gds_path))
            spice_path.write_text(cell_comp.info["netlist"].generate_netlist())

            drc_ok = self.pdk.drc(gds_path, output_dir_or_file=tmpdir / "drc")
            self.assertTrue(drc_ok)

            lvs_res = run_lvs_klayout_gf180(
                layout=str(gds_path),
                design_name=cell_comp.name,
                netlist=str(spice_path),
                output_file_path=str(tmpdir / "lvs"),
                pdk_root=str(Path(self.pdk.pdk_files["klayout_drc_file"]).parent / "lvs"),
            )
            rpt_path = Path(lvs_res["report_path"])
            self.assertTrue(rpt_path.is_file())
            parsed = _parse_lvs_report(rpt_path.read_text())
            self.assertTrue(parsed["is_pass"], parsed.get("conclusion"))


if __name__ == "__main__":
    unittest.main()
