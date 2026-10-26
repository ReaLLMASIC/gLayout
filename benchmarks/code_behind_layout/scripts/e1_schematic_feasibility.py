#!/usr/bin/env python3
"""Actual independent N(z) feasibility, without layout, LVS, PEX or S2 claims."""
import argparse,ast,importlib.util,json,math,sys,threading,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import subprocess
ROOT=Path(__file__).resolve().parents[1]
if not (ROOT/'src').is_dir() and Path('/work/src').is_dir():ROOT=Path('/work')
sys.path.insert(0,str(ROOT))
from src.spice_validation import validate_analysis
from scripts.materialize_e1_packets import local,host


def save(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def electrical_constraints(contract,corners):
    failures=[]
    for name in contract['required_corners']:
        row=corners.get(name,{})
        if not row.get('complete') or not row.get('operating_point_valid'):
            failures.append(name+':incomplete_or_invalid_operating_point');continue
        for rule in contract['specifications']:
            metric=row['metrics'].get(rule['name'])
            if not metric or metric['unit']!=rule['unit'] or metric.get('value') is None:
                failures.append(name+':missing_'+rule['name']);continue
            value=metric['value']
            if not math.isfinite(value) or 'min' in rule and value<rule['min'] or 'max' in rule and value>rule['max']:
                failures.append(name+':'+rule['name'])
        if row.get('original_strict_constraints_passed') is False:failures.append(name+':original_strict_constraints')
    return not failures,failures


def point(task,configuration,directory):
    started=time.monotonic();directory.mkdir(parents=True);reference=directory/'independent_reference.spice'
    reference.write_bytes(local(configuration['reference_file']).read_bytes());template=local(task['trusted_template']);meta=json.loads((template/'meta.json').read_text())
    contract=configuration['contract'];corners={};kind=task['target'];top=task['top_cell'];ports=meta['ports']
    if meta['bench_kind']=='mirror':
        # The retained mirror loop names its DUT mirror4_rc. This is a pure
        # subcircuit-name transport, not an extracted/physical RC assertion.
        alias=directory/'bench_cell_alias_no_RC.spice';text=reference.read_text()
        text=text.replace('.subckt mirror4 ','.subckt mirror4_rc ').replace('.ends mirror4\n','.ends mirror4_rc\n')
        if '.subckt mirror4_rc ' not in text:raise ValueError('Literal mirror benchmark alias site changed')
        alias.write_text('* Schematic-only cell-name alias; no physical parasitics or correctness claimed\n'+text)
        observation={'corners':{}};artifacts={'spice':{}}
        namespace={'out':directory,'contract':contract,'np':np,'math':math,'json':json,'subprocess':subprocess,
            'validate_analysis':validate_analysis,'observation':observation,'artifacts':artifacts,'save':lambda:None,
            'net':alias,'nodes':[{'VREF':'ref','VOUT':'out','VSS':'vdd','B':'vdd'}[p.upper()] for p in ports]}
        exec(compile((template/'bench.py').read_text(),str(template/'bench.py'),'exec'),namespace)
        for corner,row in observation['corners'].items():corners[corner]={'complete':row['converged'],'operating_point_valid':row['operating_point_valid'],'metrics':row['metrics']}
    elif meta['bench_kind']=='independent':
        scope={'__name__':'independent_schematic_bench'};exec(compile((template/'bench.py').read_text(),str(template/'bench.py'),'exec'),scope)
        scope['out']=directory
        if meta['bench_function']=='corner_run':
            record={'results':{}};scope.update(gold=reference,cell=top,name=kind,nodes=[meta['bindings'][p.upper()] for p in ports],a=SimpleNamespace(analysis_timeout=180),
                record=record,lock=threading.Lock(),save=lambda:save(directory/'raw_measurements.json',record))
        rows={}
        for corner in contract['required_corners']:
            if meta['bench_function']=='corner_run':scope['corner_run'](corner);row=scope['record']['results'][corner]
            else:row=scope['measure'](reference,top,'prelayout',corner,ports)
            rows[corner]=row;metrics={}
            if row['complete']:
                for key,binding in meta['metric_bindings'].items():
                    value=row['metrics'][binding['source']];metrics[key]={'value':abs(value) if binding.get('absolute') else value,'unit':binding['unit']}
            corners[corner]={'complete':row['complete'],'operating_point_valid':bool(row.get('development_electrical_meaning',row.get('electrical_meaning',row.get('operating_point_valid',False)))),
                'metrics':metrics}
        save(directory/'raw_measurements.json',rows)
    elif meta['bench_kind']=='ota':
        original=(template/'original_bench.py').read_text();function_name='simulate' if kind=='five_t' else 'measure'
        function=next(n for n in ast.parse(original).body if isinstance(n,ast.FunctionDef) and n.name==function_name)
        body=ast.get_source_segment(original,function);(directory/'measurement_function.py').write_text(body+'\n')
        bindings={'VDD':'vdd','GND':'0','IBIAS':'bias','IBIASN':'bn','IBIASP':'bp','VP':'vp','VN':'vn','VOUT':'out'}
        nodes=' '.join(bindings[p.upper()] for p in ports)
        scope={'np':np,'time':time,'subprocess':subprocess,'Path':Path,'validate_analysis':validate_analysis,
            'out':directory,'source':reference,'subcircuit':top,'instance_nodes':nodes,'nodes':nodes,
            'tail_node':'tail','mirror_node':'mirror','stage1_node':'stage1',
            'a':SimpleNamespace(vcm=1.1 if kind=='five_t' else 1.05,bias_ua=20,n_bias_ua=20,p_bias_ua=10)}
        exec(compile(body,str(directory/'measurement_function.py'),'exec'),scope);rows={}
        mapping={'gain':('gain_10Hz_dB','dB'),'ugb':('ugb_Hz','Hz'),'phase_margin':('phase_margin_deg','deg'),
            'settled_tracking_error':('settled_tracking_error_V','V'),'power':('power_W','W')}
        for corner in contract['required_corners']:
            name,row=scope[function_name](corner,2.);rows[name]=row
            integrity=row.get('operating_point_integrity' if kind=='five_t' else 'op_integrity',{})
            complete=bool(integrity.get('complete') and set(row.get('analyses',{}))=={'ac','tran','dc'} and
                all(v.get('returncode')==0 and v.get('integrity',{}).get('complete') for v in row['analyses'].values()))
            metrics={}
            if complete:
                metrics={key:{'value':row[src],'unit':unit} for key,(src,unit) in mapping.items() if src in row}
                metrics['nominal_tracking_error']={'value':abs(row['output_V']-scope['a'].vcm),'unit':'V'}
            strict=bool(row.get('development_feasible' if kind=='five_t' else 'development_nominal_feasible'))
            healthy=bool(complete and row.get('positive_low_frequency_gain') and .15<row['tail_V']<.8)
            if healthy and kind=='five_t':healthy=.4<row['mirror_V']<1.6 and 20e-6<row['supply_current_A']<80e-6
            if healthy and kind=='compact_miller':healthy=.3<row['stage1_V']<1.2 and 50e-6<row['supply_current_A']<160e-6
            metrics['original_development_predicate']={'value':int(strict),'unit':'1'}
            corners[corner]={'complete':complete,'operating_point_valid':healthy,'original_strict_constraints_passed':strict,'metrics':metrics}
        save(directory/'raw_measurements.json',rows)
    else:raise ValueError('Schematic feasibility has no frozen bench binding')
    complete=set(corners)==set(contract['required_corners']) and all(r['complete'] for r in corners.values())
    meets,failures=electrical_constraints(contract,corners)
    result={'scope':'independent_schematic_Nz_electrical_feasibility','fidelity':'prelayout','configuration_id':configuration['configuration_id'],
        'shared_domain_configuration_id':configuration['shared_domain_configuration_id'],'reference_id':configuration['reference_id'],
        'reference':host(reference),'contract':contract,'corners':corners,'all_analyses_complete':complete,'meets_declared_electrical_constraints':complete and meets,
        'constraint_shortfalls':failures,'physical_correctness_established':False,'S2_established':False,'wall_seconds':time.monotonic()-started}
    save(directory/'feasibility.json',result);return result


def run(preparation,workers,targets=None,adopt_root=None):
    started=time.monotonic();preparation=local(preparation);output=preparation/'private'/('schematic_feasibility_'+__import__('datetime').datetime.now(__import__('datetime').timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    output.mkdir();public=[];all_rows=[];jobs=[]
    print(json.dumps({'private_evidence_root':host(output),'targets':targets or 'all_eight'}),flush=True)
    for target in json.loads((preparation/'summary.json').read_text())['tasks']:
        if not target['task_id'].endswith('_s01'):continue
        task=json.loads((preparation/'private'/target['task_id']/'task.json').read_text())
        if targets and task['target'] not in targets:continue
        for configuration in task['configurations']:jobs.append((task,configuration,output/task['target']/configuration['configuration_id']))
    declared=25*(len(targets) if targets else 8)
    if len(jobs)!=declared:raise ValueError('Each selected shared target domain requires exactly25 configurations')
    jobs.sort(key=lambda job:(job[1]['configuration_id'],job[0]['target']))
    pending=[]
    for task,configuration,directory in jobs:
        prior=local(adopt_root)/task['target']/configuration['configuration_id']/'feasibility.json' if adopt_root else None
        if prior and prior.is_file():
            record=json.loads(prior.read_text())
            if record['contract']!=configuration['contract'] or local(record['reference']).read_bytes()!=local(configuration['reference_file']).read_bytes():
                raise ValueError('Adopted schematic point has a different independent N(z) or contract')
            directory.mkdir(parents=True);save(directory/'adopted_evidence.json',{'original_evidence':host(prior),
                'reason':'parallel_development_resource_calibration','new_solver_calls':0,'original_costs_retained':True})
            all_rows.append({'target':task['target'],'complete':record['all_analyses_complete'],'meets':record['meets_declared_electrical_constraints'],
                'evidence':host(prior),'adopted':True})
        else:pending.append((task,configuration,directory))
    save(output/'index.json',all_rows)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(point,*job):job for job in pending}
        for future in as_completed(futures):
            task,configuration,directory=futures[future]
            try:record=future.result();row={'target':task['target'],'complete':record['all_analyses_complete'],'meets':record['meets_declared_electrical_constraints'],'evidence':host(directory/'feasibility.json')}
            except Exception as error:
                directory.mkdir(parents=True,exist_ok=True);save(directory/'host_error.json',{'error':type(error).__name__+': '+str(error)})
                row={'target':task['target'],'complete':False,'meets':False,'evidence':host(directory/'host_error.json'),'host_error':True}
            all_rows.append(row);save(output/'index.json',all_rows)
            if len(all_rows)%25==0:print(json.dumps({'schematic_points_completed':len(all_rows),'declared':declared}),flush=True)
    for target in sorted({r['target'] for r in all_rows}):
        rows=[r for r in all_rows if r['target']==target];public.append({'target':target,'declared_configurations':25,'complete_configurations':sum(r['complete'] for r in rows),
            'meet_specifications':sum(r['meets'] for r in rows),'host_errors':sum(r.get('host_error',False) for r in rows),'private_raw_root':host(output/target)})
    result={'scope':'schematic_only_not_S1_S2','status':'COMPLETE','private_evidence_root':host(output),'targets':public,
        'distinct_target_logics':len(public),'shared_domain_points':declared,'point_count_not_independent_circuit_count':True,'wall_seconds':time.monotonic()-started,
        'adopted_points':sum(r.get('adopted',False) for r in all_rows),'adopt_root':str(adopt_root) if adopt_root else None,
        'workers':workers,'physical_correctness_or_S2_established':False,'formal_trials':0,'model_calls':0,'training_examples':0,'hidden_details_exported':False}
    if not targets:save(preparation/'public/schematic_feasibility.json',result)
    save(output/'summary.json',result);save(Path.cwd()/'schematic_feasibility_summary.json',result)
    print(json.dumps(result),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--preparation',type=Path,required=True);p.add_argument('--workers',type=int,choices=[1,2],default=2)
    p.add_argument('--targets',nargs='+',choices=['mirror','cascode_mirror','source_follower','stacked_switch','common_source_stage','resistive_diff','five_t','compact_miller'])
    p.add_argument('--adopt-root',type=Path);a=p.parse_args();run(a.preparation,a.workers,a.targets,a.adopt_root)
