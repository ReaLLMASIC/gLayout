"""One prospective complete nine-point long-channel ideal run after approval."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    table=json.loads((ROOT/'configs/development/c01_per_device_nf_long_family/configurations.json').read_text())
    if len(table['configurations'])!=9 or {(p['parameters']['sizing']['M1']['nf'],p['parameters']['sizing']['M2']['nf']) for p in table['configurations']}!={(a,b) for a in [2,4,6] for b in [2,4,6]}:
        raise ValueError('Preserve the entire declared nf grid')
    for p in table['configurations']:
        if any(s['w']!=15 or s['l']!=3 for s in p['parameters']['sizing'].values()):raise ValueError('Do not resize after declaration')
    command=['python3','scripts/run_eda_probe.py','--script','corpus_nf_ideal_control.py','--magic-runtime','magic-8.3.685','--timeout','1200']
    if not args.execute:
        print(json.dumps({'status':'DRAFT_NOT_DISPATCHED','points':9,'argv_base':command,'required_approval':'Parent must approve the one complete new ideal-domain run','new_calls':0}));return
    out=ROOT/'runs/development/long_nf_ideal_qualification_v1';out.mkdir(parents=True,exist_ok=False)
    old=json.loads((ROOT/'runs/development/c01_per_device_nf_qualification/20261019T032847301102Z/batch.json').read_text());oldmap={row['configuration_id']:row for row in old['jobs']}
    points=[]
    for p in table['configurations']:
        points.append({**{key:p[key] for key in ['configuration_id','reference_file','contract_file']},'independent_N_file':p['reference_file'],
            'postlayout_baseline':'/work/'+str((Path(oldmap[p['same_nf_pair_as']]['run_directory'])/'baseline').relative_to(ROOT)),
            'retained_postlayout_directory_is_bench_template_only_not_comparable_metrics':True})
    input_root=out/'input';input_root.mkdir();(input_root/'points.json').write_text(json.dumps(points,indent=2)+'\n')
    command+=['--input-dir',str(input_root)]
    state={'status':'WAITING_FOR_ACTUAL_RESOURCES','started_at_utc':datetime.now(timezone.utc).isoformat(),'pid':os.getpid(),
        'argv':command,'declared_points':9,'new_model_calls':0,'formal_training_rows':0,'old_raw_or_specifications_changed':False}
    def save():(out/'queue.json').write_text(json.dumps(state,indent=2)+'\n')
    save()
    try:
        from scripts.train_collection_queue import resource_sample
        deadline=time.monotonic()+8*3600
        while True:
            sample=resource_sample()
            if sample['actual_busy_cores']+2<=24 and sample['RAM_used_GiB']<=190 and sample['available_disk_GiB']>=4:break
            if time.monotonic()>deadline:raise TimeoutError('No resource slot; no ideal run launched')
            time.sleep(15)
        state.update(status='RUNNING_ONE_COMPLETE_DECLARED_IDEAL_GRID',resources_before_start=sample);save()
        log=out/'probe.log'
        with log.open('x') as stream:
            ran=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','OMP_NUM_THREADS':'1'})
        run=Path(json.loads(log.read_text().splitlines()[0])['output']);raw=json.loads((run/'ideal_control.json').read_text())
        state.update(status='COMPLETED_IDEAL_ATTEMPTS' if len(raw['points'])==9 else 'INCOMPLETE_RAW_RETAINED',returncode=ran.returncode,
            run_directory=str(run),completed_points=len(raw['points']),qualified_points=sum(p['ideal_application_constraints_pass'] for p in raw['points']),
            all_nine_qualified=raw.get('all_nine_ideal_qualified',False),ended_at_utc=datetime.now(timezone.utc).isoformat());save()
    except BaseException as error:
        state.update(status='PAUSED_RAW_RETAINED',error=str(error),ended_at_utc=datetime.now(timezone.utc).isoformat());save();raise
    print(json.dumps(state))


if __name__=='__main__':main()
