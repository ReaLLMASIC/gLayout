"""Dispatch or adopt the declared train pools and independent baselines into free CPU slots."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "runtime/training-venv/bin/python"
PREP = "runtime/task_preparation/independent_20261019T014450461270Z"


def cpu_sample():
    return list(map(int, Path("/proc/stat").read_text().splitlines()[0].split()[1:9]))


class AdoptedProcess:
    def __init__(self,pid):self.pid=pid
    def poll(self):
        try:
            state=Path('/proc/'+str(self.pid)+'/stat').read_text().split(') ',1)[1].split()[0]
            return -999 if state=='Z' else None
        except FileNotFoundError:return -999


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--resume',type=Path);p.add_argument('--max-active',type=int,default=3);a=p.parse_args()
    if not 1<=a.max_active<=8:raise ValueError('This study has eight declared child jobs')
    directory = a.resume.resolve() if a.resume else ROOT / "runs/development/parallel_train_qualification" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if not a.resume:directory.mkdir(parents=True)
    jobs = []
    for cid in ["c01", "c05", "c08"]:
        jobs.append({"name": cid + "_rules_v1", "cores": 2,
            "argv": [str(PYTHON), "scripts/collect_training.py", "--manifest",
                     "runtime/train_collections/" + cid + "_rules_v1/collection.json", "--execute"]})
    jobs.append({"name": "cascode_remaining", "cores": 2,
        "argv": ["python3", "scripts/independent_task_baseline.py", "--resume",
            "runs/development/independent_baselines/cascode_mirror_20261019T015834876469Z_24d091e7", "--mode", "remaining", "--workers", "1"]})
    for kind in ["source_follower", "stacked_switch", "common_source_stage", "resistive_diff"]:
        jobs.append({"name": kind + "_domain", "cores": 2,
            "argv": ["python3", "scripts/independent_task_baseline.py", "--preparation", PREP,
                     "--kind", kind, "--mode", "all", "--workers", "1"]})
    active, finished, samples = {}, [], []
    pending = list(jobs)
    if a.resume:
        old=json.loads((directory/'state.json').read_text());pending=old['pending'];finished=old['finished']
        for job in old['active']:
            pid=job['pid'];process=AdoptedProcess(pid)
            if process.poll() is None:
                command=Path('/proc/'+str(pid)+'/cmdline').read_bytes().split(b'\0')
                if [part.decode() for part in command if part]!=job['argv']:
                    raise ValueError('Existing child command differs from the declared study job')
            job['adopted_at_utc']=datetime.now(timezone.utc).isoformat()
            active[job['name']]={'process':process,'log':None,'job':job}
        with (directory/'dispatch_adjustments.jsonl').open('a') as stream:
            stream.write(json.dumps({'at_utc':datetime.now(timezone.utc).isoformat(),'reason':'User-requested parallel development execution; preserve running children and per-job frozen budgets',
                'max_active_children':a.max_active,'adopted_pids':[item['job']['pid'] for item in active.values()],'previous_state':old})+'\n')
    while pending or active:
        for name, item in list(active.items()):
            status = item["process"].poll()
            if status is not None:
                if item['log'] is not None:item["log"].close()
                finished.append({**item["job"], "returncode": None if status==-999 else status,
                    'exit_status_scope':'Adopted child ended; consult its actual completion/state artifact' if status==-999 else 'waited child exit status',
                    "finished_at_utc": datetime.now(timezone.utc).isoformat()})
                del active[name]
        first = cpu_sample()
        time.sleep(1)
        second = cpu_sample()
        delta = [b-a for a,b in zip(first,second)]
        busy = os.cpu_count() * (1 - (delta[3]+delta[4]) / sum(delta))
        available = next(int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:")) / 2**20
        samples.append({"at_utc": datetime.now(timezone.utc).isoformat(), "busy_cores": busy, "available_GiB": available})
        if pending and len(active) < a.max_active and busy + pending[0]["cores"] <= 24 and available >= 40:
            job = pending.pop(0)
            log = (directory / (job["name"] + ".log")).open("x")
            process = subprocess.Popen(job["argv"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            job.update(pid=process.pid, started_at_utc=datetime.now(timezone.utc).isoformat())
            active[job["name"]] = {"process": process, "log": log, "job": job}
        state = {"status": "RUNNING" if pending or active else "COMPLETED", "pending": pending,
            "active": [item["job"] for item in active.values()], "finished": finished, "latest_resource_sample": samples[-1],
            "dispatch_rule": f"At most {a.max_active} study children, each one two-CPU physical worker; new launch only when actual busy+2 <=24 and available RAM >=40GiB. Existing jobs retain their original timeouts.",
            'coordinator_pid':os.getpid()}
        (directory / "state.json").write_text(json.dumps(state, indent=2) + "\n")
        with (directory / "resource_samples.jsonl").open("a") as stream:
            stream.write(json.dumps(samples[-1]) + "\n")
        samples.clear()
        if pending or active:
            time.sleep(5)
    print(json.dumps({"directory": str(directory), "finished": len(finished)}), flush=True)


if __name__ == "__main__":
    main()
