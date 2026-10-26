"""One fresh S0 layer control, then the already fixed nine physical attempts."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.ratio_source_physical_qualification import read, save, resource_gate, run


def main(prepared, output, control_output):
    control_output = Path(control_output).resolve(); control_output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic(); before = resource.getrusage(resource.RUSAGE_SELF)
    before_child = resource.getrusage(resource.RUSAGE_CHILDREN)
    status = {'status': 'WAITING_FOR_FRESH_S0_SLOT', 'preparation': str(Path(prepared).resolve()),
        'fixed_nine_output': str(Path(output).resolve()), 'started_at_utc': datetime.now(timezone.utc).isoformat(),
        'source_version': 'ratio_source_v3_correct_physical_met3_enclosures',
        'fresh_S0_limit': 1, 'full_nine_point_plan_unchanged': True, 'new_ideal_calls': 0}
    save(control_output / 'combined_status.json', status)
    try:
        slot = resource_gate(control_output, started + 3600)
        if slot is None:
            status['status'] = 'NOT_RUN_FIXED_RESOURCE_HORIZON_EXPIRED'
            return status
        command = [sys.executable, 'scripts/run_eda_probe.py', '--script', 'ratio_source_pad_smoke.py',
            '--input-dir', str(Path(prepared).resolve()), '--magic-runtime', 'magic-8.3.685', '--timeout', '600']
        status.update(status='FRESH_S0_RUNNING', source_generation_argv=command, dispatch_sample=slot)
        save(control_output / 'combined_status.json', status)
        with (control_output / 'fresh_S0.log').open('x') as log:
            process = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        first = next((json.loads(line) for line in (control_output / 'fresh_S0.log').read_text().splitlines()
            if line.startswith('{"run_id":')), None)
        status['S0_returncode'] = process.returncode
        raw = Path(first['output']) if first else None
        report = read(raw / 'pad_smoke.json') if raw is not None and (raw / 'pad_smoke.json').exists() else None
        status.update(S0_run_directory=str(raw) if raw else None, actual_S0_geometry_control=report)
        if (process.returncode != 0 or not report or report['passed'] is not True or
                report['new_tool_calls'] != {'GDS_generation': 1, 'DRC': 0, 'LVS': 0, 'PEX': 0, 'SPICE': 0}):
            status.update(status='PAUSED_S0_GEOMETRY_UNKNOWN_OR_FAILED_NO_FULL_DISPATCH',
                full_nine_actual_calls=0)
            return status
        status.update(status='S0_PAD_GEOMETRY_VERIFIED_FIXED_NINE_RUNNING',
            actual_S0_profile=read(raw / 'resource_usage.json'))
        save(control_output / 'combined_status.json', status)
        final = run(prepared, output)
        status.update(status='FIXED_NINE_RETURNED', actual_nine_summary=final)
        return status
    except Exception as error:
        status.update(status='PAUSED_CONTROLLER_UNKNOWN_NO_RETRY', error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        after = resource.getrusage(resource.RUSAGE_SELF); child = resource.getrusage(resource.RUSAGE_CHILDREN)
        status.update(ended_at_utc=datetime.now(timezone.utc).isoformat(), total_coordinator_wall_seconds=time.monotonic() - started,
            actual_host_self_CPU_seconds=after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
            actual_waited_host_child_CPU_seconds=child.ru_utime + child.ru_stime - before_child.ru_utime - before_child.ru_stime,
            cost_scope='Host controller and waited clients; container source/EDA CPU is separately measured by each probe. Nested wall scopes are not additive.')
        save(control_output / 'combined_status.json', status)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preparation', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--control-output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(main(args.preparation, args.output, args.control_output), allow_nan=False))
