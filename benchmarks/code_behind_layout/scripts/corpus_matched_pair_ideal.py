"""One finite18-point ideal qualification; no layout, policy or train labels."""
import json
import argparse
import math
import os
from pathlib import Path
import sys


def qualified(result, contract):
    if set(result) != set(contract['required_corners']):
        return False
    for corner in result.values():
        if not corner['complete'] or not corner['operating_point_valid']:
            return False
        for spec in contract['specifications']:
            value = corner['metrics'].get(spec['name'])
            if (type(value) not in (int, float) or not math.isfinite(value) or
                ('min' in spec and value < spec['min']) or ('max' in spec and value > spec['max'])):
                return False
    return bool(contract['specifications'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--circuit', choices=['C02', 'C07'], help='Run this complete9point grid; the other grid has its own companion invocation')
    args = parser.parse_args()
    sys.path.insert(0, '/work')
    from src.corpus_component_benches import simulate
    inputs = Path(os.environ['PROBE_INPUT']); output = Path.cwd()
    declaration = json.loads((inputs / 'domains.json').read_text())
    if {domain['circuit_id'] for domain in declaration['domains']} != {'C02', 'C07'}:
        raise ValueError('Keep the exact two declared train families')
    domains = [domain for domain in declaration['domains'] if args.circuit is None or domain['circuit_id'] == args.circuit]
    for domain in domains:
        pairs = domain['matched_pairs']
        nf_grid = {tuple(point['parameters']['sizing'][pair[0]]['nf'] for pair in pairs) for point in domain['configurations']}
        if len(domain['configurations']) != 9 or nf_grid != {(a, b) for a in (4, 8, 12) for b in (4, 8, 12)}:
            raise ValueError('Do not filter the declared nine-point grid')
        for point in domain['configurations']:
            sizes = point['parameters']['sizing']
            if any(sizes[a] != sizes[b] or sizes[a]['w'] / sizes[a]['nf'] != .5 for a, b in pairs):
                raise ValueError('Every matched pair must retain identical per-finger dimensions')
    result = {'status': 'RUNNING_DECLARED_IDEAL_QUALIFICATION',
        'scope': 'development_train_domain_schematic_only_not_S0_S1_S2_or_training_data',
        'planned_points': 9 * len(domains), 'selected_circuit': args.circuit, 'points': [], 'model_calls': 0, 'physical_layout_calls': 0,
        'postlayout_or_existing_raw_labels_changed': False}
    def save():
        (output / 'matched_pair_ideal.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    save()
    for domain in domains:
        for point in domain['configurations']:
            work = output / point['configuration_id']; work.mkdir()
            parameters = point['parameters']; contract = point['contract']; controls = contract['numerical_controls']
            row = {'circuit_id': domain['circuit_id'], 'configuration_id': point['configuration_id'],
                   'parameters': parameters, 'reference_file': point['reference_file'], 'contract': contract}
            try:
                corners = simulate(work, domain['circuit_id'], parameters['sizing'], parameters['top_cell'],
                    inputs / point['reference_file'], parameters['circuit']['ports'], contract['analysis_contracts'],
                    controls['integration_method'], controls['independent_transient_inputs'])
                row.update(status='RETURNED_IDEAL_ANALYSES', corners=corners,
                           all_corner_ideal_specs_pass=qualified(corners, contract))
            except Exception as error:
                row.update(status='IDEAL_QUALIFICATION_UNESTABLISHED', error=type(error).__name__ + ': ' + str(error),
                           all_corner_ideal_specs_pass=False)
            result['points'].append(row); save()
    result.update(status='COMPLETED_DECLARED_IDEAL_ATTEMPTS',
        domains={domain['circuit_id']: {'declared_points': 9,
            'returned_points': sum(p['circuit_id'] == domain['circuit_id'] for p in result['points']),
            'qualified_points': sum(p['circuit_id'] == domain['circuit_id'] and p['all_corner_ideal_specs_pass'] for p in result['points'])}
            for domain in domains})
    save(); print(json.dumps({key: value for key, value in result.items() if key != 'points'}))


if __name__ == '__main__':
    main()
