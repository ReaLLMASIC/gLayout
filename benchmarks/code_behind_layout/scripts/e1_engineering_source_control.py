#!/usr/bin/env python3
"""Known complete OTA source control; never a tested policy/composition result."""
import argparse
import ast
from datetime import datetime,timezone
import difflib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.e1_matched_runner import backend,read,save


def run(target):
    task_id='draft_E1_'+target+'_s01'
    info=backend({'op':'start','manifest':'configs/development/e1_freeze_manifest_draft.json','task_id':task_id,
        'method':'G2','trial_id':'engineering_complete_source','driver_role':'engineering_mechanical_control','formal':False})
    directory=Path(info['episode_directory']);task=read(directory/'private/task.json');point=task['configurations'][0]
    source_path=Path(task['source_pack'])/'src/generators'/(target+'.py');original=source_path.read_text()
    ports=next(line.split()[2:] for line in Path(point['reference_file']).read_text().splitlines() if line.lower().startswith('.subckt '))
    site='from src.generators.'+target+'_reference import DEFAULT, PORTS'
    if original.count(site)!=1:raise ValueError('Expected complete source reference import changed')
    source=original.replace(site,'DEFAULT='+repr(point['parameters'])+'\nPORTS='+repr(ports))
    original_build=next(n for n in ast.parse(original).body if isinstance(n,ast.FunctionDef) and n.name=='build')
    actual_build=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='build')
    if ast.get_source_segment(original,original_build)!=ast.get_source_segment(source,actual_build):raise ValueError('Complete assembly function changed')
    source+='''\nimport argparse,shutil
p=argparse.ArgumentParser();p.add_argument("--configuration");p.add_argument("--output");a=p.parse_args()
configuration=json.loads(Path(a.configuration).read_text())
generated=build(Path("/tmp/engineering_control"),configuration["parameters"])
shutil.copyfile(generated,a.output)
'''
    (directory/'private/original_engineering_assembly.py').write_text(original)
    scope={'engineering_complete_target_source':True,'formal_policy_packet_unchanged':True,
        'tested_policy_or_composition_capability_established':False,'original_source':str(source_path),
        'build_function_source_identical':True,'transport':'Only independent reference import replaced by immutable parameters/visible ports; CLI appended'}
    save(directory/'private/engineering_control_scope.json',scope)
    patch=''.join(difflib.unified_diff(info['packet']['visible_sources']['generator.py'].splitlines(True),source.splitlines(True),fromfile='a/generator.py',tofile='b/generator.py'))
    base={'path':'','patch':'','configuration_ids':[],'fidelity':'','summary':'Engineering-only complete assembly control; no model/composition capability claim'}
    backend({'op':'action','episode_directory':str(directory),'action':{**base,'action':'propose_patch','patch':patch}})
    backend({'op':'action','episode_directory':str(directory),'action':{**base,'action':'request_evaluation','configuration_ids':['anchor'],'fidelity':'pex_spice'}})
    backend({'op':'seal','episode_directory':str(directory),'status':'ENGINEERING_MECHANICAL_CONTROL_COMPLETE'})
    report=backend({'op':'post_freeze','episode_directory':str(directory),'anchor_only':True});report['engineering_control_scope']=scope
    output=ROOT/'runs/development/E1_mechanical_summary'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');output.mkdir(parents=True)
    save(output/'summary.json',{'scope':'engineering_complete_source_trusted_bench_positive_control','formal_trials':0,'model_calls':0,'episodes':[report]})
    print(json.dumps({'summary':str(output/'summary.json'),'final_anchor':report['final_anchor']}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--target',choices=['five_t','compact_miller'],required=True)
    run(parser.parse_args().target)
