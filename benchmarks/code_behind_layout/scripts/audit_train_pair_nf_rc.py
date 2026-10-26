"""Read-only full-RC device/port audit for the new matched-pair train domains.

Wire contraction is an audit view only. Every electrical simulation uses the
original unsimplified full-RC netlist. No raw score, label or source is changed.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.device_intent import compare_device_intent
from src.report_parsers import spice_literal


def contracted_devices(text, top, ports):
    # Adapted from the independently tested ratio-source wire-contraction view;
    # this explicit domain contains both literal1v8 nMOS and pMOS devices.
    lines = []
    for raw in text.splitlines():
        row = raw.strip()
        if not row or row.startswith(('*', ';')):
            continue
        if row.startswith('+'):
            if not lines:
                raise ValueError('Continuation has no preceding physical element')
            lines[-1] += ' ' + row[1:]
        else:
            lines.append(row)
    parent = {}
    def find(node):
        node = node.upper(); parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]; node = parent[node]
        return node
    devices = []; actual_ports = None; tops = 0
    for row in lines:
        fields = row.split(); kind = fields[0].upper()
        if kind == '.SUBCKT':
            tops += 1
            if fields[1].upper() != top.upper():
                raise ValueError('Unexpected extracted RC hierarchy')
            actual_ports = [name.upper() for name in fields[2:]]
        elif kind.startswith('R'):
            if len(fields) != 4 or spice_literal(fields[3]) <= 0:
                raise ValueError('Physical wire resistors must be positive literal values')
            parent[find(fields[2])] = find(fields[1])
        elif kind.startswith(('X', 'M')):
            index = next((i for i, value in enumerate(fields) if value.lower().startswith('sky130_fd_pr__')), None)
            if index != 5 or fields[index].lower() not in ['sky130_fd_pr__nfet_01v8', 'sky130_fd_pr__pfet_01v8']:
                raise ValueError('Expected one flat four-terminal literal1v8 MOS device')
            devices.append(fields)
            for node in fields[1:5]:
                find(node)
        elif not kind.startswith(('.', 'C')):
            raise ValueError('Unexpected extracted physical element: ' + fields[0])
    expected = [name.upper() for name in ports]
    if tops != 1 or actual_ports is None or sorted(actual_ports) != sorted(expected):
        raise ValueError('The full-RC top or named port set differs from independent N')
    if actual_ports != expected:
        raise ValueError('Actual RC port order differs from the unchanged bench XDUT order')
    labels = {}
    for port in expected:
        root = find(port)
        if root in labels:
            raise ValueError('Wire resistance connects distinct independent reference ports')
        labels[root] = port
    names = {root: labels.get(root, 'wire_net_' + str(i))
             for i, root in enumerate(sorted({find(node) for node in parent}))}
    view = ['.subckt rc_device_intent ' + ' '.join(expected)]
    for fields in devices:
        view.append(' '.join([fields[0], *(names[find(node)] for node in fields[1:5]), *fields[5:]]))
    return '\n'.join(view + ['.ends rc_device_intent', ''])


def audit(qualification):
    qualification = Path(qualification).resolve()
    state = json.loads((qualification / 'state.json').read_text())
    plan = json.loads((Path(state['preparation']) / 'plan.json').read_text())
    points = {p['configuration_id']: p for p in plan['configurations']}
    records = []
    for row in state['records']:
        if not row.get('checked', {}).get('S1'):
            records.append({'configuration_id': row['configuration_id'], 'status': 'NOT_ASSESSED_NO_S1'})
            continue
        point = points[row['configuration_id']]; run = Path(row['result']['run_directory'])
        try:
            validation = json.loads((run / 'evidence/validation.json').read_text())
            pex = validation['artifacts']['pex']
            if validation['contract'] != point['contract']:
                raise ValueError('Raw evidence contract differs from the fixed point')
            view = contracted_devices((run / 'evidence' / pex['netlist']).read_text(), pex['top_cell'], pex['ports'])
            if pex['ports'] != point['parameters']['circuit']['ports']:
                raise ValueError('Declared PEX port order differs from the original circuit bench')
            gold = run / 'trusted/references' / (point['configuration_id'] + '.spice')
            result = compare_device_intent(view, gold.read_text())
            records.append({'configuration_id': row['configuration_id'], 'run_directory': str(run),
                'status': 'RC_DEVICE_GRAPH_MATCH' if result['is_clean'] else 'QUARANTINED_MISMATCH', 'audit': result})
        except Exception as error:
            records.append({'configuration_id': row['configuration_id'], 'run_directory': str(run),
                'status': 'QUARANTINED_UNKNOWN', 'error': type(error).__name__ + ': ' + str(error)})
    return {'status': 'READONLY_FULL_RC_INTENT_AUDIT', 'observed_at_utc': datetime.now(timezone.utc).isoformat(),
        'qualification': str(qualification), 'qualification_status': state['status'], 'declared_points': 9,
        'records': records, 'matching_points': sum(r['status'] == 'RC_DEVICE_GRAPH_MATCH' for r in records),
        'quarantined_points': sum(r['status'].startswith('QUARANTINED') for r in records),
        'model_calls': 0, 'new_physical_calls': 0, 'raw_scores_or_labels_modified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qualification', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.qualification), indent=2), flush=True)
