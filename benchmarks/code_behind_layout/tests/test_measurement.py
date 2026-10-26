"""Fictional records exercise scientific measurement logic, not physical tools."""
from copy import deepcopy
import unittest

from src.measurement import assess, audit_reference_ports, paired_summary, split_errors


def example():
    contract = {"task_id": "fixture_task", "configuration_id": "fixture_config",
                "reference_id": "fixture_reference", "required_corners": ["tt", "ss", "ff"],
                "specifications": [{"name": "gain", "unit": "dB", "min": 60},
                                   {"name": "phase_margin", "unit": "deg", "min": 60},
                                   {"name": "power", "unit": "W", "max": 0.001}]}
    record = {"task_id": "fixture_task", "configuration_id": "fixture_config",
              "reference_id": "fixture_reference", "executed": True, "gds_emitted": True,
              "checks": {name: True for name in ("drc", "lvs", "devices", "ports", "intent")},
              "pex": {"executed": True, "kind": "physical_rc", "resistance_extracted": True,
                      "capacitance_extracted": True},
              "corners": {corner: {"converged": True, "operating_point_valid": True,
                                   "metrics": {"gain": {"value": 65, "unit": "dB"},
                                               "phase_margin": {"value": 60, "unit": "deg"},
                                               "power": {"value": 0.0008, "unit": "W"}}}
                          for corner in ("tt", "ss", "ff")}}
    return contract, record


class MeasurementTests(unittest.TestCase):
    def test_unused_ota_interface_is_detected(self):
        text = ".subckt ota VIN VOUT VSS2 VSS IBIAS VDD2 VDD1 VN VP\nX0 VP VN VDD1 VDD2 IBIAS VSS VN INPUT_STAGE\nX1 VDD1 VDD2 VN VDD VSS2 GAIN_STAGE\n.ends ota\n"
        result = audit_reference_ports(text, "ota", ["VIN", "VOUT"])
        self.assertEqual(result["unused_required_pins"], ["VIN", "VOUT"])
        self.assertEqual(result["status"], "FAIL")

    def test_connected_interface_and_continuation(self):
        text = "* ignored VIN comment\n.SUBCKT ota VIN VOUT\n+ VDD VSS\nX0 VOUT VIN VSS VSS nfet\n.ends\n"
        self.assertEqual(audit_reference_ports(text, "OTA", ["VIN", "VOUT"])["status"], "PASS")
        with self.assertRaises(ValueError):
            audit_reference_ports(text, "OTA", ["UNDECLARED"])

    def test_all_conditions_and_boundary_are_required(self):
        contract, record = example()
        self.assertTrue(assess(contract, record)["S2"])
        record["corners"]["tt"]["metrics"]["phase_margin"]["value"] = 59.9
        result = assess(contract, record)
        self.assertTrue(result["S1"])
        self.assertFalse(result["S2"])

    def test_rc_extraction_cannot_be_skipped_or_synthetic(self):
        contract, initial = example()
        changes = [{"executed": False}, {"kind": "synthetic"},
                   {"resistance_extracted": False}, {"capacitance_extracted": False}]
        for change in changes:
            with self.subTest(change=change):
                record = deepcopy(initial)
                record["pex"].update(change)
                self.assertFalse(assess(contract, record)["S2"])

    def test_binding_rejects_wrong_reference_or_configuration(self):
        contract, initial = example()
        for field in ("task_id", "configuration_id", "reference_id"):
            with self.subTest(field=field):
                record = deepcopy(initial)
                record[field] = "wrong"
                result = assess(contract, record)
                self.assertTrue(result["S0"])
                self.assertFalse(result["S1"])
                self.assertFalse(result["S2"])

    def test_device_port_and_intent_checks_cannot_be_omitted(self):
        contract, initial = example()
        for check in initial["checks"]:
            with self.subTest(check=check):
                record = deepcopy(initial)
                del record["checks"][check]
                self.assertFalse(assess(contract, record)["S1"])

    def test_missing_corner_and_unconverged_operating_point(self):
        contract, initial = example()
        for field in ("missing_corner", "converged", "operating_point_valid"):
            with self.subTest(field=field):
                record = deepcopy(initial)
                if field == "missing_corner":
                    del record["corners"]["ss"]
                else:
                    record["corners"]["ss"][field] = False
                self.assertFalse(assess(contract, record)["S2"])

    def test_wrong_units_missing_and_nonfinite_values(self):
        contract, initial = example()
        for value in (None, float("nan"), float("inf"), True, "65"):
            with self.subTest(value=value):
                record = deepcopy(initial)
                record["corners"]["tt"]["metrics"]["gain"]["value"] = value
                self.assertFalse(assess(contract, record)["S2"])
        initial["corners"]["tt"]["metrics"]["power"]["unit"] = "mW"
        self.assertFalse(assess(contract, initial)["S2"])

    def test_empty_or_inverted_contract_does_not_pass_vacuously(self):
        initial, record = example()
        for change in ({"required_corners": []}, {"specifications": []},
                       {"required_corners": ["tt", "tt"]},
                       {"specifications": [{"name": "gain", "unit": "dB", "min": 80, "max": 60}]}):
            with self.subTest(change=change):
                contract = deepcopy(initial)
                contract.update(change)
                with self.assertRaises(ValueError):
                    assess(contract, record)

    def test_failed_and_timeout_outcomes_remain_in_denominator(self):
        result = paired_summary({"a": True, "b": True, "c": False},
                                {"a": True, "b": False, "c": False})
        self.assertEqual(result["coverage"], 1 / 3)
        self.assertEqual(result["regression_rate"], 0.5)
        with self.assertRaises(ValueError):
            paired_summary({"a": True, "b": True}, {"a": True})
        self.assertIsNone(paired_summary({"a": False}, {"a": True})["regression_rate"])

    def test_generation_failure_prevents_all_higher_tiers(self):
        contract, record = example()
        record["executed"] = False
        result = assess(contract, record)
        self.assertFalse(result["S0"])
        self.assertFalse(result["S1"])
        self.assertFalse(result["S2"])

    def test_lineage_and_topology_leakage(self):
        registry = {"topology_holdouts": ["cmfb"], "lineages": [
            {"lineage_id": "shared", "split": "train", "topology_family": "mirror"},
            {"lineage_id": "shared", "split": "test", "topology_family": "mirror"},
            {"lineage_id": "other", "split": "validation", "topology_family": "cmfb"}]}
        errors = split_errors(registry)
        self.assertIn("duplicate_or_conflicting_lineage:shared", errors)
        self.assertIn("topology_holdout_leakage:other", errors)
        self.assertFalse(split_errors({"lineages": [registry["lineages"][0]]}))
        compiler={"topology_holdouts":["miller_ota"],"lineages":[{
            "lineage_id":"compiler","split":"train","topology_family":"multiple_topologies",
            "topology_families":["current_mirror","miller_ota"]}]}
        self.assertIn("topology_holdout_leakage:compiler",split_errors(compiler))


if __name__ == "__main__":
    unittest.main()
