#!/usr/bin/env python3
"""Prospective fixed mirror Cartesian domain after ideal-netlist shortfall."""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
from decimal import Decimal,ROUND_UP
import itertools
import json
from pathlib import Path
import shutil
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
if not (ROOT/'src').is_dir() and Path('/work/src').is_dir():ROOT=Path('/work')
sys.path.insert(0,str(ROOT))
from scripts.materialize_e1_packets import local,host,role_table,refresh_public,save
from scripts.materialize_tasks import reference
from scripts.e1_pcell_prepare import prepare


def rebase(value,old,new):
    if isinstance(value,dict):return {k:rebase(v,old,new) for k,v in value.items()}
    if isinstance(value,list):return [rebase(v,old,new) for v in value]
    if isinstance(value,str) and (value==old or value.startswith(old+'/')):return new+value[len(old):]
    return value


def revise(preparation):
    began=time.monotonic();preparation=local(preparation)
    if json.loads((preparation/'summary.json').read_text())['status']!='DRAFT_NOT_FORMAL':raise ValueError('Only a new prospective DRAFT may be revised')
    output=ROOT/'runtime/task_preparation'/('e1_matched_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    shutil.copytree(preparation,output,ignore=lambda p,n:[name for name in n if name.startswith('schematic_feasibility') or name=='__pycache__'])
    for path in output.rglob('*.json'):
        value=rebase(json.loads(path.read_text()),host(preparation),host(output));path.chmod(0o644);save(path,value)
    scales=[Decimal('.96'),Decimal('.98'),Decimal('1'),Decimal('1.02'),Decimal('1.04')]
    pairs=list(itertools.product(scales,scales));pairs.remove((Decimal('1'),Decimal('1')));pairs.insert(0,(Decimal('1'),Decimal('1')))
    def size(anchor,scale):return float(Decimal('.01')*(Decimal(anchor)*scale/Decimal('.01')).quantize(1,rounding=ROUND_UP))
    fixed=[{'width':size('1.88',w),'length':size('3',l),'numcols':2,'device':'pfet'} for w,l in pairs]
    if len({json.dumps(p,sort_keys=True) for p in fixed})!=25:raise ValueError('Fixed Cartesian parameter grid has a collision')
    revision={'scope':'prospective_schematic_feasibility_domain_revision','status':'DRAFT_FIXED_BEFORE_QUALIFICATION',
        'supersedes':host(preparation),'target':'mirror','reason':'Old independent-N(z) FF output resistance985511.017ohm was below1Mohm; not a layout/model result.',
        'old_shortfall_evidence':host(preparation/'private/schematic_feasibility_20261019T030813798933Z/mirror/dev_07/feasibility.json'),
        'rule':'All25 fixed Cartesian width/length scales .96/.98/1/1.02/1.04 around1.88um/3um, upfront0.01um ROUND_UP; anchor first.',
        'coverage':'Only this narrowed finite25-point parameter domain; not the prior wide domain or a continuous guarantee.',
        'candidate_parameters':fixed,'formal_results_consulted':0,'layout_S2_results_used_for_selection':False}
    save(output/'private/mirror_domain_revision.json',revision)
    seed=json.loads((output/'private/draft_E1_mirror_s01/task.json').read_text())['configurations'][0];base=[]
    for index,parameters in enumerate(fixed):
        point=deepcopy(seed);ident='anchor' if index==0 else ('dev_%02d'%index if index<9 else 'hidden_%02d'%(index-8))
        point.update(configuration_id=ident,role='anchor' if index==0 else 'development' if index<9 else 'hidden',parameters=parameters)
        point.pop('shared_domain_configuration_id',None);point['parameter_only_origin']={'fixed_Cartesian_ordinal':index,'revision':'mirror_narrow_v3'};base.append(point)
    catalog=json.loads((output/'summary.json').read_text());relations=json.loads((output/'private/shared_domain_relationships.json').read_text());costs=[]
    for sized in range(3):
        task_id='draft_E1_mirror_s%02d'%(sized+1);folder=output/'private'/task_id;task=json.loads((folder/'task.json').read_text());points=role_table(base,sized)
        for point in points:
            ident=point['configuration_id'];point.update(reference_id=task_id+'_'+ident,reference_file=host(folder/'references'/(ident+'.spice')))
            local(point['reference_file']).write_text(reference('mirror',point['parameters']))
            point['contract'].update(task_id=task_id,configuration_id=ident,reference_id=point['reference_id'],immutable_parameters=point['parameters'])
        task.update(configurations=points,visible_configurations=points[:9],anchor_contract=points[0]['contract'],shared_domain_id='mirror_narrow_v3_shared25_mirror',
            domain_revision=host(output/'private/mirror_domain_revision.json'))
        save(folder/'task.json',task)
        for name in ['anchor_library','anchor_library_raw']:shutil.rmtree(folder/name)
        library=prepare(local(points[0]['reference_file']),task['top_cell'],points[0]['reference_id'],folder/'anchor_library');costs.append({'task_id':task_id,**library['generation_cost']})
        for row in catalog['tasks']:
            if row['task_id']==task_id:row.update(anchor_parameters=points[0]['parameters'],shared_domain_id=task['shared_domain_id'])
        for row in relations:
            if row['task_id']==task_id:row.update(shared_domain_id=task['shared_domain_id'],anchor_shared_id=points[0]['shared_domain_configuration_id'],
                point_roles=[{k:p[k] for k in ('configuration_id','shared_domain_configuration_id','role')} for p in points])
    catalog.update(output=host(output),domain_revision=host(output/'private/mirror_domain_revision.json'),
        additional_revision_cost={'wall_seconds':time.monotonic()-began,'primitive_library_costs':costs})
    save(output/'summary.json',catalog);save(output/'public/catalog.json',catalog);save(output/'private/shared_domain_relationships.json',relations)
    refresh_public(output)
    print(json.dumps({'preparation':host(output),'revised_target':'mirror','fixed_points':25,'other_targets_unchanged':7}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--preparation',type=Path,required=True);revise(parser.parse_args().preparation)
