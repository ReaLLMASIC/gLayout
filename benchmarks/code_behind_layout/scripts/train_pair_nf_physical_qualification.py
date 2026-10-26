"""Fixed fresh nine-point qualification for each already qualified train NF grid.

This creates development evidence, never formal training labels. No old ideal or
physical job is retried, and an unknown point stops the remaining dispatches.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_train_pair_nf_domains import declare, reference
from scripts.corpus_matched_pair_ideal import qualified

GATE_FILES = ['candidate_executor.py', 'domain_runner.py', 'training.py',
              'model_adapter.py', 'measurement.py', 'report_parsers.py',
              'device_intent.py', 'spice_validation.py']
DECLARATION = Path('configs/development/train_matched_pair_nf_v1')


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def bind_ideal(domain, result):
    rows = result.get('points', [])
    if (result.get('status') != 'COMPLETED_DECLARED_IDEAL_ATTEMPTS'
            or result.get('selected_circuit') != domain['circuit_id']
            or len(rows) != 9 or result.get('physical_layout_calls') != 0
            or result.get('model_calls') != 0):
        raise ValueError('The entire declared nine-point schematic control must have completed')
    for point, row in zip(domain['configurations'], rows):
        if (any(row.get(key) != point[key] for key in
                ['configuration_id', 'parameters', 'reference_file', 'contract'])
                or row.get('status') != 'RETURNED_IDEAL_ANALYSES'
                or not row.get('all_corner_ideal_specs_pass')
                or not qualified(row.get('corners', {}), point['contract'])):
            raise ValueError('A declared point differs from its complete passing ideal control')
    return rows


def prepare(cid, ideal, output):
    parent = ROOT / 'runtime/train_collections' / (cid.lower() + '_action_v1')
    manifest, registry = read(parent / 'collection.json'), read(parent / 'registry.json')
    declared = next(row for row in read(ROOT / DECLARATION / 'domains.json')['domains']
                    if row['circuit_id'] == cid)
    rebuilt = declare(cid, registry)
    if any(declared[key] != value for key, value in rebuilt.items()):
        raise ValueError('Declared NF grid differs from its frozen train graph/specifications')
    ideal = Path(ideal).resolve()
    result = read(ideal / 'matched_pair_ideal.json')
    rows = bind_ideal(declared, result)
    from src.spice_validation import validate_analysis
    from src.corpus_component_benches import benches
    for point, row in zip(declared['configurations'], rows):
        for corner in point['contract']['required_corners']:
            parameters = point['parameters']; controls = point['contract']['numerical_controls']
            netlist = Path('/work') / DECLARATION / point['reference_file']
            common, bodies = benches(cid, parameters['sizing'], parameters['top_cell'], netlist,
                parameters['circuit']['ports'], corner, controls['integration_method'],
                controls['independent_transient_inputs'])
            for name, body in bodies.items():
                index = body.index('.control')
                body = body[:index + 1] + ['set wr_vecnames', 'set wr_singlescale'] + body[index + 1:] + ['quit', '.endc', '.end', '']
                analysis_common = ([line for line in common if not line.startswith(('EINP ', 'EINN '))]
                    if controls['independent_transient_inputs'] and name == 'tran' else common)
                if (ideal / point['configuration_id'] / corner / (name + '.spice')).read_text() != '\n'.join(analysis_common + body):
                    raise ValueError('Current applicable bench differs from an actual qualified ideal deck')
            for name, contract in point['contract']['analysis_contracts'].items():
                raw = row['corners'][corner]['analyses'][name]
                folder = ideal / point['configuration_id'] / corner
                checked = validate_analysis(folder / (name + '.dat'),
                    folder / (('ac' if name == 'op' else name) + '.log'),
                    contract, returncode=raw['returncode'])
                if not checked['complete']:
                    raise ValueError('An actual prior ideal raw analysis is incomplete')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    trusted = output / 'trusted'
    shutil.copytree(manifest['trusted_bundle'], trusted)
    for path in trusted.rglob('*'):
        path.chmod(0o755 if path.is_dir() else 0o644)
    trusted.chmod(0o755)
    # The older C07 bundle predates the independent C02 branch in this module.
    # Applicable stimulus bytes above must match every actual ideal deck; copy
    # that verified implementation into this new, separate trusted snapshot.
    shutil.copyfile(ROOT / 'src/corpus_component_benches.py', trusted / 'component_physical.py')
    for folder in ['contracts', 'references']:
        for path in (trusted / folder).iterdir():
            path.unlink()
    points = []
    for original in declared['configurations']:
        point = json.loads(json.dumps(original))
        point['parameters']['configuration_id'] = point['configuration_id']
        text = reference(point['parameters']['circuit'], point['parameters']['sizing'], point['parameters']['top_cell'])
        if (ROOT / DECLARATION / point['reference_file']).read_text() != text:
            raise ValueError('Declared independent per-finger reference changed')
        (trusted / 'references' / (point['configuration_id'] + '.spice')).write_text(text)
        save(trusted / 'contracts' / (point['configuration_id'] + '.json'), point['contract'])
        points.append(point)
    source = Path(manifest['source_pack'])
    lineage = next(row for row in registry['lineages'] if row['lineage_id'] == declared['parent_lineage'])
    names = sorted(lineage['frozen_source_files'] + lineage['editable_paths'])
    if names != sorted(str(path.relative_to(source)) for path in source.rglob('*') if path.is_file()):
        raise ValueError('The original cropped compiler file closure changed')
    for name in GATE_FILES:
        target = output / 'gate_source/src' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'src' / name, target)
    (output / 'gate_source/src/__init__.py').write_text('')
    plan = {'status': 'PREPARED_FIXED_FRESH_NINE_NO_PHYSICAL_CALLS', 'circuit_id': cid,
        'scope': 'development_train_domain_qualification_not_formal_training',
        'parent_lineage': declared['parent_lineage'], 'parent_frozen_registry': str(parent / 'registry.json'),
        'original_ideal_run': str(ideal), 'original_ideal_result': result,
        'source_pack': str(source), 'source_files': names, 'entrypoint': 'generator.py',
        'trusted_bundle': str(trusted), 'configurations': points,
        'runtime': str(ROOT / 'runtime/GLdev'), 'magic_runtime': manifest['magic_runtime'],
        'container_image': manifest['container_image'], 'pdk_revision': manifest['pdk_revision'],
        'physical': {'workers': 1, 'cpus_per_job': 2, 'memory_GiB': 8,
                     'generation_timeout_seconds': 240, 'evaluator_timeout_seconds': 720},
        'dispatch_horizon_seconds': 3600, 'gate_files': GATE_FILES,
        'planned_points': 9, 'model_calls': 0, 'formal_training_rows': 0,
        'old_evidence_relabelled': False, 'automatic_retries': False}
    save(output / 'plan.json', plan)
    for path in output.rglob('*'):
        if path.is_file():
            path.chmod(0o444)
    return {'preparation': str(output), 'planned_fresh_physical_points': 9, 'model_calls': 0}


def resource_gate(output, deadline):
    def cpu():
        fields = list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
        return sum(fields), fields[3] + fields[4]
    while time.monotonic() < deadline:
        first = cpu(); time.sleep(1); second = cpu()
        total = second[0] - first[0]
        busy = (1 - (second[1] - first[1]) / total) * os.cpu_count() if total else os.cpu_count()
        memory = {row.split(':')[0]: int(row.split()[1]) for row in Path('/proc/meminfo').read_text().splitlines()}
        sample = {'sampled_at_utc': datetime.now(timezone.utc).isoformat(), 'actual_busy_cores': busy,
                  'RAM_used_GiB': (memory['MemTotal'] - memory['MemAvailable']) / 2**20,
                  'root_disk_free_GiB': shutil.disk_usage(ROOT).free / 2**30}
        save(output / 'resource_gate_latest.json', sample)
        if busy + 2 <= 24 and sample['RAM_used_GiB'] <= 190 and sample['root_disk_free_GiB'] >= 4:
            return sample
        time.sleep(10)
    return None


def inspect_result(result, point, plan, trusted):
    from src.domain_runner import inspect_point
    from src.training import TrustedPhysicalStore
    from src.device_intent import compare_device_intent
    source = Path(plan['source_pack'])
    expected = {name: (source / name).read_bytes() for name in plan['source_files']}
    checked = inspect_point(result, point, expected, point['parameters'], gold_control_check=False)
    if checked['execution_integrity'] != 'valid' or checked['failure_class'] not in (None, 'candidate'):
        raise ValueError('Unknown/infrastructure physical evidence: ' + str(checked.get('reason')))
    run = Path(result['run_directory'])
    if checked['S1']:
        audit = compare_device_intent((run / 'evidence/layout_lvs.spice').read_text(),
            (Path(plan['trusted_bundle']) / 'references' / (point['configuration_id'] + '.spice')).read_text())
        if not audit['is_clean']:
            raise ValueError('Per-finger device or exact terminal-graph mismatch; quarantine')
        checked['device_intent_audit'] = audit
    if checked['S2']:
        bound = {**point, 'trusted_evaluator_files': trusted, 'frozen_source_pack': str(source),
                 'frozen_source_files': plan['source_files'], 'editable_paths': [], 'lineage_editable_paths': []}
        checked = TrustedPhysicalStore.inspect_development_run(run, bound, {})
    return checked


def run(prepared, output):
    prepared = Path(prepared).resolve(); plan = read(prepared / 'plan.json')
    bind_ideal({'circuit_id': plan['circuit_id'], 'configurations': [
        {**p, 'parameters': {k: v for k, v in p['parameters'].items() if k != 'configuration_id'}}
        for p in plan['configurations']]}, plan['original_ideal_result'])
    for name in plan['gate_files']:
        if (ROOT / 'src' / name).read_bytes() != (prepared / 'gate_source/src' / name).read_bytes():
            raise ValueError('Current trusted gate changed before dispatch: ' + name)
    from src.candidate_executor import CandidateExecutor
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    executor = CandidateExecutor(plan['runtime'], output / 'physical', plan['magic_runtime'], image=plan['container_image'])
    trusted = {str(path.relative_to(Path(plan['trusted_bundle']))): path.read_text()
               for path in sorted(Path(plan['trusted_bundle']).rglob('*')) if path.is_file()}
    state = {'status': 'RUNNING_FIXED_FRESH_NINE', 'preparation': str(prepared), 'pid': os.getpid(),
        'planned_points': 9, 'records': [], 'not_started': [p['configuration_id'] for p in plan['configurations']],
        'model_calls': 0, 'formal_training_rows': 0, 'automatic_retries': False}
    save(output / 'state.json', state)
    deadline = time.monotonic() + plan['dispatch_horizon_seconds']
    for point in plan['configurations']:
        sample = resource_gate(output, deadline)
        if sample is None:
            state['status'] = 'PAUSED_RESOURCE_GATE_NO_RETRY'; break
        row = {'configuration_id': point['configuration_id'], 'resources_before_start': sample}
        try:
            for name in plan['gate_files']:
                if (ROOT / 'src' / name).read_bytes() != (prepared / 'gate_source/src' / name).read_bytes():
                    raise ValueError('Trusted gate changed during the finite qualification')
            result = executor.execute(source_dir=plan['source_pack'], source_paths=plan['source_files'],
                entrypoint=plan['entrypoint'], representation='G2', configuration=point['parameters'],
                trusted_dir=plan['trusted_bundle'], trusted_paths=list(trusted),
                context={'source_role': 'development_train_domain_qualification',
                    'parent_lineage': plan['parent_lineage'], 'split': 'train',
                    'configuration_id': point['configuration_id'], 'reference_id': point['contract']['reference_id'],
                    'pdk_revision': plan['pdk_revision']},
                generation_timeout_seconds=240, evaluator_timeout_seconds=720)
            row.update(result=result, checked=inspect_result(result, point, plan, trusted), status='RETURNED_PHYSICAL_EVIDENCE')
        except Exception as error:
            row.update(status='UNKNOWN_QUARANTINED', error=type(error).__name__ + ': ' + str(error))
            state['status'] = 'PAUSED_UNKNOWN_NO_RETRY'
        state['records'].append(row); state['not_started'].remove(point['configuration_id'])
        save(output / 'state.json', state)
        print(json.dumps(row), flush=True)
        if state['status'] != 'RUNNING_FIXED_FRESH_NINE':
            break
    if not state['not_started'] and state['status'] == 'RUNNING_FIXED_FRESH_NINE':
        state['status'] = 'COMPLETED_FIXED_NINE_PHYSICAL_ATTEMPTS'
    state.update(not_run_dispositions=[{'configuration_id': cid, 'status': 'NOT_RUN'} for cid in state['not_started']],
        qualified_points=sum(row.get('checked', {}).get('S2', False) for row in state['records']),
        ended_at_utc=datetime.now(timezone.utc).isoformat())
    save(output / 'state.json', state)
    return state


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare'); prep.add_argument('--circuit', choices=['C02', 'C07'], required=True)
    prep.add_argument('--ideal-run', type=Path, required=True); prep.add_argument('--output', type=Path, required=True)
    execution = sub.add_parser('run'); execution.add_argument('--preparation', type=Path, required=True)
    execution.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.circuit, args.ideal_run, args.output) if args.command == 'prepare' else run(args.preparation, args.output)
    print(json.dumps(result), flush=True)
