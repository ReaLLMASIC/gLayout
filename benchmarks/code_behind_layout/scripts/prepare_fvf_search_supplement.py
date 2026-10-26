"""CPU-only preparation/check/freeze of the independent20-search FVF supplement.

No model, EDA, hidden evaluation, registry edit or primary-cohort mutation occurs.
A future freeze requires an actual committed-source index and rereads both public
physical controls; qualification flags alone are insufficient.
"""
import argparse
import copy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import fvf_supplement_episode as episode
from scripts import fvf_supplement_point as physical
from scripts.prepare_fvf_supplement import TASK,EDITABLE,SERVER

ORIGIN=SERVER/'runtime/task_preparation/FVF_supplement_fullmodule_v2'
MAIN=SERVER/'runtime/protocol_freezes/E3_primary_v2/manifest.json'
DEV01=SERVER/'runs/development/FVF_supplement_points/dev_01_v1/point.json'
read=episode.read;save=episode.save;sha=episode.sha


def snapshot_files(root):
    return {str(p.relative_to(root)):sha(p) for p in sorted(Path(root).rglob('*'))
        if p.is_file() and p.name!='manifest.json' and '__pycache__' not in p.parts}


def reopen_controls(task,output):
    """Real raw/current Store/fullRC audit; no SPICE or geometry generation."""
    from src.training import TrustedPhysicalStore
    from scripts.qualify_fvf_supplement import full_rc_audit
    control=physical.binding();result=[];began,cpu=time.monotonic(),time.process_time()
    for ident,record in [('anchor',read(physical.CONTROL.parent/'run.json')),('dev_01',read(DEV01))]:
        run=Path(record.get('raw_directory') or record['run_directory'])
        point=next(p for p in task['configurations'] if p['configuration_id']==ident)
        manifest=read(run/'manifest.json')
        if manifest['phase'].startswith('development') is not True:raise ValueError('Only actual original development controls')
        if set(manifest['source_files'])!=set(control['source_files']):raise ValueError('Actual source closure differs')
        source=Path(task['source_pack_base'])
        actual=physical.verify_source(task,control,source)
        if any((run/'source'/n).read_bytes()!=b for n,b in actual.items()):raise ValueError('Control evaluated another full module/caller/library')
        trusted=run/'trusted';expected={}
        for name in control['trusted_files']:
            if name=='reference.spice':content=Path(point['reference_file']).read_text()
            elif name=='contract.json':content=json.dumps(point['contract'],indent=2)+'\n'
            else:content=(Path(control['trusted'])/name).read_text()
            if (trusted/name).read_text()!=content:raise ValueError('Control independent N/contract/vendor bench changed: '+name)
            expected[name]=content
        dry={**point,'parameters':{'parameters':point['parameters']},'editable_paths':[EDITABLE],
            'lineage_editable_paths':[EDITABLE],'frozen_source_files':[n for n in task['source_files'] if n!=EDITABLE],
            'frozen_source_pack':str(source),'intent_reference_path':'reference.spice','trusted_evaluator_files':expected}
        store=TrustedPhysicalStore.inspect_development_run(run,dry,{EDITABLE:(source/EDITABLE).read_text()})
        if store['S2'] is not True:raise ValueError('Actual current Store control did not establish S2')
        destination=Path(output)/ident;destination.mkdir(parents=True,exist_ok=False)
        audit=full_rc_audit(run,point,destination)
        if audit['status']!='RC_DEVICE_GRAPH_MATCH':raise ValueError('Actual unsimplified fullRC/deck control is incomplete')
        result.append({'configuration_id':ident,'raw_directory':str(run),'raw_manifest_sha256':sha(run/'manifest.json'),
            'source81_N_contract_trusted14_exact':True,'current_Store_S2':True,
            'full_RC_status':audit['status'],'full_RC_audit':audit,'original_cost_charged_here':False,
            'origin':'Actual development control; not formal policy or training evidence'})
    return {'status':'ACTUAL_TWO_PUBLIC_CONTROLS_REOPENED','controls':result,
        'audit_wall_seconds':time.monotonic()-began,'audit_parent_CPU_seconds':time.process_time()-cpu,
        'new_physical_calls':0,'new_model_calls':0}


