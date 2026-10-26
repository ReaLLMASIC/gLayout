"""Two authorized development controls; preserve earlier failures and specifications."""
from concurrent.futures import ThreadPoolExecutor
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.train_collection_queue import resource_sample

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--control-set',choices=['gear2_vs_original_tg','equivalent_inputs_vs_strength4'],default='gear2_vs_original_tg')
args=parser.parse_args()
out=ROOT/'runs/development/component_train_domain_qualification'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');out.mkdir(parents=True)
state={'scope':'development_only_two_worker_numerical_and_performance_controls','started_at_utc':datetime.now(timezone.utc).isoformat(),
       'jobs':[],'source_lineages':1,'formal_training_rows':0,'status':'RUNNING',
       'control_set':args.control_set,
       'unchanged':['circuit_graph','device_sizing','ports','electrical_specs','external_bias_and_load','full_positive_RC','tight_tolerances','analysis_windows','120s_per_analysis_timeout']}
lock=threading.Lock()
def save():(out/'batch.json').write_text(json.dumps(state,indent=2)+'\n')
save()

def job(cid,identifier,prelayout,solver,retry_of=None,table_domain=None,independent_inputs=False):
    deadline=time.monotonic()+3600
    # Serialize the resource decision and subprocess creation across these two lanes.
    while True:
        with lock:
            resources=resource_sample()
            if resources['actual_busy_cores']+2<=24 and resources['RAM_used_GiB']<=190:
                label=cid+'_'+identifier+('_prelayout' if prelayout else '_post_RC')+'_'+solver
                argv=['python3','scripts/run_eda_probe.py','--script','corpus_component_train_pilot.py','--magic-runtime','magic-8.3.685','--timeout','1200','--',
                    '--table','/work/configs/development/'+(table_domain or cid).lower()+'_family/configurations.json','--configuration-id',identifier,'--solver',solver]
                if prelayout:argv.append('--prelayout-only')
                if retry_of:argv+=['--retry-of',retry_of]
                if independent_inputs:argv.append('--independent-transient-inputs')
                log_path=out/(label+'.log');log=log_path.open('w')
                child=subprocess.Popen(argv,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
                record={'circuit_id':cid,'configuration_id':identifier,'prelayout':prelayout,'solver':solver,'retry_of':retry_of,'argv':argv,
                    'domain_id':table_domain or cid,'independent_transient_inputs':independent_inputs,
                    'pid':child.pid,'resources_before_start':resources,'started_at_utc':datetime.now(timezone.utc).isoformat(),'status':'RUNNING'}
                state['jobs'].append(record);save();break
        if time.monotonic()>deadline:raise TimeoutError('Actual CPU/RAM gate occupied for one hour; no child launched')
        time.sleep(15)
    returncode=child.wait();log.close()
    first=log_path.read_text().splitlines()[0];directory=Path(json.loads(first)['output'])
    path=directory/'bench_result.json';data=json.loads(path.read_text()) if path.exists() else {}
    with lock:
        record.update(returncode=returncode,run_directory=str(directory),ended_at_utc=datetime.now(timezone.utc).isoformat(),status='COMPLETED',
            all_analyses_complete=data.get('all_analyses_complete',False),all_operating_points_valid=data.get('all_operating_points_valid',False),
            full_physical_analysis_complete=data.get('full_physical_analysis_complete',False));save()
    print(json.dumps(record),flush=True)
    return returncode==0

def c07():
    original=str(ROOT/'runs/phase0/phase0_20261019T022644983717Z_corpus_component_train_pilot')
    independent=args.control_set=='equivalent_inputs_vs_strength4';solver='trap' if independent else 'gear2'
    if not job('C07','anchor',True,solver,original,independent_inputs=independent):return
    if not job('C07','anchor',False,solver,original,independent_inputs=independent):return
    for point in ['dev_nf_half','dev_nf_3quarters','dev_nf_1half','dev_nf_double','dev_len045','dev_len060','dev_unit075','dev_unit100']:
        job('C07',point,False,solver,independent_inputs=independent)

def tg():
    # Characterize the original specification failure; do not promote its domain.
    original=str(ROOT/'runs/phase0/phase0_20261019T022858135139Z_corpus_component_train_pilot')
    if args.control_set=='gear2_vs_original_tg':job('TRAIN_TG01','anchor',False,'trap',original);return
    table='TRAIN_TG01_strength4'
    if not job('TRAIN_TG01','anchor',True,'trap',original,table_domain=table):return
    if not job('TRAIN_TG01','anchor',False,'trap',original,table_domain=table):return
    for point in ['dev_nf_half','dev_nf_3quarters','dev_nf_1half','dev_nf_double','dev_len045','dev_len060','dev_unit075','dev_unit100']:
        job('TRAIN_TG01',point,False,'trap',table_domain=table)

try:
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(c07),pool.submit(tg)]
        for future in futures:future.result()
    with lock:state.update(status='COMPLETED_QUALIFICATION_ATTEMPTS',ended_at_utc=datetime.now(timezone.utc).isoformat());save()
except Exception as exc:
    with lock:state.update(status='PAUSED',reason=type(exc).__name__+': '+str(exc),ended_at_utc=datetime.now(timezone.utc).isoformat());save()
    raise
