"""Narrow devices build on both PDKs and on the gdstk backend.

The diffusion under a contact cannot shrink with the channel (CO.4 on
gf180), so a device narrower than the contact needs the dogbone shape. DRC
covers the drawn result; this covers the build itself, which DRC never
reaches if the generator raises.

It also covers a backend DRC does not: the DRC and LVS workflows run the
gdsfactory backend, while conftest.py pins the suite to gdstk.
"""
import unittest
import warnings


class NarrowFetTests(unittest.TestCase):
    WIDTHS = (0.22, 0.15)   # at the PDK minimum, and below it

    def _pdks(self):
        from glayout.pdk.gf180_mapped.gf180_mapped import gf180_mapped_pdk
        from glayout.pdk.sky130_mapped.sky130_mapped import sky130_mapped_pdk
        return (("gf180", gf180_mapped_pdk), ("sky130", sky130_mapped_pdk))

    def test_narrow_devices_build(self):
        from glayout.primitives.fet import nmos, pmos
        for pdk_name, pdk in self._pdks():
            for fet in (nmos, pmos):
                for width in self.WIDTHS:
                    with self.subTest(pdk=pdk_name, fet=fet.__name__, width=width):
                        with warnings.catch_warnings():
                            # A sub-minimum width warns and is clamped; that is
                            # the documented behaviour, not a failure.
                            warnings.simplefilter("ignore", UserWarning)
                            comp = fet(pdk, width=width, length=0.28)
                        self.assertTrue(comp.get_ports_list())

    def test_sub_minimum_width_warns_and_clamps(self):
        from glayout.pdk.gf180_mapped.gf180_mapped import gf180_mapped_pdk as pdk
        from glayout.primitives.fet import nmos
        with self.assertWarns(UserWarning):
            nmos(pdk, width=0.15, length=0.28)


if __name__ == "__main__":
    unittest.main()
