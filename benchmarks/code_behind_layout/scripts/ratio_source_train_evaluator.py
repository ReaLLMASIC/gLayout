"""Trusted ratio-source evaluator: GDS only, immutable N and original bench."""
import argparse
import json
from pathlib import Path
import subprocess


def evaluate(gds, output, trusted, configuration):
    import gdstk
    from src.physical_drc import check_gds
    from src.report_parsers import netgen_lvs_report, rc_netlist_inventory
    from src.device_intent import compare_device_intent
    from src.measurement import assess
    from physical_helpers import contracted_rc_devices, physical_wrapper, completed_corner_summary
    from original_bench import simulate

    out, trusted = Path(output), Path(trusted)
    identifier = configuration['top_cell']
    point = json.loads((trusted / 'points' / (identifier + '.json')).read_text())
    if configuration != point['parameters']:
        raise ValueError('The candidate configuration differs from the frozen independent point')
    contract = point['contract']; top = configuration['top_cell']; ports = contract['ports']
    reference_name = 'references/' + identifier + '.spice'
    reference = trusted / reference_name
    observation = {key: contract[key] for key in ('task_id', 'configuration_id', 'reference_id')}
    observation.update(executed=True, gds_emitted=True, checks={}, corners={})
    artifacts = {'spice': {}}; complete = rejected = analysis_complete = False

    def save():
        result = {'contract': contract, 'observation': observation, 'artifacts': artifacts,
            'assessment': assess(contract, observation), 'point_evaluation_complete': complete or rejected,
            'complete_domain_evaluation': False, 'analysis_complete': analysis_complete,
            'execution_integrity': 'valid' if complete or rejected else 'incomplete',
            'failure_class': None if complete and assess(contract, observation)['S2'] else
                'candidate' if complete or rejected else 'unknown',
            'scope': 'formal_train_ratio_GDS_only_immutable_reference_original_bench'}
        (out / 'validation.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
        return result

    def magic(lines, stem):
        source = '\n'.join(lines + ['puts stdout EXTRACTION_COMPLETE', 'quit -noprompt', ''])
        (out / (stem + '.tcl')).write_text(source)
        with (out / (stem + '.log')).open('w') as log:
            run = subprocess.run(['magic', '-rcfile', '/foss/pdks/sky130A/libs.tech/magic/sky130A.magicrc',
                '-noconsole', '-dnull'], input=source, text=True, cwd=out, stdout=log,
                stderr=subprocess.STDOUT, timeout=180)
        if run.returncode or '\nEXTRACTION_COMPLETE\n' not in (out / (stem + '.log')).read_text():
            raise RuntimeError('Magic did not complete the declared extraction')

    try:
        library = gdstk.read_gds(gds); matches = [cell for cell in library.cells if cell.name == top]
        if len(matches) != 1 or matches[0].bounding_box() is None:
            rejected = True
            observation['interface_error'] = 'The contract-named physical top must exist exactly once and contain geometry'
            return save()
        bbox = matches[0].bounding_box()
        area = float((bbox[1][0] - bbox[0][0]) * (bbox[1][1] - bbox[0][1]) * (library.unit / 1e-6)**2)
        drc = check_gds(gds, out / 'drc', timeout=180, top_name=top)
        (out / 'drc/metadata.json').write_text(json.dumps(drc, indent=2) + '\n')
        artifacts['drc'] = {'report': 'drc/direct_drc.rpt', 'metadata': 'drc/metadata.json'}
        observation['checks']['drc'] = drc['is_clean']; save()
        if not drc['completed']:
            raise RuntimeError('Full-rule actual-top DRC did not complete')
        if not drc['is_clean']:
            rejected = True; return save()
        magic(['drc off', 'gds read {' + str(gds) + '}', 'load ' + top, 'select top cell',
            'flatten ' + top + '_lvs', 'load ' + top + '_lvs', 'select top cell',
            'extract all', 'ext2spice lvs', 'ext2spice -o extracted_lvs.spice'], 'lvs_extract')
        with (out / 'netgen.log').open('w') as log:
            run = subprocess.run(['netgen', '-batch', 'lvs', str(out / 'extracted_lvs.spice') + ' ' + top + '_lvs',
                str(reference) + ' ' + top, '/foss/pdks/sky130A/libs.tech/netgen/sky130A_setup.tcl', str(out / 'lvs.rpt')],
                stdout=log, stderr=subprocess.STDOUT, timeout=180)
        if run.returncode or not (out / 'lvs.rpt').is_file():
            raise RuntimeError('Independent Netgen LVS did not complete')
        lvs = netgen_lvs_report((out / 'lvs.rpt').read_text())
        (out / reference_name).parent.mkdir(parents=True, exist_ok=True)
        (out / reference_name).write_bytes(reference.read_bytes())
        artifacts['lvs'] = {'report': 'lvs.rpt', 'netlist': 'extracted_lvs.spice', 'reference': reference_name}
        if not lvs['is_clean']:
            observation['checks'].update(lvs=False, devices=False, ports=False, intent=False)
            rejected = True; return save()
        intent = compare_device_intent((out / 'extracted_lvs.spice').read_text(), reference.read_text())
        (out / 'device_intent.json').write_text(json.dumps(intent, indent=2) + '\n')
        artifacts['lvs']['device_intent'] = 'device_intent.json'
        observation['checks'].update(lvs=True, devices=intent['per_device_dimensions_match'],
            ports=intent['ports_match'], intent=intent['is_clean'])
        if not intent['is_clean']:
            rejected = True; return save()
        cell = top + '_rc'; pex = out / (top + '_pex.spice')
        magic(['drc off', 'gds read {' + str(gds) + '}', 'load ' + top, 'select top cell',
            'flatten ' + cell, 'load ' + cell, 'select top cell', 'extract do local', 'extract all',
            'feedback save extraction_feedback.tcl', 'ext2sim labels on', 'ext2sim', 'extresist simplify off',
            'extresist all', 'ext2spice lvs', 'ext2spice cthresh 0', 'ext2spice extresist on',
            'ext2spice -o ' + pex.name], 'rc_extract')
        inventory = rc_netlist_inventory(pex.read_text(), cell, ports)
        (out / 'rc_inventory.json').write_text(json.dumps(inventory, indent=2) + '\n')
        artifacts['pex'] = {'netlist': pex.name, 'top_cell': cell, 'ports': inventory['ports']}
        real = inventory['has_real_RC']
        observation['pex'] = {'executed': True, 'kind': 'physical_rc',
            'resistance_extracted': real, 'capacitance_extracted': real}
        save()
        if not real:
            raise RuntimeError('Positive unsimplified RC or the exact named interface was not established')
        view = contracted_rc_devices(pex.read_text(), cell, ports)
        (out / 'rc_contracted_device_intent.spice').write_text(view)
        rc_intent = compare_device_intent(view, reference.read_text())
        (out / 'rc_device_intent.json').write_text(json.dumps(rc_intent, indent=2) + '\n')
        if not rc_intent['is_clean']:
            raise RuntimeError('Full RC omitted or changed an intended device, body, terminal or required net')
        wrapper = out / 'physical_bench_wrapper.spice'
        wrapper.write_text(physical_wrapper(pex, cell, inventory['ports'], top, ports))
        corners = simulate(point, wrapper, out / 'post_rc_measurements')
        (out / 'original_bench_measurements.json').write_text(json.dumps(corners, indent=2, allow_nan=False) + '\n')
        summary = completed_corner_summary(corners, contract['required_corners'])
        for corner, row in corners.items():
            metrics = {'area': {'value': area, 'unit': 'um2'}}
            if row['complete']:
                for spec in contract['specifications']:
                    metrics[spec['name']] = {'value': row['metrics'][spec['name']], 'unit': spec['unit']}
            observation['corners'][corner] = {'converged': row['complete'],
                'operating_point_valid': row['operating_point_valid'], 'metrics': metrics}
            prefix = 'post_rc_measurements/' + corner + '/'
            artifacts['spice'][corner] = {'analyses': {name: {'data': prefix + name + '.dat',
                'log': prefix + ('ac1' if name == 'op' else name) + '.log', 'returncode': 0}
                for name in row['analyses']}}
        complete = analysis_complete = summary['analysis_complete']
        return save()
    except Exception as error:
        observation['infrastructure_error'] = type(error).__name__ + ': ' + str(error)
        return save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gds', required=True); parser.add_argument('--output', required=True)
    parser.add_argument('--fidelity', required=True)
    args = parser.parse_args()
    if args.fidelity != 'pex_spice':
        raise ValueError('This fixed baseline consumer requires actual full RC and all original three-corner analyses')
    result = evaluate(Path(args.gds), Path(args.output), Path('/trusted'), json.loads(Path('/configuration.json').read_text()))
    print(json.dumps(result, allow_nan=False), flush=True)
    raise SystemExit(0 if result['point_evaluation_complete'] and result['assessment']['S2'] else 2)
