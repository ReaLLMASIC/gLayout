"""Assess normalized trusted-evaluator outcomes, without running EDA tools.

The evaluator must establish artifact provenance, immutable reference binding,
tool execution, and isolation before supplying records to this module.
"""
import math
import re


def audit_reference_ports(netlist, subcircuit, required_pins):
    """Find required formal pins absent from a subcircuit body.

    This limited lexical scan detects disconnected exported pins. Passing it
    does not prove circuit function, device sizing, or reference correctness.
    """
    logical_lines = []
    for line in netlist.splitlines():
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        if line.startswith("+") and logical_lines:
            logical_lines[-1] += " " + line[1:].strip()
        else:
            logical_lines.append(line)
    for index, line in enumerate(logical_lines):
        header = line.split()
        if len(header) < 2 or header[0].lower() != ".subckt" or header[1].lower() != subcircuit.lower():
            continue
        pins = []
        for token in header[2:]:
            if "=" in token or token.lower() == "params:":
                break
            pins.append(token.upper())
        required = [pin.upper() for pin in required_pins]
        if not required or any(pin not in pins for pin in required):
            raise ValueError("Required interface pins are not declared by the subcircuit")
        tokens = set()
        ended = False
        for body in logical_lines[index + 1:]:
            if body.split()[0].lower() == ".ends":
                ended = True
                break
            tokens.update(token.upper() for token in re.split(r"[\s=(),]+", body))
        if not ended:
            raise ValueError("Subcircuit has no .ends declaration")
        unused = [pin for pin in required if pin not in tokens]
        return {"status": "FAIL" if unused else "PASS", "subcircuit": header[1],
                "declared_pins": pins, "unused_required_pins": unused,
                "scope": "lexical_interface_scan_not_electrical_validation"}
    raise ValueError("Requested subcircuit was not found")


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_contract(contract):
    for field in ("task_id", "configuration_id", "reference_id"):
        if not isinstance(contract.get(field), str) or not contract[field]:
            raise ValueError("Missing contract field: " + field)
    corners = contract.get("required_corners")
    if (not isinstance(corners, list) or not corners
            or any(not isinstance(c, str) or not c for c in corners)
            or len(set(corners)) != len(corners)):
        raise ValueError("Contract must declare distinct nonempty corners")
    specs = contract.get("specifications")
    if not isinstance(specs, list) or not specs:
        raise ValueError("Contract must declare circuit specifications")
    names = set()
    for spec in specs:
        name, unit = spec.get("name"), spec.get("unit")
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("Metric names must be distinct and nonempty")
        names.add(name)
        if not isinstance(unit, str) or not unit:
            raise ValueError("Metric must declare its unit")
        bounds = [spec[key] for key in ("min", "max") if key in spec]
        if not bounds or any(not _finite(v) for v in bounds):
            raise ValueError("Metric requires finite bounds")
        if "min" in spec and "max" in spec and spec["min"] > spec["max"]:
            raise ValueError("Reversed metric bounds")


def assess(contract, observation):
    """Return nested success tiers and explicit failure reasons.

    Missing, nonfinite, unconverged, and wrong-unit measurements fail S2.
    These records are evidence summaries, not proof of physical execution.
    """
    validate_contract(contract)
    reasons = []
    s0 = observation.get("executed") is True and observation.get("gds_emitted") is True
    if not s0:
        reasons.append("generation_or_gds_failed")
    binding = True
    for field in ("task_id", "configuration_id", "reference_id"):
        if observation.get(field) != contract[field]:
            binding = False
            reasons.append(field + "_mismatch")
    checks = observation.get("checks", {})
    correct = True
    for name in ("drc", "lvs", "devices", "ports", "intent"):
        if checks.get(name) is not True:
            correct = False
            reasons.append(name + "_not_passed")
    s1 = s0 and binding and correct
    pex = observation.get("pex", {})
    physical_rc = (pex.get("executed") is True
                   and pex.get("kind") == "physical_rc"
                   and pex.get("resistance_extracted") is True
                   and pex.get("capacitance_extracted") is True)
    if not physical_rc:
        reasons.append("physical_rc_extraction_not_established")
    circuit_pass = True
    for corner in contract["required_corners"]:
        record = observation.get("corners", {}).get(corner, {})
        if record.get("converged") is not True or record.get("operating_point_valid") is not True:
            circuit_pass = False
            reasons.append(corner + ":invalid_or_missing_simulation")
        for spec in contract["specifications"]:
            metric = record.get("metrics", {}).get(spec["name"], {})
            value = metric.get("value")
            if not _finite(value) or metric.get("unit") != spec["unit"]:
                circuit_pass = False
                reasons.append(corner + ":" + spec["name"] + ":missing_nonfinite_or_wrong_unit")
                continue
            if (("min" in spec and value < spec["min"])
                    or ("max" in spec and value > spec["max"])):
                circuit_pass = False
                reasons.append(corner + ":" + spec["name"] + ":specification_failed")
    return {"S0": s0, "S1": s1, "S2": s1 and physical_rc and circuit_pass,
            "reasons": reasons}


def paired_summary(baseline, candidate):
    """Summarize matched configuration IDs, preserving failed outcomes.

    The caller supplies the declared full domain, including timeouts/failures.
    Missing records are an error, so dropping failures cannot improve coverage.
    """
    if not baseline or set(baseline) != set(candidate):
        raise ValueError("Baseline and candidate must cover the same nonempty domain")
    for outcomes in (baseline, candidate):
        if any(type(value) is not bool for value in outcomes.values()):
            raise ValueError("Outcomes must be explicit booleans; encode failures as false")
    originally_passed = [key for key, passed in baseline.items() if passed]
    regressions = sum(not candidate[key] for key in originally_passed)
    return {"configurations": len(candidate),
            "coverage": sum(candidate.values()) / len(candidate),
            "baseline_passed": len(originally_passed),
            "regressions": regressions,
            "regression_rate": (regressions / len(originally_passed)
                                if originally_passed else None)}


def split_errors(registry):
    """Check the current registry for conflicting lineage and topology splits."""
    errors, assignments = [], {}
    holdouts = set(registry.get("topology_holdouts", []))
    for row in registry.get("lineages", []):
        lineage, split = row.get("lineage_id"), row.get("split")
        if not lineage or split not in ("train", "validation", "test"):
            errors.append("invalid_lineage_assignment")
            continue
        if lineage in assignments:
            errors.append("duplicate_or_conflicting_lineage:" + lineage)
        assignments[lineage] = split
        topology = row.get("topology_family")
        if not topology:
            errors.append("missing_topology:" + lineage)
        families=row.get("topology_families",[])
        if not isinstance(families,list) or any(not isinstance(x,str) or not x for x in families):
            errors.append("invalid_topology_families:"+lineage)
            families=[]
        if ({topology}|set(families)) & holdouts and split != "test":
            errors.append("topology_holdout_leakage:" + lineage)
    return errors
