from pathlib import Path
import unittest
from src.report_parsers import magic_drc_report, netgen_lvs_report, rc_netlist_inventory, duplicate_subcircuits

FIXTURES=Path(__file__).parent/"fixtures"


class ActualToolReportTests(unittest.TestCase):
    def test_duplicate_subcircuit_namespace_is_rejected(self):
        self.assertEqual(duplicate_subcircuits(".subckt NMOS D G S B\n.ends\n.subckt nmos D G S B\n.ends\n"),["nmos"])
        text=(FIXTURES/"device4_allnet_pex.spice").read_text()
        self.assertFalse(rc_netlist_inventory(text+"\n.subckt device4_rc D B S G\n.ends\n","device4_rc",["D","G","S","B"])["has_real_RC"])

    def test_unique_match_cannot_hide_disconnected_ota_inputs(self):
        old=netgen_lvs_report((FIXTURES/"ota_legacy_disconnected_lvs.rpt").read_text())
        self.assertTrue(old["matched_uniquely"])
        self.assertFalse(old["is_clean"])
        self.assertEqual(old["disconnected_nodes"],["VIN","VOUT"])
        fixed=netgen_lvs_report((FIXTURES/"ota_repaired_lvs.rpt").read_text())
        self.assertTrue(fixed["is_clean"])

    def test_numeric_zero_is_required_and_legacy_empty_count_is_rejected(self):
        self.assertFalse(magic_drc_report((FIXTURES/"ota_clean_drc.rpt").read_text())["is_clean"])
        self.assertTrue(magic_drc_report("ota7 count: 0\n----------------------------------------\n")["is_clean"])
        self.assertFalse(magic_drc_report("")["is_clean"])
        bad=magic_drc_report((FIXTURES/"known_underwidth_full_drc.rpt").read_text())
        self.assertFalse(bad["is_clean"])
        self.assertGreater(bad["error_count"],0)

    def test_actual_all_net_mos_requires_external_terminals_and_both_R_C(self):
        text=(FIXTURES/"device4_allnet_pex.spice").read_text()
        result=rc_netlist_inventory(text,"device4_rc",["D","G","S","B"])
        self.assertTrue(result["has_real_RC"])
        self.assertEqual(result["counts"],{"R":505,"C":268,"X":2,"M":0})
        self.assertFalse(rc_netlist_inventory(text,"device4_rc",["D","G","S"])["has_real_RC"])
        without_r="\n".join(s for s in text.splitlines() if not s.upper().startswith("R"))
        self.assertFalse(rc_netlist_inventory(without_r,"device4_rc",["D","G","S","B"])["has_real_RC"])
        self.assertFalse(rc_netlist_inventory(text+"\nCbad D B -41.9857f\n","device4_rc",["D","G","S","B"])["has_real_RC"])


if __name__=="__main__":
    unittest.main()