def prepare(output,main_manifest=MAIN):
    if ROOT!=SERVER:raise ValueError('Private25 inputs stay on their original trusted execution endpoint')
    output=Path(output).resolve();output.relative_to(ROOT/'runtime/task_preparation')
    if output.exists():raise ValueError('Use one unused DRAFT output')
    original_main=read(main_manifest);episode.main.verify(original_main)
    if original_main['status']!='FROZEN_E3' or original_main['freeze_id']!='E3_primary_v2':raise ValueError('Actual main freeze required')
    if original_main['budget']!=episode.BUDGET:raise ValueError('Common16k/1024 source/history/physical budget changed')
    task=read(ORIGIN/'private/task.json');physical.binding()
    for point in task['configurations']:physical.selected_point(task,point['configuration_id'])
    output.mkdir(parents=True,mode=0o700)
    base=output/'base';episode.main.capsule(ORIGIN/'private/task.json',base)
    task=copy.deepcopy(task);task.update(source_pack_base=str(base),source_overrides={EDITABLE:str(base/EDITABLE)},frozen_source_overrides={},
        logical_group='fvf_feedback',merge_sensitivity_group='vendor_glayout_connected',
        status='DRAFT_E3_FVF_SUPPLEMENT_TASK',formal_admission=False,formal_dispatch_allowed=False)
    for point in task['configurations']:
        target=output/'private/references'/(point['configuration_id']+'.spice');target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(Path(point['reference_file']).read_bytes());point['reference_file']=str(target)
    task_path=output/'private/task.json';save(task_path,task)
    control=physical.binding();trusted=output/'private/trusted_template'
    shutil.copytree(control['trusted'],trusted)
    if sorted(str(p.relative_to(trusted)) for p in trusted.rglob('*') if p.is_file())!=control['trusted_files']:
        raise ValueError('Actual qualified fourteen-file trusted closure differs')
    packet=read(ORIGIN/'public/task_packet.json');save(output/'public/packet.json',packet)
    for field in ('model_config','risk_model'):
        p=episode.main.project(original_main[field]);target=output/'method'/p.name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(p.read_bytes())
    implementations={**original_main['implementation_sha256'],**{n:sha(ROOT/n) for n in episode.LIVE}}
    manifest={'status':episode.DRAFT,'formal_dispatch':False,'cohort_id':episode.COHORT,
        'manifest_path':str(output/'manifest.json'),'preparation':str(output),'task':str(task_path),
        'packet':str(output/'public/packet.json'),'task_ids':[TASK],'search_plan':episode.matrix(),
        'trusted_template':str(trusted),'trusted_sha256':copy.deepcopy(control['trusted_sha256']),
        'budget':copy.deepcopy(episode.BUDGET),'fidelity_policy':'F0_actual_full_each_selected_configuration',
        'selection_seeds':list(episode.SEEDS),'risk_weights':copy.deepcopy(original_main['risk_weights']),
        'risk_model':str(output/'method'/Path(original_main['risk_model']).name),
        'model_config':str(output/'method'/Path(original_main['model_config']).name),
        'main_manifest':str(Path(main_manifest).resolve()),'main_manifest_sha256':sha(main_manifest),
        'supplement_release_file':str(ROOT/'runtime/evaluation_releases'/episode.COHORT/'hidden_release.json'),
        'dispatch_directory':str(ROOT/'runs/formal/E3_FVF_supplement_dispatch'/episode.COHORT),
        'implementation_sha256':implementations,'file_sha256':{},
        'fixed_point_budgets':{'generation_seconds':240,'evaluator_seconds':900,'point_total_seconds_including_gate':1800,
            'single_worker':True,'CPUs':2,'memory_GiB':8,'actual_busy_limit':24,'RAM_used_limit_GiB':190,'disk_free_minimum_GiB':4},
        'hidden_gate':'Original1730 sealed +12 actual models + own exact20 frozen selected sources; no feedback after source sealing',
        'original_baseline_plan':{'points':25,'source':str(base),'roles':{'anchor':1,'development':8,'hidden':16},
            'cost':'Fresh formal evaluation only after both releases, never relabel development qualification'},
        'maximum_search_full_point_calls':160,'maximum_selected_source_postfreeze_points':500,
        'maximum_new_original_baseline_points':25,'maximum_new_physical_points':685,
        'study_scope':{'complex_OTA':True,'project_supervised_topology_holdout':True,'base_pretraining_known':False,
            'topology':'fvf_feedback','ancestry':'vendor_glayout_connected','new_ancestry_clusters':0,
            'initial_state':'Original feasible source; no proven poor-area or editing gain claimed',
            'primary24_1730_7clusters_unchanged':True,'not_training_or_selector_calibration':True,
            'prior_use':'Development15pF qualification and E2 source use disclosed; formal hidden vectors not read'},
        'freeze_blockers':['Root review and committed implementation index','Actual this-exact-packet CPU preflight',
            'Raw reopening of two completed public controls','Independent prospective readonly supplement freeze; no policy dispatch authorized now'],
        'created_at_utc':datetime.now(timezone.utc).isoformat()}
    controls=reopen_controls(task,output/'audits');save(output/'audits/control_reopen.json',controls)
    manifest['file_sha256']=snapshot_files(output);save(output/'manifest.json',manifest)
    return manifest


