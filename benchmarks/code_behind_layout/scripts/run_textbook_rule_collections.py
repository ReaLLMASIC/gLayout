"""Chain capsule, isolated calibration smoke, rule pool, freeze and launch for qualified textbook domains (E4 stage 1).

For every declared textbook domain whose nine points qualified (results/derived/textbook_train_domain_development_qualification.json):
  1. prepare_textbook_train_collection.py   -> read-only draft capsule (trusted evaluator + contracts + references)
  2. corpus_additional_capsule_smoke.py      -> one real isolated anchor evaluation + packet token fit (calibration.json)
  3. copy calibration to results/derived/<cid>_collection_draft_matrix_calibration.json (never overwritten)
  4. prepare_textbook_rule_collection.py     -> eight deterministic rule candidates (no model)
  5. freeze_textbook_train_collection.py --kind rules -> runtime/train_collections/<cid>_rules_v1 (frozen, read-only)
  6. collect_training.py --manifest ... --execute  launched detached under the shared CPU/RAM gate
Steps already done for a domain are detected and skipped, so the script is re-runnable.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import random
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts.train_collection_queue import resource_sample
PYTHON = str(ROOT / 'runtime/training-venv/bin/python')
GLDEV = str(ROOT / 'runtime/GLdev/bin/python')


def now(): return datetime.now(timezone.utc).isoformat()


def run(argv, log, cwd=ROOT, python=PYTHON):
    with open(log, 'a') as handle:
        handle.write('\n$ ' + ' '.join(argv) + '\n'); handle.flush()
        return subprocess.run([python] + argv, cwd=cwd, stdout=handle, stderr=subprocess.STDOUT, text=True).returncode


def last_json(log):
    for line in reversed(Path(log).read_text().splitlines()):
        if line.startswith('{'):
            try: return json.loads(line)
            except ValueError: pass
    return {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--domains', nargs='*', default=None, help='declared domain ids (default: every domain whose nine points qualified)')
    parser.add_argument('--max-concurrent', type=int, default=3)
    parser.add_argument('--max-containers', type=int, default=13, help='launch only while running docker containers + 2 workers stay within this count')
    parser.add_argument('--execute', action='store_true', required=True)
    args = parser.parse_args()
    out = ROOT / 'runs/train_collection_queues' / ('textbook_rules_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')); out.mkdir(parents=True)
    state = {'started_at_utc': now(), 'domains': {}, 'status': 'RUNNING'}
    def save(): (out / 'queue.json').write_text(json.dumps(state, indent=2) + '\n')
    save()
    subprocess.run([sys.executable, 'scripts/corpus_textbook_domain_summary.py'], cwd=ROOT, stdout=subprocess.DEVNULL, check=True)
    qualification = json.loads((ROOT / 'results/derived/textbook_train_domain_development_qualification.json').read_text())['circuits']
    domains = args.domains or sorted(k for k, v in qualification.items() if v.get('all_nine_points_ready'))
    launched = []
    for cid in domains:
        rec = state['domains'].setdefault(cid, {'steps': {}})
        log = out / (cid + '.log')
        if not qualification.get(cid, {}).get('all_nine_points_ready'):
            rec['status'] = 'NOT_QUALIFIED'; save(); continue
        collection = ROOT / 'runtime/train_collections' / (cid.lower() + '_rules_v1/collection.json')
        if not collection.exists():
            preps = sorted((ROOT / 'runtime/collection_preparation').glob(cid.lower() + '_collection_2*/preparation.json'))
            if not preps:
                if run(['scripts/prepare_textbook_train_collection.py', '--domain', cid], log, python=GLDEV): rec['status'] = 'FAILED_capsule'; save(); continue
                preps = sorted((ROOT / 'runtime/collection_preparation').glob(cid.lower() + '_collection_2*/preparation.json'))
            prep = preps[-1]; rec['steps']['capsule'] = str(prep)
            calibration = ROOT / 'results/derived' / (cid.lower() + '_collection_draft_matrix_calibration.json')
            if not calibration.exists():
                if run(['scripts/corpus_additional_capsule_smoke.py', '--preparation', str(prep)], log): rec['status'] = 'FAILED_calibration_smoke'; rec['steps']['smoke'] = last_json(log); save(); continue
                report = last_json(log)
                shutil.copyfile(Path(report['result_path']).parent / 'calibration.json', calibration)
            rec['steps']['calibration'] = str(calibration)
            rules = sorted((ROOT / 'runtime/collection_preparation').glob(cid.lower() + '_rule_collection_2*/preparation.json'))
            if not rules:
                if run(['scripts/prepare_textbook_rule_collection.py', '--preparation', str(prep)], log): rec['status'] = 'FAILED_rule_pool'; save(); continue
                rules = sorted((ROOT / 'runtime/collection_preparation').glob(cid.lower() + '_rule_collection_2*/preparation.json'))
            rec['steps']['rule_pool'] = str(rules[-1])
            if run(['scripts/freeze_textbook_train_collection.py', '--preparation', str(rules[-1]), '--kind', 'rules'], log): rec['status'] = 'FAILED_freeze'; save(); continue
        rec['steps']['collection'] = str(collection)
        output_root = ROOT / 'runs/train_collection' / (cid.lower() + '_rules_v1')
        if (output_root / 'completion.json').exists() or output_root.exists():
            rec['status'] = 'ALREADY_LAUNCHED_OR_COMPLETE'; save(); continue
        deadline = time.monotonic() + 7200
        lock = open(ROOT / 'runs/train_collection_queues/launch.lock', 'a')
        while True:
            fcntl.flock(lock, fcntl.LOCK_EX)
            resources = resource_sample(); active = sum(1 for p in launched if p.poll() is None)
            containers = subprocess.run(['docker', 'ps', '-q'], capture_output=True, text=True).stdout.count('\n'); resources['running_containers'] = containers
            if (active < args.max_concurrent and containers + 2 <= args.max_containers and resources['actual_busy_cores'] + 2 <= 24
                    and resources['RAM_used_GiB'] <= 190 and resources.get('available_disk_GiB', 99) >= 4): break
            if time.monotonic() > deadline: rec['status'] = 'GATE_TIMEOUT'; save(); break
            fcntl.flock(lock, fcntl.LOCK_UN); time.sleep(30 + random.uniform(0, 20))
        if rec.get('status') == 'GATE_TIMEOUT': fcntl.flock(lock, fcntl.LOCK_UN); lock.close(); continue
        handle = open(out / (cid + '_collection.log'), 'w')
        process = subprocess.Popen([PYTHON, str(ROOT / 'scripts/collect_training.py'), '--manifest', str(collection), '--execute'], cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT,
                                   env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'OMP_NUM_THREADS': '2'}, start_new_session=True)
        time.sleep(75); fcntl.flock(lock, fcntl.LOCK_UN); lock.close()  # containers are up before the next orchestrator samples the gate
        launched.append(process); rec.update(status='LAUNCHED', pid=process.pid, launched_at_utc=now(), resources_before_launch=resources); save()
    for process in launched: process.wait()
    for cid, rec in state['domains'].items():
        if rec.get('status') == 'LAUNCHED':
            completion = ROOT / 'runs/train_collection' / (cid.lower() + '_rules_v1/completion.json')
            rec['completion'] = json.loads(completion.read_text()) if completion.exists() else None
            rec['status'] = 'COLLECTION_' + str((rec['completion'] or {}).get('status'))
    state.update(status='DONE', ended_at_utc=now()); save()
    print(json.dumps({cid: rec.get('status') for cid, rec in state['domains'].items()}))


if __name__ == '__main__':
    main()
