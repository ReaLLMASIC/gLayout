"""One fixed train-source development control; no candidate source or domain edits."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def physical_wrapper(pex, cell, actual_ports, top, expected_ports):
    """Only permute the extracted named ports into the unchanged original bench."""
    expected = [p.upper() for p in expected_ports]
    if len(actual_ports) != len(expected) or sorted(p.upper() for p in actual_ports) != sorted(expected):
        raise ValueError('Full RC does not expose exactly the four independent reference ports')
    if not all(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', p) for p in [cell, top, *expected]):
        raise ValueError('Unexpected ratio-source interface identifier')
    return '\n'.join(['* Original bench wrapper: named port permutation only',
        '.include "' + str(pex) + '"', '.subckt ' + top + ' ' + ' '.join(expected),
        'Xphysical ' + ' '.join(p.upper() for p in actual_ports) + ' ' + cell,
        '.ends ' + top, ''])


def contracted_rc_devices(text, top, expected_ports):
    """All MOS retained; collapse physical wire R only for a second graph check.

    The unsimplified RC text is used for every electrical simulation. This
    separate view proves that extraction retained every intended device, body,
    terminal and named net; positive total R/C alone cannot establish that.
    """
    from src.report_parsers import spice_literal
    parent = {}

    def find(node):
        node = node.upper()
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left, right):
        parent[find(right)] = find(left)

    lines = []
    for raw in text.splitlines():
        row = raw.strip()
        if not row or row.startswith(('*', ';')):
            continue
        if row.startswith('+'):
            if not lines:
                raise ValueError('RC continuation lacks a preceding line')
            lines[-1] += ' ' + row[1:]
        else:
            lines.append(row)
    devices, ports, subcircuits = [], None, 0
    for row in lines:
        fields = row.split(); kind = fields[0].upper()
        if kind == '.SUBCKT':
            subcircuits += 1
            if fields[1].upper() != top.upper():
                raise ValueError('Expected one flat extracted RC subcircuit')
            ports = [p.upper() for p in fields[2:]]
        elif kind.startswith('R'):
            if len(fields) != 4 or spice_literal(fields[3]) < 0:
                raise ValueError('Unsupported or negative physical wire resistor')
            union(fields[1], fields[2])
        elif kind.startswith(('X', 'M')):
            index = next((i for i, value in enumerate(fields) if value.lower().startswith('sky130_fd_pr__')), None)
            if index != 5 or 'nfet_01v8' not in fields[index].lower():
                raise ValueError('Ratio source RC must retain literal four-terminal SKY130 nMOS devices')
            devices.append(fields)
            for node in fields[1:5]:
                find(node)
        elif not kind.startswith(('.', 'C')):
            raise ValueError('Undeclared full-RC element: ' + fields[0])
    expected = [p.upper() for p in expected_ports]
    if subcircuits != 1 or ports is None or sorted(ports) != sorted(expected):
        raise ValueError('RC named ports or flat hierarchy differ from independent intent')
    labels = {}
    for port in expected:
        root = find(port)
        if root in labels:
            raise ValueError('Physical resistors short two distinct named reference ports')
        labels[root] = port
    names = {root: labels.get(root, 'rcnet_' + str(index))
             for index, root in enumerate(sorted({find(node) for node in parent}))}
    result = ['.subckt rc_device_intent ' + ' '.join(expected)]
    for fields in devices:
        result.append(' '.join([fields[0], *(names[find(node)] for node in fields[1:5]), *fields[5:]]))
    return '\n'.join(result + ['.ends rc_device_intent', ''])


def completed_corner_summary(corners, required_corners):
    """An actual performance rejection is known only after all analyses finish."""
    complete = (set(corners) == set(required_corners) and
                all(corners[name].get('complete') is True for name in required_corners))
    return {'analysis_complete': complete,
            'S2': complete and all(corners[name].get('ideal_application_constraints_pass') is True
                                   for name in required_corners),
            'status': 'COMPLETE' if complete else 'UNESTABLISHED_UNKNOWN'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configuration-id', required=True)
    args = parser.parse_args()
    prepared = Path(os.environ['PROBE_INPUT'])
    sys.path.insert(0, str(prepared / 'source_snapshot'))
    from src.train_generators.ratio_source import write_gds
    from src.train_generators.ratio_source_intent import point, reference_spice
    from src.train_generators.ratio_source_bench import simulate
    from src.physical_drc import check_gds
    from src.report_parsers import netgen_lvs_report, rc_netlist_inventory
    from src.device_intent import compare_device_intent
    manifest = read(prepared / 'physical_plan.json')
    row, = [r for r in manifest['configurations'] if r['configuration_id'] == args.configuration_id]
    if row != point(row['parameters']['K'], row['parameters']['R']):
        raise ValueError('The original fixed configuration or specification changed')
    out = Path.cwd(); top = row['parameters']['top_cell']; ports = row['contract']['ports']
    reference = out / 'independent_N.spice'
    reference.write_bytes((prepared / row['reference_file']).read_bytes())
    if reference.read_text() != reference_spice(row):
        raise ValueError('Independent literal per-finger N(z) changed')
    shutil.copytree(prepared / 'source_snapshot', out / 'source_snapshot')
    save(out / 'configuration.json', row)
    record = {'scope': 'DEVELOPMENT_TRAIN_SOURCE_FIXED_NINE_DOMAIN_NOT_TRAINING_EXAMPLE',
        'configuration_id': row['configuration_id'], 'status': 'RUNNING',
        'S0': False, 'S1': False, 'S2': False, 'analysis_complete': False,
        'model_calls': 0, 'source_or_domain_edits': False,
        'started_at_utc': datetime.now(timezone.utc).isoformat()}

    def progress():
        save(out / 'physical_qualification.json', record)

    def magic(lines, stem):
        tcl = '\n'.join(lines + ['puts stdout EXTRACTION_COMPLETE', 'quit -noprompt', ''])
        (out / (stem + '.tcl')).write_text(tcl)
        with (out / (stem + '.log')).open('w') as log:
            ran = subprocess.run(['magic', '-rcfile', '/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc',
                '-noconsole', '-dnull'], input=tcl, text=True, cwd=out,
                stdout=log, stderr=subprocess.STDOUT, timeout=180)
        if ran.returncode or '\nEXTRACTION_COMPLETE\n' not in (out / (stem + '.log')).read_text():
            raise RuntimeError('Magic did not complete its declared extraction')

    progress()
    try:
        gds = write_gds(row['parameters'], out)
        if not Path(gds).is_file():
            raise RuntimeError('Source did not emit its declared GDS')
        record.update(S0=True, gds=str(gds)); progress()
        drc = check_gds(gds, out / 'drc_full', timeout=180, top_name=top)
        record['drc'] = drc; progress()
        if not drc['completed']:
            raise RuntimeError('Full-rule actual-top DRC was incomplete')
        if not drc['is_clean']:
            record.update(status='COMPLETE_PHYSICAL_REJECTION', failure_stage='full_rule_DRC')
            return record
        magic(['drc off', 'gds read {' + str(gds) + '}', 'load ' + top, 'select top cell',
            'flatten ' + top + '_lvs', 'load ' + top + '_lvs', 'select top cell',
            'extract all', 'ext2spice lvs', 'ext2spice -o extracted_lvs.spice'], 'lvs_extract')
        with (out / 'netgen.log').open('w') as log:
            ran = subprocess.run(['netgen', '-batch', 'lvs', str(out / 'extracted_lvs.spice') + ' ' + top + '_lvs',
                str(reference) + ' ' + top, '/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl', str(out / 'lvs.rpt')],
                stdout=log, stderr=subprocess.STDOUT, timeout=180)
        if ran.returncode or not (out / 'lvs.rpt').exists():
            raise RuntimeError('Independent Netgen LVS did not complete')
        record['lvs'] = netgen_lvs_report((out / 'lvs.rpt').read_text())
        if not record['lvs']['is_clean']:
            record.update(status='COMPLETE_PHYSICAL_REJECTION', failure_stage='independent_LVS')
            return record
        intent = compare_device_intent((out / 'extracted_lvs.spice').read_text(), reference.read_text())
        save(out / 'device_intent.json', intent); record['device_intent'] = intent
        if not intent['is_clean']:
            record.update(status='COMPLETE_PHYSICAL_REJECTION', failure_stage='independent_perfinger_terminal_graph')
            return record
        record['S1'] = True; progress()
        cell = top + '_rc'; pex = out / (top + '_pex.spice')
        magic(['drc off', 'gds read {' + str(gds) + '}', 'load ' + top, 'select top cell',
            'flatten ' + cell, 'load ' + cell, 'select top cell', 'extract do local', 'extract all',
            'feedback save extraction_feedback.tcl', 'ext2sim labels on', 'ext2sim', 'extresist simplify off',
            'extresist all', 'ext2spice lvs', 'ext2spice cthresh 0', 'ext2spice extresist on',
            'ext2spice -o ' + pex.name], 'rc_extract')
        inventory = rc_netlist_inventory(pex.read_text(), cell, ports)
        save(out / 'rc_inventory.json', inventory); record['full_RC'] = inventory
        if not inventory['has_real_RC']:
            raise RuntimeError('Positive unsimplified RC or exact named interface was not established')
        view = contracted_rc_devices(pex.read_text(), cell, ports)
        (out / 'rc_contracted_device_intent.spice').write_text(view)
        rc_intent = compare_device_intent(view, reference.read_text())
        save(out / 'rc_device_intent.json', rc_intent); record['full_RC_device_intent'] = rc_intent
        if not rc_intent['is_clean']:
            raise RuntimeError('Full RC omitted or changed intended devices, bodies, terminals or required nets')
        wrapper = out / 'physical_bench_wrapper.spice'
        wrapper.write_text(physical_wrapper(pex, cell, inventory['ports'], top, ports))
        record['bench_transport'] = {'kind': 'wire_only_named_port_permutation',
            'original_ports': ports, 'actual_RC_ports': inventory['ports'],
            'original_bench_stimuli_solver_formulas_and_limits_unchanged': True,
            'independent_device_graph_checked_before_and_after_RC': True}
        corners = simulate(row, wrapper, out / 'post_rc_measurements')
        record.update(corners=corners, actual_SPICE_calls=18,
            **completed_corner_summary(corners, row['contract']['required_corners']))
        if not record['analysis_complete']:
            record['error'] = 'Required original corner analyses incomplete; no performance counterexample established'
    except Exception as error:
        record.update(status='UNESTABLISHED_UNKNOWN', error=type(error).__name__ + ': ' + str(error))
    finally:
        record['ended_at_utc'] = datetime.now(timezone.utc).isoformat(); progress()
    return record


if __name__ == '__main__':
    result = main()
    print(json.dumps({k: v for k, v in result.items() if k not in ('corners', 'device_intent', 'full_RC_device_intent')}, allow_nan=False))
    raise SystemExit(0 if result['status'] in ('COMPLETE', 'COMPLETE_PHYSICAL_REJECTION') else 2)
