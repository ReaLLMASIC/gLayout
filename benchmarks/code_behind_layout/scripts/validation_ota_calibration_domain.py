"""Nine prospectively declared validation geometries; OP/AC calibration only."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
ANCHOR=ROOT/'runs/phase0/phase0_20261019T033315453464Z_validation_row_ota_probe'
SOURCE=['src/generators/validation_row_ota.py','src/generators/validation_row_ota_reference.py','src/generators/terminal_access.py']


def save(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def now():return datetime.now(timezone.utc).isoformat()


def gate():
    def cpu():
        values=list(map(int,Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
        return sum(values),values[3]+values[4]
    while True:
        first=cpu();time.sleep(1);second=cpu()
        busy=os.cpu_count()*(1-(second[1]-first[1])/(second[0]-first[0]))
        memory={p[0].rstrip(':'):int(p[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if len(p:=line.split())>=2}
        used=(memory['MemTotal']-memory['MemAvailable'])/2**30
        if busy+2<=24 and used<=190 and shutil.disk_usage(ROOT).free>=4*2**30:
            return {'at_utc':now(),'busy_cores':busy,'RAM_used_GiB':used}
        time.sleep(15)


def complete_measurement(run):
    data=json.loads((run/'qualification.json').read_text())
    complete=data['status']=='COMPLETE_VALIDATION_AC_CALIBRATION'
    if complete:
        assert data['DRC']['completed'] and data['DRC']['is_clean'] and data['LVS']['is_clean']
        assert data['device_intent']['is_clean'] and data['RC']['has_real_RC']
        assert all(data['measurements']['postlayout_'+c]['complete'] for c in ['tt','ss','ff'])
    return {'run_directory':str(run),'status':data['status'],'actual_AC_calibration_complete':complete,
        'full_S2_established':False,'postlayout':{c:data['measurements'].get('postlayout_'+c) for c in ['tt','ss','ff']}}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    snapshot=args.output/'source_snapshot';snapshot.mkdir()
    for name in SOURCE:(snapshot/Path(name).name).write_bytes((ROOT/name).read_bytes())
    for name in SOURCE:
        assert (ROOT/name).read_bytes()==(ANCHOR/Path(name).name).read_bytes(),'Anchor source differs from the declared calibration assembly'
    assert complete_measurement(ANCHOR)['actual_AC_calibration_complete']
    rows=[]
    # Fixed before new physical outcomes; no rejection sampling or replacement.
    for gap in [18.,24.,36.]:
        for pitch in [2.,3.,4.]:
            ident='gap%d_pitch%d'%(gap,pitch);folder=args.output/ident;folder.mkdir()
            case={'configuration_id':ident,'layout':{'device_gap':gap,'bus_pitch':pitch,'bus_width':.8},
                'reuse_schematic_run':str(ANCHOR),'reference_binding':'Same fixed sized independent N for every layout geometry'}
            save(folder/'case.json',case);rows.append({'configuration_id':ident,'layout':case['layout'],'input':str(folder),'status':'NOT_RUN'})
    state={'scope':'validation_only_nominal_TT_to_worst_TT_SS_FF_UGB_calibration','parent_lineage':'research_validation_row_bus_ota',
        'source_ancestry':'Separately authored source; shared primitive access and high-level row/global-bus strategy disclosed',
        'declared_configurations':9,'status':'DECLARED_NOT_RUN','created_at_utc':now(),'controller_pid':os.getpid(),
        'full_S2_claim':False,'formal_benchmark_trial':False,'points':rows,'fixed_reference_anchor':str(ANCHOR)}
    save(args.output/'domain.json',state)
    if not args.execute:return
    state['status']='RUNNING';save(args.output/'domain.json',state)
    for row in rows:
        if row['layout']=={'device_gap':24.,'bus_pitch':3.,'bus_width':.8}:
            row.update(status='ADOPTED_EXACT_ORIGINAL_CALIBRATION_ANCHOR',measurement=complete_measurement(ANCHOR),new_physical_runs=0)
            save(args.output/'domain.json',state);continue
        row['resource_sample_before_launch']=gate()
        for name in SOURCE:assert (ROOT/name).read_bytes()==(snapshot/Path(name).name).read_bytes(),'Declared source changed before dispatch'
        command=['python3',str(ROOT/'scripts/run_eda_probe.py'),'--script','validation_row_ota_probe.py',
            '--magic-runtime','magic-8.3.685','--timeout','900','--input-dir',row['input']]
        row.update(status='RUNNING',started_at_utc=now(),argv=command);save(args.output/'domain.json',state)
        with (Path(row['input'])/'probe.log').open('w') as log:
            child=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            row['child_pid']=child.pid;save(args.output/'domain.json',state);code=child.wait()
        first=json.loads((Path(row['input'])/'probe.log').read_text().splitlines()[0]);run=Path(first['output'])
        row.update(status='PROCESS_EXITED',waited_returncode=code,ended_at_utc=now(),new_physical_runs=1)
        if not (run/'qualification.json').is_file():
            row['status']='INCOMPLETE_UNKNOWN';state['status']='PAUSED_INFRASTRUCTURE';save(args.output/'domain.json',state);return
        row['measurement']=complete_measurement(run);save(args.output/'domain.json',state)
        if code and row['measurement']['status'] not in ['PHYSICAL_REJECTED_OR_INCOMPLETE','INDEPENDENT_CONNECTIVITY_OR_INTENT_REJECTED','INCOMPLETE_OR_ELECTRICALLY_INFEASIBLE']:
            state['status']='PAUSED_INFRASTRUCTURE';save(args.output/'domain.json',state);return
    state.update(status='TERMINAL_DECLARED_DOMAIN',completed_at_utc=now(),
        complete_AC_points=sum(row['measurement']['actual_AC_calibration_complete'] for row in rows))
    save(args.output/'domain.json',state)


if __name__=='__main__':main()
