"""Declare two complete train-only matched-pair nf grids; run no simulator.

Unlike the old unequal-finger mirror, each electrically matched device pair
retains identical per-finger dimensions. Different functional pairs may have
different nf. Both graphs remain the existing cropped compiler lineage.
"""
import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEVELS = (4, 8, 12)
PAIR_NAMES = {'C02': (('M1', 'M3'), ('M2', 'M4')),
              'C07': (('M1', 'M2'), ('M3', 'M4'))}


def reference(circuit, sizing, name):
    """An independent literal per-finger N; never call the layout/compiler."""
    lines = ['.subckt ' + name + ' ' + ' '.join(circuit['ports'])]
    for device in circuit['devices']:
        size = sizing[device['name']]
        model = {'nfet': 'sky130_fd_pr__nfet_01v8', 'pfet': 'sky130_fd_pr__pfet_01v8'}[device['kind']]
        for finger in range(size['nf']):
            lines.append('X' + device['name'] + '_f' + str(finger) + ' ' + ' '.join(device['nets']) +
                f" {model} w={size['w']/size['nf']:g} l={size['l']:g}")
    return '\n'.join(lines + ['.ends ' + name, ''])


def declare(cid, parent_registry):
    if cid not in PAIR_NAMES:
        raise ValueError('Only the two actual train graphs are declared')
    lineage = 'textbook_universal_compiler_cropped'
    if not any(row['lineage_id'] == lineage and row['split'] == 'train' for row in parent_registry['lineages']):
        raise ValueError('The source assignment is not train')
    anchor, = [row for row in parent_registry['configurations'] if row['domain_role'] == 'anchor']
    circuit = anchor['parameters']['circuit']
    if circuit['circuit_id'] != cid or {d['name'] for d in circuit['devices']} != {'M1', 'M2', 'M3', 'M4'}:
        raise ValueError('The actual frozen four-device graph changed')
    pairs = PAIR_NAMES[cid]
    for pair in pairs:
        devices = [next(d for d in circuit['devices'] if d['name'] == name) for name in pair]
        if devices[0]['kind'] != devices[1]['kind']:
            raise ValueError('An electrically matched pair changed device flavor')
    points = []
    for first in LEVELS:
        for second in LEVELS:
            identifier = cid.lower() + f'_matched_nf_{first}_{second}'
            sizing = copy.deepcopy(anchor['parameters']['sizing'])
            for pair, nf in zip(pairs, (first, second)):
                for name in pair:
                    sizing[name].update(w=.5 * nf, nf=nf)
            contract = copy.deepcopy(anchor['contract'])
            contract.update(task_id=cid.lower() + '_matched_pair_nf_v1', configuration_id=identifier,
                reference_id=identifier + '_literal_perfinger', scope='DRAFT_TRAIN_DOMAIN_IDEAL_QUALIFICATION_ONLY')
            points.append({'configuration_id': identifier, 'role': 'anchor' if (first, second) == (8, 8) else 'development',
                'parameters': {'circuit': circuit, 'sizing': sizing, 'top_cell': 'train_pair_nf_' + cid.lower()},
                'contract': contract, 'reference_file': cid.lower() + '/references/' + identifier + '.spice'})
    return {'circuit_id': cid, 'parent_lineage': lineage, 'independent_source_lineages_added': 0,
        'matched_pairs': [list(pair) for pair in pairs], 'levels': list(LEVELS), 'configurations': points,
        'whole_grid_preserved': True, 'width_semantics': 'w is total width; w/nf=.5um for every finger; matching partners always share nf and dimensions.',
        'specifications_bias_load_corners_numerical_controls': 'Copied unchanged from the actual frozen train family. No post-layout outcome used to select these points.',
        'qualification_status': 'NOT_RUN', 'formal_training_rows': 0}


def prepare(output):
    if output.exists():
        raise ValueError('Preserve the prior DRAFT; do not overwrite a declared grid')
    domains = []
    for cid, source in [('C02', 'c02_action_v1'), ('C07', 'c07_action_v1')]:
        registry = json.loads((ROOT / 'runtime/train_collections' / source / 'registry.json').read_text())
        domain = declare(cid, registry)
        domain['parent_frozen_registry'] = 'runtime/train_collections/' + source + '/registry.json'
        domains.append(domain)
    output.mkdir(parents=True)
    for domain in domains:
        for point in domain['configurations']:
            path = output / point['reference_file']; path.parent.mkdir(parents=True, exist_ok=True)
            parameters = point['parameters']
            path.write_text(reference(parameters['circuit'], parameters['sizing'], parameters['top_cell']))
    (output / 'domains.json').write_text(json.dumps({'status': 'DRAFT_TRAIN_ONLY_IDEAL_QUALIFICATION',
        'domains': domains, 'new_model_calls': 0, 'new_simulations': 0,
        'old_domain_or_frozen_collection_changed': False}, indent=2) + '\n')
    return {'status': 'DRAFT_PREPARED_NOT_SIMULATED', 'domains': len(domains), 'points': 18,
            'index': str(output / 'domains.json'), 'independent_source_lineages_added': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'configs/development/train_matched_pair_nf_v1')
    print(json.dumps(prepare(parser.parse_args().output), indent=2))
