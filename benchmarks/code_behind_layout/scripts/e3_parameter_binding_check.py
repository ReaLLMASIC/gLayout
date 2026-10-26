#!/usr/bin/env python3
"""Read the actual 24 prepared sources and check P's exact initial binding.

This performs no generation, EDA, model request, source rewrite or domain change.
Only the trusted backend reads the private preparation; the report contains no
hidden configuration values or outcomes.
"""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.e3_parameter_episode import binding, canonical, parse_controls
from src.e3_parameters import render


def inspect(task_path):
    task = json.loads(task_path.read_text())
    domain, pdk, original = binding(task)
    if len(task['editable_paths']) != 1:
        raise ValueError('Exactly one complete original layout module is bound')
    module = task['editable_paths'][0]
    actual = Path(task['source_overrides'][module]).read_bytes()
    controls = parse_controls(canonical(task['parameter_controls']))
    candidate = render(task['target'], original, controls, pdk).encode()
    return {'task_id': task['task_id'], 'target': task['target'],
        'editable_module': module, 'actual_initial_bytes': len(actual),
        'rendered_initial_bytes': len(candidate), 'source_bytes_identical': actual == candidate,
        'all_declared_knobs_present': set(controls) == set(domain['parameters']),
        'original_module': task['expanded_parameter_baseline']['immutable_original_module'],
        'actual_initial_module': task['source_overrides'][module],
        'scope': 'Exact initial source binding only; independent physical device-intent qualification is separate'}


def check(preparation, output):
    began, cpu = time.monotonic(), time.process_time()
    files = sorted((preparation/'private').glob('draft_E3_*/task.json'))
    if len(files) != 24:
        raise ValueError('The current source inventory declares exactly24 editing states')
    rows = []
    for path in files:
        try:
            rows.append(inspect(path))
        except (OSError, ValueError, KeyError, TypeError) as error:
            rows.append({'task_id': path.parent.name, 'source_bytes_identical': False,
                'error': type(error).__name__+': '+str(error)})
    passed = sum(row['source_bytes_identical'] for row in rows)
    report = {'scope': 'development_actual_parameter_initial_byte_binding_not_physical',
        'preparation': str(preparation), 'declared_states': 24, 'bound_states': passed,
        'status': 'COMPLETE' if passed == 24 else 'BINDING_FAILED', 'states': rows,
        'wall_seconds': time.monotonic()-began, 'process_CPU_seconds': time.process_time()-cpu,
        'new_generation_calls': 0, 'new_EDA_calls': 0, 'new_model_calls': 0,
        'hidden_values_exported': False, 'formal_trials': 0}
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError('Never overwrite an actual control report')
    output.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'states'}), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preparation', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    check(args.preparation, args.output)
