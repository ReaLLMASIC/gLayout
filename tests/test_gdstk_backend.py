"""End-to-end sanity for the gdstk backend: import, build, write GDS."""
import os
import tempfile
import unittest


class GdstkBackendTests(unittest.TestCase):
    """Run with GLAYOUT_BACKEND=gdstk. These tests verify that the native
    gdstk backend can build the primitives and routers the repo exposes."""

    @classmethod
    def setUpClass(cls):
        os.environ["GLAYOUT_BACKEND"] = "gdstk"
        os.environ.setdefault("PDK_ROOT", "/tmp")
        # Force (re)binding in case the selector was imported earlier.
        from glayout import backend
        backend.set_backend("gdstk")

    def test_backend_selected(self):
        from glayout import backend
        self.assertEqual(backend.get_backend(), "gdstk")

    def test_component_api(self):
        from glayout.backend import Component, Port, rectangle
        c = Component("probe")
        r = rectangle(size=(5, 3), layer=(1, 0))
        ref = c << r
        ref.movex(10)
        self.assertEqual(c.bbox, ((10.0, 0.0), (15.0, 3.0)))
        c.add_port(name="p1", center=(0, 0), width=1, orientation=0, layer=(1, 0))
        self.assertIn("p1", c.ports)

    def test_add_ref_array(self):
        """add_ref(columns=, rows=, spacing=) lays out a repeated reference.

        `test_bjt_gdsfactory` builds its contact rings this way. Without it
        the notebook dies on a TypeError halfway through.
        """
        from glayout.backend import Component, rectangle
        c = Component("array_probe")
        unit = rectangle(size=(1, 1), layer=(1, 0))
        ref = c.add_ref(unit, columns=3, rows=2, spacing=(2, 2))
        self.assertIsNotNone(ref)
        # 3 columns at pitch 2 span 1 + 2*2 = 5; 2 rows span 1 + 2 = 3.
        (x0, y0), (x1, y1) = c.bbox
        self.assertAlmostEqual(x1 - x0, 5.0)
        self.assertAlmostEqual(y1 - y0, 3.0)

    def test_add_ref_array_needs_spacing(self):
        from glayout.backend import Component, rectangle
        c = Component("array_probe_nospacing")
        with self.assertRaises(ValueError):
            c.add_ref(rectangle(size=(1, 1), layer=(1, 0)), columns=2)

    def test_primitives_build(self):
        from glayout.pdk.sky130_mapped.sky130_mapped import sky130_mapped_pdk as pdk
        from glayout.primitives.via_gen import via_stack, via_array
        from glayout.primitives.fet import nmos, pmos
        from glayout.primitives.guardring import tapring
        self.assertIsNotNone(via_stack(pdk, "active_diff", "met2").bbox)
        self.assertIsNotNone(via_array(pdk, "active_diff", "met2", num_vias=(2, 3)).bbox)
        self.assertIsNotNone(nmos(pdk, fingers=1).bbox)
        self.assertIsNotNone(pmos(pdk, fingers=1).bbox)
        self.assertIsNotNone(tapring(pdk).bbox)

    def test_routing_build(self):
        from glayout.pdk.sky130_mapped.sky130_mapped import sky130_mapped_pdk as pdk
        from glayout.backend import Port
        from glayout.routing.c_route import c_route
        from glayout.routing.L_route import L_route
        from glayout.routing.straight_route import straight_route
        layer = pdk.get_glayer("met2")
        pa = Port("a", orientation=90, center=(0, 0), width=1, layer=layer)
        pb = Port("b", orientation=90, center=(10, 0), width=1, layer=layer)
        pc = Port("c", orientation=270, center=(0, 10), width=1, layer=layer)
        pd = Port("d", orientation=0, center=(10, 10), width=1, layer=pdk.get_glayer("met5"))
        self.assertIsNotNone(c_route(pdk, pa, pb, extension=2).bbox)
        self.assertIsNotNone(L_route(pdk, pa, pd).bbox)
        self.assertIsNotNone(straight_route(pdk, pa, pc).bbox)

    def test_composite_diff_pair_writes_gds(self):
        from glayout.pdk.sky130_mapped.sky130_mapped import sky130_mapped_pdk as pdk
        from glayout.cells.elementary.diff_pair.diff_pair import diff_pair
        dp = diff_pair(pdk)
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "dp.gds")
            dp.write_gds(path)
            self.assertGreater(os.path.getsize(path), 0)


if __name__ == "__main__":
    unittest.main()
