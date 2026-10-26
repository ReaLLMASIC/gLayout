"""Qualify all wide-nf ideal points after the C02 single physical lane releases."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.train_collection_queue import resource_sample
out=ROOT/'runs/development/wide_nf_ideal_qualification'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');out.mkdir(parents=True)
predecessor=ROOT/'runs/development/c02_nf_followup/20261019T034325972594Z/queue.json'
state={'status':'WAITING_FOR_C02_LANE_RELEASE','pid':os.getpid(),'started_at_utc':datetime.now(timezone.utc).isoformat(),'predecessor':str(predecessor),'new_model_calls':0,'formal_training_rows':0,'old_raw_or_contracts_changed':False}
def save():(out/'queue.json').write_text(json.dumps(state,indent=2)+'\n')
save();deadline=time.monotonic()+8*3600
try:
    while True:
        prior=json.loads(predecessor.read_text())
        if prior['status'] in ['COMPLETED_IDEAL_CONTROLS_AND_C02_FREEZE_AWAITING_VERIFIED_LOCAL_BACKUP','PAUSED_RAW_RETAINED']:break
        if time.monotonic()>deadline:raise TimeoutError('C02 qualification lane remains occupied; no new simulation dispatched')
        time.sleep(10)
    old=json.loads((ROOT/'runs/development/c01_per_device_nf_qualification/20261019T032847301102Z/batch.json').read_text());oldmap={p['configuration_id']:p for p in old['jobs']}
    table=json.loads((ROOT/'configs/development/c01_per_device_nf_wide_family/configurations.json').read_text());points=[]
    for point in table['configurations']:
        points.append({**{k:point[k] for k in ['configuration_id','reference_file','contract_file']},'independent_N_file':point['reference_file'],
            'postlayout_baseline':'/work/'+str((Path(oldmap[point['same_nf_pair_as']]['run_directory'])/'baseline').relative_to(ROOT)),
            'retained_postlayout_directory_is_bench_template_only_not_comparable_metrics':True})
    input_root=out/'input';input_root.mkdir();(input_root/'points.json').write_text(json.dumps(points,indent=2)+'\n')
    while True:
        sample=resource_sample()
        if sample['actual_busy_cores']+2<=24 and sample['RAM_used_GiB']<=190 and sample['available_disk_GiB']>=4:break
        if time.monotonic()>deadline:raise TimeoutError('No actual resource slot for predeclared wide-domain ideal controls')
        time.sleep(15)
    command=['python3','scripts/run_eda_probe.py','--script','corpus_nf_ideal_control.py','--magic-runtime','magic-8.3.685','--timeout','1200','--input-dir',str(input_root)]
    state.update(status='RUNNING_WHOLE_PREDECLARED_IDEAL_DOMAIN',resources_before_start=sample,argv=command);save()
    log=out/'probe.log'
    with log.open('x') as stream:ran=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','OMP_NUM_THREADS':'1'})
    run=Path(json.loads(log.read_text().splitlines()[0])['output']);raw=json.loads((run/'ideal_control.json').read_text())
    state.update(status='COMPLETED_IDEAL_QUALIFICATION_ATTEMPTS',returncode=ran.returncode,run_directory=str(run),all_nine_ideal_qualified=raw.get('all_nine_ideal_qualified',False),
        qualified_points=sum(p['ideal_application_constraints_pass'] for p in raw['points']),completed_points=len(raw['points']),ended_at_utc=datetime.now(timezone.utc).isoformat());save()
except Exception as exc:
    state.update(status='PAUSED_RAW_RETAINED',error=str(exc),ended_at_utc=datetime.now(timezone.utc).isoformat());save();raise
