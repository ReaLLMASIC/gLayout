"""Read actual C05/C08 development domain qualification; no formal admission."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
batch=max((ROOT/'runs/development/additional_train_domain_qualification').glob('*/batch.json'),key=lambda p:p.stat().st_mtime)
state=json.loads(batch.read_text());result={'scope':'development_train_domain_qualification_not_formal','batch':str(batch),'completed_point_jobs':len(state['jobs']),'expected_point_jobs':18,'circuits':{}}
for cid in ['C05','C08']:
    points=[]
    for job in state['jobs']:
        if job['circuit_id']!=cid:continue
        root=Path(job['run_directory']);path=root/'baseline/physical.json'
        if not path.exists():
            points.append({'configuration_id':job['configuration_id'],'physical_complete':False,'core_constraints_pass':False,'raw_run':str(root),'reason':'No physical record'});continue
        raw=json.loads(path.read_text());complete=bool(raw.get('full_physical_analysis_complete') and raw.get('DRC',{}).get('is_clean') and raw.get('LVS',{}).get('is_clean') and raw.get('RC',{}).get('has_real_RC'))
        corners={corner:row['metrics'] for corner,row in raw.get('corners',{}).items()};failures=[]
        for corner,m in corners.items():
            if not 0<m.get('bias_V',0)<1.8:failures.append(corner+':bias_outside_rails')
            if cid=='C05':
                if not .1<m.get('output_bias_V',0)<1.7:failures.append(corner+':follower_output_bias')
                if m.get('gain_10Hz_real',0)<.6:failures.append(corner+':gain_below_0p6')
            else:
                if abs(m.get('output_bias_V',0)-.9)>.015:failures.append(corner+':OTA_output_bias')
                if m.get('gain_10Hz_dB',0)<25:failures.append(corner+':gain_below_25dB')
                if m.get('phase_margin_deg',0)<60:failures.append(corner+':PM_below_60deg')
                if m.get('settled_tracking_error_V',1)>.015:failures.append(corner+':tracking_above_15mV')
        points.append({'configuration_id':job['configuration_id'],'physical_complete':complete,'core_constraints_pass':complete and not failures,'core_constraint_failures':failures,'corners':corners,'area_um2':raw.get('area_um2'),'raw_run':str(root)})
    metrics=['gain_10Hz_real','f3db_Hz','DUT_supply_power_W'] if cid=='C05' else ['gain_10Hz_dB','ugb_Hz','phase_margin_deg','settled_tracking_error_V','DUT_supply_power_W']
    ranges={name:{'min':min(values),'max':max(values)} for name in metrics if (values:=[m[name] for p in points if p['physical_complete'] for m in p.get('corners',{}).values() if name in m])}
    result['circuits'][cid]={'completed_points':len(points),'physical_complete_points':sum(p['physical_complete'] for p in points),'core_feasible_points':sum(p['core_constraints_pass'] for p in points),'all_points_ready':len(points)==9 and all(p['core_constraints_pass'] for p in points),'actual_metric_ranges':ranges,'points':points,'constraints_frozen':False,'formal_training_rows':0}
out=ROOT/'results/derived/C05_C08_domain_development_qualification.json';out.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({cid:{key:value for key,value in row.items() if key!='points'} for cid,row in result['circuits'].items()},indent=2))