def preflight(manifest_path,tokenizer):
    from src.local_model_adapter import decision_prompt
    from src.model_adapter import prompt_token_budget
    from src.policy_state import current_state_request
    from src.e3_feedback import compact,public_checked
    m=episode.verify_manifest(manifest_path);original=read(m['packet']);actual=read(DEV01)
    feedback={'configuration_id':actual['configuration_id'],'revision':0,'checked':public_checked(actual['checked']),
        'objective':actual['objective'],'episode_status':'RUNNING','physical_feedback':compact(actual['physical_feedback'])}
    reports=[]
    for method in episode.METHODS:
        packet=episode.policy_packet(original,m,method,'2099-01-01T00:00:00+00:00')
        histories=[('initial',[]),('one_actual_public_development_payload',[{'observation':feedback}])]
        for label,history in histories:
            request=current_state_request(packet,history,packet['visible_sources'])
            tokens=prompt_token_budget(tokenizer,decision_prompt(request),{'max_context_tokens':16384,'max_new_tokens':1024})
            reports.append({'method':method,'case':label,**tokens})
    return {'status':'ACTUAL_CPU_PACKET_PREFLIGHT','cohort_id':episode.COHORT,'cases':reports,
        'all_fit':all(r['fits_with_full_output_reserve'] for r in reports),'source_history_truncated':False,
        'payload_scope':'One actual public dev01 point, serialized only as a capacity probe; not a policy trial',
        'whole_episode_capacity_guaranteed':False,'new_model_calls':0,'new_EDA_calls':0,
        'tokenizer_revision':'381fc969f78efac66bc87ff7ddeadb7e73c218a7'}


def rebase(value,old,new):
    if isinstance(value,dict):return {k:rebase(v,old,new) for k,v in value.items()}
    if isinstance(value,list):return [rebase(v,old,new) for v in value]
    if isinstance(value,str) and (value==str(old) or value.startswith(str(old)+'/')):return str(new)+value[len(str(old)):]
    return value


def rebase_json_copy(path,old,new):
    original=read(path);updated=rebase(original,old,new)
    # Preserve original trusted/model JSON bytes, including formatting. Only
    # path-bearing metadata in this new copy needs serialization.
    if updated!=original:
        path.chmod(0o644);save(path,updated)


