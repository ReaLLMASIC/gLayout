"""One two-CPU development worker per queue: qualify a textbook train domain anchor first, then its eight development points."""
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

MAX_CONTAINERS = 13  # two-CPU containers; 26 logical cores
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts.train_collection_queue import resource_sample

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--circuits', nargs='+', required=True, help='declared domain ids, e.g. C03 or C03_cfg1')
parser.add_argument('--anchor-only', action='store_true', help='stop after the anchor controls (smoke run)')
parser.add_argument('--prelayout-only', action='store_true', help='schematic controls only, no layout')
args = parser.parse_args()
import re
for domain in args.circuits:
    if not re.fullmatch(r'C\d\d(_cfg\d)?', domain) or not (ROOT / 'configs/development' / (domain.lower() + '_family/configurations.json')).is_file(): raise SystemExit('undeclared domain ' + domain)
out = ROOT / 'runs/development/textbook_train_domain_qualification' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'); out.mkdir(parents=True)
state = {'scope': 'development_only_single_worker_original_compiler_qualification', 'circuits': args.circuits,
         'started_at_utc': datetime.now(timezone.utc).isoformat(), 'jobs': [], 'source_lineages': 1, 'formal_training_rows': 0, 'status': 'RUNNING'}
def save(): (out / 'batch.json').write_text(json.dumps(state, indent=2) + '\n')
save()


def job(cid, identifier, prelayout):
    deadline = time.monotonic() + 8 * 3600
    label = cid + '_' + identifier + ('_prelayout' if prelayout else '_post_RC')
    for earlier in sorted(ROOT.glob('runs/development/textbook_train_domain_qualification/*/batch.json')):
        if earlier.resolve() == (out / 'batch.json').resolve(): continue
        for done in json.loads(earlier.read_text()).get('jobs', []):
            if ((done.get('circuit_id'), done.get('configuration_id'), done.get('prelayout')) == (cid, identifier, prelayout) and done.get('returncode') == 0
                    and (prelayout or (done.get('full_physical_analysis_complete') and done.get('DRC_clean') and done.get('LVS_clean')))):
                record = {**done, 'reused_from_batch': str(earlier), 'reused': True}; state['jobs'].append(record); save(); print(json.dumps(record), flush=True); return True
    while True:
        resources = resource_sample()
        containers = subprocess.run(['docker', 'ps', '-q'], capture_output=True, text=True).stdout.count('\n')
        if containers + 1 <= MAX_CONTAINERS and resources['actual_busy_cores'] + 2 <= 24 and resources['RAM_used_GiB'] <= 190: break
        if time.monotonic() > deadline: raise TimeoutError('Actual CPU/RAM/container dispatch gate remained occupied for eight hours; no additional worker launched')
        time.sleep(15)
    argv = ['python3', 'scripts/run_eda_probe.py', '--script', 'corpus_textbook_train_pilot.py', '--magic-runtime', 'magic-8.3.685', '--timeout', '1200', '--',
            '--table', '/work/configs/development/' + cid.lower() + '_family/configurations.json', '--configuration-id', identifier]
    if prelayout: argv.append('--prelayout-only')
    record = {'circuit_id': cid, 'configuration_id': identifier, 'prelayout': prelayout, 'argv': argv, 'resources_before_start': resources, 'started_at_utc': datetime.now(timezone.utc).isoformat()}
    with (out / (label + '.log')).open('w') as log: ran = subprocess.run(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    first = (out / (label + '.log')).read_text().splitlines()[0]; directory = Path(json.loads(first)['output'])
    record.update(returncode=ran.returncode, run_directory=str(directory), ended_at_utc=datetime.now(timezone.utc).isoformat())
    path = directory / 'bench_result.json'; data = json.loads(path.read_text()) if path.exists() else {}
    record.update(all_analyses_complete=data.get('all_analyses_complete', False), all_operating_points_valid=data.get('all_operating_points_valid', False),
                  full_physical_analysis_complete=data.get('full_physical_analysis_complete', False),
                  DRC_clean=(data.get('DRC') or {}).get('is_clean'), LVS_clean=(data.get('LVS') or {}).get('is_clean'),
                  positive_RC=(data.get('RC') or {}).get('has_real_RC'), area_um2=data.get('area_um2'))
    state['jobs'].append(record); save(); print(json.dumps(record), flush=True)
    return ran.returncode == 0


try:
    qualified = []
    for cid in args.circuits:
        ok = job(cid, 'anchor', True)
        if ok and not args.prelayout_only: ok = job(cid, 'anchor', False)
        if ok: qualified.append(cid)
    if not args.anchor_only:
        for cid in qualified:
            table = json.loads((ROOT / 'configs/development' / (cid.lower() + '_family/configurations.json')).read_text())
            for point in table['configurations']:
                if point['configuration_id'] != 'anchor': job(cid, point['configuration_id'], args.prelayout_only)
    state.update(status='COMPLETED_QUALIFICATION_ATTEMPTS', qualified_anchors=qualified, ended_at_utc=datetime.now(timezone.utc).isoformat()); save()
except Exception as exc:
    state.update(status='PAUSED', reason=type(exc).__name__ + ': ' + str(exc), ended_at_utc=datetime.now(timezone.utc).isoformat()); save(); raise
