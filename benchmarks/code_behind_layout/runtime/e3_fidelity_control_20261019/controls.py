"""Two declared fresh E3 F3 transport controls, no model or hidden point."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time
import shutil

ROOT = Path('/srv/code-behind-layout')
sys.path.insert(0, str(ROOT))
from scripts.e2_execution import resource_gate
from scripts.e3_fidelity_point import evaluate

PREPARATION = ROOT/'runtime/task_preparation/e3_expanded_P_20261019T035505371049Z'
CALIBRATION = ROOT/'runs/development/promotion_calibration_20261019T0353Z_nine_validation.json'
OUT = ROOT/'runs/development/E3_fidelity_controls'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
OUT.mkdir(parents=True, exist_ok=False)
plan = {'scope':'two_development_actual_F3_transport_controls_NOT_FORMAL',
    'source_preparation':str(PREPARATION),'calibration':str(CALIBRATION),
    'cases':['draft_E3_five_t_edit01','draft_E3_compact_miller_edit01'],
    'configuration':'anchor','policy':'F3','allow_screening':False,
    'per_point_absolute_wall_budget_seconds':1800,
    'nominal_vs_full_TT_UGB_relative_tolerance':1e-6,
    'objective_arithmetic_relative_tolerance':1e-12,
    'model_calls':0,'hidden_points':0,'new_full_point_attempts_max':2}
(OUT/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
snapshot=OUT/'implementation_snapshot';snapshot.mkdir()
for name in ['scripts/e3_fidelity_point.py','scripts/e3_nominal_objective.py',
    'scripts/e3_trusted_objective.py','scripts/e2_stage_prepare.py','scripts/e2_cached_evaluator.py',
    'scripts/e2_nominal_bench.py','scripts/e2_spice_process_profile.py',
    'runtime/e3_fidelity_control_20261019/controls.py']:
    destination=snapshot/name;destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(ROOT/name,destination)
print(json.dumps({'output':str(OUT),'plan':plan}),flush=True)
rows=[]
for identifier in plan['cases']:
    waiting_started=time.monotonic()
    sample=resource_gate()
    queue_wall=time.monotonic()-waiting_started
    deadline=(datetime.now(timezone.utc)+timedelta(seconds=1800)).isoformat()
    result=evaluate(PREPARATION/'private'/identifier/'task.json','anchor',OUT/identifier,
        policy='F3',calibration_path=CALIBRATION,allow_screening=False,deadline=deadline,formal=False)
    nominal=(result.get('nominal_actual') or {}).get('measurement',{})
    full=result.get('full_actual') or {}
    nominal_ugb=nominal.get('metrics',{}).get('tt_ugb_Hz')
    feedback=full.get('physical_feedback',{})
    tt=feedback.get('corners',{}).get('tt',{}).get('metrics',{}).get('ugb',{}).get('value')
    difference=(abs(tt-nominal_ugb)/abs(tt)) if tt and nominal_ugb else None
    arithmetic=[]
    for corner,measurements in feedback.get('corners',{}).items():
        metrics=measurements['metrics']
        if all(key in metrics for key in ['ugb','area','ugb_per_area']):
            ugb=metrics['ugb']['value'];area=metrics['area']['value'];objective=metrics['ugb_per_area']['value']
            arithmetic.append({'corner':corner,'relative_error':abs(objective*area-ugb)/abs(ugb)})
    row={'task_id':identifier,'point':str(OUT/identifier/'fidelity_point.json'),
        'dispatch_sample':sample,'resource_queue_wall_seconds':queue_wall,'nominal_actual_complete':nominal.get('complete',False),
        'promotion_decision':result.get('promotion_decision'),
        'full_checked':full.get('checked'),
        'nominal_vs_full_TT_UGB_relative_difference':difference,
        'objective_arithmetic_checks':arithmetic,'costs':result['costs']}
    row['transport_control_passed']=bool(nominal.get('complete') and full.get('checked',{}).get('S2')
        and difference is not None and difference<=1e-6 and len(arithmetic)==3
        and all(value['relative_error']<=1e-12 for value in arithmetic))
    rows.append(row)
    (OUT/'summary.json').write_text(json.dumps({'plan':plan,'rows':rows,'complete':len(rows)==2,
        'all_transport_controls_passed':len(rows)==2 and all(r['transport_control_passed'] for r in rows)},indent=2)+'\n')
    print(json.dumps(row),flush=True)
