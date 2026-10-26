"""Declare, freeze and launch multi-state textbook collections (E4 stage 2) under the shared CPU/RAM gate.

For every domain with a frozen parent rule collection runtime/train_collections/<domain>_rules_v1:
  1. prepare_textbook_variant_states.py --kind <lattice|faults>  -> read-only draft (states + rule proposer)
  2. freeze_textbook_multistate_collection.py                     -> runtime/train_collections/<domain>_<kind>_v1
  3. collect_training_v2.py --manifest ... --execute               launched detached when the gate admits it
Steps already done are detected and skipped; the queue record is runs/train_collection_queues/textbook_<kind>_<ts>/queue.json.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import random
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts.train_collection_queue import resource_sample
PYTHON = str(ROOT / 'runtime/training-venv/bin/python')


def now(): return datetime.now(timezone.utc).isoformat()


def run(argv, log):
    with open(log, 'a') as handle:
        handle.write('\n$ ' + ' '.join(argv) + '\n'); handle.flush()
        return subprocess.run([PYTHON] + argv, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, text=True).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=['lattice', 'faults', 'faults_extra', 'faults_more', 'faults_more2'], required=True)
    parser.add_argument('--domains', nargs='+', required=True)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--collection-version', default='v1')
    parser.add_argument('--refresh-trusted', action='store_true')
    parser.add_argument('--max-concurrent', type=int, default=3)
    parser.add_argument('--gate-hours', type=float, default=24)
    parser.add_argument('--max-containers', type=int, default=13, help='launch only while running docker containers + this collection\'s workers stay within this count (two CPUs each)')
    parser.add_argument('--execute', action='store_true', required=True)
    args = parser.parse_args()
    out = ROOT / 'runs/train_collection_queues' / ('textbook_' + args.kind + '_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')); out.mkdir(parents=True)
    state = {'started_at_utc': now(), 'kind': args.kind, 'workers': args.workers, 'domains': {}, 'status': 'RUNNING'}
    def save(): (out / 'queue.json').write_text(json.dumps(state, indent=2) + '\n')
    save(); launched = []
    for cid in args.domains:
        dom = cid.lower(); rec = state['domains'].setdefault(cid, {'steps': {}}); log = out / (cid + '.log')
        parent = ROOT / 'runtime/train_collections' / (dom + '_rules_v1/collection.json')
        if not parent.exists(): rec['status'] = 'NO_PARENT_RULE_COLLECTION'; save(); continue
        collection = ROOT / 'runtime/train_collections' / (dom + '_' + args.kind + '_' + args.collection_version + '/collection.json')
        if not collection.exists():
            preps = sorted((ROOT / 'runtime/collection_preparation').glob(dom + '_' + args.kind + '_' + args.collection_version + '_2*/preparation.json'))
            if not preps:
                if run(['scripts/prepare_textbook_variant_states.py', '--domain', cid, '--kind', args.kind, '--workers', str(args.workers), '--collection-version', args.collection_version], log): rec['status'] = 'FAILED_declare'; save(); continue
                preps = sorted((ROOT / 'runtime/collection_preparation').glob(dom + '_' + args.kind + '_' + args.collection_version + '_2*/preparation.json'))
            rec['steps']['declaration'] = str(preps[-1])
            if run(['scripts/freeze_textbook_multistate_collection.py', '--preparation', str(preps[-1])] + (['--refresh-trusted'] if args.refresh_trusted else []), log): rec['status'] = 'FAILED_freeze'; save(); continue
        rec['steps']['collection'] = str(collection)
        output_root = ROOT / 'runs/train_collection' / (dom + '_' + args.kind + '_' + args.collection_version)
        if output_root.exists(): rec['status'] = 'ALREADY_LAUNCHED_OR_COMPLETE'; save(); continue
        deadline = time.monotonic() + args.gate_hours * 3600
        lock = open(ROOT / 'runs/train_collection_queues/launch.lock', 'a')
        while True:
            fcntl.flock(lock, fcntl.LOCK_EX)
            resources = resource_sample(); active = sum(1 for p in launched if p.poll() is None)
            containers = int(subprocess.run(['docker', 'ps', '-q'], capture_output=True, text=True).stdout.count('\n')); resources['running_containers'] = containers
            if (active < args.max_concurrent and containers + args.workers <= args.max_containers and resources['actual_busy_cores'] + 2 <= 24
                    and resources['RAM_used_GiB'] <= 190 and resources.get('available_disk_GiB', 99) >= 4): break
            if time.monotonic() > deadline: rec['status'] = 'GATE_TIMEOUT'; save(); break
            fcntl.flock(lock, fcntl.LOCK_UN); time.sleep(30 + random.uniform(0, 20))
        if rec.get('status') == 'GATE_TIMEOUT': fcntl.flock(lock, fcntl.LOCK_UN); lock.close(); continue
        handle = open(out / (cid + '_collection.log'), 'w')
        process = subprocess.Popen([PYTHON, str(ROOT / 'scripts/collect_training_v2.py'), '--manifest', str(collection), '--execute'], cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT,
                                   env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'OMP_NUM_THREADS': '2'}, start_new_session=True)
        time.sleep(75); fcntl.flock(lock, fcntl.LOCK_UN); lock.close()  # containers are up before the next orchestrator samples the gate
        launched.append(process); rec.update(status='LAUNCHED', pid=process.pid, launched_at_utc=now(), resources_before_launch=resources); save()
    for process in launched: process.wait()
    for cid, rec in state['domains'].items():
        if rec.get('status') == 'LAUNCHED':
            completion = ROOT / 'runs/train_collection' / (cid.lower() + '_' + args.kind + '_' + args.collection_version + '/completion.json')
            rec['completion'] = json.loads(completion.read_text()) if completion.exists() else None
            rec['status'] = 'COLLECTION_' + str((rec['completion'] or {}).get('status'))
    state.update(status='DONE', ended_at_utc=now()); save()
    print(json.dumps({cid: rec.get('status') for cid, rec in state['domains'].items()}))


if __name__ == '__main__': main()
