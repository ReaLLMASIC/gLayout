"""Qualify the predeclared nine-point per-device nf domain after C02 releases."""
from datetime import datetime,timezone
import json
import shutil
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.train_collection_queue import resource_sample

out=ROOT/'runs/development/c01_per_device_nf_qualification'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');out.mkdir(parents=True)
prior=ROOT/'runs/development/component_train_domain_qualification/20261019T031410828736Z/batch.json'
table_path=ROOT/'configs/development/c01_per_device_nf_family/configurations.json'
table=json.loads(table_path.read_text());commands=json.loads((table_path.parent/'qualification_commands.json').read_text())['commands']
base=json.loads((ROOT/'runtime/train_collections/c01_collection_v1/collection.json').read_text())
input_root=out/'input';source=input_root/'source_pack';shutil.copytree(base['source_pack'],source)
for path in source.rglob('*'):path.chmod(0o755 if path.is_dir() else 0o644)
source.chmod(0o755)
state={'source_pack_copied_byte_for_byte_from':base['source_pack'],'runtime_probe_input':str(input_root),'status':'WAITING_FOR_C02_LANE_RELEASE','started_at_utc':datetime.now(timezone.utc).isoformat(),
    'predecessor_batch':str(prior),'declared_table':table,'jobs':[],'source_lineages':1,'formal_training_rows':0,'model_requests':0}
def save():(out/'batch.json').write_text(json.dumps(state,indent=2)+'\n')
save();deadline=time.monotonic()+8*3600
try:
    while json.loads(prior.read_text())['status'] not in ['COMPLETED_QUALIFICATION_ATTEMPTS','PAUSED']:
        if time.monotonic()>deadline:raise TimeoutError('C02 predecessor window exceeded; no NF qualification launched')
        time.sleep(15)
    state['status']='RUNNING_OR_RESOURCE_WAIT';save()
    for item in commands:
        while True:
            sample=resource_sample()
            if sample['actual_busy_cores']+2<=24 and sample['RAM_used_GiB']<=190:break
            if time.monotonic()>deadline:raise TimeoutError('Actual CPU/RAM gate unavailable; no extra job launched')
            time.sleep(15)
        identifier=item['configuration_id'];log_path=out/(identifier+'.log')
        command=list(item['argv']);separator=command.index('--');command[separator:separator]=['--input-dir',str(input_root)]
        record={'configuration_id':identifier,'declared_probe_arguments':item['argv'],'argv':command,'started_at_utc':datetime.now(timezone.utc).isoformat(),
                'resource_sample_before_start':sample,'status':'RUNNING'}
        state['jobs'].append(record);save()
        with log_path.open('w') as log:ran=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        run=Path(json.loads(log_path.read_text().splitlines()[0])['output']);raw_path=run/'baseline/physical.json'
        raw=json.loads(raw_path.read_text()) if raw_path.exists() else {}
        audit=None
        if raw.get('LVS',{}).get('is_clean'):
            code="import json,sys;from pathlib import Path;from src.device_intent import compare_device_intent;p=Path(sys.argv[1]);print(json.dumps(compare_device_intent((p/'layout_lvs.spice').read_text(),(p/'target.spice').read_text())))"
            audit=json.loads(subprocess.check_output([str(ROOT/'runtime/training-venv/bin/python'),'-c',code,str(run/'baseline')],cwd=ROOT,text=True))
        corners={};feasible=True
        for corner,row in raw.get('corners',{}).items():
            metrics=row.get('metrics',{});band=[v['relative_error'] for v in metrics.get('dc_sweep_relative_errors',[]) if .7-1e-7<=v['voltage_V']<=1+1e-7]
            passed=(row.get('complete') and len(band)==4 and metrics.get('nominal_current_relative_error',float('inf'))<=.05
                and metrics.get('output_resistance_ohm',0)>=300000 and max(band)<=.05 and 0<metrics.get('bias_V',0)<1.8)
            corners[corner]={'complete':row.get('complete'),'application_constraints_pass':bool(passed),'metrics':metrics};feasible=feasible and bool(passed)
        full=bool(raw.get('full_physical_analysis_complete') and raw.get('DRC',{}).get('is_clean') and raw.get('LVS',{}).get('is_clean') and raw.get('RC',{}).get('has_real_RC') and audit and audit['is_clean'])
        record.update(status='COMPLETED',returncode=ran.returncode,run_directory=str(run),ended_at_utc=datetime.now(timezone.utc).isoformat(),
            full_physical_and_device_intent_complete=full,device_intent_audit=audit,corners=corners,
            application_constraints_pass=bool(full and len(corners)==3 and feasible),area_um2=raw.get('area_um2'))
        save();print(json.dumps({key:value for key,value in record.items() if key not in ['corners','device_intent_audit']}),flush=True)
    state.update(status='COMPLETED_QUALIFICATION_ATTEMPTS',ended_at_utc=datetime.now(timezone.utc).isoformat(),
        qualified_points=sum(bool(job.get('application_constraints_pass')) for job in state['jobs']),
        all_nine_points_qualified=all(job.get('application_constraints_pass') for job in state['jobs']) and len(state['jobs'])==9);save()
except Exception as exc:
    state.update(status='PAUSED',reason=type(exc).__name__+': '+str(exc),ended_at_utc=datetime.now(timezone.utc).isoformat());save();raise
