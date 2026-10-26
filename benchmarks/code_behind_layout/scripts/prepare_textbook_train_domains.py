"""Declare textbook train domains (E4 stage 1): per-point references and applicable benches before any layout.

Runs on the trusted server where the pinned public compiler checkout exists. For each circuit the first-pass
textbook design point (textbook_sharing.nominal) is the anchor; eight development sizings are derived by fixed
finger, length and unit-width transforms that keep every finger count integral and every unit width inside the
sky130 model bins. Bench parameters (reference current, test voltage, replica bias generators, loads) and the
prospective application constraints are copied from the textbook benchmark's declared case and specification
floors into the contract; the bench renderer (src/corpus_textbook_benches.py) reads them from there.

    runtime/GLdev/bin/python scripts/prepare_textbook_train_domains.py --circuits C03 C13 C14 C04 C06 C12
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'vendor/textbook-sharing-readonly'
REVISION = '1f90e33913208e572744b7c5a144a7da8c073235'
CATEGORY = {'C01': 'mirror', 'C02': 'mirror', 'C03': 'mirror', 'C13': 'mirror', 'C14': 'mirror', 'C04': 'single', 'C06': 'single', 'C12': 'single', 'C07': 'diff_r', 'C15': 'single', 'C16': 'diff_r', 'C17': 'diff_r'}
MIN_UNIT_WIDTH = 0.42
MIN_LENGTH = 0.15
PRESIM_ROOT = Path('/srv/textbook_layout_sharing/runs/presim_cases')


def presim_sizing(cid, cfg):
    """Per-device sizing of a textbook benchmark size configuration, read from its presimulated per-finger schematic."""
    folder = PRESIM_ROOT / f'{cid}_sky130_{cfg}'
    record = json.loads((folder / f'presim_{cid}_sky130_{cfg}.json').read_text())
    if record.get('status') != 'passed': return None
    sizes = {}
    for line in (folder / f'{cid}_sky130_{cfg}_schematic.spice').read_text().splitlines():
        m = re.match(r'X(M\d+)_f(\d+)\s+\S+\s+\S+\s+\S+\s+\S+\s+(\S+)\s+w=([\d.]+)\s+l=([\d.]+)', line)
        if m:
            entry = sizes.setdefault(m.group(1), {'nf': 0, 'unit': float(m.group(4)), 'l': float(m.group(5))}); entry['nf'] += 1
    return {device: {'w': round(v['nf'] * v['unit'], 3), 'l': v['l'], 'nf': v['nf']} for device, v in sizes.items()}
# Declared deviations from the textbook first-pass point, decided from schematic controls (2026-10-23):
#  * C03: at 20 uA the Wilson input node (two stacked V_GS) sits at 1.90 V in the slow corner, above the 1.8 V supply;
#    the domain declares 5 uA (as the C02 cascode domain does) so that the input node keeps supply headroom.
#  * single-stage amplifiers: a 10 mV input step drives a 250 V/V stage into clipping, so the step test uses 1 mV.
REFERENCE_CURRENT_OVERRIDE = {'C03': 5e-6}
INPUT_STEP_V = 0.001
CANDIDATES = [('dev_nf_half', 'nf', .5), ('dev_nf_3quarters', 'nf', .75), ('dev_nf_1half', 'nf', 1.5), ('dev_nf_double', 'nf', 2),
              ('dev_len075', 'len', .75), ('dev_len150', 'len', 1.5), ('dev_unit075', 'unit', .75), ('dev_unit100', 'unit', 1.),
              ('dev_len200', 'len', 2), ('dev_nf_triple', 'nf', 3), ('dev_unit125', 'unit', 1.25), ('dev_len125', 'len', 1.25),
              ('dev_unit150', 'unit', 1.5), ('dev_nf_quadruple', 'nf', 4)]


def transform(sizing, kind, value):
    out = {}
    for device, size in sizing.items():
        if 'nf' not in size:
            out[device] = dict(size)  # passives keep the textbook geometry; only MOS devices follow the grid
            continue
        nf, unit, length = size['nf'], size['w'] / size['nf'], size['l']
        if kind == 'nf':
            scaled = nf * value
            if abs(scaled - round(scaled)) > 1e-9 or round(scaled) < 1: return None
            nf = int(round(scaled))
        elif kind == 'len': length = round(length * value, 3)
        else: unit = value
        if unit < MIN_UNIT_WIDTH - 1e-9 or length < MIN_LENGTH - 1e-9: return None
        out[device] = {'w': round(nf * unit, 3), 'l': length, 'nf': nf}
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--circuits', nargs='+', required=True, choices=sorted(CATEGORY))
    parser.add_argument('--sizing-cfgs', nargs='*', default=None, help='textbook size configurations (cfg1 cfg2 cfg3) to declare as separate domains instead of the nominal point')
    args = parser.parse_args()
    revision = subprocess.check_output(['git', '-C', str(PUBLIC), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != REVISION: raise ValueError('Public compiler revision differs')
    sys.path.insert(0, str(PUBLIC / 'benchmarks/textbook_sharing'))
    # textbook_sharing.nominal imports the passive-geometry helpers, which need glayout.sharing; the frozen cropped
    # compiler pack of the train lineage supplies it (read only, no layout is built here).
    sys.path.insert(1, str(ROOT / 'runtime/train_collections/c01_collection_v1/source_pack'))
    from textbook_sharing.circuits import CIRCUITS
    from textbook_sharing.netlist import Circuit, emit_subckt
    from textbook_sharing.nominal import nominal
    jobs = [(cid, None) for cid in args.circuits] if not args.sizing_cfgs else [(cid, cfg) for cid in args.circuits for cfg in args.sizing_cfgs]
    for cid, cfg in jobs:
        category = CATEGORY[cid]; domain = cid if cfg is None else f'{cid}_{cfg}'; dom = domain.lower()
        descriptor = CIRCUITS[cid].to_json()
        case = nominal(cid, 'sky130')
        if cfg is None: anchor = {device: ({'w': size['w'], 'l': size['l'], 'nf': size['nf']} if 'nf' in size else dict(size)) for device, size in case.sizing.items()}
        else:
            anchor = presim_sizing(cid, cfg)
            if anchor is None or set(anchor) != {d['name'] for d in descriptor['devices'] if d.get('kind') in ('nfet', 'pfet')}:
                print(json.dumps({'circuit': cid, 'cfg': cfg, 'skipped': 'presimulation not passed or device set differs'})); continue
        out = ROOT / 'configs/development' / (dom + '_family')
        if out.exists(): raise ValueError('Do not overwrite an existing declared domain: ' + str(out))
        (out / 'contracts').mkdir(parents=True); (out / 'references').mkdir()
        (out / 'circuit_input.json').write_text(json.dumps(descriptor, indent=2) + '\n')
        points = [('anchor', anchor)]
        for identifier, kind, value in CANDIDATES:
            sizing = transform(anchor, kind, value)
            if sizing is not None and sizing != anchor and all(sizing != s for _, s in points): points.append((identifier, sizing))
            if len(points) == 9: break
        if len(points) != 9: raise ValueError(cid + ': could not derive eight distinct admissible development sizings')
        ports = descriptor['ports']
        if category == 'mirror':
            vt = case.load['vout_nom']; tol = case.load['tol']
            inport = 'IIN1' if 'IIN1' in ports else 'IB1'
            extra = {port: case.bias[port]['i'] for port in ports if port in case.bias and port != inport and isinstance(case.bias[port], dict)}
            iref = REFERENCE_CURRENT_OVERRIDE.get(cid, case.bias['IREF'] if 'IREF' in case.bias else case.bias[inport]['i'])
            nop = {'supply_V': 1.8, 'temperature_C': 27, 'reference_current_A': iref, 'extra_current_sources_A': extra,
                   'output_test_V': round(vt, 4), 'tolerance': tol, 'output_transient_levels_V': [round(vt - .025, 4), round(vt + .025, 4)],
                   'output_DC_sweep_V': [0, 1.8, .05],
                   'load_definition': 'Output voltage source swept over the full supply range; output-port current is measured. The reference current enters the input current port (' + inport + ') from the 1.8 V supply; declared extra bias currents enter their ports from the same supply.',
                   'power_definition': 'DUT has no VDD pin. Report input-port and output-port dissipation and the external reference-supply work separately.',
                   'textbook_case': {'load': case.load, 'bias': {k: v for k, v in case.bias.items()}, 'rule': 'textbook_sharing.nominal first-pass point'},
                   'declared_deviation': ('reference current %g A instead of the first-pass %g A: supply headroom of the input node at the slow corner (schematic control)' % (iref, case.bias['IREF'])) if cid in REFERENCE_CURRENT_OVERRIDE else None}
            constraints = {'nominal_current_relative_error_max': case.specs['err']['abs_max'], 'compliance_low_V_max': round(case.specs['vmin']['max'], 4)}
            analysis_contracts = {'op': {'kind': 'op', 'columns': 4, 'expected_rows': 1},
                                  'ac': {'kind': 'ac', 'columns': 3, 'start': 10, 'end': 1e9, 'points': 161, 'scale': 'log'},
                                  'tran': {'kind': 'transient', 'columns': 3, 'start': 0, 'end': 4e-6, 'required_windows': [[1.8e-6, 1.99e-6], [2.8e-6, 2.99e-6]]},
                                  'dc': {'kind': 'dc', 'columns': 3, 'start': 0, 'end': 1.8, 'points': 37, 'scale': 'linear'}}
            objective_metric = 'area'
        elif category == 'diff_r':
            replicas = {port: {'replica': spec['replica'], 'current': spec['current'], 'kind': spec.get('kind', 'diode')}
                        for port, spec in case.bias.items() if port in ports and isinstance(spec, dict) and 'replica' in spec}
            nop = {'supply_V': 1.8, 'temperature_C': 27, 'load_capacitance_F': case.load['CL'], 'input_common_mode_V': case.load['vcm'],
                   'differential_step_V': .01, 'replica_bias': replicas,
                   'tail_current_A': case.bias['IB1']['i'] if 'IB1' in case.bias else None,
                   'drive_definition': 'Both inputs are driven as VCM +/- VD/2 through ideal controlled sources (as in the C07 bench); each output carries the declared load capacitance to ground; the differential output is measured.',
                   'power_definition': 'Main 1.8 V supply current of the DUT; replica bias generators are fed from a separate 1.8 V bias supply; the ideal tail sink is external.',
                   'textbook_case': {'load': case.load, 'bias': case.bias, 'rule': 'textbook_sharing.nominal first-pass point'}}
            constraints = {'gain_lf_dB_min': case.specs['gain_lf']['min'], 'f3db_Hz_min': case.specs['f3db']['min']}
            analysis_contracts = {'op': {'kind': 'op', 'columns': 4, 'expected_rows': 1},
                                  'ac': {'kind': 'ac', 'columns': 3, 'start': 10, 'end': 1e9, 'points': 161, 'scale': 'log'},
                                  'tran': {'kind': 'transient', 'columns': 3, 'start': 0, 'end': 4e-6, 'required_windows': [[1.8e-6, 1.99e-6], [2.8e-6, 2.99e-6]]},
                                  'dc': {'kind': 'dc', 'columns': 4, 'start': -.1, 'end': .1, 'points': 41, 'scale': 'linear'}}
            objective_metric = 'area'
        else:
            replicas = {port: {'replica': spec['replica'], 'current': spec['current'], 'kind': spec.get('kind', 'diode')}
                        for port, spec in case.bias.items() if port in ports and isinstance(spec, dict) and 'replica' in spec}
            nop = {'supply_V': 1.8, 'temperature_C': 27, 'load_capacitance_F': case.load['CL'], 'input_step_V': INPUT_STEP_V, 'replica_bias': replicas,
                   'dc_servo': 'Disclosed DC servo of the textbook benchmark: a 1e6 H inductor from VOUT1 to VIN1 and a 1e6 F capacitor from the AC/step source to VIN1 fix V_in,dc = V_out,dc and leave AC and step behaviour untouched; the DC transfer sweep drives VIN1 directly.',
                   'power_definition': 'Main 1.8 V supply current of the DUT; replica bias generators are fed from a separate 1.8 V bias supply.',
                   'textbook_case': {'load': case.load, 'bias': case.bias, 'rule': 'textbook_sharing.nominal first-pass point'}}
            constraints = {'gain_lf_dB_min': case.specs['gain_lf']['min'], 'f3db_Hz_min': case.specs['f3db']['min']}
            analysis_contracts = {'op': {'kind': 'op', 'columns': 4, 'expected_rows': 1},
                                  'ac': {'kind': 'ac', 'columns': 3, 'start': 10, 'end': 1e9, 'points': 161, 'scale': 'log'},
                                  'tran': {'kind': 'transient', 'columns': 3, 'start': 0, 'end': 4e-6, 'required_windows': [[1.8e-6, 1.99e-6], [2.8e-6, 2.99e-6]]},
                                  'dc': {'kind': 'dc', 'columns': 3, 'start': 0, 'end': 1.8, 'points': 37, 'scale': 'linear'}}
            objective_metric = 'area'
        rows = []
        for identifier, sizing in points:
            reference = out / 'references' / (identifier + '.spice')
            reference.write_text(emit_subckt('sky130', Circuit.from_json(descriptor), sizing, 'corpus_' + cid.lower(), per_finger=True, lvs=True))
            contract = {'task_id': 'development_train_domain_' + dom, 'configuration_id': identifier,
                        'reference_id': dom + '_' + identifier + '_perfinger', 'required_corners': ['tt', 'ss', 'ff'],
                        'scope': 'DRAFT_DEVELOPMENT_QUALIFICATION_NOT_FORMAL', 'bench_category': category,
                        'objective': {'id': dom + '_area_min', 'metric': objective_metric, 'unit': 'um2', 'direction': 'min', 'corner_aggregation': 'worst'},
                        'specifications': [],
                        'pending_before_freeze': ['Actual schematic and full physical domain qualification; prospective application constraints are not formal labels.'],
                        'prospective_application_constraints': constraints, 'nominal_operating_point': nop, 'analysis_contracts': analysis_contracts}
            file = out / 'contracts' / (identifier + '.json'); file.write_text(json.dumps(contract, indent=2) + '\n')
            rows.append({'configuration_id': identifier, 'role': 'anchor' if identifier == 'anchor' else 'development',
                         'parameters': {'sizing': sizing}, 'reference_file': str(reference.relative_to(ROOT)), 'contract_file': str(file.relative_to(ROOT))})
        table = {'scope': 'DRAFT_DEVELOPMENT_QUALIFICATION_ONLY', 'source_revision': revision, 'parent_lineage': 'textbook_universal_compiler_cropped',
                 'circuit_id': cid, 'domain_id': domain, 'textbook_sizing_source': ('textbook_sharing.nominal first-pass point' if cfg is None else f'presimulated size configuration {cfg} of the textbook benchmark'),
                 'circuit_name': descriptor.get('name'), 'bench_category': category,
                 'circuit_input_file': str((out / 'circuit_input.json').relative_to(ROOT)), 'configurations': rows,
                 'textbook_specification_floors': case.specs, 'declared_by': 'scripts/prepare_textbook_train_domains.py',
                 'ancestry': 'Same cropped universal compiler source; no new source lineage. Geometry and per-finger references are fixed before any layout.'}
        (out / 'configurations.json').write_text(json.dumps(table, indent=2) + '\n')
        print(json.dumps({'circuit': cid, 'domain': domain, 'category': category, 'table': str(out / 'configurations.json'), 'points': [p for p, _ in points], 'physical_runs': 0, 'model_requests': 0}))


if __name__ == '__main__':
    main()
