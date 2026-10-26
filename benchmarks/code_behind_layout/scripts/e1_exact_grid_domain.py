#!/usr/bin/env python3
"""Create prospective common-PCell-expressible domains, never rewrite old gold."""
from copy import deepcopy
from datetime import datetime,timezone
from decimal import Decimal,ROUND_UP
import argparse,importlib,itertools,json,sys
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
FIELDS={
 'mirror':(['width'],['length'],'mirror4',None),
 'cascode_mirror':(['width'],['length'],'cascode_mirror','cascode_mirror_reference'),
 'source_follower':(['input_width','bias_width'],['input_length','bias_length'],'source_follower','source_follower_reference'),
 'stacked_switch':(['n_width','p_width'],['length'],'stacked_switch','stacked_switch_reference'),
 'common_source_stage':(['n_width','p_width'],['length'],'common_source_stage','common_source_reference'),
 'resistive_diff':(['input_width','bias_width'],['input_length','bias_length'],'resistive_diff','resistive_diff_reference'),
 'five_t':(['input_width'],['input_length'],'five_t_ota','five_t_reference'),
 'compact_miller':(['input_width'],['input_length'],'compact_miller_ota','compact_miller_reference')}


def save(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def exact(value):return float(Decimal('.01')*(Decimal(str(value))/Decimal('.01')).quantize(1,rounding=ROUND_UP))


def domain(original,kind):
    widths,lengths,top,module=FIELDS[kind];default=original['configurations'][0]['parameters'];rows=[];seen=set()
    def add(parameters,origin):
        parameters=dict(parameters)
        for name in widths+lengths:parameters[name]=exact(parameters[name])
        key=json.dumps(parameters,sort_keys=True)
        if key not in seen:seen.add(key);rows.append({'parameters':parameters,'parameter_only_origin':origin})
    for point in original['configurations']:add(point['parameters'],{'original_configuration_id':point['configuration_id'],'rule':'Upfront ROUND_UP onto pinned0.01um MOS-size grid'})
    # Complete any parameter-only collisions in a fixed geometric order. No
    # measurement, feasibility flag or objective value is consulted here.
    for w,l in itertools.product([.96,.98,1.,1.02,1.04],[.96,.98,1.,1.02,1.04]):
        parameters=dict(default)
        for key in widths:parameters[key]=float(Decimal(str(default[key]))*Decimal(str(w)))
        for key in lengths:parameters[key]=float(Decimal(str(default[key]))*Decimal(str(l)))
        add(parameters,{'width_scale':w,'length_scale':l,'rule':'Deterministic supplement after parameter collisions'})
    if len(rows)<25:raise ValueError('The parameter-only legal grid did not produce25 distinct configurations')
    return rows[:25]


def materialize(bindings_path):
    bindings=json.loads(bindings_path.read_text());out=ROOT/'runtime/task_preparation'/('e1_exact_grid_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    (out/'private').mkdir(parents=True,mode=0o700);(out/'public').mkdir();newbindings=deepcopy(bindings);newbindings['domain_version']='exact_grid_v2';newbindings['supersedes_bindings']=str(bindings_path)
    summary=[]
    for record in newbindings['targets']:
        kind=record['target'];oldpath=Path(record['template']);oldpath=oldpath if oldpath.is_absolute() else ROOT/oldpath;original=json.loads(oldpath.read_text())
        folder=out/'private'/kind;folder.mkdir();(folder/'references').mkdir();rows=domain(original,kind);widths,lengths,top,module=FIELDS[kind]
        if module:
            reference_module=importlib.import_module('src.generators.'+module)
            builder=reference_module.schematic;shutil.copyfile(ROOT/'src/generators'/(module+'.py'),folder/'independent_reference_builder.py')
        else:
            from scripts.materialize_tasks import reference
            builder=lambda parameters:reference('mirror',parameters)
            shutil.copyfile(ROOT/'scripts/materialize_tasks.py',folder/'independent_reference_builder.py')
        points=[]
        for index,row in enumerate(rows):
            ident='anchor' if index==0 else ('dev_%02d'%index if index<9 else 'hidden_%02d'%(index-8));parameters=row['parameters'];gold=builder(parameters)
            reference_path=folder/'references'/(ident+'.spice');reference_path.write_text(gold)
            contract=deepcopy(original['configurations'][0]['contract']);contract.update(task_id='exact_grid_v2_'+kind,configuration_id=ident,reference_id='independent_exact_grid_v2_'+kind+'_'+ident,immutable_parameters=parameters)
            if kind in ('five_t','compact_miller') and not any(s['name']=='original_development_predicate' for s in contract['specifications']):
                contract['specifications'].append({'name':'original_development_predicate','unit':'1','min':1,'max':1})
            points.append({'configuration_id':ident,'role':'anchor' if index==0 else 'development' if index<9 else 'hidden','parameters':parameters,
                'reference_id':contract['reference_id'],'reference_file':str(reference_path),'contract':contract,'parameter_only_origin':row['parameter_only_origin']})
        task=deepcopy(original);task.update(status='DRAFT_PROSPECTIVE_EXACT_GRID_V2',task_id='exact_grid_v2_'+kind,configurations=points,formal_admission=False,
            original_template=str(oldpath),domain_version='exact_grid_v2',legal_MOS_dimension_grid_um=.01,
            dimension_rule='Both independent N(z) and primitive API receive these exact dimensions upfront; constructor ROUND_UP is an identity. PDK geometry grid remains0.005um.',
            selection_rule='Original parameter rows snapped upfront; collisions supplemented by a fixed parameter-only Cartesian order, no S2/specification/quality filtering.',
            prior_qualification_not_reused=True)
        if kind in ('five_t','compact_miller'):shutil.copytree(oldpath.parent/'trusted_bench',folder/'trusted_bench')
        save(folder/'task.json',task);record['template']=str(folder/'task.json')
        summary.append({'target':kind,'distinct_configurations':25,'common_PCell_dimension_grid_um':.01,'new_physical_measurements':0})
    save(out/'bindings.json',newbindings);save(out/'public/domain_revision.json',{'scope':'prospective_development_grid_domain_revision','domain_version':'exact_grid_v2',
        'reason':'Actual standalone target control extractedL0.520 for declared0.515; primitives/fet.py uses mappedpdk.snap_to_2xgrid ROUND_UP. Old domain and failed control retained.',
        'selection_does_not_use_S2_or_objective':True,'targets':summary,'formal_trials':0,'training_examples':0})
    print(json.dumps({'new_domain_root':str(out),'bindings':str(out/'bindings.json'),'targets':len(summary),'configurations':200}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bindings',type=Path,required=True);a=p.parse_args();materialize(a.bindings.resolve())
