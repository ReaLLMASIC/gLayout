"""Use one released qualification lane for ideal-nf controls and C02 final smoke."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.train_collection_queue import resource_sample
out=ROOT/'runs/development/c02_nf_followup'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');out.mkdir(parents=True)
predecessor=ROOT/'runs/development/c01_per_device_nf_qualification/20261019T032847301102Z/batch.json'
preparation=ROOT/'runtime/collection_preparation/c02_collection_20261019T034001855210Z/preparation.json'
state={'status':'WAITING_FOR_NINE_ORIGINAL_NF_POINTS','pid':os.getpid(),'started_at_utc':datetime.now(timezone.utc).isoformat(),'predecessor':str(predecessor),'steps':[],
    'model_inferences':0,'existing_raw_changed':False,'physical_workers':1,'cpus_per_physical_job':2}
def save():(out/'queue.json').write_text(json.dumps(state,indent=2)+'\n')
save();deadline=time.monotonic()+8*3600

def run(name,command,physical):
    if physical:
        while True:
            sample=resource_sample()
            if sample['actual_busy_cores']+2<=24 and sample['RAM_used_GiB']<=190:break
            if time.monotonic()>deadline:raise TimeoutError('No actual resource slot before dispatch deadline')
            time.sleep(15)
    else:sample=None
    record={'step':name,'argv':command,'resources_before_dispatch':sample,'started_at_utc':datetime.now(timezone.utc).isoformat()};state['steps'].append(record);save()
    log=out/(name+'.log')
    with log.open('x') as stream:ran=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','OMP_NUM_THREADS':'1','TOKENIZERS_PARALLELISM':'false'})
    record.update(returncode=ran.returncode,ended_at_utc=datetime.now(timezone.utc).isoformat(),log=str(log));save()
    if ran.returncode:raise RuntimeError(name+' failed; original raw retained and no model collection launched')
    return log

try:
    while True:
        prior=json.loads(predecessor.read_text())
        if prior['status']=='COMPLETED_QUALIFICATION_ATTEMPTS':break
        if prior['status']=='PAUSED':raise RuntimeError('NF qualification paused; do not assume the missing points passed')
        if time.monotonic()>deadline:raise TimeoutError('NF predecessor did not finish within bounded dispatch window')
        time.sleep(10)
    table=json.loads((ROOT/'configs/development/c01_per_device_nf_family/configurations.json').read_text());byid={row['configuration_id']:row for row in table['configurations']}
    if len(prior['jobs'])!=9 or any(job['status']!='COMPLETED' for job in prior['jobs']):raise ValueError('Retain complete original nine-point denominator')
    input_root=out/'input';input_root.mkdir();points=[]
    for job in prior['jobs']:
        point=byid[job['configuration_id']];base=Path(job['run_directory'])/'baseline'
        points.append({**{key:point[key] for key in ['configuration_id','reference_file','contract_file']},'postlayout_baseline':'/work/'+str(base.relative_to(ROOT))})
    (input_root/'points.json').write_text(json.dumps(points,indent=2)+'\n')
    log=run('nf_same_N_ideal_controls',['python3','scripts/run_eda_probe.py','--script','corpus_nf_ideal_control.py','--magic-runtime','magic-8.3.685','--timeout','1200','--input-dir',str(input_root)],True)
    ideal_run=Path(json.loads(log.read_text().splitlines()[0])['output']);state['ideal_control']=str(ideal_run/'ideal_control.json');save()
    run('c02_isolated_capsule_smoke',[str(ROOT/'runtime/training-venv/bin/python'),'scripts/corpus_additional_capsule_smoke.py','--preparation',str(preparation)],True)
    calibrations=[p for p in (ROOT/'runs/development/additional_capsule_smoke').glob('*/calibration.json') if json.loads(p.read_text()).get('preparation_path')==str(preparation)]
    if len(calibrations)!=1:raise ValueError('Expected one actual final C02 trusted-evaluator calibration')
    state['C02_calibration']=str(calibrations[0]);save()
    run('c02_prospective_action_freeze',[str(ROOT/'runtime/training-venv/bin/python'),'scripts/freeze_component_action_collection.py','--preparation',str(preparation),'--calibration',str(calibrations[0])],False)
    state.update(status='COMPLETED_IDEAL_CONTROLS_AND_C02_FREEZE_AWAITING_VERIFIED_LOCAL_BACKUP',collection_manifest=str(ROOT/'runtime/train_collections/c02_action_v1/collection.json'),ended_at_utc=datetime.now(timezone.utc).isoformat());save()
except Exception as exc:
    state.update(status='PAUSED_RAW_RETAINED',reason=type(exc).__name__+': '+str(exc),ended_at_utc=datetime.now(timezone.utc).isoformat());save();raise
