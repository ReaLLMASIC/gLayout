from pathlib import Path
import unittest

from src.e3_parameters import interface, render
from src.e3_task_prepare import DEFAULTS, EDITABLE, INITIALS

ROOT = Path(__file__).resolve().parents[1]
PDK = {"rules": {name: {name: {"min_width": width}} for name, width in [("met3", .14), ("met4", .3), ("met5", .3)]}}


class ExpandedParameterTests(unittest.TestCase):
    def test_actual_width_rule_controls_lower_bound(self):
        row = interface("common_source_stage", PDK)["parameters"]["output_width_um"]
        self.assertEqual(row["min"], .3)
        self.assertEqual(row["max"], 2.5)

    def test_every_old_initial_state_is_in_stronger_family(self):
        for target in EDITABLE:
            if target == "mirror":
                continue
            original = (ROOT/EDITABLE[target]).read_text()
            for values in INITIALS[target]:
                render(target, original, values, PDK)

    def test_shift_collision_uses_original_coordinates_once(self):
        source = (ROOT/EDITABLE["cascode_mirror"]).read_text()
        after = render("cascode_mirror", source, {"external_rail_offset_um": 12, "stack_width_um": .8}, PDK)
        self.assertIn('segment("met5",(-30,82),(130,82),1)', after)
        #70 is also the explicit IREF right rail endpoint; the declared macro
        # offset moves that endpoint as well as the external rail heights.
        self.assertIn('[("RHIGH","IREF",94,35,82)', after)
        self.assertIn('("OHIGH","IOUT",106,108,160)', after)

    def test_new_interior_value_is_accepted_but_offgrid_or_resize_rejected(self):
        source = (ROOT/EDITABLE["stacked_switch"]).read_text()
        after = render("stacked_switch", source, {"separation_um": 25.005, "signal_width_um": .305}, PDK)
        self.assertIn('separation=25.005, signal_width=0.305', after)
        with self.assertRaises(ValueError):
            render("stacked_switch", source, {"separation_um": 25.001, "signal_width_um": .3}, PDK)
        with self.assertRaises(ValueError):
            render("stacked_switch", source, {**DEFAULTS["stacked_switch"], "width": 9}, PDK)


if __name__ == "__main__":
    unittest.main()
