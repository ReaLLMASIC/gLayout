#!/usr/bin/env python3
"""Fresh development-only G0/G1/G2 budget calibration on validation_mirror."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import re,shlex,shutil,subprocess,sys,time,uuid

ROOT=Path(__file__).resolve().parents[1]
if not (ROOT/'src').exists() and Path('/work/src').is_dir():ROOT=Path('/work')
sys.path.insert(0,str(ROOT))
from scripts.e1_development_pilot import G2_FILES,INITIALIZERS,effective_pdk_rules,visible_physical_feedback
from src.model_adapter import check_utc_budget

SSH=['ssh','-i','~/.ssh/cbl_server_key','-o','BatchMode=yes',
    '-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=12','cbl-server']
REMOTE='/srv/code-behind-layout'
INITIAL='''import argparse,json
import gdstk
p=argparse.ArgumentParser();p.add_argument("--configuration");p.add_argument("--output")
a=p.parse_args();configuration=json.load(open(a.configuration))
library=gdstk.Library();top=library.new_cell("validation_mirror")
# Construct the declared physical circuit with the allowed interface.
library.write_gds(a.output)
'''

def contract():
    return {'task_id':'development_validation_mirror_composition','configuration_id':'anchor',
        'reference_id':'independent_validation_nfet_w3_l1_f2','required_corners':['tt','ss','ff'],
        'specifications':[{'name':'absolute_current_error','unit':'1','max':.03},
            {'name':'output_resistance','unit':'ohm','min':1e6}],
        'analysis_contracts':{'op':{'kind':'op','columns':4,'expected_rows':1},
            'dc':{'kind':'dc','columns':4,'start':.1,'end':1.7,'points':17,'scale':'linear'}}}

def prepare_primitives():
    from glayout import sky130
    from glayout.primitives.fet import nmos
    from src.generators.validation_mirror import schematic
    out=Path.cwd()
    component=nmos(sky130,width=3,length=1,fingers=2,with_dummy=False,with_tie=True,with_dnwell=False).copy()
    metadata={'cell':'nfet_w3_l1_f2','model':'sky130_fd_pr__nfet_01v8','width_per_finger_um':3,
        'length_um':1,'fingers':2,'parallel_multiplier':1,'dummy_devices':0,'units':'um',
        'bbox_um':[list(map(float,row)) for row in component.bbox],
        'ports':{name:{'center_um':list(map(float,port.center)),'width_um':float(port.width),
            'orientation_degrees':float(port.orientation),'layer':list(port.layer)} for name,port in component.ports.items()}}
    remove=[v for k,v in sky130.glayers.items() if k.endswith(('_label','_pin'))]+[(64,44)]
    component=component.remove_layers(remove,include_labels=True);component.name=metadata['cell']
    component.write_gds(out/'nfet.gds')
    (out/'all_ports.json').write_text(json.dumps(metadata,indent=2)+'\n')
    (out/'pdk_all.json').write_text(json.dumps({'layers':sky130.glayers,'rules':sky130.grules},indent=2)+'\n')
    (out/'reference.spice').write_text(schematic())
    print(json.dumps({'prepared':'generic NMOS only','target_geometry_provided':False}),flush=True)

def prepare_bundle(preparation):
    out=ROOT/'runs/development/validation_bundles'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out.mkdir(parents=True);metadata=json.loads((preparation/'all_ports.json').read_text())
    terminals={t:['multiplier_0_'+name+'_'+s for s in 'NESW'] for t,name in [('D','drain'),('G','gate'),('S','source')]}
    terminals['B']=['tie_'+s+'_top_met_'+s for s in 'NESW']
    keep=[name for group in terminals.values() for name in group]
    metadata={**metadata,'logical_terminals':terminals,'ports':{name:metadata['ports'][name] for name in keep}}
    for method in ('G0','G1','G2'):
        library=out/method;library.mkdir()
        if method!='G0':
            shutil.copyfile(preparation/'nfet.gds',library/'nfet.gds')
            (library/'nfet.json').write_text(json.dumps(metadata,separators=(',',':'))+'\n')
        if method=='G2':
            for name in G2_FILES:
                path=library/'glayout'/name;path.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ROOT/'vendor/glayout/src/glayout'/name,path)
            for name in INITIALIZERS:
                path=library/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('')
    raw=out/'raw';raw.mkdir();shutil.copyfile(preparation/'all_ports.json',raw/'all_ports.json')
    shutil.copyfile(preparation/'pdk_all.json',raw/'pdk_all.json')
    shutil.copyfile(preparation/'reference.spice',raw/'reference.spice')
    rules=effective_pdk_rules(json.loads((preparation/'pdk_all.json').read_text()))
    (out/'pdk_rules.json').write_text(json.dumps(rules,separators=(',',':'))+'\n')
    public={'bundle':str(out),'primitive':metadata,'pdk_rules':rules,'contract':contract(),
        'preparation_run':str(preparation),'formal_trials':0,'training_examples':0}
    (out/'public.json').write_text(json.dumps(public,indent=2)+'\n')
    print(json.dumps({'bundle':str(out),'public_file':str(out/'public.json')}),flush=True)

def task_packet(public,method,deadline,bounded=False):
    docs={'interface_version':'validation_named_top_v2',
        'scope':'Development validation circuit composition; no complete target assembly is supplied.',
        'CLI':'python generator.py --configuration PATH --output PATH. Emit only candidate.gds. Contract target cell validation_mirror must exist exactly once, with a complete resolvable hierarchy. Unreferenced cells are permitted and excluded from target evaluation; all referenced children and the full recursive bbox are checked. Cell/label identifiers: ASCII letters/digits/_/$. Units um; grid .005um.',
        'patch_format':'Ordinary unified diff --- a/generator.py +++ b/generator.py with accurate hunk counts and final newline. Malformed patches consume a decision.',
        'netlist':'Ports REF OUT GND. Two identical NMOS devices, each two parallel fingers of per-finger W=3um L=1um; no dummy. Reference drain+gate and output gate→REF; output drain→OUT; all source/body→GND. Model sky130_fd_pr__nfet_01v8. Four physical extracted nfets total. No size edits.',
        'bench':'VDD=1.8V; IREF from VDD to REF=10uA; OUT clamped .9V. Post-RC TT/SS/FF OP and 17point OUT sweep .1..1.7V/.1. At .9V steady DC absolute current error≤3%, output resistance≥1Mohm.',
        'PDK':public['pdk_rules'],
        'labels':'Use exported net labels REF OUT GND. Remove primitive labels. Labels must touch corresponding electrical metal with matching pin layer: met1 67/20,pin67/16,label67/5; met2 68/20,pin68/16,label68/5; met3 69/20,pin69/16,label69/5; met4 70/20,pin70/16,label70/5.'}
    if method!='G0':docs['primitive']={'read_only_gds':'/library/nfet.gds','read_only_metadata':'/library/nfet.json',**public['primitive']}
    if method=='G0':docs['API']='Only gdstk/numpy/math and generic Python. Draw actual MOS layers, contacts, vias and routing. No PCell or glayout/gdsfactory. All effective PDK rules and layer map are supplied as data.'
    elif method=='G1':docs['API']='Only gdstk/numpy/math and generic Python. Read frozen generic nfet.gds, instantiate twice, explicitly route polygons and vias. Metadata contains four logical terminals/16 real access ports in primitive local coordinates; translate with references. No glayout/gdsfactory.'
    else:docs['API']='G1 generic nfet GDS+metadata plus gdsfactory Component/import_gds/port.Port and cropped glayout PDK/ports/routing utilities. from glayout.pdk.sky130_mapped.sky130_mapped import sky130_mapped_pdk; from glayout.routing.straight_route import straight_route; from glayout.routing.L_route import L_route; from glayout.routing.c_route import c_route. Reconstruct Ports from center,width,orientation,layer metadata, place references, add returned route Components. straight_route(pdk,port1,port2,width=.3),L_route(pdk,port1,port2),c_route(pdk,port1,port2,extension=2). from glayout.primitives.via_gen import via_stack; via_stack(pdk,bottom,top,fullbottom=True,fulltop=True) returns Component. No fet or circuit generator is exposed. Export then rename top using gdstk if needed.'
    packet={'task_id':contract()['task_id'],'goal':'Implement the declared physical validation NMOS mirror with '+method+'. Read source, propose patch, inspect real feedback, finish within fixed budget. All failures count; excluded from formal results/training.',
        'contract':contract(),'allowed_paths':['generator.py'],'visible_sources':{'generator.py':'Complete editable scaffold; use read_source'},
        'documents':docs,'visible_configurations':['anchor'],'budget':{'decisions':10,'physical_evaluations':3,'wall_seconds':1200,'deadline_utc':deadline}}
    if bounded:
        packet['budget'].update(maximum_output_tokens=1024,maximum_context_tokens=8192)
        packet['documents']['output_budget']='Each complete ACTION_JSON, including its patch and final EOS, is limited to1024 tokens in the fixed Qwen2.5-Coder tokenizer. Input plus the full1024 output reserve must fit8192. Overlong actions are retained and rejected before execution. Use concise necessary edits; successive small valid patches may build on the current source. No source or feedback is truncated.'
    return packet

def evaluate(args):
    import fcntl
    from src.candidate_executor import CandidateExecutor
    budget={'budget':{'deadline_utc':args.deadline_utc}} if args.deadline_utc else {'budget':{}}
    check_utc_budget(budget)
    work=ROOT/'runs/development/validation_inputs'/str(uuid.uuid4());trusted=work/'trusted';trusted.mkdir(parents=True)
    source=args.source;source_paths=['generator.py']
    if args.gold_control:
        source=work/'source';source.mkdir();shutil.copyfile(args.gold_control,source/'control.gds')
        (source/'generator.py').write_text('import argparse,shutil\np=argparse.ArgumentParser();p.add_argument("--configuration");p.add_argument("--output");a=p.parse_args();shutil.copyfile("/source/control.gds",a.output)\n')
        source_paths.append('control.gds')
    shutil.copyfile(ROOT/'scripts/validation_task_evaluator.py',trusted/'evaluate.py')
    shutil.copyfile(args.bundle/'raw/reference.spice',trusted/'reference.spice')
    (trusted/'contract.json').write_text(json.dumps(contract(),indent=2)+'\n')
    (trusted/'src').mkdir();(trusted/'src/__init__.py').write_text('')
    paths=['evaluate.py','reference.spice','contract.json','src/__init__.py']
    for name in ('physical_drc.py','report_parsers.py','measurement.py','spice_validation.py'):
        shutil.copyfile(ROOT/'src'/name,trusted/'src'/name);paths.append('src/'+name)
    library=args.bundle/args.method;library_paths=[str(p.relative_to(library)) for p in library.rglob('*') if p.is_file()]
    executor=CandidateExecutor(ROOT/'runtime/GLdev',ROOT/'runs/development/validation_physical',ROOT/'runtime/magic-8.3.685',timeout=480)
    queued=time.monotonic();slot=None
    # A single additional 2CPU physical pipeline keeps the existing domain queue running.
    while slot is None:
        check_utc_budget(budget);handle=(ROOT/'runtime/validation_budget_physical_slot').open('a')
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB);slot=handle
        except BlockingIOError:handle.close();time.sleep(.1)
    try:
        check_utc_budget(budget)
        result=executor.execute(source_dir=source,source_paths=source_paths,entrypoint='generator.py',representation=args.method,
            configuration={'width':3,'length':1,'fingers':2,'top_cell':'validation_mirror','ports':['REF','OUT','GND'],
                'pdk_rules':json.loads((args.bundle/'pdk_rules.json').read_text())},trusted_dir=trusted,trusted_paths=paths,
            library_dir=library,library_paths=library_paths,fidelity=args.fidelity,phase='development_validation_budget_calibration',
            context={'source_role':'trusted_evaluator_control' if args.gold_control else 'fresh_GPT_development_candidate',
                'interface_version':'validation_named_top_v2',
                'configuration_id':'anchor','reference_id':contract()['reference_id'],'pdk_revision':'0fe599b2afb6708d281543108caf8310912f54af'},
            generation_timeout_seconds=120,evaluator_timeout_seconds=480)
    finally:slot.close()
    run=Path(result['run_directory']);manifest=json.loads((run/'manifest.json').read_text())
    boundary=json.loads((run/'evidence/gds_boundary.json').read_text()) if (run/'evidence/gds_boundary.json').exists() else {}
    result.update(tiers=(result.get('physical_result') or {}).get('assessment',
        {'S0':manifest['candidate']['returncode']==0 and boundary.get('gds_parse_complete') is True,'S1':False,'S2':False}),
        queue_wait_seconds=time.monotonic()-queued-sum(manifest[s]['wall_seconds'] for s in ('candidate','trusted') if s in manifest),
        physical_wall_seconds=sum(manifest[s]['wall_seconds'] for s in ('candidate','trusted') if s in manifest),fidelity=args.fidelity)
    cpu=0;missing=0
    for stage in ('candidate','trusted'):
        if stage not in manifest:continue
        path=run/(stage+'_stage/resource_usage.json')
        if path.exists():u=json.loads(path.read_text());cpu+=u['child_user_cpu_seconds']+u['child_system_cpu_seconds']
        else:missing+=1
    result.update(physical_waited_child_cpu_seconds=cpu,physical_cpu_records_missing=missing)
    console=(run/'candidate_stage/console.log').read_text(errors='replace')
    errors=[s.strip() for s in console.splitlines() if re.match(r'^[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception):',s.strip())]
    if errors:result['candidate_error']={'type':errors[-1].split(':',1)[0],'message':errors[-1][:600]}
    if args.result_file:args.result_file.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)

def run_policy(method,public,deadline,batch,bounded=False,tokenizer=None):
    from src.model_adapter import GptDecisionAdapter
    from src.candidate_executor import VisibleActionGateway
    out=batch/method;source=out/'source';source.mkdir(parents=True);(source/'generator.py').write_text(INITIAL)
    packet=task_packet(public,method,deadline,bounded)
    if bounded and tokenizer is None:
        from transformers import AutoTokenizer
        tokenizer=AutoTokenizer.from_pretrained(ROOT/'runtime/policy_tokenizer',local_files_only=True,trust_remote_code=False)
    adapter=GptDecisionAdapter(out/'decisions',tokenizer=tokenizer)
    session=adapter.start(packet,json.loads((ROOT/'configs/models'/('gpt_bounded.draft.json' if bounded else 'gpt.json')).read_text()))
    remote_source=REMOTE+'/runs/development/validation_policy/'+session['session_id']+'/source'
    calls=[];actions=[];rejections=[];began=datetime.now(timezone.utc);started=time.monotonic();error=None;finished=False
    def callback(name,fidelity):
        check_utc_budget(packet)
        if name!='anchor' or len(calls)>=packet['budget']['physical_evaluations']:raise ValueError('Physical evaluation budget exhausted')
        index=len(calls);record={'N_z':index+1,'fidelity':fidelity,'source':(source/'generator.py').read_text(),
            'requested_at_utc':datetime.now(timezone.utc).isoformat(),'status':'REQUESTED'}
        calls.append(record);save()
        subprocess.run(SSH+['mkdir -p '+shlex.quote(remote_source)],check=True,capture_output=True,text=True,timeout=30)
        subprocess.run(['scp']+SSH[1:-1]+[str(source/'generator.py'),'cbl-server:'+remote_source+'/generator.py'],check=True,capture_output=True,text=True,timeout=30)
        check_utc_budget(packet)
        result_file=REMOTE+'/runs/development/validation_policy/'+session['session_id']+'/physical_%02d.json'%index
        command=' '.join(map(shlex.quote,['python3',REMOTE+'/scripts/validation_budget_pilot.py','--evaluate','--method',method,
            '--bundle',public['bundle'],'--source',remote_source,'--fidelity',fidelity,'--deadline-utc',deadline,'--result-file',result_file]))
        try:
            r=subprocess.run(SSH+[command],text=True,capture_output=True,timeout=660)
            (out/('physical_%02d.stdout'%index)).write_text(r.stdout);(out/('physical_%02d.stderr'%index)).write_text(r.stderr)
            record.update(json.loads(r.stdout));record['transport_returncode']=r.returncode
        except Exception as exc:
            record.update(transport_error=type(exc).__name__+': '+str(exc),remote_result_file=result_file);save();raise
        record['elapsed_wall_seconds']=time.monotonic()-started;save()
        feedback=visible_physical_feedback(record)
        feedback['interface_error']=(record.get('physical_result') or {}).get('interface_error')
        return feedback
    def save():
        ended=datetime.now(timezone.utc)
        summary={'phase':'development_validation_budget_calibration','method':method,'formal_trials':0,'training_examples':0,
            'shared_token_budget_enforced':bounded,
            'started_at_utc':began.isoformat(),'deadline_utc':deadline,'updated_at_utc':ended.isoformat(),
            'elapsed_utc_seconds':(ended-began).total_seconds(),'elapsed_monotonic_seconds':time.monotonic()-started,
            'actions':actions,'rejections':rejections,'physical_calls':calls,
            'actual_N_z':sum('run_directory' in row for row in calls),'attempted_physical_requests':len(calls),'usage':session['usage'],
            'error':error,'finished':finished,'session_id':session['session_id'],'output':str(out)}
        (out/'calibration.json').write_text(json.dumps(summary,indent=2)+'\n');return summary
    gateway=VisibleActionGateway(packet,source,callback);observation={'status':'begin'};save()
    try:
        for _ in range(packet['budget']['decisions']):
            check_utc_budget(packet);action=adapter.step(session,observation);check_utc_budget(packet)
            actions.append(action['action']);save()
            try:
                check_utc_budget(packet)
                observation=gateway.dispatch(action)
            except (ValueError,subprocess.CalledProcessError) as exc:
                observation={'status':'rejected_action','error':str(exc)};rejections.append(observation)
            if action['action']=='finish':finished=True;break
        check_utc_budget(packet)
        if len(calls)<3 and (not calls or calls[-1]['source']!=(source/'generator.py').read_text() or calls[-1].get('fidelity')!='pex_spice'):
            callback('anchor','pex_spice')
    except Exception as exc:error=type(exc).__name__+': '+str(exc)
    finally:adapter.finish(session)
    result=save();print(json.dumps({'method':method,'finished':finished,'actions':actions,'N_z':len(calls),'error':error}),flush=True)
    return result

def batch(public_file,bounded=False):
    public=json.loads(public_file.read_text());control=json.loads(Path(public['local_control_result']).read_text())
    if control.get('tiers',{}).get('S2') is not True:raise ValueError('Actual full-flow gold control must pass before dispatch')
    out=ROOT/'runs/development/validation_policy'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');out.mkdir(parents=True)
    began=datetime.now(timezone.utc);deadline=(began+timedelta(seconds=1200)).isoformat()
    record={'phase':'development_validation_budget_calibration','started_at_utc':began.isoformat(),'deadline_utc':deadline,
        'decisions_per_method':10,'physical_calls_per_method':3,'simultaneous_physical_pipelines':1,
        'public_bundle':str(public_file),'gold_control':public['local_control_result'],'formal_trials':0,'training_examples':0}
    record.update(shared_token_budget_enforced=bounded,maximum_output_tokens=1024 if bounded else None,
        maximum_context_tokens=8192 if bounded else None,prior_batch_regraded=False)
    (out/'batch.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({'batch':str(out),**record}),flush=True)
    tokenizer=None
    if bounded:
        from transformers import AutoTokenizer
        tokenizer=AutoTokenizer.from_pretrained(ROOT/'runtime/policy_tokenizer',local_files_only=True,trust_remote_code=False)
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(lambda method:run_policy(method,public,deadline,out,bounded,tokenizer),('G0','G1','G2')))
    record['methods']=results;record['ended_at_utc']=datetime.now(timezone.utc).isoformat()
    (out/'batch.json').write_text(json.dumps(record,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group(required=True)
    m.add_argument('--prepare-primitives',action='store_true');m.add_argument('--prepare-bundle',type=Path)
    m.add_argument('--evaluate',action='store_true');m.add_argument('--batch',type=Path)
    m.add_argument('--bounded-batch',type=Path)
    p.add_argument('--method',choices=['G0','G1','G2'],default='G0');p.add_argument('--bundle',type=Path)
    p.add_argument('--source',type=Path);p.add_argument('--gold-control',type=Path);p.add_argument('--result-file',type=Path)
    p.add_argument('--deadline-utc');p.add_argument('--fidelity',choices=['basic','pex_spice'],default='pex_spice');a=p.parse_args()
    if a.prepare_primitives:prepare_primitives()
    elif a.prepare_bundle:prepare_bundle(a.prepare_bundle)
    elif a.evaluate:evaluate(a)
    else:batch(a.bounded_batch or a.batch,bounded=bool(a.bounded_batch))
