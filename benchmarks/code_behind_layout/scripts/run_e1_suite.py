"""Run the frozen E1 matrix with bounded parallelism and no automatic trial retries."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import random
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.e1_matched_runner import SSH,REMOTE


def now(): return datetime.now(timezone.utc).isoformat()


def save(filename, value):
    temporary = filename.with_suffix(filename.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temporary.replace(filename)


def plan(manifest):
    if manifest['status'] != 'FROZEN_E1' or manifest['formal_dispatch'] is not True:
        raise ValueError('The full formal suite requires the actual E1-only freeze')
    if len(manifest['tasks']) != 24 or len(set(manifest['task_ids'])) != 24:
        raise ValueError('The frozen task matrix must contain exactly 24 tasks')
    if {row['task_id'] for row in manifest['tasks']} != set(manifest['task_ids']):
        raise ValueError('Task metadata and dispatch identities disagree')
    if manifest['methods'] != ['G0', 'G1', 'G2'] or manifest['trials'] != 5:
        raise ValueError('Formal E1 has exactly three methods and five trials')
    if manifest['runtime']['candidate_CPUs'] != 2:
        raise ValueError('The shared per-episode physical worker budget changed')
    if not Path(manifest['backend_manifest_path']).is_absolute():
        raise ValueError('The freeze must name its actual trusted-endpoint manifest')
    rng = random.Random(manifest['dispatch_order_seed'])
    blocks = [(task, trial) for task in sorted(manifest['task_ids']) for trial in range(1, 6)]
    rng.shuffle(blocks)
    jobs = []
    for task, trial in blocks:
        methods = list(manifest['methods']); rng.shuffle(methods)
        jobs.extend({'task_id': task, 'method': method, 'trial_id': str(trial), 'status': 'NOT_RUN'} for method in methods)
    return jobs


def resources():
    code = '''import json,os,time
from pathlib import Path
def cpu():return [int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
a=cpu();time.sleep(1);b=cpu();d=[y-x for x,y in zip(a,b)]
m={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemTotal:','MemAvailable:'))}
disk=os.statvfs('/srv/code-behind-layout')
print(json.dumps({'busy_cores':os.cpu_count()*(1-(d[3]+d[4])/sum(d)),'RAM_used_GiB':(m['MemTotal']-m['MemAvailable'])/2**30,'disk_available_GiB':disk.f_bavail*disk.f_frsize/2**30}))
'''
    result = subprocess.run(SSH + ['python3 -c ' + shlex.quote(code)], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(result.stdout)


def alive(job):
    result = subprocess.run(['ps', '-p', str(job['pid']), '-o', 'command='], capture_output=True, text=True)
    return result.returncode == 0 and 'e1_matched_runner.py' in result.stdout and job['dispatch_record'] in result.stdout


def collect(job):
    filename = Path(job['dispatch_record'])
    if filename.exists():
        client = json.loads(filename.read_text())
        identity = (client['task_id'], client['method'], str(client['trial_id']))
        if identity != (job['task_id'], job['method'], job['trial_id']) or client['formal'] is not True:
            raise ValueError('A child result does not belong to its declared formal trial')
        job.update(episode_directory=client['episode_directory'], local_output_directory=client['local_output_directory'])
        episode = Path(client['local_output_directory']) / 'episode.json'
        if episode.exists():
            row = json.loads(episode.read_text())
            if row['phase'] != 'formal_E1' or (row['task_id'], row['method'], str(row['trial_id'])) != identity:
                raise ValueError('Episode report identity or experiment phase changed')
            job.update(status='RECORDED', episode_json=str(episode), ended_at_utc=now())
            return
    job.update(status='UNRESOLVED_PROCESS_EXIT', ended_at_utc=now(),
               reason='Retain all raw records; an interrupted formal trial is never automatically repeated')


def archive_evidence(job):
    command='python3 '+shlex.quote(REMOTE+'/scripts/archive_e1_episode.py')+' --episode '+shlex.quote(job['episode_directory'])
    result=subprocess.run(SSH+[command],capture_output=True,text=True,check=True)
    record=json.loads(result.stdout)
    if record['status']!='COMPRESSED_RAW_RETAINED' or record['hidden_evidence_exported'] is not False:
        raise ValueError('Completed private evidence archive was not established')
    job['evidence_archive']=record


def run(args):
    manifest_path = args.manifest.resolve(); manifest = json.loads(manifest_path.read_text())
    jobs = plan(manifest)
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    with (out / 'coordinator.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state_file = out / 'state.json'
        if state_file.exists():
            state = json.loads(state_file.read_text())
            if state['freeze_id'] != manifest['freeze_id'] or state['manifest'] != str(manifest_path):
                raise ValueError('Resume must use exactly the same E1 freeze')
            jobs = state['jobs']
            if [(j['task_id'], j['method'], j['trial_id']) for j in jobs] != [(j['task_id'], j['method'], j['trial_id']) for j in plan(manifest)]:
                raise ValueError('The original fixed dispatch order changed')
        else:
            state = {'status': 'RUNNING', 'freeze_id': manifest['freeze_id'], 'manifest': str(manifest_path),
                     'created_at_utc': now(), 'jobs': jobs, 'formal_episodes_planned': 360}
        state.update(coordinator_pid=os.getpid(), maximum_simultaneous_episodes=args.workers,
                     resource_rule='Each episode retains one 2-CPU worker; new launch requires actual busy+2<=24 and RAM used<=190GiB',
                     automatic_retry=False)
        children = {}; logs = {}
        while True:
            active = []
            for index, job in enumerate(jobs):
                if job['status'] != 'RUNNING': continue
                process = children.get(index)
                running = process.poll() is None if process is not None else alive(job)
                if running: active.append(index); continue
                if process is not None:
                    job['waited_returncode'] = process.returncode; logs.pop(index).close()
                else: job['waited_returncode'] = None
                collect(job)
                if job['status']=='RECORDED':
                    try:archive_evidence(job)
                    except (OSError,ValueError,subprocess.CalledProcessError) as error:
                        job.update(status='ARCHIVE_PAUSED',archive_error=str(error))
            unresolved = any(j['status'] in ('UNRESOLVED_PROCESS_EXIT','ARCHIVE_PAUSED') for j in jobs)
            pause = (out / 'PAUSE_REQUESTED').exists() or unresolved
            pending = next((i for i, j in enumerate(jobs) if j['status'] == 'NOT_RUN'), None)
            if pending is None and not active:
                state['status'] = 'PAUSED_UNRESOLVED' if unresolved else 'COMPLETED'; break
            if pause and not active: state['status'] = 'PAUSED'; break
            if not pause and pending is not None and len(active) < args.workers:
                sample = resources(); state['last_resource_sample'] = {**sample, 'at_utc': now()}
                if sample['disk_available_GiB']<4 and not active:
                    state['status']='PAUSED_STORAGE_CAPACITY'; break
                if sample['busy_cores'] + 2 <= 24 and sample['RAM_used_GiB'] <= 190 and sample['disk_available_GiB']>=4:
                    job = jobs[pending]; folder = out / ('%03d_%s_%s_%s' % (pending, job['task_id'], job['method'], job['trial_id']))
                    folder.mkdir(); record = folder / 'client.json'; log = (folder / 'runner.log').open('x')
                    command = [sys.executable, str(ROOT / 'scripts/e1_matched_runner.py'), '--manifest', manifest['backend_manifest_path'],
                               '--task', job['task_id'], '--method', job['method'], '--trial', job['trial_id'], '--formal', '--dispatch-record', str(record)]
                    process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                        env={**os.environ, 'TOKENIZERS_PARALLELISM': 'false', 'OMP_NUM_THREADS': '1'})
                    job.update(status='RUNNING', pid=process.pid, argv=command, started_at_utc=now(),
                               dispatch_record=str(record), resources_before_launch=sample)
                    children[pending] = process; logs[pending] = log
            state.update(updated_at_utc=now(), jobs=jobs); save(state_file, state)
            index = [{k:j[k] for k in ('task_id','method','trial_id','episode_json')} for j in jobs if 'episode_json' in j]
            (out / 'episode_index.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in index))
            time.sleep(5)
        state.update(updated_at_utc=now(), coordinator_pid=None, jobs=jobs); save(state_file, state)
        index = [{k:j[k] for k in ('task_id','method','trial_id','episode_json')} for j in jobs if 'episode_json' in j]
        (out / 'episode_index.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in index))
        print(json.dumps({'status':state['status'],'planned':360,'recorded':len(index),'output':str(out)}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--workers', type=int, choices=[1,2,3,4], default=4)
    run(p.parse_args())
