#!/usr/bin/env python3
"""New DRAFT snapshot for calibrated serial OTA corner scheduling only."""
import argparse
import ast
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.materialize_e1_packets import refresh_public
from src.e1_benchmarks import build_trusted


def save(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def read(path):return json.loads(path.read_text())


def rebase(value,old,new):
    if isinstance(value,dict):return {k:rebase(v,old,new) for k,v in value.items()}
    if isinstance(value,list):return [rebase(v,old,new) for v in value]
    if isinstance(value,str) and (value==old or value.startswith(old+'/')):return new+value[len(old):]
    return value


def check_serial_only(original,revised,function):
    old=ast.parse(original);new=ast.parse(revised)
    before=next(n for n in old.body if isinstance(n,ast.FunctionDef) and n.name==function)
    after=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name==function)
    if ast.get_source_segment(original,before)!=ast.get_source_segment(revised,after):raise ValueError('Original OTA measurement function changed')
    changes=0
    for node in ast.walk(old):
        if isinstance(node,ast.Call) and ((isinstance(node.func,ast.Name) and node.func.id=='ThreadPoolExecutor') or
                (isinstance(node.func,ast.Attribute) and node.func.attr=='ThreadPoolExecutor')):
            for keyword in node.keywords:
                if keyword.arg=='max_workers' and isinstance(keyword.value,ast.Constant) and keyword.value.value==2:
                    keyword.value.value=1;changes+=1
    if changes!=1 or ast.dump(old)!=ast.dump(new):raise ValueError('Only one corner ThreadPoolExecutor2-to-1 scheduling edit is permitted')


def bind(preparation,bindings):
    began=time.monotonic();cpu=time.process_time();catalog=read(preparation/'summary.json')
    if catalog['status']!='DRAFT_NOT_FORMAL' or catalog['formal_trials']!=0:raise ValueError('Never hot-edit a frozen or tested task snapshot')
    if not bindings or not set(bindings).issubset({'five_t','compact_miller'}):raise ValueError('Explicit calibrated OTA source-template bindings required')
    for target,path in bindings.items():
        task=read(preparation/'private'/('draft_E1_'+target+'_s01')/'task.json')
        original=(Path(task['trusted_template'])/'original_bench.py').read_text();revised=(Path(path).parent/'trusted_bench/original_retained_bench.py').read_text()
        check_serial_only(original,revised,'simulate' if target=='five_t' else 'measure')
    output=ROOT/'runtime/task_preparation'/('e1_matched_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    shutil.copytree(preparation,output,ignore=lambda p,n:[name for name in n if name.startswith('schematic_feasibility') or name=='__pycache__'])
    for path in output.rglob('*.json'):
        value=rebase(read(path),str(preparation),str(output));path.chmod(0o644);save(path,value)
    for target,path in bindings.items():
        for sized in range(1,4):
            folder=output/'private'/('draft_E1_'+target+'_s%02d'%sized);task=read(folder/'task.json');template=folder/'trusted_template'
            shutil.rmtree(template);task.pop('trusted_template');task.pop('trusted_template_files');task['source_template']=str(Path(path).resolve())
            files=build_trusted(task,task['configurations'][0],template)
            task.update(trusted_template=str(template),trusted_template_files=files,
                prospective_corner_scheduling={'workers':1,'measurement_function_source_unchanged':True,'calibrated_source_template':str(path)})
            save(folder/'task.json',task)
    catalog.update(output=str(output),previous_task_root=str(preparation),
        prospective_serial_bench_revision={'bindings':bindings,'parameter_domains_and_independent_references_unchanged':True,
            'measurement_function_source_unchanged':True,'old_snapshots_unchanged':True,'wall_seconds':time.monotonic()-began,'process_CPU_seconds':time.process_time()-cpu})
    save(output/'summary.json',catalog);save(output/'public/catalog.json',catalog);refresh_public(output)
    print(json.dumps({'preparation':str(output),'serial_targets':list(bindings),'new_physical_calls':0,'model_calls':0}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--preparation',type=Path,required=True);parser.add_argument('--bindings',type=Path,required=True)
    args=parser.parse_args();bind(args.preparation.resolve(),read(args.bindings))
