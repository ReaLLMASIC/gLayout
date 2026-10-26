"""Finite maintenance for queue1728183 and three explicitly bound GPT parents."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.quiesce_gpt_teacher_collection import process, collector, boundary, same_process, tcp_requests

QUEUE = 1728183
COLLECTORS = {1456983: 'c01', 1954893: 'c05', 2076669: 'c07'}
EXPECTED_START_TICKS = {1728183: '220474015', 1456983: '220144144',
                        1954893: '220686373', 2076669: '220771452'}


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.pending')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(value, stream, indent=2, allow_nan=False); stream.write('\n')
    temporary.replace(path); path.chmod(0o600)


def inspect_collectors():
    result = []
    for path in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            if path.stat().st_uid != os.getuid():
                continue
            argv = [value.decode() for value in path.read_bytes().split(b'\0') if value]
            if len(argv) < 2 or Path(argv[1]).name not in ['collect_training.py', 'run_frozen_training_collection.py']:
                continue
            if Path(argv[1]).is_absolute() and Path(argv[1]) not in [ROOT / 'scripts/collect_training.py',
                                                                  ROOT / 'scripts/run_frozen_training_collection.py']:
                continue
            item = process(int(path.parent.name))
            if item:
                found = collector(item)
                if found:
                    found['boundary'] = boundary(found['output']); result.append(found)
        except (FileNotFoundError, ProcessLookupError):
            continue
    return sorted(result, key=lambda row: row['pid'])


def health(timeout=2):
    rows = []
    for port in [8115, 8116]:
        with urllib.request.urlopen('http://127.0.0.1:' + str(port) + '/transport-health', timeout=timeout) as stream:
            data = json.load(stream)
        rows.append({'port': port, **{key: data.get(key) for key in
            ['status', 'global_teacher_slots', 'active_forwards', 'context16384_route_enabled',
             'literal_span_route_enabled', 'started_at_utc']}})
    return rows


def ready_health(rows):
    return all(row['status'] == 'READY' and row['global_teacher_slots'] == 2
               and row['context16384_route_enabled'] is True for row in rows)


def status(record_path, health_timeout=2):
    record = read(record_path); live = []
    for row in record['processes']:
        current = process(row['pid'])
        if not same_process(row, current) or current['state'] not in ['T', 't']:
            raise ValueError('An exact recorded parent is no longer stopped; no drain claim')
        live.append(current)
    collectors = inspect_collectors()
    initial = {row['pid']: row for row in record['initial_collectors']}
    for row in collectors:
        if row['pid'] in initial and any(row[key] != initial[row['pid']][key]
                                         for key in ['manifest', 'output', 'backend', 'sampling_mode']):
            raise ValueError('Original collector manifest/output binding changed')
    unexpected = [row for row in collectors if row['pid'] not in COLLECTORS]
    boundaries = [row['boundary'] for row in collectors]
    connections = tcp_requests()  # Inspect before these short health GETs.
    transport = health(health_timeout)
    ready = (len(live) == 4 and len(collectors) == 3 and not unexpected
             and all(row['safe_eight_trial_boundary'] for row in boundaries)
             and not connections and ready_health(transport)
             and all(row['active_forwards'] == 0 for row in transport))
    return {'at_utc': now(), 'ready_for_root_local_paired_drain': ready,
            'exact_stopped_parents': live, 'collectors': collectors,
            'unexpected_collectors': unexpected, 'remote_TCP_requests': connections,
            'remote_transport_health': transport, 'signals_sent': False,
            'whole96trial_collection_complete_not_claimed': True}


def restore(record_path, reason, require_health=True):
    lock = Path(record_path).with_suffix('.restore.lock')
    with lock.open('a') as stream:
        lock.chmod(0o600); fcntl.flock(stream, fcntl.LOCK_EX)
        record = read(record_path)
        if record['status'] in ['RESTORED', 'ABORTED_RESTORED']:
            return record
        if require_health:
            proof = health()
            if not ready_health(proof):
                raise ValueError('Old/new gate must be READY, global2, context16ktrue before restore')
            record['restore_transport_health'] = proof
        for row in sorted(record['processes'], key=lambda row: row['pid'] == QUEUE):
            if not row['changed_by_this_operation'] or row.get('continued_at_utc'):
                continue
            current = process(row['pid'])
            if not same_process(row, current) or current['state'] not in ['T', 't']:
                raise ValueError('Exact PID/argv/cwd/startticks changed or already resumed')
            os.kill(row['pid'], signal.SIGCONT)
            row['continued_at_utc'] = now()
            row['administrative_pause_wall_seconds'] = time.time() - row['stopped_epoch_s']
            save(record_path, record)
        record.update(status='ABORTED_RESTORED' if reason.startswith('ABORT') else 'RESTORED',
                      restore_reason=reason, restored_at_utc=now(),
                      physical_children_T0_brokers_gate_not_signalled=True)
        save(record_path, record)
        return record


def watchdog(record_path):
    record = read(record_path)
    delay = max(0, record['automatic_restore_deadline_epoch_s'] - time.time())
    time.sleep(delay)
    try:
        return restore(record_path, 'FIVE_MINUTE_LIMIT_WITH_HEALTHY_OLD_OR_NEW_CONTEXT16K_GATE')
    except Exception as error:
        record = read(record_path)
        record['automatic_restore_blocked'] = {'at_utc': now(), 'error': type(error).__name__ + ': ' + str(error)}
        save(record_path, record)
        return record


def prepare(record_path):
    record_path = Path(record_path)
    if record_path.exists():
        raise ValueError('This maintenance recovery record already exists; do not repeat')
    deadline = time.monotonic() + 60
    queue = process(QUEUE); collectors = inspect_collectors()
    if (not queue or queue['start_ticks'] != EXPECTED_START_TICKS[QUEUE]
            or Path(queue['cwd']) != ROOT or len(queue['argv']) < 3
            or (Path(queue['argv'][1]) if Path(queue['argv'][1]).is_absolute()
                else ROOT / queue['argv'][1]).resolve() != ROOT / 'scripts/train_collection_queue.py'
            or '--execute' not in queue['argv']):
        raise ValueError('Authorized exact queue is not the research execute queue')
    if {row['pid'] for row in collectors} != set(COLLECTORS):
        raise ValueError('Actual GPT collector inventory differs from the three authorized parents')
    for row in collectors:
        if row['start_ticks'] != EXPECTED_START_TICKS[row['pid']]:
            raise ValueError('Explicitly authorized collector startticks changed')
        if COLLECTORS[row['pid']] not in row['manifest'].lower():
            raise ValueError('Current collector manifest does not identify the authorized C05/C07 scope')
    record = {'scope': 'One bounded shared-train-GPT-gate maintenance; no physical/model dispatch',
              'status': 'INSPECTED_BEFORE_SIGNALS', 'started_at_utc': now(),
              'initial_queue': queue, 'initial_collectors': collectors,
              'processes': [], 'events': [], 'paired_remote_proofs': [],
              'no_Docker_physical_T0_gate_or_broker_signals': True,
              'excluded_signal_PIDs': [84545, 38052, 48730, 83336],
              'whole96trial_collection_complete_not_claimed': True}
    save(record_path, record)

    def stop(item):
        current = process(item['pid'])
        if not same_process(item, current):
            raise ValueError('Exact target changed before individual SIGSTOP')
        row = {**item, 'original_state': current['state'],
               'changed_by_this_operation': current['state'] not in ['T', 't'],
               'stop_requested_at_utc': now(), 'stopped_epoch_s': time.time()}
        record['processes'].append(row); save(record_path, record)
        if row['changed_by_this_operation']:
            os.kill(row['pid'], signal.SIGSTOP)
        for _ in range(20):
            current = process(row['pid'])
            if same_process(row, current) and current['state'] in ['T', 't']:
                return row
            time.sleep(.01)
        raise RuntimeError('Individual exact parent did not stop')

    try:
        stop(queue)
        record['automatic_restore_deadline_epoch_s'] = record['processes'][0]['stopped_epoch_s'] + 300
        save(record_path, record)
        while time.monotonic() < deadline:
            for item in collectors:
                if any(row['pid'] == item['pid'] for row in record['processes']):
                    continue
                if not same_process(item, process(item['pid'])):
                    raise ValueError('Original collector identity changed while waiting')
                before = boundary(item['output'])
                if before['safe_eight_trial_boundary']:
                    row = stop(item); after = boundary(item['output'])
                    row['boundary_after_stop'] = after
                    if not after['safe_eight_trial_boundary']:
                        if row['changed_by_this_operation']:
                            os.kill(row['pid'], signal.SIGCONT)
                        record['processes'].remove(row)
                        record['events'].append({'at_utc': now(), 'event': 'BOUNDARY_RACE_RESTORED', 'pid': item['pid']})
                    save(record_path, record)
            if len(record['processes']) == 4:
                remaining = deadline - time.monotonic()
                if remaining <= .1:
                    break
                proof = status(record_path, min(2, remaining / 4))
                record['paired_remote_proofs'].append(proof); save(record_path, record)
                last = record['paired_remote_proofs'][-3:]
                if len(last) == 3 and all(row['ready_for_root_local_paired_drain'] for row in last):
                    record.update(status='PARENTS_QUIESCED', quiesced_at_utc=now())
                    save(record_path, record)
                    log = record_path.with_suffix('.watchdog.log').open('x')
                    log_path = record_path.with_suffix('.watchdog.log'); log_path.chmod(0o600)
                    argv = [sys.executable, str(Path(__file__).resolve()), 'watchdog', '--record', str(record_path)]
                    child = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log,
                                             stderr=subprocess.STDOUT, start_new_session=True)
                    record['five_minute_watchdog'] = {'pid': child.pid, 'argv': argv, 'log': str(log_path)}
                    save(record_path, record)
                    return record
            time.sleep(min(2, max(0, deadline - time.monotonic())))
        raise TimeoutError('The fixed60second actual boundary/drain horizon expired')
    except Exception as error:
        latest = read(record_path); latest['aborted_error'] = type(error).__name__ + ': ' + str(error)
        save(record_path, latest)
        return restore(record_path, 'ABORT_BOUNDARY_OR_DRAIN_NOT_READY_WITHIN60S', require_health=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'status', 'restore', 'watchdog'])
    parser.add_argument('--record', type=Path, required=True)
    args = parser.parse_args()
    result = (prepare(args.record) if args.operation == 'prepare' else status(args.record)
              if args.operation == 'status' else restore(args.record, 'ROOT_EXPLICIT_RESTORE')
              if args.operation == 'restore' else watchdog(args.record))
    print(json.dumps(result, allow_nan=False), flush=True)
