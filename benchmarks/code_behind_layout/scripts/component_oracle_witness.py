#!/usr/bin/env python3
"""Bounded engineering edit witness for an already-qualified component anchor."""
import argparse,difflib,json,shutil,sys,time
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.candidate_executor import CandidateExecutor
from src.domain_runner import inspect_point,source_contents

def run(preparation,baseline,extension):
    original=Path(preparation)/'private/mirror/source_pack'
    task=json.loads((Path(baseline)/'private/task.json').read_text())
    point=next(p for p in task['configurations'] if p['role']=='anchor')
    out=ROOT/'runs/development/component_oracles'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    source=out/'source';source.parent.mkdir(parents=True,mode=0o700);shutil.copytree(original,source)
    name='glayout/cells/elementary/current_mirror/current_mirror.py';path=source/name;before=path.read_text()
    old='extension=3*maxmet_sep';new='extension='+str(extension)+'*maxmet_sep'
    if before.count(old)!=2:raise ValueError('Expected exactly source/gate C-route extension declarations')
    after=before.replace(old,new);path.write_text(after)
    patch=''.join(difflib.unified_diff(before.splitlines(keepends=True),after.splitlines(keepends=True),fromfile='a/'+name,tofile='b/'+name))
    (out/'engineering_patch.diff').write_text(patch)
    trusted=out/'trusted';shutil.copytree(Path(baseline)/'private/trusted_common',trusted)
    shutil.copyfile(point['reference_file'],trusted/'reference.spice')
    (trusted/'contract.json').write_text(json.dumps(point['contract'],indent=2)+'\n')
    files=sorted(set(task['frozen_source_files'])|set(task['editable_paths']))
    trusted_files=sorted(str(p.relative_to(trusted)) for p in trusted.rglob('*') if p.is_file())
    executor=CandidateExecutor(ROOT/'runtime/GLdev',out/'physical',ROOT/'runtime/magic-8.3.685',timeout=720)
    result=executor.execute(source_dir=source,source_paths=files,entrypoint='generator.py',representation='G2',
        configuration=point['parameters'],trusted_dir=trusted,trusted_paths=trusted_files,
        phase='development_component_engineering_witness',context={'source_role':'transparent_engineering_heuristic',
            'configuration_id':point['configuration_id'],'reference_id':point['reference_id'],'parent_lineage':task['parent_lineage'],
            'pdk_revision':task['pdk_revision'],'candidate_id':'mirror_extension_'+str(extension),'initial_state_id':'unmodified_materialized_source'},
        generation_timeout_seconds=120,evaluator_timeout_seconds=720)
    # Compare trusted reports with the exact source/configuration actually executed.
    checked=inspect_point(result,point,source_contents(source,files,binary=True),point['parameters'],gold_control_check=False)
    original_state=json.loads((Path(baseline)/'private/state.json').read_text())
    original_run=Path(original_state['points'][point['configuration_id']]['run_directory'])
    base=json.loads((original_run/'evidence/validation.json').read_text())
    candidate=(result.get('physical_result') or {})
    definition=point['contract']['objective'];metric=definition['metric']
    objectives={}
    for key,value in [('baseline',base),('candidate',candidate)]:
        observations=value.get('observation',{}).get('corners',{})
        values=[observations.get(c,{}).get('metrics',{}).get(metric,{}).get('value') for c in point['contract']['required_corners']]
        objectives[key]=max(values) if all(isinstance(v,(int,float)) for v in values) else None
    record={'phase':'development_component_engineering_witness','formal_trials':0,'training_examples':0,
        'patch_origin':'transparent engineering heuristic, never model-generated','route_extension_multiplier':extension,
        'configuration_id':point['configuration_id'],'baseline_run':str(original_run),'run_directory':result['run_directory'],
        'inspection':checked,'objective_definition':definition,'objectives':objectives,
        'source_files':files,'patch_file':str(out/'engineering_patch.diff')}
    (out/'witness.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--preparation',type=Path,required=True)
    p.add_argument('--baseline',type=Path,required=True);p.add_argument('--extension',type=int,choices=[1,2],default=1);a=p.parse_args()
    run(a.preparation,a.baseline,a.extension)
