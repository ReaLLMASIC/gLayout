"""Account actual recorded probe and executor CPU, without counting E1 twice."""
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timezone
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def read(filename):return json.loads(filename.read_text())


def account(root):
    records=[];unresolved=[]
    phase0=root/'runs/phase0'
    for directory in sorted(phase0.iterdir()) if phase0.exists() else []:
        manifest=directory/'pilot_manifest.json'
        if not manifest.exists():continue
        row=read(manifest);usage=directory/'resource_usage.json'
        if row['status']=='RUNNING':
            unresolved.append({'id':directory.name,'kind':'live_or_unreconciled_probe','CPU_seconds':None});continue
        cpu=wall=None
        if usage.exists():
            u=read(usage);cpu=sum(u[key] for key in ('self_user_cpu_seconds','self_system_cpu_seconds','children_user_cpu_seconds','children_system_cpu_seconds'))
            wall=u['wall_seconds']
        records.append({'id':directory.name,'category':'profiled_probe','phase':row.get('phase'),'script':row.get('script',row.get('case')),
            'status':row['status'],'source':str(usage if usage.exists() else manifest),'CPU_seconds':cpu,'stage_wall_seconds':wall})
    # E1 already records all physical children in this host-owned state. Its
    # capsule preparation is a subset of the phase0 profiles above, so it is not
    # added again. Compressed raw need not be reopened to redo this accounting.
    for base in (root/'runs/development/E1_matched',root/'runs/formal/E1'):
        for directory in sorted(base.iterdir()) if base.exists() else []:
            filename=directory/'private/state.json'
            if not filename.exists():continue
            state=read(filename)
            if state.get('in_flight_point'):unresolved.append({'id':directory.name,'kind':'E1_point_in_flight','CPU_seconds':None})
            for stage in ('search','post_freeze_diagnostic','hidden'):
                cost=state['costs_by_stage'][stage]
                if not cost['physical_calls']:continue
                records.append({'id':directory.name+':'+stage,'category':'E1_physical_children','phase':state['phase'],
                    'status':state['post_freeze_status'],'source':str(filename),
                    'CPU_seconds':cost['waited_child_CPU_seconds'],'stage_wall_seconds':cost['stage_wall_seconds'],
                    'missing_CPU_records':cost['missing_CPU_records'],'physical_calls':cost['physical_calls']})
            archive=directory/'private/evidence_archive.json'
            if archive.exists():
                cost=read(archive)
                records.append({'id':directory.name+':archival','category':'private_evidence_archival','phase':state['phase'],
                    'status':cost['status'],'source':str(archive),'CPU_seconds':cost['archive_CPU_seconds'],
                    'stage_wall_seconds':cost['archive_wall_seconds']})
    skip={'source','source_pack','trusted','library','accepted','candidate_output','geometry_packages','capsules',
          'E1_matched'}
    for base in (root/'runs/train_collection',root/'runs/development',root/'runs/formal'):
        if not base.exists():continue
        for path,dirs,names in os.walk(base):
            directory=Path(path)
            dirs[:]=[name for name in dirs if name not in skip and not (directory==root/'runs/formal' and name=='E1')]
            if 'manifest.json' not in names:continue
            filename=directory/'manifest.json';row=read(filename)
            if not row.get('run_id','').startswith('executor_'):continue
            for stage in ('candidate','trusted'):
                if stage not in row:continue
                ufile=directory/(stage+'_stage/resource_usage.json');usage=read(ufile) if ufile.exists() else None
                records.append({'id':row['run_id']+':'+stage,'category':'executor_'+stage,'phase':row['phase'],
                    'status':row[stage]['status'],'source':str(ufile if usage else filename),
                    'CPU_seconds':usage['child_user_cpu_seconds']+usage['child_system_cpu_seconds'] if usage else None,
                    'stage_wall_seconds':row[stage]['wall_seconds']})
            if row['status']=='RUNNING':unresolved.append({'id':row['run_id'],'kind':'executor_in_flight','CPU_seconds':None})
    ids=[r['id'] for r in records]
    if len(ids)!=len(set(ids)):raise ValueError('The same observed event was included twice')
    groups=defaultdict(list)
    for row in records:groups[row['category']].append(row)
    def summarize(rows):
        known=[r['CPU_seconds'] for r in rows if r['CPU_seconds'] is not None]
        return {'event_records':len(rows),'observed_CPU_seconds':sum(known),'observed_CPU_hours':sum(known)/3600,
            'events_with_unavailable_CPU':sum(r['CPU_seconds'] is None for r in rows),
            'nested_stage_CPU_records_unavailable':sum(r.get('missing_CPU_records',0) for r in rows),
            'stage_wall_seconds_sum':sum(r['stage_wall_seconds'] for r in rows if r['stage_wall_seconds'] is not None),
            'status_counts':dict(Counter(r['status'] for r in rows))}
    return {'generated_at_utc':datetime.now(timezone.utc).isoformat(),'scope':'Observed probe/executor CPU and archival work, including failures; this is a partial research ledger, not complete E5 or deployment break-even',
        'totals':summarize(records),'categories':{key:summarize(rows) for key,rows in groups.items()},
        'records':records,'inflight_or_unreconciled':unresolved,
        'double_count_control':'E1 point stages use the host state once; their raw executor tree is excluded. Capsule preparation profiles are counted once under phase0; primitive geometry is their subset.',
        'interpretation':'CPU is actual waited-for process CPU, never cores multiplied by wall. Stage wall sums overlap in calendar time and are not study elapsed time. Missing telemetry and in-flight consumption stay unavailable.',
        'not_yet_included':['GPU training/inference events and allocation idle time','GPT/provider usage and engineering-agent time','unprofiled host schedulers and CLI overhead','deployment stream and comparable-quality savings'],
        'prices_or_break_even_inferred':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=account(a.root.resolve());a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'output':str(a.output),'totals':result['totals'],'unresolved':len(result['inflight_or_unreconciled'])}))
