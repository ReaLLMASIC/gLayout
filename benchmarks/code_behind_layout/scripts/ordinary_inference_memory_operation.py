"""One reviewed longest-TRAIN engineering probe; exact own8114 restoration.

--prepare-only reads the live drain evidence and saves a private0600 recovery
record. It sends no signal and does not import torch. Root reviews that receipt
before --execute; neither mode changes a collector or an experiment's records.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OLD_PID = 2515684
QUEUE = 'runs/train_collection_queues/20261019T054505066451Z/queue.json'
MATCHED = 'runs/train_proposals/matched_t0_planning_context_v1/completion.json'
KEYS = ['settings', 'teacher_source_settings', 'variants', 'base_revision', 'tokenizer_revision', 'native_tools']


def now(): return datetime.now(timezone.utc).isoformat()
def read(path): return json.loads(Path(path).read_text())


def save(path, value, mode=0o644):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.pending')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, 'w') as stream: json.dump(value, stream, indent=2); stream.write('\n')
    temporary.replace(path)


def process(pid):
    try:
        directory = Path('/proc') / str(pid)
        status = (directory / 'stat').read_text().rsplit(')', 1)[1].split()
        if status[0] == 'Z': return None
        return {'pid': pid, 'argv': [x.decode() for x in (directory / 'cmdline').read_bytes().split(b'\0') if x],
            'start_ticks': status[19], 'cwd': os.readlink(directory / 'cwd')}
    except FileNotFoundError: return None


def no_future_dispatch(queue, terminal):
    events = [event for event in queue.get('events', []) if event.get('lane') == 'T0']
    if queue.get('pid') != 1728183 or not events or events[-1].get('event') not in ('LANE_PAUSED', 'LANE_PAUSED_UNKNOWN'):
        raise ValueError('Original uniquequeue T0 lane has no final paused record; do not modify it')
    if (terminal.get('status') != 'COMPLETED_PROPOSAL_MATRIX' or terminal.get('planned_proposals') != 96
            or terminal.get('returned_attempts') != 96 or terminal.get('remaining_not_run') != 0):
        raise ValueError('Original matched96 is not terminal; maintenance cannot consume its GPU window')
    return {'queue': QUEUE, 'queue_pid': queue['pid'], 'last_T0_event': events[-1],
        'matched_completion': MATCHED, 'original96_terminal': terminal,
        'reservation': 'No new T0 dispatcher is authorized by this one-shot operation. Existing paused lane is not resumed or edited.'}


def idle(inspection, sockets):
    if (inspection.get('service_pid') != OLD_PID or not inspection.get('service_exact_argv_matches')
            or inspection.get('actual_T0_clients') or inspection.get('pending_received_requests') or sockets):
        raise ValueError('Own8114 has a changed identity, active client, received request or TCP connection')


def health():
    with urllib.request.urlopen('http://127.0.0.1:8114/health', timeout=8) as response: return json.load(response)


def inspect():
    result = subprocess.run(['python3', 'scripts/gpu_context_calibration_queue.py', '--inspect-only'],
        cwd=ROOT, capture_output=True, text=True, check=True, timeout=30)
    inspection = json.loads(result.stdout)
    tcp = subprocess.run(['ss', '-Htn', 'state', 'all', '( sport = :8114 or dport = :8114 )'],
        capture_output=True, text=True, check=True, timeout=10)
    # ss includes LISTEN; retain it in the receipt but only a connected socket
    # or a nonempty listen receive queue can invalidate the drained window.
    lines = [line for line in tcp.stdout.splitlines() if line.strip()]
    busy = [line for line in lines if not line.split()[0] == 'LISTEN' or line.split()[1] != '0']
    idle(inspection, busy)
    metadata = read(ROOT / 'runs/development/local_policy_service/current.json')
    identity = process(OLD_PID)
    if metadata.get('pid') != OLD_PID or not identity or identity['argv'] != metadata['argv'] or identity['cwd'] != str(ROOT):
        raise ValueError('Own8114 exact argv/cwd changed')
    source = Path(metadata['argv'][1]).resolve()
    if source != ROOT / 'scripts/serve_local_policy.py': raise ValueError('Unexpected own8114 executable script')
    reservation = no_future_dispatch(read(ROOT / QUEUE), read(ROOT / MATCHED))
    ready = health()
    if ready.get('status') != 'READY' or ready.get('pid') != OLD_PID: raise ValueError('Own8114 is not READY')
    return metadata, identity, source, ready, {'inspection': inspection, 'socket_lines': lines,
        'busy_socket_lines': busy, 'no_future_dispatch': reservation, 'at_utc': now()}


def prepare(output):
    output = output.resolve(); output.relative_to(ROOT / 'runs/development/ordinary_inference_memory_maintenance')
    if output.exists(): raise ValueError('Use a new one-shot maintenance directory')
    metadata, identity, source, ready, proof = inspect()
    output.mkdir(parents=True)
    private = ROOT / 'runtime/service_restore' / ('ordinary_inference_memory_' + output.name)
    private.mkdir(mode=0o700)
    recovery = private / 'restore.json'
    save(recovery, {'metadata': metadata, 'identity': identity, 'health': ready}, 0o600)
    (private / 'original_service.py').write_bytes(source.read_bytes()); (private / 'original_service.py').chmod(0o600)
    (output / 'calibration_source.py').write_bytes((ROOT / 'scripts/calibrate_ordinary_inference_memory.py').read_bytes())
    state = {'scope': 'development_ordinary_inference_capacity_maintenance_no_labels', 'status': 'PREPARED_NO_SIGNALS_NO_GPU',
        'prepared_at_utc': now(), 'restore_key': str(recovery), 'original_8114_pid': OLD_PID,
        'proof': proof, 'maximum_calibration_seconds': 900, 'timeout_terminate_wait_seconds': 260,
        'generation_calls_maximum': 2, 'new_model_calls_so_far': 0, 'new_physical_calls': 0, 'training_examples': 0,
        'events': [], 'signals_sent': 0, 'calibration_output': 'runs/development/ordinary_inference_memory/longest_train_BF16_v1'}
    save(output / 'operation.json', state)
    return state


def wait_calibration(child, on_timeout):
    try: return child.wait(timeout=900), False
    except subprocess.TimeoutExpired:
        child.terminate()
        on_timeout()
        return child.wait(timeout=260), True


def execute(output):
    output = output.resolve(); output.relative_to(ROOT / 'runs/development/ordinary_inference_memory_maintenance')
    state = read(output / 'operation.json')
    if state['status'] != 'PREPARED_NO_SIGNALS_NO_GPU': raise ValueError('Do not repeat an attempted operation')
    private = Path(state['restore_key']).parent; recovery = read(private / 'restore.json')
    if (private / 'restore.json').stat().st_mode & 0o077: raise ValueError('Recovery record must be private0600')
    metadata, identity, source, before, proof = inspect()
    if metadata != recovery['metadata'] or identity != recovery['identity']:
        raise ValueError('Actual original service changed since prepared recovery')
    if source.read_bytes() != (private / 'original_service.py').read_bytes(): raise ValueError('Original service source changed')
    script = ROOT / 'scripts/calibrate_ordinary_inference_memory.py'
    if script.read_bytes() != (output / 'calibration_source.py').read_bytes(): raise ValueError('Reviewed calibration source changed')
    calibration = ROOT / state['calibration_output']
    if calibration.exists(): raise ValueError('Never reexecute an existing engineering output')
    with (output / 'dispatch_reservation.json').open('x') as stream:
        json.dump({'at_utc': now(), 'pid': os.getpid(), 'own8114_only': OLD_PID}, stream)
    def event(kind, **values):
        state['events'].append({'event': kind, 'at_utc': now(), **values}); save(output / 'operation.json', state)
    state.update(status='EXECUTING_ONE_SHOT', pid=os.getpid(), started_at_utc=now(), final_drain_proof=proof)
    started = time.monotonic(); cpu = resource.getrusage(resource.RUSAGE_SELF)
    child = None; stop_requested = False
    child_cpu = None
    def child_terminate_record():
        state['signals_sent'] += 1; state['calibration_terminate_requested'] = True
        event('CALIBRATION_CHILD_SIGTERM_REQUESTED', child_pid=child.pid)
    def interrupted(signum, frame): raise InterruptedError('Supervisor received signal '+str(signum))
    previous_handler = signal.signal(signal.SIGTERM, interrupted)
    try:
        if process(OLD_PID) != identity: raise ValueError('Original service identity changed before signal')
        os.kill(OLD_PID, signal.SIGTERM); stop_requested = True; state['signals_sent'] += 1
        event('OWN8114_SIGTERM_REQUESTED', pid=OLD_PID)
        deadline = time.monotonic() + 90
        while process(OLD_PID):
            if time.monotonic() > deadline: raise TimeoutError('Own8114 stop incomplete; no second resident model launched')
            time.sleep(.5)
        event('OWN8114_ACTUALLY_STOPPED')
        request = '/srv/code-behind-layout/runs/development/matched_t0_proposal_service/fixed_16k_v1/requests/ada9c2d5-0244-4069-b9ca-188bdb9e84ce/request.json'
        adapter = ROOT / 'checkpoints/development_gpu_calibration_20261018T2330Z/development_SFT_checkpoint/adapter/policy'
        snapshot = read(ROOT / 'configs/training/backbone_cache.json')['snapshot']
        argv = [str(ROOT / 'runtime/training-venv/bin/python'), '-B', str(script), '--execute', '--request', request,
            '--engineering-adapter', str(adapter), '--snapshot', snapshot, '--output', str(calibration)]
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'OMP_NUM_THREADS': '2', 'OPENBLAS_NUM_THREADS': '2',
            'TOKENIZERS_PARALLELISM': 'false', 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'}
        with (output / 'calibration.log').open('x') as stream:
            child_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
            child = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            event('SOLE_CALIBRATION_CHILD_STARTED', child_pid=child.pid, argv=argv)
            child_started = time.monotonic(); returncode, timed_out = wait_calibration(child, child_terminate_record)
        state.update(calibration_returncode=returncode, calibration_timed_out=timed_out,
            calibration_child_wall_seconds=time.monotonic()-child_started)
        event('CALIBRATION_CHILD_ACTUALLY_EXITED', returncode=returncode, timed_out=timed_out)
        state['calibration_result'] = read(calibration / 'calibration.json') if (calibration / 'calibration.json').exists() else None
    except BaseException as exc:
        state.update(error=type(exc).__name__+': '+str(exc)); event('OPERATION_ERROR_RAW_RETAINED', error=state['error'])
    finally:
        try:
            if child is not None and child.poll() is None:
                if not state.get('calibration_terminate_requested'):
                    child.terminate(); child_terminate_record(); child.wait(timeout=260)
                if child.poll() is None:
                    raise RuntimeError('Calibration child has not exited; restoration blocked to avoid two resident models')
            if child_cpu is not None and child is not None and child.poll() is not None:
                waited = resource.getrusage(resource.RUSAGE_CHILDREN)
                state['calibration_waited_child_CPU_seconds'] = {'user': waited.ru_utime-child_cpu.ru_utime,
                    'system': waited.ru_stime-child_cpu.ru_stime}
            if stop_requested:
                if process(OLD_PID): raise RuntimeError('Original SIGTERM still pending; no second service launched')
                if source.read_bytes() != (private / 'original_service.py').read_bytes(): raise RuntimeError('Original restoration source changed')
                fresh = ROOT / 'runs/development/local_policy_service' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
                argv = list(metadata['argv']); argv[argv.index('--output')+1] = str(fresh)
                with (output / 'restored8114.log').open('x') as stream:
                    restored = subprocess.Popen(argv, cwd=identity['cwd'], env={**os.environ, **metadata['environment_overrides']},
                        stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                current = {**metadata, 'pid': restored.pid, 'argv': argv, 'output': str(fresh), 'started_at_utc': now(),
                    'replaces_pid': OLD_PID, 'restart_reason': 'Two longest-TRAIN ordinary engineering generations; exact own8114 settings restored'}
                save(ROOT / 'runs/development/local_policy_service/current.json', current)
                deadline = time.monotonic() + 300
                while True:
                    path = fresh / 'service.json'; after = read(path) if path.exists() else {}
                    if after.get('status') == 'READY': break
                    if restored.poll() is not None or time.monotonic() > deadline: raise RuntimeError('Own8114 restore did not become READY')
                    time.sleep(1)
                if any(before[key] != after[key] for key in KEYS): raise RuntimeError('Restored own8114 settings differ')
                if process(restored.pid)['argv'] != argv: raise RuntimeError('Restored own8114 argv mismatch')
                state['restored_8114_pid'] = restored.pid
                event('OWN8114_RESTORED_READY_SAME_SETTINGS', pid=restored.pid, output=str(fresh),
                    actual_restore_load_wall_seconds=after.get('load_and_grammar_wall_seconds'))
            result = state.get('calibration_result') or {}
            state['status'] = 'COMPLETED_ENGINEERING_MAINTENANCE' if not state.get('error') and result.get('status') == 'COMPLETED_TWO_ORDINARY_ENGINEERING_GENERATIONS' else 'CAPACITY_NOT_ESTABLISHED_RAW_RETAINED_SERVICE_RESTORED'
        except BaseException as exc: state.update(status='RESTORE_REQUIRED', restore_error=type(exc).__name__+': '+str(exc))
        after_cpu = resource.getrusage(resource.RUSAGE_SELF)
        state.update(ended_at_utc=now(), supervisor_wall_seconds=time.monotonic()-started,
            supervisor_user_CPU_seconds=after_cpu.ru_utime-cpu.ru_utime, supervisor_system_CPU_seconds=after_cpu.ru_stime-cpu.ru_stime)
        event('ONE_SHOT_OPERATION_TERMINAL', status=state['status'])
        signal.signal(signal.SIGTERM, previous_handler)
    return state


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare-only', action='store_true'); mode.add_argument('--execute', action='store_true')
    parser.add_argument('--output', type=Path, required=True); args = parser.parse_args()
    result = prepare(args.output) if args.prepare_only else execute(args.output)
    print(json.dumps(result, indent=2))
