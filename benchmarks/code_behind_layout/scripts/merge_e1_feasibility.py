#!/usr/bin/env python3
"""Bind eight explicitly selected qualification runs to the final DRAFT domain."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def save(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def merge(preparation,bindings_path):
    bindings=json.loads(bindings_path.read_text());catalog=json.loads((preparation/'summary.json').read_text())
    declared={row['target'] for row in catalog['tasks']}
    if set(bindings['targets'])!=declared or len(declared)!=8:raise ValueError('Exactly one explicit run binding per target is required')
    targets=[];point_index=[];processed=0
    for target in sorted(declared):
        task=json.loads((preparation/'private'/('draft_E1_'+target+'_s01')/'task.json').read_text())
        source=bindings['targets'][target];raw=Path(source['private_raw_root']);complete=meets=host_errors=0
        for point in task['configurations']:
            directory=raw/target/point['configuration_id'];filename=directory/'feasibility.json';error=directory/'host_error.json'
            if filename.is_file():
                row=json.loads(filename.read_text())
                if row['configuration_id']!=point['configuration_id'] or row['shared_domain_configuration_id']!=point['shared_domain_configuration_id']:
                    raise ValueError('A qualification point has another configuration identity')
                if row['contract']!=point['contract'] or Path(row['reference']).read_bytes()!=Path(point['reference_file']).read_bytes():
                    raise ValueError('A qualification point has another independent N(z) or contract: '+str(filename))
                complete+=bool(row['all_analyses_complete']);meets+=bool(row['meets_declared_electrical_constraints']);processed+=1
                point_index.append({'target':target,'configuration_id':point['configuration_id'],'evidence':str(filename)})
            elif error.is_file():
                host_errors+=1;processed+=1;point_index.append({'target':target,'configuration_id':point['configuration_id'],'host_error':str(error)})
        targets.append({'target':target,'declared_configurations':25,'complete_configurations':complete,'meet_specifications':meets,
            'host_errors':host_errors,'private_raw_root':str(raw/target),'producer':source['producer']})
    save(preparation/'private/qualified_schematic_bindings.json',{'input_bindings':str(bindings_path),'points':point_index,'selection':bindings})
    result={'scope':'schematic_only_not_S1_S2','status':'COMPLETE' if processed==200 else 'INCOMPLETE',
        'preparation':str(preparation),'targets':targets,'shared_domain_points':200,'processed_points':processed,
        'distinct_target_logics':8,'point_count_not_independent_circuit_count':True,'formal_trials':0,'model_calls':0,
        'physical_correctness_or_S2_established':False,'private_bindings':str(preparation/'private/qualified_schematic_bindings.json'),
        'original_partial_and_retry_costs_retained':True}
    save(preparation/'public/schematic_feasibility.json',result)
    print(json.dumps({'report':str(preparation/'public/schematic_feasibility.json'),**{k:result[k] for k in ['status','processed_points','targets']}}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--preparation',type=Path,required=True);parser.add_argument('--bindings',type=Path,required=True)
    args=parser.parse_args();merge(args.preparation.resolve(),args.bindings.resolve())
