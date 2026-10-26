"""Printed-table SOFTWARE fixtures only; no simulated physical measurements."""
import json
import unittest

from scripts.telescopic_ota_characterization import device_OP


class TelescopicOPParserTests(unittest.TestCase):
    # Shortened BSIM table shape follows the actual ngspice 'show all' format.
    # These arbitrary numbers test parsing, not circuit performance.
    table = """ BSIM4v5: Berkeley Short Channel IGFET Model-4
     device m.xdut.xn1_0.msky13 m.xdut.xp1_0.msky13
         gm 0.0001 0.0002
        gds 0.000001 0.000002
         id 0.000003 -0.000004
        vds 0.2 -0.3
      vdsat 0.1 -0.1
"""

    def test_per_device_table_keeps_sign_and_requires_complete_inventory(self):
        result = device_OP(self.table, 2)
        self.assertTrue(result["complete"])
        self.assertEqual(result["devices"]["m.xdut.xp1_0.msky13"]["id"], -0.000004)
        self.assertFalse(device_OP(self.table, 3)["complete"])

    def test_nonfinite_or_unreadable_device_field_is_unknown_and_serializable(self):
        for token in ["nan", "inf", "unavailable"]:
            with self.subTest(token=token):
                result = device_OP(self.table.replace("gm 0.0001", "gm "+token), 2)
                self.assertFalse(result["complete"])
                self.assertEqual(result["parse_errors"][0]["raw_value"], token)
                json.dumps(result, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