def freeze(draft_path,source_index,output,check_only=False):
    """Software API only until separate Root approval; this never runs policies."""
    draft_path=Path(draft_path).resolve();m=episode.verify_manifest(draft_path);old=draft_path.parent
    index=read(source_index)
    if not re.fullmatch('[0-9a-f]{40}',index['revision']):raise ValueError('Actual committed40-character Git revision required')
    for n,value in m['implementation_sha256'].items():
        if index['files_sha256'].get(n)!=value or sha(ROOT/n)!=value:raise ValueError('Actual committed source index mismatch: '+n)
    capacity=read(old/'public/capacity.json')
    if not capacity['all_fit'] or capacity['cohort_id']!=episode.COHORT:raise ValueError('Exact current CPU capacity proof required')
    # Do not reuse a stale capacity report after changing packet bytes.
    if capacity['packet_sha256']!=sha(m['packet']):raise ValueError('Capacity was measured for another packet')
    audit_dir=old/'freeze_reopen'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    reopen_controls(read(m['task']),audit_dir)
    if check_only:return {'status':'CHECKED_NOT_FROZEN','cohort_id':episode.COHORT,'new_model_or_EDA_calls':0}
    output=Path(output).resolve();output.relative_to(ROOT/'runtime/protocol_freezes')
    if output.exists():raise ValueError('Never overwrite a previous freeze/partial output')
    shutil.copytree(old,output)
    for folder in [output,*(p for p in output.rglob('*') if p.is_dir())]:folder.chmod(folder.stat().st_mode|0o700)
    # Rebase only this new output copy. Old development source/raw and primary
    # frozen paths remain unchanged; every reference byte is copied unchanged.
    for p in sorted(output.rglob('*.json')):
        rebase_json_copy(p,old,output)
    task=read(output/'private/task.json');task.update(status='FROZEN_E3_FVF_SUPPLEMENT_TASK',formal_admission=True,formal_dispatch_allowed=True)
    save(output/'private/task.json',task)
    final=rebase(m,old,output);final.update(status=episode.FROZEN,formal_dispatch=True,
        freeze_id=episode.COHORT,source_revision=index['revision'],frozen_at_utc=datetime.now(timezone.utc).isoformat(),
        freeze_blockers=[])
    save(output/'committed_source_index.json',index)
    # Identity differs at the task/host provenance level, not in the original
    # electrical contract, benchmark, N(z), solver or source bytes.
    final['file_sha256']=snapshot_files(output);save(output/'manifest.json',final)
    for p in output.rglob('*'):p.chmod(0o555 if p.is_dir() else 0o444)
    output.chmod(0o555);episode.verify_manifest(output/'manifest.json',formal=True)
    return {'status':final['status'],'manifest':str(output/'manifest.json'),'cohort_id':episode.COHORT,
        'searches':20,'new_model_or_EDA_calls':0}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--mode',choices=['prepare','preflight','check','freeze'],required=True)
    p.add_argument('--output',type=Path);p.add_argument('--manifest',type=Path);p.add_argument('--source-index',type=Path)
    a=p.parse_args();began,cpu=time.monotonic(),time.process_time()
    if a.mode=='prepare':
        if not a.output:p.error('New DRAFT output required')
        m=prepare(a.output);r={'status':m['status'],'manifest':m['manifest_path'],'searches':len(m['search_plan']),
            'private25_not_exported':True,'new_EDA_or_model_calls':0}
    elif a.mode=='preflight':
        from transformers import AutoTokenizer
        cache=read(ROOT/'configs/training/backbone_cache.json')
        tokenizer=AutoTokenizer.from_pretrained(cache['snapshot'],local_files_only=True,trust_remote_code=False)
        r=preflight(a.manifest,tokenizer);r['packet_sha256']=sha(read(a.manifest)['packet'])
        out=Path(a.manifest).parent;save(out/'public/capacity.json',r)
        m=read(a.manifest);m['file_sha256']=snapshot_files(out);save(a.manifest,m)
    else:
        if not(a.manifest and a.source_index):p.error('DRAFT manifest and committed source index required')
        if a.mode=='freeze' and not a.output:p.error('Unused immutable output required')
        r=freeze(a.manifest,a.source_index,a.output,a.mode=='check')
    r.update(operation_wall_seconds=time.monotonic()-began,operation_parent_CPU_seconds=time.process_time()-cpu)
    print(json.dumps(r,indent=2,allow_nan=False))


if __name__=='__main__':main()
