"""Derive new student datasets only after real collection completion; never train."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
COLLECTIONS=['c01_planning_action_gpt_teacher_v1','c07_action_v1','c05_natural_action_teacher_v1','c01_enumeration_action_v1','c01_natural_action_repair_v1','c02_action_v1','c05_minimal_gpt_teacher_v1','c08_minimal_gpt_teacher_v1',
             'c05_collection_v1','c08_collection_v1','c01_rules_v1','c05_rules_v1','c08_rules_v1']


def now():return datetime.now(timezone.utc).isoformat()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--max-hours',type=float,default=8)
    args=parser.parse_args()
    if not 0<args.max_hours<=8:raise ValueError('Maximum watch window is eight hours; no collection is interrupted')
    out=ROOT/'runs/train_student_readmission_watch'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');out.mkdir(parents=True)
    state={'pid':os.getpid(),'started_at_utc':now(),'status':'WATCHING','collections':COLLECTIONS,'events':[],
           'formal_training_runs':0,'raw_T1_T4_reused':False,'negative_labels_from_quarantine':False}
    def save():(out/'watch.json').write_text(json.dumps(state,indent=2)+'\n')
    save();done=set();deadline=time.monotonic()+args.max_hours*3600
    while time.monotonic()<deadline and len(done)<len(COLLECTIONS):
        for name in COLLECTIONS:
            if name in done:continue
            raw=ROOT/'runs/train_collection'/name;completion=raw/'completion.json'
            if not completion.exists():continue
            status=json.loads(completion.read_text()).get('status')
            if status!='COMPLETED_INITIAL_BATCH':
                state['events'].append({'at_utc':now(),'collection':name,'status':'NOT_ADMITTED_COLLECTION_'+str(status)});done.add(name);save();continue
            destination=ROOT/'runs/train_collection'/(name+'_student_readmission_v1')
            if destination.exists():
                state['events'].append({'at_utc':now(),'collection':name,'status':'EXISTING_DERIVED_DIRECTORY_REQUIRES_RECONCILIATION','output':str(destination)})
                done.add(name);save();continue
            command=[str(ROOT/'runtime/training-venv/bin/python'),'scripts/prepare_student_data.py','--input-root',str(raw),'--output-root',str(destination)]
            with (out/(name+'.log')).open('w') as log:
                result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','OMP_NUM_THREADS':'1','TOKENIZERS_PARALLELISM':'false'},timeout=600)
            report=destination/'student_selection.json';selection=json.loads(report.read_text()) if report.exists() else None
            state['events'].append({'at_utc':now(),'collection':name,'returncode':result.returncode,
                'status':'DERIVED_NOT_TRAINED' if result.returncode==0 else 'ADMISSION_OR_INTERFACE_PAUSED_RAW_RETAINED',
                'command':command,'output':str(destination),'selection':selection})
            done.add(name);save()
            with (out/'actual_yield_snapshot.log').open('a') as log:
                subprocess.run(['python3','scripts/training_pilot_status.py'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=120)
        time.sleep(15)
    state.update(status='WATCH_WINDOW_ENDED' if len(done)<len(COLLECTIONS) else 'COMPLETED_DERIVATIONS',ended_at_utc=now(),unresolved_collections=sorted(set(COLLECTIONS)-done));save()


if __name__=='__main__':main()
