"""The mimcap primitive builds on its own, not only through mimcap_array.

`mimcap_array` passes `with_extension=False`, so every cell in the suite
reaches the primitive through the one path that skips the appendix code. A
direct `mimcap(pdk, size)` -- the obvious way to use it -- goes down the
other branch, and that is where it raised `TypeError: 'tuple' object does
not support item assignment`.

The appendix branch is entered only when the requested size leaves
`min_via_distance < 0.4`, so the size matters: 5x5 reaches it. Both MIM
options are covered because they build different stacks (A on
met2/FuseTop/met3, B on met4/FuseTop/met5) around the same code.
"""
import unittest


class MimcapBuildTests(unittest.TestCase):
    SIZES = ((5.0, 5.0), (10.0, 4.0))   # square hits the appendix branch

    def _pdk(self):
        from glayout.pdk.gf180_mapped.gf180_mapped import gf180_mapped_pdk
        return gf180_mapped_pdk

    def test_mimcap_builds_with_extensions(self):
        """The default path. This is the one that regressed."""
        from glayout.primitives.mimcap import mimcap
        pdk = self._pdk()
        for option in ("A", "B"):
            for size in self.SIZES:
                with self.subTest(option=option, size=size):
                    comp = mimcap(pdk, size=size, option=option)
                    self.assertTrue(comp.get_ports_list())

    def test_mimcap_builds_without_extensions(self):
        """The path mimcap_array takes, which never regressed.

        Kept so a future change that fixes one branch by breaking the other
        does not look like a pass.
        """
        from glayout.primitives.mimcap import mimcap
        pdk = self._pdk()
        for option in ("A", "B"):
            with self.subTest(option=option):
                comp = mimcap(pdk, size=(5.0, 5.0), option=option,
                              with_extension=False)
                self.assertTrue(comp.get_ports_list())

    def test_mimcap_array_builds(self):
        from glayout.primitives.mimcap import mimcap_array
        comp = mimcap_array(self._pdk(), rows=2, columns=2, size=(5.0, 5.0))
        self.assertTrue(comp.get_ports_list())

    def test_plates_land_on_the_layers_the_option_names(self):
        """Option A is a met2/met3 stack, option B a met4/met5 one.

        Building is not enough: the two options differ only in which metals
        they draw, so a fix that builds both while drawing the same stack
        would pass every check above.

        Read back from the written GDS rather than from the Component, so
        this does not depend on which backend is active.
        """
        import gdstk
        import tempfile
        from glayout.primitives.mimcap import mimcap
        pdk = self._pdk()
        expected = {"A": ("met2", "met3"), "B": ("met4", "met5")}
        for option, glayers in expected.items():
            with self.subTest(option=option):
                comp = mimcap(pdk, size=(5.0, 5.0), option=option)
                with tempfile.TemporaryDirectory() as tmp:
                    path = tmp + "/mimcap.gds"
                    comp.write_gds(path)
                    top = gdstk.read_gds(path).top_level()[0]
                    top.flatten()
                    drawn = {(p.layer, p.datatype) for p in top.polygons}
                for glayer in glayers:
                    layer, datatype = pdk.get_glayer(glayer)
                    self.assertIn((int(layer), int(datatype)), drawn,
                                  "option %s should draw %s" % (option, glayer))


if __name__ == "__main__":
    unittest.main()
