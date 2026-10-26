#!/usr/bin/env python3
"""Bounded anchor qualification for the approved distinct component source states."""
import argparse,json,shutil,sys,threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.candidate_executor import CandidateExecutor
from src.domain_runner import inspect_point,source_contents

def qualify(preparation,baselines,workers):
    if workers not in (1,2):raise ValueError('One or two 2CPU workers only')
    preparation=Path(preparation);catalog=json.loads((preparation/'initial_states.json').read_text())
    directory=ROOT/'runs/development/component_state_qualification'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory.mkdir(parents=True,mode=0o700);records={};lock=threading.Lock();paused=threading.Event()
    def save():
        result={'phase':'development_distinct_component_initial_state_qualification','directory':str(directory),
            'preparation':str(preparation),'states':records,'declared_states':12,'formal_trials':0,'training_examples':0,
            'full_25_point_qualification_complete':False,'maximum_workers':workers}
        (directory/'qualification.json').write_text(json.dumps(result,indent=2)+'\n')
    def one(state):
        if paused.is_set():return
        ident=state['initial_state_id'];baseline=Path(baselines[state['kind']]);task=json.loads((baseline/'private/task.json').read_text())
        point=next(p for p in task['configurations'] if p['role']=='anchor');original=json.loads((baseline/'private/state.json').read_text())['points'][point['configuration_id']]
        if state['origin']=='natural_clean_but_poor':
            row={'initial_state_id':ident,'origin':state['origin'],'inspection':original,
                'evidence_mode':'Existing actual unmodified-source GDS anchor; all four materialized anchor geometry+labels previously compared equal to their independent full-flow controls',
                'new_physical_calls':0,'cost_charged_to':str(baseline/'public/summary.json')}
        else:
            work=directory/ident;trusted=work/'trusted';shutil.copytree(baseline/'private/trusted_common',trusted)
            shutil.copyfile(point['reference_file'],trusted/'reference.spice');(trusted/'contract.json').write_text(json.dumps(point['contract'],indent=2)+'\n')
            files=state['source_files'];source=Path(state['source_pack']);names=sorted(str(p.relative_to(trusted)) for p in trusted.rglob('*') if p.is_file())
            executor=CandidateExecutor(ROOT/'runtime/GLdev',work/'physical',ROOT/'runtime/magic-8.3.685',timeout=720)
            result=executor.execute(source_dir=source,source_paths=files,entrypoint='generator.py',representation='G2',
                configuration=point['parameters'],trusted_dir=trusted,trusted_paths=names,phase='development_component_state_qualification',
                context={'source_role':state['origin'],'initial_state_id':ident,'candidate_id':ident,'parent_lineage':state['parent_lineage'],
                    'configuration_id':point['configuration_id'],'reference_id':point['reference_id'],'pdk_revision':task['pdk_revision']},
                generation_timeout_seconds=120,evaluator_timeout_seconds=720)
            point={**point,'gold_control':{'run_directory':original['run_directory']}}
            try:checked=inspect_point(result,point,source_contents(source,files,binary=True),point['parameters'])
            except (OSError,KeyError,TypeError,ValueError) as exc:
                checked={'S0':False,'S1':False,'S2':False,'execution_integrity':'incomplete','failure_class':'unknown','reason':str(exc),'run_directory':result['run_directory']}
            run=Path(result['run_directory']);manifest=json.loads((run/'manifest.json').read_text());cost={'stage_wall_seconds':0.,'waited_child_CPU_seconds':0.,'missing_CPU_records':0}
            for stage in ('candidate','trusted'):
                if stage not in manifest:continue
                cost['stage_wall_seconds']+=manifest[stage]['wall_seconds'];path=run/(stage+'_stage/resource_usage.json')
                if path.exists():usage=json.loads(path.read_text());cost['waited_child_CPU_seconds']+=usage['child_user_cpu_seconds']+usage['child_system_cpu_seconds']
                else:cost['missing_CPU_records']+=1
            row={'initial_state_id':ident,'origin':state['origin'],'inspection':checked,'run_directory':str(run),
                'new_physical_calls':1,'cost':cost,'unchanged_reference':point['reference_id'],'historical_source_edited_for_compatibility':False}
        if row['inspection']['failure_class'] in ('unknown','infrastructure'):paused.set()
        with lock:records[ident]=row;save()
        print(json.dumps({'initial_state_id':ident,'S2':row['inspection']['S2'],'failure_class':row['inspection']['failure_class'],'reason':row['inspection'].get('reason'),'new_physical_calls':row['new_physical_calls']}),flush=True)
    save()
    with ThreadPoolExecutor(max_workers=workers) as pool:list(pool.map(one,catalog['states']))
    save()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--preparation',type=Path,required=True);p.add_argument('--baselines',type=Path,required=True);p.add_argument('--workers',type=int,default=2);a=p.parse_args()
    qualify(a.preparation,json.loads(a.baselines.read_text()),a.workers)
