#!/usr/bin/env python3
"""Four authorized development lanes for the eight independent N(z) domains."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
LANES=[['mirror','compact_miller'],['cascode_mirror','five_t'],['source_follower','resistive_diff'],['stacked_switch','common_source_stage']]


def save(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def resources():
    def cpu():return [int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    first=cpu();time.sleep(1);delta=[b-a for a,b in zip(first,cpu())]
    memory={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemTotal:','MemAvailable:'))}
    return {'busy_cores':os.cpu_count()*(1-(delta[3]+delta[4])/sum(delta)),
        'RAM_used_GiB':(memory['MemTotal']-memory['MemAvailable'])/2**30}


def run(preparation,adopt_root):
    output=ROOT/'runs/development/E1_schematic_parallel'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');output.mkdir(parents=True)
    index={'scope':'parallel_development_resource_calibration','preparation':str(preparation),'adopt_root':str(adopt_root),
        'per_lane_CPU_quota':2,'per_lane_solver_threads':2,'maximum_lanes':4,'jobs':[]}
    handles=[];processes=[]
    for number,targets in enumerate(LANES):
        while True:
            sample=resources()
            if sample['busy_cores']+2<=24 and sample['RAM_used_GiB']<=190:break
            time.sleep(10)
        log=output/('lane_%d.log'%number);handle=log.open('w');handles.append(handle)
        argv=[sys.executable,str(ROOT/'scripts/run_eda_probe.py'),'--script','e1_schematic_feasibility.py','--timeout','14400','--',
            '--preparation',str(preparation),'--workers','2','--targets',*targets,'--adopt-root',str(adopt_root)]
        process=subprocess.Popen(argv,stdout=handle,stderr=subprocess.STDOUT,cwd=ROOT);processes.append(process)
        index['jobs'].append({'lane':number,'targets':targets,'PID':process.pid,'argv':argv,'log':str(log),
            'resource_sample_before_launch':sample,'started_at_utc':datetime.now(timezone.utc).isoformat()})
        save(output/'dispatch.json',index)
    summaries=[]
    for process,handle,job in zip(processes,handles,index['jobs']):
        job['returncode']=process.wait();handle.close();job['ended_at_utc']=datetime.now(timezone.utc).isoformat()
        first=json.loads(Path(job['log']).read_text().splitlines()[0]);raw=Path(first['output']);job['producer']=str(raw)
        report=raw/'schematic_feasibility_summary.json'
        if report.is_file():summaries.append(json.loads(report.read_text()));job['summary']=str(report)
        save(output/'dispatch.json',index)
    targets=[target for report in summaries for target in report['targets']]
    complete=len(summaries)==4 and len(targets)==8 and len({t['target'] for t in targets})==8 and all(j['returncode']==0 for j in index['jobs'])
    result={'scope':'schematic_only_not_S1_S2','status':'COMPLETE' if complete else 'INCOMPLETE_INFRASTRUCTURE',
        'targets':targets,'distinct_target_logics':8,'shared_domain_points':200,'point_count_not_independent_circuit_count':True,
        'private_lane_summaries':[job.get('summary') for job in index['jobs']],'dispatch':str(output/'dispatch.json'),
        'adopted_points':sum(report['adopted_points'] for report in summaries),'formal_trials':0,'model_calls':0,
        'physical_correctness_or_S2_established':False,'original_partial_costs_retained':True,'rerun_reason':'parallel_development_resource_calibration'}
    save(output/'summary.json',result);save(preparation/'public/schematic_feasibility.json',result)
    print(json.dumps({'summary':str(output/'summary.json'),'status':result['status']}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--preparation',type=Path,required=True);parser.add_argument('--adopt-root',type=Path,required=True)
    args=parser.parse_args();run(args.preparation.resolve(),args.adopt_root.resolve())
