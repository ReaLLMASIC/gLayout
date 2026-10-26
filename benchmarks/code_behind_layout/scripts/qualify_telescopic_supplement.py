"""Finite development qualification of the private, fixed telescopic domain.

validate is software-only. ideal uses the retained electrical functions in a
trusted 2CPU probe; full uses CandidateExecutor then actual raw inspection and
the current Store's development predicate. Neither creates training labels or
policy trials. Existing/unknown attempts are never automatically retried.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time

ROOT = Path('/work') if Path('/work/src').is_dir() else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_telescopic_supplement import SERVER, TARGET, read, save, digest, validate


def local_path(path):
    path = Path(path)
    if ROOT == Path('/work') and path.is_relative_to(SERVER):
        return ROOT/path.relative_to(SERVER)
    return path


def resource_gate(deadline, samples):
    """Same actual-host gates as current physical collectors, with finite UTC."""
    def cpu():
        numbers = list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
        return sum(numbers), numbers[3]+numbers[4]
    began = time.monotonic()
    while datetime.now(timezone.utc).timestamp() < deadline:
        first = cpu(); time.sleep(1); second = cpu()
        busy = (1-(second[1]-first[1])/(second[0]-first[0]))*os.cpu_count()
        memory = {line.split()[0].rstrip(':'): int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()}
        used = (memory['MemTotal']-memory['MemAvailable'])/1024**2
        free = shutil.disk_usage(ROOT).free/1024**3
        sample = {'at_utc': datetime.now(timezone.utc).isoformat(), 'busy_cores': busy,
            'used_RAM_GiB': used, 'root_free_GiB': free, 'queue_wall_seconds': time.monotonic()-began,
            'queue_CPU_seconds': None}
        samples.append(sample)
        if busy+2 <= 24 and used <= 190 and free >= 4:
            return sample
        time.sleep(min(10, max(0, deadline-datetime.now(timezone.utc).timestamp())))
    raise TimeoutError('Finite qualification resource/dispatch window exhausted')


def inside_ideal(preparation, configuration_id):
    task = validate(preparation)
    point = next(p for p in task['configurations'] if p['configuration_id'] == configuration_id)
    trusted = local_path(point['trusted_dir'])
    sys.path.insert(0, str(trusted))
    # Load the exact copied validator before the original bench adds /work to
    # sys.path; its import then resolves this frozen module.
    import src.spice_validation
    if Path(src.spice_validation.__file__).resolve() != (trusted/'src/spice_validation.py').resolve():
        raise ValueError('Ideal analysis validator must come from the frozen trusted capsule')
    spec = importlib.util.spec_from_file_location('supplement_original_bench', trusted/'original_bench.py')
    bench = importlib.util.module_from_spec(spec); spec.loader.exec_module(bench)
    reference = local_path(point['reference_file'])
    if reference.read_bytes() != (trusted/'reference.spice').read_bytes():
        raise ValueError('Ideal sized independent N differs from its physical capsule')
    declaration = read(trusted/'telescopic_declaration.json'); control = read(trusted/'telescopic_bias.json')
    calls = []; out = Path.cwd()
    def invoke(argv, cwd, logname, timeout, stdin=None):
        before = resource.getrusage(resource.RUSAGE_CHILDREN); started = time.monotonic(); code = None
        error = None
        try:
            with (cwd/logname).open('w') as log:
                result = subprocess.run(argv, cwd=cwd, input=stdin, text=True, stdout=log,
                    stderr=subprocess.STDOUT, timeout=timeout); code = result.returncode
        except subprocess.TimeoutExpired:
            error = 'original_per_analysis_timeout'
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        row = {'argv': argv, 'returncode': code, 'error': error, 'wall_seconds': time.monotonic()-started,
            'actual_waited_child_CPU_seconds': after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
            'timeout_seconds': timeout, 'log': str(cwd/logname)}
        calls.append(row); save(out/'actual_processes.json', calls); return row
    rows = bench.electrical(reference, task['top_cell'], task['ports'], control, declaration, out, invoke)
    result = {'scope': 'development_schematic_only_not_S1_S2', 'configuration_id': configuration_id,
        'complete': set(rows) == set(declaration['corners']) and all(r['complete'] for r in rows.values()),
        'specifications_passed': all(r['specifications_passed'] for r in rows.values()),
        'corners': rows, 'actual_SPICE_calls': len(calls), 'new_GDS_DRC_LVS_PEX_calls': 0,
        'original_bench_sha256': digest(trusted/'original_bench.py'), 'reference_sha256': digest(reference)}
    save(out/'ideal_point.json', result)
    return result


def verify_ideal_family(preparation, ideal_output):
    task = validate(preparation); state = read(Path(ideal_output)/'state.json')
    if state.get('phase') != 'ideal' or state.get('status') != 'QUALIFICATION_COMPLETE_PASS':
        raise ValueError('All25 original ideal controls must complete and meet specifications before any new physical control')
    if state['preparation_manifest_sha256'] != digest(Path(preparation)/'private/manifest.json'):
        raise ValueError('Ideal controls used another frozen domain')
    records = state['points']
    if set(records) != {p['configuration_id'] for p in task['configurations']}:
        raise ValueError('Ideal qualification must retain the entire fixed 25-point denominator')
    for point in task['configurations']:
        record = records[point['configuration_id']]
        raw = Path(record['raw_directory']); actual = read(raw/'ideal_point.json')
        if (actual['configuration_id'] != point['configuration_id'] or not actual['complete']
                or not actual['specifications_passed'] or actual['actual_SPICE_calls'] != 12):
            raise ValueError('Actual ideal point is missing/incomplete/nonpositive')
        if actual['reference_sha256'] != digest(point['reference_file']):
            raise ValueError('Actual ideal control independent N differs')
        if (actual['original_bench_sha256'] != digest(Path(point['trusted_dir'])/'original_bench.py')
                or set(actual['corners']) != set(point['contract']['required_corners'])):
            raise ValueError('Actual ideal corner/benchmark binding differs')
        from src.spice_validation import validate_analysis
        for corner, row in actual['corners'].items():
            if set(row['analyses']) != {'op', 'ac', 'transient', 'dc'} or not row['specifications_passed']:
                raise ValueError('Original ideal analyses or specifications are incomplete')
            for name, item in row['analyses'].items():
                if not validate_analysis(raw/corner/(name+'.dat'), raw/corner/(name+'.log'),
                        item['contract'], item['process']['returncode'])['complete']:
                    raise ValueError('Saved ideal raw coverage does not establish completeness')
    return task


def full_rc_audit(run, task, point, output):
    """Required audit view; never rewrite the unsimplified SPICE netlist."""
    from scripts.audit_train_pair_nf_rc import contracted_devices
    from src.device_intent import compare_device_intent
    from src.training import TrustedPhysicalStore
    started = time.monotonic(); before = resource.getrusage(resource.RUSAGE_SELF)
    audit = {'status': 'RUNNING', 'required_after_S1': True,
        'scope': 'readonly_wire_contraction_view_of_actual_full_RC_not_a_SPICE_replacement',
        'run_directory': str(run), 'original_RC_changed': False}
    try:
        evidence = run/'evidence'; validation = read(evidence/'validation.json')
        if validation['contract'] != point['contract']:
            raise ValueError('Actual full-RC evidence contract differs from independent point')
        pex = validation['artifacts']['pex']
        audit.update(netlist=pex.get('netlist'), top_cell=pex.get('top_cell'), ports=pex.get('ports'))
        # The original fixed bench receives this exact artifact and port order.
        if pex['ports'] != task['ports'] or pex['top_cell'] != task['top_cell']+'_rc':
            raise ValueError('Full-RC top/port order differs from the fixed independent bench')
        path = TrustedPhysicalStore._file(evidence, pex['netlist'])
        reference = TrustedPhysicalStore._file(run/'trusted', 'reference.spice')
        if reference.read_bytes() != Path(point['reference_file']).read_bytes():
            raise ValueError('Full-RC independent reference differs from prepared N(z)')
        view = contracted_devices(path.read_text(), pex['top_cell'], task['ports'])
        graph = compare_device_intent(view, reference.read_text())
        audit.update(reference='trusted/reference.spice', audit=graph,
            status='RC_DEVICE_GRAPH_MATCH' if graph['is_clean'] else 'QUARANTINED_MISMATCH')
        if not graph['is_clean']:
            audit['error'] = 'Actual unsimplified full-RC device/port graph differs from independent N(z)'
    except (ValueError, OSError, KeyError, TypeError) as error:
        audit.update(status='QUARANTINED_UNKNOWN', error=type(error).__name__+': '+str(error))
    finally:
        after = resource.getrusage(resource.RUSAGE_SELF)
        audit.update(wall_seconds=time.monotonic()-started,
            actual_CPU_seconds=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime)
        save(output/'full_rc_intent_audit.json', audit)
    return audit


def full_point(task, point, output, deadline):
    from src.candidate_executor import CandidateExecutor
    from src.domain_runner import inspect_point, source_contents
    from src.training import TrustedPhysicalStore
    from scripts.e2_execution import measured_cost
    executor = CandidateExecutor(ROOT/'runtime/GLdev', output/'physical', ROOT/'runtime/magic-8.3.685', timeout=3000)
    configuration = {'parameters': point['parameters']}
    source = Path(task['source_pack'])
    result = executor.execute(source_dir=source, source_paths=task['source_files'], entrypoint=task['entrypoint'],
        representation='G2', configuration=configuration, trusted_dir=point['trusted_dir'], trusted_paths=point['trusted_files'],
        fidelity='pex_spice', phase='development_telescopic_supplement_qualification',
        context={'source_role': 'trusted_evaluator_control', 'candidate_id': task['task_id'],
            'initial_state_id': task['task_id'], 'parent_lineage': task['parent_lineage'],
            'configuration_id': point['configuration_id'], 'reference_id': point['reference_id'],
            'pdk_revision': point['pdk_revision']}, generation_timeout_seconds=240, evaluator_timeout_seconds=3000,
        execution_deadline_utc=datetime.fromtimestamp(deadline, timezone.utc).isoformat())
    run = Path(result['run_directory']); expected = source_contents(source, task['source_files'], binary=True)
    try:
        checked = inspect_point(result, point, expected, configuration, gold_control_check=False)
    except (ValueError, OSError, KeyError, TypeError) as error:
        checked = {'S0': False, 'S1': False, 'S2': False, 'execution_integrity': 'incomplete',
            'failure_class': 'unknown', 'reason': type(error).__name__+': '+str(error)}
    rc_audit = None
    if checked.get('S1') or (result.get('physical_result') or {}).get('assessment', {}).get('S1'):
        rc_audit = full_rc_audit(run, task, point, output)
        if rc_audit['status'] != 'RC_DEVICE_GRAPH_MATCH':
            checked = {**checked, 'S2': False, 'execution_integrity': 'incomplete', 'failure_class': 'unknown',
                'reason': 'Required full-RC graph audit quarantined: '+rc_audit.get('error', rc_audit['status'])}
    store_checked = None
    if checked['S2'] and checked['execution_integrity'] == 'valid':
        dry = {**point, 'parameters': configuration, 'source_files': task['source_files'],
            'editable_paths': [TARGET], 'lineage_editable_paths': [TARGET],
            'frozen_source_files': [name for name in task['source_files'] if name != TARGET],
            'frozen_source_pack': str(source), 'intent_reference_path': 'reference.spice',
            'trusted_evaluator_files': {name: (Path(point['trusted_dir'])/name).read_text() for name in point['trusted_files']}}
        store_checked = TrustedPhysicalStore.inspect_development_run(run, dry, {TARGET: (source/TARGET).read_text()})
        if not store_checked['S2']: raise ValueError('Current raw Store predicate contradicts the positive point')
    record = {'configuration_id': point['configuration_id'], 'raw_directory': str(run), 'checked': checked,
        'Store_development_check': store_checked, 'full_RC_device_port_audit': rc_audit,
        'actual_costs_by_stage': measured_cost(run),
        'formal_training_label': False, 'new_model_calls': 0}
    save(output/'point.json', record)
    return record


def run(preparation, output, phase, ideal_output=None):
    if ROOT != SERVER:
        raise ValueError('Actual qualification runs only on the private research server')
    task = validate(preparation)
    if phase == 'full': task = verify_ideal_family(preparation, ideal_output)
    output = Path(output).resolve(); output.relative_to(ROOT/'runs/development/telescopic_supplement_qualification')
    output.mkdir(parents=True, exist_ok=False); output.chmod(0o700)
    started = time.monotonic(); before = resource.getrusage(resource.RUSAGE_SELF)
    deadline = datetime.now(timezone.utc).timestamp()+task['qualification']['each_phase_dispatch_window_seconds']
    state = {'status': 'RUNNING', 'phase': phase, 'scope': 'development_qualification_not_formal_not_training',
        'preparation': str(Path(preparation).resolve()), 'preparation_manifest_sha256': digest(Path(preparation)/'private/manifest.json'),
        'declared_configurations': 25, 'points': {}, 'resource_samples': [], 'new_model_calls': 0,
        'automatic_retry': False, 'deadline_utc': datetime.fromtimestamp(deadline, timezone.utc).isoformat()}
    def checkpoint():
        temporary = output/'state.tmp'; save(temporary, state); temporary.replace(output/'state.json')
    checkpoint()
    # Explicit fixed order, not priority or selection using observed quality.
    for point in task['configurations']:
        ident = point['configuration_id']; record = {'status': 'RESERVED', 'actual_point_calls': 0}
        state['points'][ident] = record; checkpoint()
        try:
            resource_gate(deadline, state['resource_samples']); checkpoint()
            validate(preparation)
            record.update(status='RUNNING', actual_point_calls=1); checkpoint()
            work = output/ident; work.mkdir(); record['raw_attempt_directory'] = str(work); checkpoint()
            if phase == 'ideal':
                command = [sys.executable, str(ROOT/'scripts/run_eda_probe.py'), '--script',
                    'qualify_telescopic_supplement.py', '--input-dir', str(Path(preparation).resolve()),
                    '--timeout', str(min(2400, max(1, int(deadline-datetime.now(timezone.utc).timestamp())))),
                    '--', '--inside-ideal-point', ident]
                record['transport_argv'] = command; checkpoint()
                old_umask = os.umask(0o077)
                try:
                    with (work/'probe_transport.log').open('w') as log:
                        process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                            timeout=max(1, deadline-datetime.now(timezone.utc).timestamp()+30))
                finally: os.umask(old_umask)
                first = json.loads((work/'probe_transport.log').read_text().splitlines()[0])
                raw = Path(first['output'])
                record.update(raw_directory=str(raw), transport_returncode=process.returncode,
                    resource_usage=read(raw/'resource_usage.json') if (raw/'resource_usage.json').is_file() else None)
                checkpoint()
                actual = read(raw/'ideal_point.json')
                record.update(actual_SPICE_calls=actual['actual_SPICE_calls'],
                    complete=actual['complete'], specifications_passed=actual['specifications_passed'],
                    resource_usage=read(raw/'resource_usage.json') if (raw/'resource_usage.json').is_file() else None)
                if not actual['complete']: raise ValueError('Original ideal analysis did not complete')
                record['status'] = 'PASS' if actual['specifications_passed'] else 'COMPLETE_SHORTFALL'
            else:
                actual = full_point(task, point, work, deadline)
                record.update(raw_directory=actual['raw_directory'], checked=actual['checked'],
                    full_RC_device_port_audit=actual['full_RC_device_port_audit'],
                    actual_costs_by_stage=actual['actual_costs_by_stage'])
                if actual['checked']['execution_integrity'] != 'valid':
                    raise ValueError('Physical execution is incomplete/unknown, not a negative training label')
                record['status'] = 'PASS' if actual['checked']['S2'] else 'COMPLETE_SHORTFALL'
            checkpoint()
        except (ValueError, OSError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
            record.update(status='UNKNOWN_STOPPED', error=type(error).__name__+': '+str(error))
            state['status'] = 'UNKNOWN_STOPPED'; checkpoint(); break
    else:
        state['status'] = ('QUALIFICATION_COMPLETE_PASS' if all(p['status'] == 'PASS' for p in state['points'].values())
                           else 'QUALIFICATION_COMPLETE_SHORTFALL')
    after = resource.getrusage(resource.RUSAGE_SELF)
    state['coordinator_wall_seconds'] = time.monotonic()-started
    state['coordinator_actual_CPU_seconds'] = after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime
    checkpoint()
    summary = {'status': state['status'], 'scope': state['scope'], 'phase': phase,
        'declared_configurations': 25, 'attempted_configurations': sum(p['actual_point_calls'] for p in state['points'].values()),
        'complete_configurations': sum(p['status'] in ('PASS', 'COMPLETE_SHORTFALL') for p in state['points'].values()),
        'passed_configurations': sum(p['status'] == 'PASS' for p in state['points'].values()),
        'not_run': 25-sum(p['actual_point_calls'] for p in state['points'].values()),
        'new_model_calls': 0, 'formal_training_labels': 0, 'formal_policy_trials': 0,
        'hidden_vectors_exported': False, 'formal_admission': False,
        'coordinator_wall_seconds': state['coordinator_wall_seconds'],
        'coordinator_actual_CPU_seconds': state['coordinator_actual_CPU_seconds']}
    save(output/'public_summary.json', summary); return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=['validate', 'ideal', 'full'])
    p.add_argument('--preparation', type=Path); p.add_argument('--output', type=Path)
    p.add_argument('--ideal-output', type=Path)
    p.add_argument('--inside-ideal-point')
    args = p.parse_args()
    if args.inside_ideal_point:
        result = inside_ideal(Path(os.environ['PROBE_INPUT']), args.inside_ideal_point)
        print(json.dumps({'complete': result['complete'], 'scope': result['scope']}))
    elif args.mode == 'validate':
        if not args.preparation: p.error('validate requires --preparation')
        task = validate(args.preparation)
        print(json.dumps({'status': 'DRAFT_INPUTS_VALID_NO_EDA', 'configurations': len(task['configurations']),
            'new_model_calls': 0, 'new_physical_calls': 0}))
    else:
        if not args.mode or not args.preparation or not args.output or args.mode == 'full' and not args.ideal_output:
            p.error('ideal/full require preparation/output; full also requires the complete ideal output')
        print(json.dumps(run(args.preparation, args.output, args.mode, args.ideal_output), indent=2))
