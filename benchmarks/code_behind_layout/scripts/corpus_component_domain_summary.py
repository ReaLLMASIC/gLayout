"""Summarize only actual completed C07/TG qualification, never formal labels."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
batches=sorted((ROOT/'runs/development/component_train_domain_qualification').glob('*/batch.json'))
states=[json.loads(batch.read_text()) for batch in batches]
jobs=[job for state in states for job in state['jobs'] if job.get('status')!='RUNNING']
result={'scope':'development_component_train_qualification_not_formal','batches':[{'path':str(path),'status':state['status']} for path,state in zip(batches,states)],'circuits':{},'source_lineages':1,'formal_training_rows':0}
for cid in ['C02','C07','TRAIN_TG01']:
    controls=[];points=[]
    for job in jobs:
        if job['circuit_id']!=cid:continue
        path=Path(job['run_directory'])/'bench_result.json'
        if not path.exists():path=Path(job['run_directory'])/'evaluation/physical.json'
        raw=json.loads(path.read_text()) if path.exists() else {}
        row={'configuration_id':job['configuration_id'],'run_directory':job['run_directory'],'returncode':job['returncode'],
             'solver':job.get('solver','trap'),'retry_of':job.get('retry_of'),'domain_id':job.get('domain_id',cid),
             'independent_transient_inputs':job.get('independent_transient_inputs',False),
             'analysis_complete':raw.get('all_analyses_complete',False),'operating_points_valid':raw.get('all_operating_points_valid',False),
             'corners':{name:item['metrics'] for name,item in raw.get('corners',{}).items()}}
        if job['prelayout']:controls.append(row)
        else:
            row.update(full_physical_analysis_complete=raw.get('full_physical_analysis_complete',False),area_um2=raw.get('area_um2'),
                DRC_clean=raw.get('DRC',{}).get('is_clean',False),LVS_clean=raw.get('LVS',{}).get('is_clean',False),positive_RC=raw.get('RC',{}).get('has_real_RC',False))
            row['qualified']=all(row[key] for key in ['analysis_complete','operating_points_valid','full_physical_analysis_complete','DRC_clean','LVS_clean','positive_RC'])
            points.append(row)
    metrics=({name for point in points for values in point['corners'].values() for name,value in values.items() if type(value) in [int,float]})
    ranges={name:{'min':min(values),'max':max(values)} for name in sorted(metrics) if (values:=[values[name] for point in points for values in point['corners'].values() if type(values.get(name)) in [int,float]])}
    control=lambda point:point['domain_id']+'__'+point['solver']+('__independent_inputs' if point['independent_transient_inputs'] else '')
    domains={solver:{'unique_configurations_attempted':len({point['configuration_id'] for point in points if control(point)==solver}),
                     'unique_configurations_qualified':len({point['configuration_id'] for point in points if control(point)==solver and point['qualified']})} for solver in {control(point) for point in points}}
    for domain in domains.values():domain['all_nine_points_ready']=domain['unique_configurations_qualified']==9
    result['circuits'][cid]={'schematic_controls':controls,'actual_postlayout_attempts_completed':len(points),'qualified_attempts':sum(point['qualified'] for point in points),
        'domains_by_solver':domains,'all_nine_points_ready':any(domain['all_nine_points_ready'] for domain in domains.values()),
        'actual_metric_ranges':ranges,'points':points,'prospective_specs_frozen':False}
out=ROOT/'results/derived/component_train_domain_development_qualification.json';out.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({cid:{key:value for key,value in result['circuits'][cid].items() if key not in ['points','schematic_controls']} for cid in result['circuits']},indent=2))
