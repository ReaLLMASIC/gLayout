"""Prepare and execute exactly nine fresh train-source physical controls, once."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.train_generators.ratio_source_intent import K_VALUES, R_VALUES, point, reference_spice
from src.train_generators.ratio_source_bench import analysis_decks, measure, numeric_rows
from src.spice_validation import validate_analysis

SOURCES = ['src/__init__.py', 'src/train_generators/__init__.py',
    'src/train_generators/ratio_source.py', 'src/train_generators/ratio_source_intent.py',
    'src/train_generators/ratio_source_bench.py', 'src/generators/__init__.py',
    'src/generators/terminal_access.py', 'src/physical_drc.py', 'src/report_parsers.py',
    'src/device_intent.py', 'src/spice_validation.py', 'scripts/ratio_source_physical_probe.py',
    'scripts/ratio_source_physical_qualification.py', 'scripts/run_eda_probe.py', 'scripts/profile_probe.py']
DOMAIN = ROOT / 'configs/development/ratio_source_array_v1'


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path); temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n'); temporary.replace(path)


def fixed_points():
    return [point(k, ratio) for k in K_VALUES for ratio in R_VALUES]


def ideal_binding(ideal_run):
    ideal_run = Path(ideal_run).resolve(); result = read(ideal_run / 'ideal_qualification.json')
    domain = read(DOMAIN / 'domain.json'); expected = fixed_points()
    if domain['configurations'] != expected or read(ideal_run / 'domain_snapshot.json') != domain:
        raise ValueError('The original nine-point domain differs from the actual ideal snapshot')
    rows = result.get('points', [])
    if (result['status'] != 'COMPLETED_FIXED_NINE_POINT_IDEAL_ATTEMPTS' or len(rows) != 9
            or result.get('all_nine_ideal_qualified') is not True
            or [r['configuration_id'] for r in rows] != [r['configuration_id'] for r in expected]):
        raise ValueError('All nine original ideal controls must complete and qualify; no successful subset')
    for row, control in zip(rows, expected):
        if (row['configuration'] != control or not row['all_corners_complete']
                or not row['all_corners_ideal_specs_pass'] or set(row['corners']) != {'tt', 'ss', 'ff'}
                or not all(c['complete'] and c['ideal_application_constraints_pass'] for c in row['corners'].values())):
            raise ValueError('An original ideal corner is incomplete or fails the unchanged prior specifications')
        text = reference_spice(control)
        if ((DOMAIN / control['reference_file']).read_text() != text
                or (ideal_run / control['configuration_id'] / 'independent_N.spice').read_text() != text):
            raise ValueError('An independent per-finger reference differs from the ideal control')
        reference = ideal_run / control['configuration_id'] / 'independent_N.spice'
        container_reference = '/work/' + str(reference.relative_to(ROOT))
        for corner in control['contract']['required_corners']:
            work = ideal_run / control['configuration_id'] / 'analyses' / corner
            for name, deck in analysis_decks(control, container_reference, corner).items():
                if (work / (name + '.spice')).read_text() != deck:
                    raise ValueError('An actual ideal stimulus differs from the unchanged source bench')
            data = {}
            for name, contract in control['contract']['analysis_contracts'].items():
                log = work / (('ac1' if name == 'op' else name) + '.log')
                if not validate_analysis(work / (name + '.dat'), log, contract, 0)['complete']:
                    raise ValueError('An actual prior ideal analysis is incomplete: ' + corner + '/' + name)
                data[name] = numeric_rows(work / (name + '.dat'))
            audited = measure(control, data)
            if (not audited['ideal_application_constraints_pass'] or
                    any(row['corners'][corner][key] != value for key, value in audited.items())):
                raise ValueError('Prior ideal raw measurements do not reproduce the declared passing controls')
    return domain, result


def prepare(ideal_run, output):
    domain, _ = ideal_binding(ideal_run)
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    for name in SOURCES:
        target = output / 'source_snapshot' / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    for row in domain['configurations']:
        target = output / row['reference_file']; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((DOMAIN / row['reference_file']).read_bytes())
    shutil.copyfile(DOMAIN / 'lineage_declaration.json', output / 'lineage_declaration.json')
    shutil.copyfile(Path(ideal_run) / 'ideal_qualification.json', output / 'original_ideal_qualification.json')
    plan = {'status': 'PREPARED_FIXED_NINE_ONCE_NO_PHYSICAL_CALLS',
        'scope': 'development_train_source_physical_qualification_not_formal_or_training_examples',
        'prepared_at_utc': datetime.now(timezone.utc).isoformat(),
        'original_ideal_run': str(Path(ideal_run).resolve()), 'original_domain': str(DOMAIN),
        'configurations': domain['configurations'], 'source_files': SOURCES,
        'vendor_revision': subprocess.check_output(['git', '-C', str(ROOT / 'vendor/glayout'), 'rev-parse', 'HEAD'], text=True).strip(),
        'fixed_order': [p['configuration_id'] for p in domain['configurations']],
        'maximum_fresh_physical_points': 9, 'workers': 1, 'CPU_per_worker': 2, 'memory_GiB_per_worker': 8,
        'per_analysis_wall_timeout_s': 120, 'per_point_outer_wall_timeout_s': 3600,
        'new_dispatch_resource_gate_horizon_s_from_plan_start': 3600,
        'dispatch_gate': 'actual busy+2<=24 cores, used RAM<=190GiB, disk free>=4GiB',
        'no_candidate_replacement_or_retry': True, 'no_specification_or_domain_changes': True,
        'old_frozen_helpers_or_source_assignments_modified': False, 'model_calls': 0,
        'training_examples_admitted': 0, 'new_EDA_calls': 0}
    save(output / 'physical_plan.json', plan)
    for p in output.rglob('*'):
        if p.is_file(): p.chmod(0o444)
    return {'status': plan['status'], 'preparation': str(output), 'planned_fresh_physical_points': 9, 'new_EDA_calls': 0}


def resource_gate(output, deadline):
    def cpu():
        row = list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:9])); return sum(row), row[3] + row[4]
    while True:
        if time.monotonic() >= deadline:
            save(output / 'resource_gate_latest.json', {'status': 'FIXED_DISPATCH_HORIZON_EXPIRED',
                'observed_at_utc': datetime.now(timezone.utc).isoformat(), 'new_job_dispatched': False})
            return None
        first = cpu(); time.sleep(1); second = cpu()
        busy = (1 - (second[1] - first[1]) / (second[0] - first[0])) * os.cpu_count()
        memory = {line.split(':')[0]: int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()}
        used = (memory['MemTotal'] - memory['MemAvailable']) / 2**20
        free = shutil.disk_usage(ROOT).free / 2**30
        sample = {'sample_utc': datetime.now(timezone.utc).isoformat(), 'actual_busy_cores': busy,
                  'used_RAM_GiB': used, 'disk_free_GiB': free}
        save(output / 'resource_gate_latest.json', sample)
        if busy + 2 <= 24 and used <= 190 and free >= 4:
            return sample
        time.sleep(10)


def run(prepared, output):
    prepared = Path(prepared).resolve(); plan = read(prepared / 'physical_plan.json')
    ideal_binding(plan['original_ideal_run'])
    if plan['configurations'] != fixed_points() or plan['source_files'] != SOURCES:
        raise ValueError('Prepared fixed nine-point plan or source closure changed')
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    state = {'status': 'RUNNING_FIXED_NINE_ONCE', 'preparation': str(prepared), 'planned_points': 9,
        'started_at_utc': datetime.now(timezone.utc).isoformat(), 'records': [],
        'not_started': list(plan['fixed_order']), 'model_calls': 0, 'training_examples': 0,
        'source_assignments_modified': False, 'no_automatic_retries': True}
    gate_deadline = time.monotonic() + plan['new_dispatch_resource_gate_horizon_s_from_plan_start']
    save(output / 'state.json', state)
    for row in plan['configurations']:
        for name in SOURCES:
            if (ROOT / name).read_bytes() != (prepared / 'source_snapshot' / name).read_bytes():
                raise ValueError('Prepared physical source closure changed: ' + name)
        revision = subprocess.check_output(['git', '-C', str(ROOT / 'vendor/glayout'), 'rev-parse', 'HEAD'], text=True).strip()
        if revision != plan['vendor_revision']:
            raise ValueError('Declared MOS/PDK source revision changed')
        identifier = row['configuration_id']; sample = resource_gate(output, gate_deadline)
        if sample is None:
            state.update(status='STOPPED_RESOURCE_GATE_TIMEOUT',
                not_run_dispositions=[{'configuration_id': name, 'status': 'NOT_RUN',
                    'reason': 'Fixed one-hour dispatch horizon expired; never terminate a running point'}
                    for name in state['not_started']])
            break
        command = [sys.executable, 'scripts/run_eda_probe.py', '--script', 'ratio_source_physical_probe.py',
            '--input-dir', str(prepared), '--magic-runtime', 'magic-8.3.685', '--timeout', '3600',
            '--', '--configuration-id', identifier]
        record = {'configuration_id': identifier, 'status': 'DISPATCHED_ONCE', 'argv': command,
            'resource_dispatch_sample': sample, 'started_at_utc': datetime.now(timezone.utc).isoformat()}
        state['not_started'].remove(identifier); state['records'].append(record); save(output / 'state.json', state)
        logpath = output / (identifier + '.log')
        with logpath.open('x') as log:
            process = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        record.update(returncode=process.returncode, ended_at_utc=datetime.now(timezone.utc).isoformat())
        lines = logpath.read_text().splitlines()
        first = next((json.loads(line) for line in lines if line.startswith('{"run_id":')), None)
        if first is not None:
            record['run_directory'] = first['output']; raw = Path(first['output']) / 'physical_qualification.json'
            record['actual_result'] = read(raw) if raw.exists() else None
        record['status'] = 'ACTUAL_ATTEMPT_TERMINAL_NO_RETRY'; save(output / 'state.json', state)
        if (record.get('actual_result') or {}).get('status') not in ('COMPLETE', 'COMPLETE_PHYSICAL_REJECTION'):
            state.update(status='PAUSED_UNKNOWN_NO_RETRY',
                not_run_dispositions=[{'configuration_id': name, 'status': 'NOT_RUN',
                    'reason': 'Prior point unknown/infrastructure state; no further physical dispatch'}
                    for name in state['not_started']])
            break
    if state['status'] == 'RUNNING_FIXED_NINE_ONCE':
        state['status'] = 'COMPLETED_FIXED_NINE_PHYSICAL_ATTEMPTS'
    state.update(
        ended_at_utc=datetime.now(timezone.utc).isoformat(),
        S2_points=sum(bool((r.get('actual_result') or {}).get('S2')) for r in state['records']),
        unknown_points=sum((r.get('actual_result') or {}).get('status') not in ('COMPLETE', 'COMPLETE_PHYSICAL_REJECTION') for r in state['records']))
    save(output / 'state.json', state)
    return {k: v for k, v in state.items() if k != 'records'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='mode', required=True)
    p = sub.add_parser('prepare'); p.add_argument('--ideal-run', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('run'); p.add_argument('--preparation', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.ideal_run, args.output) if args.mode == 'prepare' else run(args.preparation, args.output)
    print(json.dumps(result, allow_nan=False))
