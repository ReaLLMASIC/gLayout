"""Prospective train-only source collection through the isolated physical gateway.

This runner never starts model training or a formal benchmark test. It requires
an explicit frozen collection and an execute flag. Completed engineering runs
cannot be supplied as baselines or relabelled by this program.
"""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.candidate_executor import CandidateExecutor,apply_source_patch
from src.model_adapter import validate_action
from src.training import TrustedPhysicalStore,admit_candidates,build_matched_samples,frozen_train_registry


def save(path,value):
    Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def load(path):
    manifest=json.loads(path.read_text())
    if manifest.get('sampling',{}).get('mode')!='train_collection_action_gpt':raise ValueError('This independent16k version collects ordinary ACTION proposals only')
    if manifest.get('status')!='frozen' or manifest.get('role')!='train_collection':
        raise ValueError('Collection requires an explicit frozen train_collection manifest')
    identity=json.loads((path.parent/'freeze_identity.json').read_text())
    for name,expected in identity.items():
        if hashlib.sha256((path.parent/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('An explicitly frozen collection artifact changed: '+name)
    registry=json.loads(Path(manifest['registry_path']).read_text());assignments=frozen_train_registry(registry)
    states=[json.loads(line) for line in Path(manifest['initial_states_path']).read_text().splitlines() if line.strip()]
    if not states or len({state['initial_state_id'] for state in states})!=len(states):raise ValueError('Initial states must be nonempty and distinct')
    gpt_mode=manifest['sampling']['mode'] in ['train_collection_source_gpt','train_collection_action_gpt']
    action_teacher=manifest['sampling']['mode']=='train_collection_action_gpt'
    rule_mode=manifest['sampling']['mode']=='train_collection_rules'
    source_mode=manifest['sampling']['mode'] in ['train_collection_source','train_collection_source_gpt','train_collection_rules']
    if manifest['sampling']['mode'] not in ['train_collection','train_collection_source','train_collection_source_gpt','train_collection_action_gpt','train_collection_rules']:raise ValueError('Unknown frozen proposal interface')
    if rule_mode:
        sampling=manifest['sampling'];rule_path=Path(sampling['rule_proposer_path']).resolve()
        if (sampling.get('backend')!='frozen_rule_proposer' or sampling.get('model') is not None or sampling.get('seed') is not None or
            len(sampling.get('rule_ids',[]))!=8 or len(set(sampling['rule_ids']))!=8):raise ValueError('Rule collection requires eight explicit deterministic rules without a model/seed')
        if str(rule_path.relative_to(path.parent.resolve())) not in identity:raise ValueError('Rule implementation must be included in the collection freeze identity')
        spec=importlib.util.spec_from_file_location('frozen_collection_rules',rule_path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        if module.RULE_IDS!=sampling['rule_ids']:raise ValueError('Frozen rule order differs from its declared implementation')
    elif gpt_mode:
        if (manifest['sampling'].get('backend')!='isolated_gpt_cli' or manifest['sampling'].get('model')!='gpt-6.1-sol' or
            manifest['sampling'].get('reasoning_effort')!='high' or manifest['sampling'].get('trials')!=list(range(1,9)) or
            manifest['sampling'].get('proposal_workers')!=2 or manifest['sampling'].get('seed') is not None):raise ValueError('GPT teacher needs the exact frozen independent-trial interface, without invented seeds')
    elif manifest['sampling']['variant']!='T0' or len(manifest['sampling']['seeds'])!=8 or len(set(manifest['sampling']['seeds']))!=8:raise ValueError('This collection has eight actual distinct T0 sampling seeds')
    if (manifest['sampling']['max_new_tokens']!=(0 if rule_mode else 3072 if source_mode else 1024) or
        manifest['sampling']['max_context_tokens']!=16384 or
        manifest['sampling']['timeout_seconds']!=(5 if rule_mode else 240 if source_mode or action_teacher else 60)):raise ValueError('Collection generation budgets changed')
    version=manifest.get('teacher_instruction_version');preselection=manifest.get('student_preselection')
    if action_teacher:
        if (manifest.get('teacher_interface_version')!='ordinary_action_teacher_context_v2' or version is not None or
            preselection!={'student_interface_version':'ordinary_policy_action_context_v2','max_new_tokens':1024,'max_context_tokens':16384,'stage':'before_physics'}):
            raise ValueError('ACTION teacher requires its explicit interface freeze and canonical student preselection')
        interface=Path(manifest['teacher_interface_path']).resolve()
        for file in ['broker.py','collector.py','src/model_adapter.py','src/local_model_adapter.py','src/policy_state.py','action_schema.json']:
            relative=str((interface/file).relative_to(path.parent.resolve()))
            if relative not in identity:raise ValueError('ACTION teacher interface source must be included in freeze identity: '+file)
        if Path(__file__).read_bytes()!=(interface/'collector.py').read_bytes():raise ValueError('ACTION teacher requires its exact frozen collector implementation')
        if (interface/'src/student_interface.py').read_bytes()!=(ROOT/'src/student_interface.py').read_bytes():
            raise ValueError('The explicit16k student mapping differs from this frozen collection')
    elif version is not None or preselection is not None:
        if (version!='minimal_source_edit_v1' or not source_mode or rule_mode or
            preselection!={'student_interface_version':'ordinary_policy_action_context_v2','max_new_tokens':1024,'max_context_tokens':16384,'stage':'before_physics'}):
            raise ValueError('Minimal-source teacher requires the explicitly frozen ordinary-action preselection')
    if manifest['physical']['workers']!=1 or manifest['physical']['cpus_per_job']!=2:raise ValueError('This fixed batch has one two-CPU worker per collection')
    for key in ['pdk_revision','container_image','magic_runtime']:
        if not manifest.get(key):raise ValueError('Collection lacks frozen physical identity: '+key)
    if '@sha256:' not in manifest['container_image']:raise ValueError('Physical image must be immutable by digest')
    output=Path(manifest['output_root']).resolve();evidence=Path(manifest['evidence_root']).resolve()
    output.relative_to(ROOT/'runs/train_collection')
    if evidence!=output:raise ValueError('This collection keeps its evidence under its declared output root')
    source=Path(manifest['source_pack']);trusted=Path(manifest['trusted_bundle'])
    source_files=sorted(str(p.relative_to(source)) for p in source.rglob('*') if p.is_file())
    trusted_files={str(p.relative_to(trusted)):p.read_text() for p in trusted.rglob('*') if p.is_file()}
    for state in states:
        assignment=assignments.get(state['parent_lineage'],{})
        if assignment.get('split')!='train' or state.get('origin') not in ['natural','injected']:raise ValueError('Initial state is outside the frozen train source group')
        if (not state['base_source'] or not set(state['base_source']).issubset(assignment['editable_paths']) or
            not all(isinstance(v,str) for v in state['base_source'].values())):raise ValueError('Retain complete declared editable text modules')
        if source_mode and list(state['base_source'])!=['textbook_sharing/layout.py']:raise ValueError('Full-source teacher uses only the complete layout module')
        if set(source_files)!=set(assignment['editable_paths'])|set(assignment['frozen_source_files']):raise ValueError('Frozen/text source partition differs from the actual capsule')
        if Path(assignment['frozen_source_pack']).resolve()!=source.resolve():raise ValueError('Registry and collection source capsule differ')
        points=[p for p in registry['configurations'] if p['parent_lineage']==state['parent_lineage'] and p.get('split')=='train' and (state.get('task_id') is None or p['contract']['task_id']==state['task_id'])]
        if len(points)!=9 or sum(p.get('domain_role')=='anchor' for p in points)!=1 or sum(p.get('domain_role')=='development' for p in points)!=8:raise ValueError('Expected one anchor and eight development points')
        for point in points:
            if point['trusted_evaluator_files']!=trusted_files:raise ValueError('Trusted bundle differs from frozen registry files')
    return manifest,registry,states,source_files


def workspace(source,files,editable,destination):
    shutil.copytree(source,destination)
    for path in destination.rglob('*'):
        if path.is_dir():path.chmod(0o755)
    destination.chmod(0o755)
    for name,text in editable.items():
        target=destination/name;target.chmod(0o644);target.write_text(text)
    for name in files:
        (destination/name).chmod(0o444)
    return destination


def source_patch(before,after,name):
    """Mechanical unified diff preserving exact new-source bytes, including EOF."""
    lines=difflib.unified_diff(before.splitlines(keepends=True),after.splitlines(keepends=True),fromfile='a/'+name,tofile='b/'+name)
    return ''.join(line if line.endswith('\n') else line+'\n\\ No newline at end of file\n' for line in lines)


def source_identity(sources,semantic=False):
    if not semantic:return tuple(sorted(sources.items()))
    result=[]
    for name,source in sorted(sources.items()):
        try:key=('parsed',ast.dump(ast.parse(source),include_attributes=False))
        except (SyntaxError,ValueError):key=('unparsed_exact_text',source)
        result.append((name,key))
    return tuple(result)


def summary(point,result):
    checked=result['checked'];record=result['result'].get('physical_result') or {}
    metrics=[row['metrics'] for row in record.get('observation',{}).get('corners',{}).values()]
    objective=point['contract']['objective']
    values=[m[objective['metric']]['value'] for m in metrics if objective['metric'] in m]
    quality=(max(values) if objective['direction']=='min' else min(values)) if values and checked['S2'] else None
    return {'configuration_id':point['configuration_id'],'S0':checked['S0'],'S1':checked['S1'],'S2':checked['S2'],
            'objective':quality,'failure_class':checked['failure_class'],'reason':checked.get('reason')}


def packet(manifest,state,points,baseline):
    objective=points[0]['contract']['objective']
    contract={'family':points[0]['contract']['task_id'],'topology':'C01 fixed 1:1 NMOS current mirror; VSS IB1 IOUT1',
              'devices_D_G_S_B':{'M1':['IB1','IB1','VSS','VSS'],'M2':['IOUT1','IB1','VSS','VSS']},
              'objective':objective,'constraints':points[0]['contract']['specifications'],
              'corners':points[0]['contract']['required_corners'],'analysis_contracts':points[0]['contract']['analysis_contracts'],
              'nominal_bench':points[0]['contract']['nominal_operating_point'],
              'compliance_sample_grid_V':points[0]['contract'].get('declared_compliance_sample_grid_V',[]),
              'geometry_domain':[{'id':p['configuration_id'],'role':p['domain_role'],'sizing':p['parameters']['sizing']} for p in points],
              'immutable':'Transistor graph, sizing, references, PDK, testbench and every library file outside the two complete editable modules are fixed.'}
    circuit=points[0]['parameters']['circuit'];cid=circuit['circuit_id']
    if cid!='C01':
        device_order=[device['name'] for device in circuit['devices']]
        if any(set(size)!={'w','l','nf'} for point in points for size in point['parameters']['sizing'].values()):
            raise ValueError('The complete geometry matrix must retain every sizing field')
        contract={'family':points[0]['contract']['task_id'],'topology':cid+' '+circuit['name'],'ports':circuit['ports'],
            'devices':[{'name':d['name'],'kind':d['kind'],'nets_D_G_S_B':d['nets']} for d in circuit['devices']],
            'objective':objective,'constraints':points[0]['contract']['specifications'],'corners':points[0]['contract']['required_corners'],
            'analysis_contracts':points[0]['contract']['analysis_contracts'],'nominal_bench':points[0]['contract']['nominal_operating_point'],
            'power_definition':points[0]['contract']['power_definition'],
            'geometry_domain':{'device_order':device_order,'columns':['w_total_um','l_um','nf'],
                'points':[{'id':p['configuration_id'],'role':p['domain_role'],
                    'device_values':[[p['parameters']['sizing'][name][key] for key in ['w','l','nf']] for name in device_order]} for p in points]},
            'immutable':'Only the declared complete module changes; all circuit graph/sizes, other source files, references, PDK and testbenches are fixed.'}
    visible={'task_id':manifest['collection_id']+'__'+state['initial_state_id'],
       'goal':'Propose exactly one executable ordinary unified source diff improving real GDS area while satisfying every physical constraint across the declared domain. Return propose_patch directly. Core source is complete; preserve frozen APIs.',
       'contract':contract,'allowed_paths':list(state['base_source']),'visible_sources':state['base_source'],
       'documents':{'frozen_api':'The layout module calls the frozen MOS-group construction and row assembly APIs. The complete enumeration module may choose/reorder legal sharing plans. Device sizes/netlists cannot be edited. Output is still the declared component.',
                    'patch_format':'Use full ordinary unified diff headers --- a/path, +++ b/path and exact @@ old/new counts. No patch repair is performed.'},
       'visible_configurations':[p['configuration_id'] for p in points],'budget':{'decisions':1,'maximum_output_tokens':1024}}
    if manifest['sampling']['mode'] in ['train_collection_source','train_collection_source_gpt']:
        visible['goal']='Produce the complete replacement source text of textbook_sharing/layout.py, improving real GDS area while satisfying every declared physical constraint across the domain. Preserve the full build API and immutable graph/sizes/libraries. Return exactly the source_text JSON proposal; its entire content becomes the module unchanged.'
        visible['contract']['immutable']='Only the declared complete layout module may change. Every other source file, including enumeration.py, and all device graphs/sizes/references/PDK/testbenches are frozen.'
        visible['documents']['patch_format']='Return the whole executable module in source_text with no fences or omitted sections; the coordinator mechanically derives its diff. No code repair or stripping is performed.'
        visible['budget']['maximum_output_tokens']=3072
        if manifest.get('teacher_instruction_version')=='minimal_source_edit_v1':
            policy=('Keep every unchanged source line byte-for-byte, including comments, docstrings, imports, names, formatting and ordering. '
                    'Make only the smallest necessary executable layout/planning changes for this task. Do not rewrite documentation, reorganize code, '
                    'rename symbols or reformat unaffected code. The entire returned module is mechanically differenced against this exact input. '
                    'Its resulting ordinary propose_patch ACTION_JSON, including EOS, must fit 1024 student output tokens and 16384 total student tokens. '
                    'An oversized diff is retained as a failed proposal and will not receive physical evaluation; no coordinator repair or shortening occurs.')
            visible['goal']+=' Make only minimal necessary layout edits and preserve every unaffected source line exactly; follow source_edit_policy.'
            visible['documents']['source_edit_policy']=policy
    if manifest['sampling']['mode']=='train_collection_action_gpt':
        visible['goal']='Return exactly one ordinary propose_patch ACTION_JSON improving the declared physical objective across the visible domain. You may edit the complete layout and enumeration modules using the smallest necessary executable planning changes. Preserve unaffected source lines and every frozen physical constraint and API. Invalid diffs and oversized actions are retained as failed proposals; no patch repair occurs.'
        visible['budget']['maximum_context_tokens']=16384
    template=json.loads(Path(manifest['teacher_packet_template']).read_text())
    visible.update(goal=template['goal'],documents=template['documents'],contract=template['contract'])
    visible['budget'].update(maximum_context_tokens=16384,maximum_output_tokens=1024)
    observation={'status':'begin','actual_new_baseline':[summary(p,baseline[p['configuration_id']]) for p in points]}
    if manifest['sampling']['mode']=='train_collection_action_gpt':
        diagnostics={}
        for point,entry in zip(points,observation['actual_new_baseline']):
            result=baseline[point['configuration_id']]['result']
            if result.get('status')!='CANDIDATE_FAILED':continue
            console=Path(result['run_directory'])/'candidate_stage/console.log'
            if not console.is_file():continue
            excerpt=console.read_text(errors='replace')
            if excerpt not in diagnostics:diagnostics[excerpt]={'id':'generation_diagnostic_'+str(len(diagnostics)+1),'configuration_ids':[],'actual_run_ids':[],'console_excerpt':excerpt}
            record=diagnostics[excerpt];record['configuration_ids'].append(point['configuration_id']);record['actual_run_ids'].append(Path(result['run_directory']).name)
            entry['generation_diagnostic_id']=record['id']
        if diagnostics:observation['baseline_generation_diagnostics']=list(diagnostics.values())
    return visible,[{'observation':observation}]


def sample(manifest,packet,history,seed,out,tokenizer=None):
    gpt_mode=manifest['sampling']['mode'] in ['train_collection_source_gpt','train_collection_action_gpt']
    action_teacher=manifest['sampling']['mode']=='train_collection_action_gpt'
    source_mode=manifest['sampling']['mode'] in ['train_collection_source','train_collection_source_gpt']
    body=({'mode':manifest['sampling']['mode'],'trial_id':seed,'request':{'task_packet':packet,'visible_history':history}} if gpt_mode else
        {'variant':'T0','mode':manifest['sampling']['mode'],'sampling':{'temperature':manifest['sampling']['temperature'],'top_p':manifest['sampling']['top_p'],'seed':seed},'request':{'task_packet':packet,'visible_history':history}})
    save(out/'request.json',body);began_utc=datetime.now(timezone.utc).isoformat();begin=time.monotonic()
    request=urllib.request.Request('http://127.0.0.1:'+('8116' if action_teacher else '8115' if gpt_mode else '8114')+'/context16384/decision',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=manifest['sampling']['timeout_seconds']) as response:raw=response.read().decode();status=response.status
    except urllib.error.HTTPError as exc:raw=exc.read().decode();status=exc.code
    except Exception as exc:raw=json.dumps({'error':type(exc).__name__+': '+str(exc)});status=None
    wall=time.monotonic()-begin;(out/'response.json').write_text(raw+'\n')
    try:result=json.loads(raw)
    except json.JSONDecodeError:result={'error':'Response was not a JSON object; raw response preserved'}
    if not isinstance(result,dict):result={'error':'Response was not a JSON object; raw response preserved'}
    record={'seed':seed,'http_status':status,'started_at_utc':began_utc,'ended_at_utc':datetime.now(timezone.utc).isoformat(),'client_wall_seconds':wall,'inference_id':result.get('inference_id'),'usage':result.get('usage'),'model':result.get('model'),'error':result.get('error')}
    if gpt_mode:record.update(seed=None,trial_id=seed,proposal_generator='isolated_gpt_cli')
    if wall>manifest['sampling']['timeout_seconds']:record['error']='model proposal exceeded declared wall budget; never applied'
    action=result.get('action')
    if not record['error']:
        try:
            cache=json.loads((ROOT/'configs/training/backbone_cache.json').read_text())
            model=result['model'];usage=result['usage']
            expected=None if gpt_mode else {'do_sample':True,'temperature':manifest['sampling']['temperature'],'top_p':manifest['sampling']['top_p'],'seed':seed}
            if gpt_mode:
                if (model.get('source_role')!=('isolated_GPT_formal_train_action_teacher' if action_teacher else 'isolated_GPT_formal_train_source_teacher') or model.get('requested_model')!='gpt-6.1-sol' or
                    model.get('settings',{}).get('reasoning_effort')!='high' or usage.get('request_mode')!=manifest['sampling']['mode'] or result.get('native_tools')!=[]):raise ValueError('Actual isolated GPT teacher identity or native-tool boundary differs')
                if action_teacher:
                    if tokenizer is None:raise ValueError('ACTION teacher needs the pinned shared tokenizer')
                    raw_action=result['raw_action_text']
                    if json.loads(raw_action)!=action:raise ValueError('Parsed ACTION differs from its exact returned text')
                    raw_tokens=len(tokenizer(raw_action,add_special_tokens=False)['input_ids'])+1
                    record['raw_action_output_tokens_in_student_tokenizer']=raw_tokens
                    if model['settings']['max_new_tokens']!=1024 or raw_tokens>1024:raise ValueError('Actual raw ACTION exceeds the frozen output budget; no patch applied')
                    if model['settings'].get('maximum_context_tokens')!=16384:raise ValueError('Actual teacher context differs from the explicit16k interface')
            elif (model['base_revision']!=cache['revision'] or model['variant']!='T0' or
                model['source_role']!=('base_model_formal_train_collection_source' if source_mode else 'base_model_formal_train_collection') or
                usage.get('request_mode')!=manifest['sampling']['mode'] or usage.get('decoding_settings')!=expected):
                raise ValueError('Actual served model role or sampling differs from frozen collection')
            if source_mode:
                proposal=result['proposal']
                if set(proposal)!={'source_text'} or not isinstance(proposal['source_text'],str) or not proposal['source_text'].strip():raise ValueError('Teacher did not return one complete nonempty source_text module')
                if model['settings']['max_new_tokens']!=3072:raise ValueError('Actual teacher output budget differs from its freeze')
                if usage.get('output_format')!='complete_module_source':raise ValueError('Teacher response has the wrong declared source format')
                if gpt_mode:
                    if tokenizer is None:raise ValueError('GPT source budget requires the pinned student tokenizer')
                    generated_tokens=len(tokenizer(json.dumps(proposal),add_special_tokens=False)['input_ids'])+1
                    record['source_output_tokens_in_student_tokenizer']=generated_tokens
                    if generated_tokens>3072:raise ValueError('Complete GPT source exceeds declared 3072-token output budget; raw source retained, never truncated')
                text=proposal['source_text'];(out/'proposed_layout.py').write_text(text)
                path='textbook_sharing/layout.py'
                action={'action':'propose_patch','path':'','patch':source_patch(packet['visible_sources'][path],text,path),'configuration_ids':[],'fidelity':'','summary':'Mechanical diff of the complete unchanged teacher source_text'}
                record['proposal_format']='complete_module_source'
                if text==packet['visible_sources'][path]:record['no_source_change']=True
                else:validate_action(action,packet)
            else:
                validate_action(action,packet)
        except (ValueError,TypeError,KeyError) as exc:record['error']=type(exc).__name__+': '+str(exc)
    if not isinstance(action,dict) or action.get('action')!='propose_patch':record['error']=record['error'] or 'candidate did not propose a source patch'
    save(out/'attempt.json',record)
    return record,action


def sample_rule(manifest,packet,history,rule_id,out):
    """Execute the trusted frozen rule; no model request or patch repair occurs."""
    started=datetime.now(timezone.utc).isoformat();wall=time.monotonic();cpu=time.process_time()
    path='textbook_sharing/layout.py';rule_path=Path(manifest['sampling']['rule_proposer_path'])
    save(out/'request.json',{'mode':'train_collection_rules','rule_id':rule_id,'request':{'task_packet':packet,'visible_history':history}})
    record={'proposal_generator':'frozen_rule_proposer','rule_id':rule_id,'seed':None,'model':None,'error':None,'started_at_utc':started}
    action=None
    try:
        spec=importlib.util.spec_from_file_location('frozen_collection_rules',rule_path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        text=module.propose(packet['visible_sources'][path],rule_id)
        save(out/'response.json',{'proposal':{'source_text':text},'model':None,'rule_id':rule_id})
        (out/'proposed_layout.py').write_text(text)
        action={'action':'propose_patch','path':'','patch':source_patch(packet['visible_sources'][path],text,path),
                'configuration_ids':[],'fidelity':'','summary':'Mechanical diff of the exact deterministic rule output'}
        if text==packet['visible_sources'][path]:record['no_source_change']=True
        else:validate_action(action,packet)
    except (ValueError,TypeError,KeyError,OSError) as exc:record['error']=type(exc).__name__+': '+str(exc)
    record.update(ended_at_utc=datetime.now(timezone.utc).isoformat(),client_wall_seconds=time.monotonic()-wall,
        usage={'rule_proposer_path':str(rule_path),'rule_id':rule_id,'process_cpu_seconds':time.process_time()-cpu,
               'wall_seconds':time.monotonic()-wall,'model_inferences':0,'model_tokens':None})
    if record['client_wall_seconds']>manifest['sampling']['timeout_seconds']:record['error']='Deterministic rule exceeded its declared wall budget; never applied'
    save(out/'attempt.json',record)
    return record,action


def preselect_student_action(manifest,task,history,patch,task_id,out,tokenizer):
    """New-version prospective gate only; it never changes a teacher proposal."""
    from src.student_interface import PolicyBudgetError,canonical_action,encode_policy_action,student_request
    visible={key:value for key,value in task.items() if key!='visible_sources'}
    visible.update(task_id=task_id,editable_paths=list(task['visible_sources']))
    request=student_request({'base_source':task['visible_sources'],'visible_contract':visible,'visible_feedback':history},'ordinary_policy_action_context_v2',16384)
    save(out/'student_request.json',request)
    (out/'student_target_action.json').write_text(canonical_action(patch,request)+'\n')
    try:
        encoded=encode_policy_action(tokenizer,request,patch,manifest['student_preselection']['max_context_tokens'],manifest['student_preselection']['max_new_tokens'])
        result={'accepted':True,'student_interface_version':'ordinary_policy_action_context_v2','prompt_tokens':encoded.prompt_tokens,
            'completion_tokens_including_EOS':encoded.completion_tokens,'total_tokens':len(encoded.input_ids)}
    except PolicyBudgetError as exc:result={'accepted':False,'student_interface_version':'ordinary_policy_action_context_v2',**exc.details}
    save(out/'student_preselection.json',result)
    return result


def execute(manifest,registry,states,files,identity_path):
    gpt_mode=manifest['sampling']['mode'] in ['train_collection_source_gpt','train_collection_action_gpt']
    action_teacher=manifest['sampling']['mode']=='train_collection_action_gpt'
    rule_mode=manifest['sampling']['mode']=='train_collection_rules'
    if rule_mode:health={'backend':'frozen_rule_proposer','model_inferences':0,'model_service_required':False}
    else:
        with urllib.request.urlopen('http://127.0.0.1:'+('8116' if action_teacher else '8115' if gpt_mode else '8114')+'/context16384/health',timeout=10) as response:health=json.load(response)
    cache=json.loads((ROOT/'configs/training/backbone_cache.json').read_text())
    source_mode=manifest['sampling']['mode'] in ['train_collection_source','train_collection_source_gpt','train_collection_rules']
    if rule_mode:pass
    elif gpt_mode:
        if (health.get('status')!='READY' or health.get('backend')!='isolated_gpt_cli' or health.get('model')!='gpt-6.1-sol' or
            health.get('reasoning_effort')!='high' or health.get('native_tools_enabled') is not False or health.get('maximum_concurrent_requests')!=2):raise ValueError('The frozen isolated GPT teacher broker is not ready')
        if action_teacher and (health.get('teacher_interface_version')!=manifest['teacher_interface_version'] or health.get('max_new_tokens')!=1024 or health.get('max_context_tokens')!=16384):raise ValueError('Frozen ACTION teacher broker interface differs')
    elif (health.get('status')!='READY' or not health.get('train_collection_sampling_enabled') or
        (source_mode and not health.get('train_collection_source_enabled')) or
        health.get('base_revision')!=cache['revision'] or health.get('settings',{}).get('max_new_tokens')!=1024):
        raise ValueError('The fixed backbone service is not ready for explicitly authorized train_collection sampling')
    output=Path(manifest['output_root'])
    if output.exists():raise ValueError('Collection output exists; preserve it and reconcile partial work before another launch')
    output.mkdir(parents=True);save(output/'collection_manifest.json',manifest)
    shutil.copyfile(__file__,output/'collector_snapshot.py')
    save(output/'freeze_identity.json',json.loads(Path(identity_path).read_text()))
    save(output/'policy_service_at_start.json',health)
    save(output/'effective_registry_origin.json',{'frozen_registry_path':manifest['registry_path'],'collection_manifest':manifest,'permitted_runtime_additions':['configurations[].gold_control'],'source_and_contract_changes_permitted':False})
    controls=dict(manifest.get('gold_controls',{}));attempts=[];pool_rows=[];processed_states=[]
    effective=json.loads(json.dumps(registry));assignments={p['lineage_id']:p for p in effective['lineages']}
    point_map={p['configuration_id']:p for p in effective['configurations']}
    original={name:(Path(manifest['source_pack'])/name).read_text() for state in states for name in state['base_source']}
    def physical(source,point,state,candidate_id,dual=False):
        context={'candidate_id':candidate_id,'initial_state_id':state['initial_state_id'],'parent_lineage':state['parent_lineage'],'split':'train','source_role':'formal_train','pdk_revision':manifest['pdk_revision'],'configuration_id':point['configuration_id'],'reference_id':point['reference_id']}
        if dual:context['evidence_roles']=['trusted_evaluator_control']
        runner=CandidateExecutor(ROOT/'runtime/GLdev',output/'physical',Path(manifest['magic_runtime']),image=manifest['container_image'],timeout=manifest['physical']['evaluator_timeout_seconds'])
        result=runner.execute(source_dir=source,source_paths=files,entrypoint='generator.py',representation='G2',configuration=point['parameters'],trusted_dir=manifest['trusted_bundle'],trusted_paths=list(point['trusted_evaluator_files']),fidelity='pex_spice',context=context,phase='formal_train',generation_timeout_seconds=manifest['physical']['generation_timeout_seconds'],evaluator_timeout_seconds=manifest['physical']['evaluator_timeout_seconds'])
        return result
    with ThreadPoolExecutor(max_workers=manifest['physical']['workers']) as workers:
        for state in states:
            work=output/state['initial_state_id'];work.mkdir()
            points=[p for p in effective['configurations'] if p['parent_lineage']==state['parent_lineage'] and (state.get('task_id') is None or p['contract']['task_id']==state['task_id'])]
            assignment=assignments[state['parent_lineage']]
            base=workspace(Path(manifest['source_pack']),files,state['base_source'],work/'baseline_source')
            dual=state['base_source']==original and not controls
            if not controls and not dual:raise ValueError('First collection state needs the immutable original source or predeclared fresh gold controls')
            baseline_id=state['initial_state_id']+'__baseline';baseline={}
            futures={workers.submit(physical,base,p,state,baseline_id,dual):p for p in points}
            raw_baseline={}
            for future in as_completed(futures):
                point=futures[future];result=future.result();raw_baseline[point['configuration_id']]=result
                save(work/'baseline_results.json',raw_baseline)
                print(json.dumps({'stage':'baseline','state':state['initial_state_id'],'configuration':point['configuration_id'],'status':result['status']}),flush=True)
            if dual:
                for point in points:
                    result=raw_baseline[point['configuration_id']];record=result.get('physical_result') or {}
                    if not(record.get('point_evaluation_complete') and record.get('assessment',{}).get('S2')):raise RuntimeError('Immutable original source failed its frozen gold control; stop affected collection')
                    controls[point['configuration_id']]={'run_directory':result['run_directory']}
            for point in points:
                point['gold_control']=controls[point['configuration_id']]
                checked_point={**point,**{key:assignment[key] for key in ['editable_paths','frozen_source_pack','frozen_source_files']}}
                checked_point.update(lineage_editable_paths=assignment['editable_paths'],editable_paths=list(state['base_source']))
                result=raw_baseline[point['configuration_id']]
                checked=TrustedPhysicalStore._inspect_execution_run(Path(result['run_directory']),checked_point,state['base_source'])
                baseline[point['configuration_id']]={'result':result,'checked':checked}
            save(output/'effective_registry.json',effective);save(output/'gold_controls.json',controls)
            task,history=packet(manifest,state,points,baseline);save(work/'task_packet.json',task);save(work/'visible_history.json',history)
            # Tokenizer-only preflight; it never loads model weights or allocates a GPU.
            from transformers import AutoTokenizer
            from src.local_model_adapter import decision_prompt
            if source_mode:from src.local_model_adapter import source_proposal_prompt
            snapshot=json.loads((ROOT/'configs/training/backbone_cache.json').read_text())['snapshot']
            tokenizer=AutoTokenizer.from_pretrained(snapshot,local_files_only=True,trust_remote_code=False)
            prompt=(source_proposal_prompt if source_mode and not rule_mode else decision_prompt)({'task_packet':task,'visible_history':history})
            encoded=tokenizer.apply_chat_template([{'role':'user','content':prompt}],tokenize=True,add_generation_prompt=True,return_dict=True)
            reserve=manifest['sampling']['max_new_tokens'];count=len(encoded['input_ids']);save(work/'context_size.json',{'input_tokens':count,'output_reserve':reserve,'truncated':False})
            if count+reserve>16384:raise RuntimeError('Full source/contract exceeds frozen context; no proposal requested and no truncation allowed')
            pending={};candidates={};seen={};semantic_dedup=source_mode or action_teacher;initial_identity=source_identity(state['base_source'],semantic_dedup)
            def requests():
                identifiers=manifest['sampling']['rule_ids'] if rule_mode else manifest['sampling']['trials'] if gpt_mode else manifest['sampling']['seeds']
                if rule_mode:
                    for identifier in identifiers:
                        cid=state['initial_state_id']+'__rule_'+identifier;proposal=work/cid;proposal.mkdir()
                        attempt,action=sample_rule(manifest,task,history,identifier,proposal);yield cid,proposal,attempt,action
                elif gpt_mode:
                    with ThreadPoolExecutor(max_workers=2) as generation:
                        futures={}
                        for identifier in identifiers:
                            cid=manifest['collection_id']+'__'+state['initial_state_id']+'__trial_'+str(identifier);proposal=work/cid;proposal.mkdir()
                            futures[generation.submit(sample,manifest,task,history,identifier,proposal,tokenizer)]=(cid,proposal)
                        for future in as_completed(futures):
                            cid,proposal=futures[future];attempt,action=future.result();yield cid,proposal,attempt,action
                else:
                    for identifier in identifiers:
                        cid=state['initial_state_id']+'__seed_'+str(identifier);proposal=work/cid;proposal.mkdir()
                        attempt,action=sample(manifest,task,history,identifier,proposal,tokenizer);yield cid,proposal,attempt,action
            for cid,proposal,attempt,action in requests():
                attempt.update(candidate_id=cid,initial_state_id=state['initial_state_id'])
                if attempt['error']:attempt['status']='RULE_PROPOSAL_FAILED' if rule_mode else 'MODEL_REQUEST_OR_ACTION_FAILED';attempts.append(attempt);save(output/'attempts.json',attempts);continue
                if attempt.get('no_source_change'):attempt['status']='CANDIDATE_NO_SOURCE_CHANGE';attempts.append(attempt);save(output/'attempts.json',attempts);continue
                source=workspace(Path(manifest['source_pack']),files,state['base_source'],proposal/'source')
                for name in state['base_source']:(source/name).chmod(0o644)
                try:apply_source_patch(source,action['patch'],assignment['editable_paths'])
                except (ValueError,subprocess.CalledProcessError) as exc:
                    attempt.update(status='CANDIDATE_INVALID_PATCH',error=str(exc),patch_stderr=getattr(exc,'stderr',''));attempts.append(attempt);save(output/'attempts.json',attempts);continue
                edited={name:(source/name).read_text() for name in state['base_source']};identity=source_identity(edited,semantic_dedup)
                if identity==initial_identity:attempt['status']='semantic_no_source_change_before_physics' if source_mode else 'CANDIDATE_NO_SOURCE_CHANGE'
                elif identity in seen:attempt.update(status='semantic_duplicate_before_physics' if source_mode else 'CANDIDATE_DUPLICATE_SOURCE',duplicate_of=seen[identity])
                else:
                    if manifest.get('student_preselection'):
                        selection=preselect_student_action(manifest,task,history,action['patch'],points[0]['contract']['task_id'],proposal,tokenizer)
                        attempt['student_preselection']=selection
                        if not selection['accepted']:
                            attempt['status']='STUDENT_BUDGET_REJECTED_BEFORE_PHYSICS';attempts.append(attempt);save(output/'attempts.json',attempts);continue
                    seen[identity]=cid;attempt['status']='PHYSICAL_QUEUED'
                    for name in edited:(source/name).chmod(0o444)
                    visible_contract={key:value for key,value in task.items() if key!='visible_sources'}
                    visible_contract.update(task_id=points[0]['contract']['task_id'],editable_paths=list(state['base_source']))
                    row={'candidate_id':cid,'initial_state_id':state['initial_state_id'],'parent_lineage':state['parent_lineage'],'split':'train','source_role':'formal_train','origin':state['origin'],'ancestry':state['ancestry'],'pdk_revision':manifest['pdk_revision'],'base_source':state['base_source'],'candidate_source':edited,'visible_contract':visible_contract,'visible_feedback':history,'candidate_patch':action['patch'],'proposal_generation':attempt.copy(),'outcomes':[]}
                    candidates[cid]=row
                    for point in points:pending[workers.submit(physical,source,point,state,cid)]=(cid,point)
                attempts.append(attempt);save(output/'attempts.json',attempts)
            for future in as_completed(pending):
                cid,point=pending[future];result=future.result();run=Path(result['run_directory']);row=candidates[cid]
                row['outcomes'].append({'configuration_id':point['configuration_id'],'role':point['domain_role'],'evidence_path':str((run/'manifest.json').relative_to(output)),'baseline_evidence_path':str((Path(baseline[point['configuration_id']]['result']['run_directory'])/'manifest.json').relative_to(output)),'baseline_candidate_id':baseline_id})
                save(work/(cid+'_outcomes.json'),row)
                print(json.dumps({'stage':'candidate','candidate':cid,'configuration':point['configuration_id'],'status':result['status']}),flush=True)
            for row in candidates.values():
                row['outcomes'].sort(key=lambda item:item['configuration_id']);pool_rows.append(row)
            processed_states.append(state)
            if source_mode or action_teacher:
                for attempt in attempts:
                    if attempt['candidate_id'] in candidates:attempt['status']='DECLARED_DOMAIN_ATTEMPTS_COMPLETE'
                save(output/'attempts.json',attempts)
            (output/'candidates.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in pool_rows))
            store=TrustedPhysicalStore(output,effective);admitted=[];rejections=[]
            for row in pool_rows:
                try:admitted.extend(admit_candidates([row],effective,store))
                except (ValueError,OSError,KeyError) as exc:rejections.append({'candidate_id':row['candidate_id'],'error':str(exc)})
            save(output/'admission_rejections.json',rejections)
            if rejections:
                save(output/'completion.json',{'status':'PAUSED_ADMISSION_UNCERTAINTY','rejections':rejections,'formal_model_training_runs':0})
                raise RuntimeError('Physical evidence failed independent admission; retain raw records and pause rather than creating negative labels')
            labels=json.loads(Path(manifest['label_rule_path']).read_text())
            if admitted:datasets,report=build_matched_samples(admitted,labels)
            else:datasets={key:[] for key in ['T1','T2','T3','T4']};report={'initial_states':0}
            for method,rows in datasets.items():(output/(method+'.jsonl')).write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows))
            program_ids={source_identity(row['candidate_source'],True) for row in pool_rows}
            valid_program_ids={identity for identity in program_ids if all(key[0]=='parsed' for _,key in identity)}
            save(output/'yield.json',{'collection_id':manifest['collection_id'],'phase':'formal_train_collection','main_benchmark_protocol_status':manifest['main_benchmark_protocol_status'],'attempts':len(attempts),'distinct_candidates_with_all_declared_point_attempts':len(pool_rows),'unique_terminal_source_programs':len(program_ids),'unique_valid_terminal_AST_programs':len(valid_program_ids),'distinct_initial_source_programs':len({source_identity(row['base_source'],True) for row in processed_states}),'source_lineages':len({row['parent_lineage'] for row in processed_states}),'admitted_candidate_pool':len(admitted),'effective_samples_by_method':{key:len(rows) for key,rows in datasets.items()},'report':report,'formal_model_training_runs':0,'effective_pipeline_pilot_target':manifest['budget']['effective_example_pipeline_pilot_target']})
    save(output/'completion.json',{'status':'COMPLETED_INITIAL_BATCH','initial_states':len(states),'attempts':len(attempts),'formal_model_training_runs':0,'finished_at_utc':datetime.now(timezone.utc).isoformat()})


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,required=True)
    action=p.add_mutually_exclusive_group(required=True);action.add_argument('--validate-only',action='store_true');action.add_argument('--execute',action='store_true')
    a=p.parse_args();manifest,registry,states,files=load(a.manifest.resolve())
    if a.validate_only:print(json.dumps({'validated':True,'initial_states':len(states),'configurations':len(registry['configurations']),'source_files':len(files),'formal_collection_launched':False}));return
    execute(manifest,registry,states,files,a.manifest.resolve().parent/'freeze_identity.json')


if __name__=='__main__':main()
