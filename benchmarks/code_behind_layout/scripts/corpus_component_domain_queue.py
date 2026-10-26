"""One two-CPU development worker: qualify both anchors before expanding domains."""
from datetime import datetime,timezone
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.train_collection_queue import resource_sample

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--circuit',choices=['C02','C07','TRAIN_TG01'],help='Run only this explicitly approved development domain')
args=parser.parse_args()
circuits=[args.circuit] if args.circuit else ['C07','TRAIN_TG01']
out=ROOT/'runs/development/component_train_domain_qualification'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');out.mkdir(parents=True)
state={'scope':'development_only_single_worker_original_compiler_qualification','started_at_utc':datetime.now(timezone.utc).isoformat(),'jobs':[],'source_lineages':1,'formal_training_rows':0,'status':'RUNNING'}
def save():(out/'batch.json').write_text(json.dumps(state,indent=2)+'\n')
save()


def job(cid,identifier,prelayout):
    deadline=time.monotonic()+3600
    while True:
        resources=resource_sample()
        if resources['actual_busy_cores']+2<=24 and resources['RAM_used_GiB']<=190:break
        if time.monotonic()>deadline:raise TimeoutError('Actual CPU/RAM dispatch gate remained occupied for one hour; no additional worker launched')
        time.sleep(15)
    label=cid+'_'+identifier+('_prelayout' if prelayout else '_post_RC')
    argv=['python3','scripts/run_eda_probe.py','--script','corpus_component_train_pilot.py','--magic-runtime','magic-8.3.685','--timeout','1200','--',
          '--table','/work/configs/development/'+cid.lower()+'_family/configurations.json','--configuration-id',identifier]
    if prelayout:argv.append('--prelayout-only')
    record={'circuit_id':cid,'configuration_id':identifier,'prelayout':prelayout,'argv':argv,'resources_before_start':resources,'started_at_utc':datetime.now(timezone.utc).isoformat()}
    with (out/(label+'.log')).open('w') as log:ran=subprocess.run(argv,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    first=(out/(label+'.log')).read_text().splitlines()[0];directory=Path(json.loads(first)['output'])
    record.update(returncode=ran.returncode,run_directory=str(directory),ended_at_utc=datetime.now(timezone.utc).isoformat())
    path=directory/'bench_result.json';data=json.loads(path.read_text()) if path.exists() else {}
    record.update(all_analyses_complete=data.get('all_analyses_complete',False),all_operating_points_valid=data.get('all_operating_points_valid',False),full_physical_analysis_complete=data.get('full_physical_analysis_complete',False))
    state['jobs'].append(record);save();print(json.dumps(record),flush=True)
    return ran.returncode==0


try:
    qualified=[]
    for cid in circuits:
        if job(cid,'anchor',True) and job(cid,'anchor',False):qualified.append(cid)
    for cid in qualified:
        table=json.loads((ROOT/'configs/development'/(cid.lower()+'_family/configurations.json')).read_text())
        for point in table['configurations']:
            if point['configuration_id']!='anchor':job(cid,point['configuration_id'],False)
    state.update(status='COMPLETED_QUALIFICATION_ATTEMPTS',ended_at_utc=datetime.now(timezone.utc).isoformat());save()
except Exception as exc:
    state.update(status='PAUSED',reason=type(exc).__name__+': '+str(exc),ended_at_utc=datetime.now(timezone.utc).isoformat());save();raise
