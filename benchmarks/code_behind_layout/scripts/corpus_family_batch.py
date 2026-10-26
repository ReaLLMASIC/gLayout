"""Bounded actual development C01 family collection with explicit new points."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--workers',type=int,choices=[1,2,3,4],default=2)
p.add_argument('--baseline-only',action='store_true')
p.add_argument('--configuration-ids',nargs='+')
a=p.parse_args()
table=ROOT/'configs/development/c01_family/configurations.json'
points=json.loads(table.read_text())['configurations']
ids=a.configuration_ids or [point['configuration_id'] for point in points if point['configuration_id']!='anchor']
if not set(ids).issubset({point['configuration_id'] for point in points}):raise ValueError('Undeclared point')
out=ROOT/'runs/development/corpus_family_yield'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');out.mkdir(parents=True)
summary={'scope':'development_family_yield_not_formal_or_training','table':str(table),'workers':a.workers,'baseline_only':a.baseline_only,'jobs':[],'formal_training_rows':0}
existing={}
if not a.baseline_only:
    for prior in (ROOT/'runs/development/corpus_family_yield').glob('*/batch.json'):
        previous=json.loads(prior.read_text())
        if previous['baseline_only']:
            existing.update({job['configuration_id']:Path(job['output']) for job in previous['jobs']})
    if not set(ids).issubset(existing):raise ValueError('Complete the new-point baseline batch first')
def run(configuration_id):
 command=[sys.executable,str(ROOT/'scripts/run_eda_probe.py'),'--script','corpus_yield_pilot.py','--magic-runtime','magic-8.3.685','--timeout','1800','--input-dir',str(ROOT/'runs/phase0/phase0_20261018T234220871091Z_fvf_textbook_cropped_source_smoke'),'--','--circuit','C01','--limit','0' if a.baseline_only else '8','--family-table','/work/configs/development/c01_family/configurations.json','--configuration-id',configuration_id]
 if not a.baseline_only:
  command.extend(['--existing-baseline','/work/'+str(existing[configuration_id].relative_to(ROOT))])
 start=time.monotonic();result=subprocess.run(command,text=True,capture_output=True)
 (out/(configuration_id+'_stdout.log')).write_text(result.stdout);(out/(configuration_id+'_stderr.log')).write_text(result.stderr)
 first=json.loads(result.stdout.splitlines()[0]) if result.stdout.strip() else {}
 return {'configuration_id':configuration_id,'returncode':result.returncode,'wall_seconds':time.monotonic()-start,'run_id':first.get('run_id'),'output':first.get('output'),'argv':command}
with ThreadPoolExecutor(max_workers=a.workers) as pool:
 for future in as_completed([pool.submit(run,name) for name in ids]):
  job=future.result();summary['jobs'].append(job);(out/'batch.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(job),flush=True)
print(json.dumps({'batch':str(out/'batch.json'),'completed':len(summary['jobs'])}),flush=True)
