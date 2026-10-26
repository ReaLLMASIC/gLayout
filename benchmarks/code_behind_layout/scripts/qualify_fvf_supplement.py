"""One explicit development FVF full-module anchor control; no policy or freeze.

prepare only copies the exact source and vendor-OTA trusted capsule. run consumes
that reviewed bundle once through CandidateExecutor and retains every failure.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import resource
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.prepare_fvf_supplement import SERVER,EDITABLE,GENERATOR,inputs


def read(path):return json.loads(Path(path).read_text())
def save(path,value):Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(task_path,output):
    if ROOT!=SERVER:raise ValueError('Only the original private execution endpoint')
    from scripts.e3_task_prepare import capsule
    task=read(task_path);_,_,proof,original,caller,_=inputs()
    if (task['editable_paths']!=[EDITABLE] or Path(task['source_overrides'][EDITABLE]).read_text()!=original or
        Path(task['frozen_source_overrides']['component_build.py']).read_text()!=caller or
        Path(task['frozen_source_overrides']['generator.py']).read_text()!=GENERATOR):
        raise ValueError('The control must consume the actual complete335-line module/caller/envelope')
    point,=[p for p in task['configurations'] if p['role']=='anchor']
    output=output.resolve();output.relative_to(ROOT/'runs/development/FVF_fullmodule_control')
    output.mkdir(parents=True,exist_ok=False);output.chmod(0o700)
    start,cpu=time.monotonic(),time.process_time()
    source=output/'inputs/source';capsule(task_path,source)
    trusted=output/'inputs/trusted';shutil.copytree(task['trusted_template'],trusted)
    for folder in [trusted,*(p for p in trusted.rglob('*') if p.is_dir())]:folder.chmod(folder.stat().st_mode|0o700)
    for name,content in [('contract.json',json.dumps(point['contract'],indent=2)+'\n'),
                         ('reference.spice',Path(point['reference_file']).read_text())]:
        p=trusted/name
        if p.exists():p.chmod(0o644)
        p.write_text(content)
    meta=read(trusted/'meta.json')
    if meta['bench_kind']!='vendor_ota' or meta['circuit']!='fvf' or meta['top_cell']!=task['top_cell']:
        raise ValueError('Use the actual vendor-FVF trusted template, never E1_binding')
    source_files=sorted(str(p.relative_to(source)) for p in source.rglob('*') if p.is_file())
    trusted_files=sorted(str(p.relative_to(trusted)) for p in trusted.rglob('*') if p.is_file())
    if source_files!=sorted(task['source_files']):raise ValueError('Source capsule closure differs')
    for name in trusted_files:(trusted/name).read_text()  # Same textual snapshot contract as the current Store.
    origin=Path(task['existing_development_qualification']['generation_cost_origin'])/(point['configuration_id']+'.gds')
    if not origin.is_file():raise ValueError('Original actual anchor GDS is missing')
    control={'status':'PREPARED_NO_EDA','scope':'development_FVF_fullmodule_anchor_only_not_formal_not_training',
        'task_path':str(task_path.resolve()),'task':task['task_id'],'point':point,'top_cell':task['top_cell'],
        'source':str(source),'source_files':source_files,'trusted':str(trusted),'trusted_files':trusted_files,
        'source_sha256':{n:sha(source/n) for n in source_files},'trusted_sha256':{n:sha(trusted/n) for n in trusted_files},
        'actual_original_GDS':str(origin),'original_GDS_sha256':sha(origin),'source_equivalence':proof,
        'implementation_sha256':{n:sha(ROOT/n) for n in ['scripts/qualify_fvf_supplement.py','scripts/audit_train_pair_nf_rc.py',
            'src/candidate_executor.py','src/domain_runner.py','src/training.py','src/device_intent.py']},
        'maximum_physical_calls':1,'workers':1,'CPUs':2,'memory_GiB':8,
        'generation_timeout_seconds':240,'evaluator_timeout_seconds':900,'total_window_seconds':1800,
        'parent_lineage':task['parent_lineage'],'new_model_calls':0,'formal_dispatch_allowed':False,
        'preparation_wall_seconds':time.monotonic()-start,'preparation_parent_CPU_seconds':time.process_time()-cpu}
    save(output/'control.json',control)
    return {k:control[k] for k in ['status','scope','task','source_equivalence','maximum_physical_calls','CPUs','memory_GiB',
        'generation_timeout_seconds','evaluator_timeout_seconds','total_window_seconds','preparation_wall_seconds','preparation_parent_CPU_seconds']}


PORT_NODES={'AVDD':'vdd','AVSS':'0','INP':'vp','INM':'vn','VOUT':'out','NBC_10U':'bias1','NB_10U':'bias2'}


def verify_deck(text,ports,cell):
    rows=[line.split() for line in text.splitlines() if line.split() and line.split()[0].upper()=='XDUT']
    expected=['XDUT',*(PORT_NODES[p.upper()] for p in ports),cell]
    if len(rows)!=1 or [v.upper() for v in rows[0]]!=[v.upper() for v in expected]:
        raise ValueError('Actual SPICE XDUT order/binding differs from the exact full-RC port declaration')
    includes=[line.split()[1:] for line in text.splitlines() if line.split() and line.split()[0].lower()=='.include']
    if includes!=[['/evidence/post_rc_measurements/fvf7_pex.spice']]:
        raise ValueError('The actual bench did not consume the retained unsimplified full-RC artifact')


def full_rc_audit(run,point,output):
    started,cpu=time.monotonic(),time.process_time();audit={'status':'QUARANTINED_UNKNOWN','required_after_S1':True,'original_RC_changed':False}
    try:
        evidence=run/'evidence';validation=read(evidence/'validation.json')
        if validation['contract']!=point['contract']:raise ValueError('FullRC contract differs from independently prepared point')
        pex=validation['artifacts']['pex'];ports=pex['ports']
        if pex['top_cell']!='fvf7_rc' or set(p.upper() for p in ports)!=set(PORT_NODES) or len(ports)!=7:
            raise ValueError('FullRC must have the complete unique seven independent port names')
        path=evidence/pex['netlist'];text=path.read_text()
        copied=evidence/'post_rc_measurements/fvf7_pex.spice'
        if copied.read_bytes()!=path.read_bytes():raise ValueError('SPICE transport changed the actual unsimplified RC bytes')
        binding=read(evidence/'post_rc_measurements/bench_binding.json')
        if binding['ports']!=ports or binding['parameters']!=point['parameters']:
            raise ValueError('Actual bench port sequence or immutable sizing differs')
        decks=[]
        for corner in point['contract']['required_corners']:
            for analysis in ['ac','transient','dc']:
                deck=evidence/'post_rc_measurements/post_rc'/corner/(analysis+'.spice')
                verify_deck(deck.read_text(),ports,pex['top_cell']);decks.append(str(deck.relative_to(evidence)))
        reference=run/'trusted/reference.spice'
        if reference.read_bytes()!=Path(point['reference_file']).read_bytes():raise ValueError('Independent N(z) changed')
        from scripts.audit_train_pair_nf_rc import contracted_devices
        from src.device_intent import compare_device_intent
        view=contracted_devices(text,pex['top_cell'],ports)
        graph=compare_device_intent(view,reference.read_text())
        (output/'full_rc_audit_view.spice').write_text(view)
        audit.update(status='RC_DEVICE_GRAPH_MATCH' if graph['is_clean'] else 'QUARANTINED_MISMATCH',
            actual_PEX_port_order=ports,actual_bench_decks_checked=decks,transport_copy_bytes_equal=True,
            actual_deck_order_exact=True,graph=graph)
    except (ValueError,OSError,KeyError,TypeError) as error:
        audit['error']=type(error).__name__+': '+str(error)
    finally:
        audit.update(wall_seconds=time.monotonic()-started,parent_CPU_seconds=time.process_time()-cpu)
        save(output/'full_rc_intent_audit.json',audit)
    return audit


def geometry(first,second,top_name):
    import gdstk
    def load(path):
        library=gdstk.read_gds(path);top,=[c for c in library.cells if c.name==top_name];top.flatten();layers={}
        for polygon in top.get_polygons():layers.setdefault((polygon.layer,polygon.datatype),[]).append(polygon)
        labels=sorted((x.text,tuple(x.origin),x.layer,x.texttype,x.rotation,x.magnification,x.x_reflection) for x in top.labels)
        return library,layers,labels
    a,left,la=load(first);b,right,lb=load(second)
    if (a.unit,a.precision)!=(b.unit,b.precision):raise ValueError('GDS units/precision changed')
    changed=[list(layer) for layer in set(left)|set(right) if gdstk.boolean(left.get(layer,[]),right.get(layer,[]),'xor',precision=a.precision/a.unit)]
    return {'equal':not changed and la==lb,'changed_layers':changed,'all_label_attributes_equal':la==lb,
            'translation_removed':False,'precision_in_GDS_units':a.precision/a.unit}


def run(output):
    if ROOT!=SERVER:raise ValueError('Physical control only on the original execution host')
    output=output.resolve();control=read(output/'control.json');journal=output/'run.json'
    with journal.open('x') as stream:stream.write('{}\n')
    state={'status':'WAITING_RESOURCE_GATE','scope':control['scope'],'physical_call_reservations':0,'new_model_calls':0,
        'automatic_retry':False,'resource_samples':[],'started_at_utc':datetime.now(timezone.utc).isoformat()}
    began,cpu=time.monotonic(),time.process_time();deadline=time.time()+control['total_window_seconds'];result=None
    try:
        for kind in ['source','trusted']:
            for name,value in control[kind+'_sha256'].items():
                if sha(Path(control[kind])/name)!=value:raise ValueError('Prepared '+kind+' bytes drifted: '+name)
        for name,value in control['implementation_sha256'].items():
            if sha(ROOT/name)!=value:raise ValueError('Reviewed control implementation drifted: '+name)
        if sha(Path(control['actual_original_GDS']))!=control['original_GDS_sha256']:raise ValueError('Original GDS drifted')
        from scripts.qualify_telescopic_supplement import resource_gate
        resource_gate(deadline,state['resource_samples'])
        from src.candidate_executor import CandidateExecutor
        from src.domain_runner import inspect_point,source_contents
        from src.training import TrustedPhysicalStore
        from scripts.e2_execution import measured_cost
        state.update(status='ONE_CALL_RESERVED',physical_call_reservations=1);save(journal,state)
        point=control['point'];source=Path(control['source']);trusted=Path(control['trusted']);configuration={'parameters':point['parameters']}
        executor=CandidateExecutor(ROOT/'runtime/GLdev',output/'physical',ROOT/'runtime/magic-8.3.685',timeout=900)
        result=executor.execute(source_dir=source,source_paths=control['source_files'],entrypoint='generator.py',representation='G2',
            configuration=configuration,trusted_dir=trusted,trusted_paths=control['trusted_files'],fidelity='pex_spice',
            phase='development_FVF_fullmodule_control',context={'source_role':'trusted_evaluator_control','candidate_id':control['task'],
                'initial_state_id':control['task'],'parent_lineage':control['parent_lineage'],'configuration_id':point['configuration_id'],
                'reference_id':point['reference_id'],'pdk_revision':'0fe599b2afb6708d281543108caf8310912f54af'},
            generation_timeout_seconds=240,evaluator_timeout_seconds=900,execution_deadline_utc=datetime.fromtimestamp(deadline,timezone.utc).isoformat())
        raw=Path(result['run_directory']);state['raw_directory']=str(raw);state['actual_stage_costs']=measured_cost(raw)
        expected=source_contents(source,control['source_files'],binary=True)
        checked=inspect_point(result,point,expected,configuration,gold_control_check=False);state['checked']=checked
        if (raw/'accepted/candidate.gds').is_file():state['geometry']=geometry(raw/'accepted/candidate.gds',Path(control['actual_original_GDS']),control['top_cell'])
        if checked['S1']:
            audit=full_rc_audit(raw,point,output);state['full_RC_audit']=audit
            if audit['status']!='RC_DEVICE_GRAPH_MATCH':raise ValueError('Required actual fullRC/deck audit did not pass')
        if checked['S2']:
            dry={**point,'parameters':configuration,'editable_paths':[EDITABLE],'lineage_editable_paths':[EDITABLE],
                'frozen_source_files':[n for n in control['source_files'] if n!=EDITABLE],'frozen_source_pack':str(source),
                'intent_reference_path':'reference.spice','trusted_evaluator_files':{n:(trusted/n).read_text() for n in control['trusted_files']}}
            state['current_Store']=TrustedPhysicalStore.inspect_development_run(raw,dry,{EDITABLE:(source/EDITABLE).read_text()})
        state['status']='COMPLETE_POSITIVE_CONTROL' if (checked['S2'] and state.get('current_Store',{}).get('S2') and state.get('geometry',{}).get('equal')) else 'CONTROL_NOT_ESTABLISHED'
    except (ValueError,OSError,KeyError,TypeError,TimeoutError) as error:
        state.update(status='UNKNOWN_OR_PRECONDITION_FAILURE_NO_RETRY',error=type(error).__name__+': '+str(error))
    finally:
        state.update(wall_seconds=time.monotonic()-began,parent_CPU_seconds=time.process_time()-cpu,
            completed_at_utc=datetime.now(timezone.utc).isoformat(),formal_trials=0,training_examples=0,old_results_relabelled=False)
        save(journal,state)
    return state


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--mode',choices=['prepare','run'],required=True)
    p.add_argument('--task',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    started,cpu=time.monotonic(),time.process_time()
    try:value=prepare(a.task,a.output) if a.mode=='prepare' else run(a.output)
    except BaseException as error:
        failure={'status':'DRIVER_FAILURE_NO_AUTOMATIC_RETRY','mode':a.mode,'error':repr(error),
            'wall_seconds':time.monotonic()-started,'parent_CPU_seconds':time.process_time()-cpu}
        if a.mode=='prepare' and a.output.is_dir() and not (a.output/'control.json').exists():
            save(a.output/'preparation_failure.json',failure)
        print(json.dumps(failure),file=sys.stderr,flush=True)
        raise
    print(json.dumps(value,indent=2,allow_nan=False),flush=True)
