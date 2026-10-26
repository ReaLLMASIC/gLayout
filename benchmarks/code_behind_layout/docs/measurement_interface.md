# Normalized measurement interface

`src/measurement.py` consumes summaries produced by a trusted physical evaluator and computes S0/S1/S2. It is a criterion checker, not a simulator, raw-log parser, artifact authenticator, or sandbox. The current repository has no physical evaluator. Logical test fixtures cannot become experiment records or training labels.

## Contract and observation fields

The contract declares `task_id`, `configuration_id`, `reference_id`, a nonempty `required_corners` list, and a nonempty `specifications` list. Every specification has a distinct `name`, an exact `unit`, and finite `min` and/or `max` bounds. Bounds are inclusive. `reference_id` must eventually be issued by the read-only configuration-to-netlist binding; matching a string alone cannot prove netlist identity.

An observation supplies matching identifiers, explicit boolean `executed` and `gds_emitted`, and boolean `checks` for `drc`, `lvs`, `devices`, `ports`, and `intent`. PEX includes `executed`, `kind` equal to `physical_rc`, `resistance_extracted`, and `capacitance_extracted`. Each required corner includes `converged`, `operating_point_valid`, and `metrics`; each metric includes a numeric `value` and its `unit`. The adapter must normalize units before assessment. Missing values, NaN, infinity, boolean values used as numbers, and wrong units cannot pass S2.

Invoke the implemented criterion checker with real adapter summaries once available:

```sh
python3 scripts/research.py assess --contract /absolute/path/contract.json --observation /absolute/path/observation.json
```

The command returns exit 0 for S2 and exit 2 for failure. This does not certify the origin of an arbitrary supplied JSON file.

## Required physical adapter work

Before formal use, implement and validate parsers against actual Magic, Netgen, extraction and simulator logs. Bind all artifacts to the same source revision and configuration, immutable reference netlist, PDK/deck and tool versions. Establish device types, sizes, terminal order, body ties, and operating-point validity using circuit-appropriate checks. Confirm extraction contains the needed R and C. Save raw logs and process exit codes, classify timeouts, and prohibit a model from editing the evaluator or hidden inputs.

The current tests exercise nested tiers, binding mismatches, omitted checks, capacitance-only or synthetic extraction, missing corners, convergence, units, nonfinite values, feasibility bounds, failed-outcome denominators, and obvious lineage/topology split conflicts. Source ancestry, near-duplicate detection, hidden-data permissions, cache identities, real tool parsers, and model isolation remain pending.

The observed OTA reference problem is also covered by a test and a CLI check:

```sh
python3 scripts/research.py audit-reference --netlist results/raw/ota_reference.spice --subcircuit opamp_twostage_traced --required-pins VIN VOUT
```

This actual reference returns exit 2 with VIN and VOUT unused. The lexical scan joins SPICE continuation lines and ignores full-line comments; it does not resolve arbitrary include files, behavioral expressions or aliases, and cannot establish electrical correctness. It supplies an early rejection for the concrete disconnected-interface defect found in the pilot.
