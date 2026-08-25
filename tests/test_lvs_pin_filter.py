"""The reference netlist decides which layout labels are pins.

Covers the staging step that stops a composite from inheriting its children's
standalone pin names. Pure Python: no PDK, no klayout, no GDS toolchain, so it
runs on every PR -- unlike the LVS workflow, which is triggered by `workflow_run`
and therefore only runs on the default branch, after a merge.
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

_MODULE = Path(__file__).resolve().parent / "lvs" / "klayout_gf180.py"


def _load():
    """tests/lvs is not a package, so load the runner by path."""
    spec = importlib.util.spec_from_file_location("klayout_gf180", _MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PinFilterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load()

    def _gds(self, workdir, labels):
        import gdstk
        lib = gdstk.Library()
        cell = lib.new_cell("cell_under_test")
        for text in labels:
            cell.add(gdstk.Label(text, (0, 0)))
        path = Path(workdir) / "cell_under_test.gds"
        lib.write_gds(str(path))
        return path

    def _labels(self, path):
        import gdstk
        return sorted(l.text for c in gdstk.read_gds(str(path)).cells for l in c.labels)

    def test_ports_come_from_the_top_subckt(self):
        with tempfile.TemporaryDirectory() as d:
            spice = Path(d) / "c.spice"
            spice.write_text(
                ".subckt other A B\n.ends\n"
                ".subckt cell_under_test Vdd Vss Iin spike\n.ends\n"
            )
            self.assertEqual(
                self.mod._top_level_ports(spice, "cell_under_test"),
                ["Vdd", "Vss", "Iin", "spike"],
            )

    def test_inherited_label_is_dropped_and_pins_are_kept(self):
        # VTAIL is a diff_pair pin standalone and an internal net in a parent.
        with tempfile.TemporaryDirectory() as d:
            gds = self._gds(d, ["Vdd", "Vss", "VTAIL", "spike"])
            dropped, all_gone = self.mod._filter_pin_labels(gds, ["Vdd", "Vss", "spike"])
            self.assertEqual(dropped, ["VTAIL"])
            self.assertFalse(all_gone)
            self.assertEqual(self._labels(gds), ["Vdd", "Vss", "spike"])

    def test_matching_ignores_case(self):
        # Generators and schematics disagree in practice: `vdd` vs `Vdd`.
        with tempfile.TemporaryDirectory() as d:
            gds = self._gds(d, ["vdd", "vss"])
            dropped, all_gone = self.mod._filter_pin_labels(gds, ["Vdd", "Vss"])
            self.assertEqual(dropped, [])
            self.assertFalse(all_gone)
            self.assertEqual(self._labels(gds), ["vdd", "vss"])

    def test_dropping_every_label_is_flagged(self):
        # Not inheritance but a naming mismatch: the caller warns instead of
        # leaving the layout silently pinless.
        with tempfile.TemporaryDirectory() as d:
            gds = self._gds(d, ["n1", "n2"])
            dropped, all_gone = self.mod._filter_pin_labels(gds, ["Vdd", "Vss"])
            self.assertEqual(sorted(dropped), ["n1", "n2"])
            self.assertTrue(all_gone)

    def test_a_layout_without_labels_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            gds = self._gds(d, [])
            dropped, all_gone = self.mod._filter_pin_labels(gds, ["Vdd", "Vss"])
            self.assertEqual(dropped, [])
            self.assertFalse(all_gone)

    def test_unreadable_ports_drop_nothing(self):
        # Safety net: without a port list, keep every label rather than
        # stripping the layout of all its pins.
        with tempfile.TemporaryDirectory() as d:
            gds = self._gds(d, ["Vdd", "VTAIL"])
            dropped, all_gone = self.mod._filter_pin_labels(gds, [])
            self.assertEqual(dropped, [])
            self.assertFalse(all_gone)
            self.assertEqual(self._labels(gds), ["VTAIL", "Vdd"])


if __name__ == "__main__":
    unittest.main()
