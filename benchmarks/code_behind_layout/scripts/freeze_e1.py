"""Freeze the actual E1 task/implementation bytes after physical and circuit controls."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.device_intent import compare_device_intent
from src.domain_runner import inspect_point,source_contents
from src.measurement import split_errors,validate_contract
from src.model_adapter import PACKET_FIELDS

LIVE_IMPLEMENTATION=[
    'src/candidate_executor.py','src/domain_runner.py','src/model_adapter.py','src/local_model_adapter.py',
    'src/policy_state.py','src/e1_packets.py','src/e1_benchmarks.py','src/report_parsers.py',
    'src/measurement.py','src/spice_validation.py','src/device_intent.py','src/e1_analysis.py',
    'scripts/e1_matched_runner.py','scripts/materialize_e1_packets.py','scripts/e1_pcell_prepare.py',
    'scripts/run_eda_probe.py','scripts/analyze_e1.py','scripts/run_e1_suite.py','scripts/archive_e1_episode.py']


def read(path):return json.loads(Path(path).read_text())
def save(path,value):Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def path(value):return Path(value) if Path(value).is_absolute() else ROOT/value
def digest(filename):return hashlib.sha256(Path(filename).read_bytes()).hexdigest()


def rebase(value,old,new):
    if isinstance(value,dict):return {key:rebase(item,old,new) for key,item in value.items()}
    if isinstance(value,list):return [rebase(item,old,new) for item in value]
    if isinstance(value,str) and (value==str(old) or value.startswith(str(old)+'/')):
        return str(new)+value[len(str(old)):]
    return value


def mechanical_controls(summaries,catalog,packet_root):
    targets={row['target'] for row in catalog['tasks']};verified={};bindings=[]
    for summary_path in summaries:
        for row in read(summary_path)['episodes']:
            private=Path(row['episode_directory'])/'private';state=read(private/'state.json');task=read(private/'task.json')
            if state.get('driver_role')!='engineering_mechanical_control' or state.get('formal_trial') is not False:
                raise ValueError('A qualification control must remain independent of tested-policy trials')
            if not row['final_anchor']['complete'] or row['final_anchor']['S2'] is not True:
                raise ValueError('Actual mechanical anchor did not establish its complete physical contract: '+task['target'])
            point=next(p for p in task['configurations'] if p['role']=='anchor')
            record=state['points'][point['configuration_id']];run=Path(record['run_directory']);manifest=read(run/'manifest.json')
            frozen_task=read(packet_root/'private'/task['task_id']/'task.json')
            frozen_point=next(p for p in frozen_task['configurations'] if p['role']=='anchor')
            if point['contract']!=frozen_point['contract']:
                raise ValueError('Mechanical control uses a different task contract')
            if (run/'trusted/reference.spice').read_bytes()!=Path(point['reference_file']).read_bytes():
                raise ValueError('Mechanical control reference is not the independently bound N(z)')
            if Path(point['reference_file']).read_bytes()!=Path(frozen_point['reference_file']).read_bytes():
                raise ValueError('Mechanical control does not qualify the actual new task reference')
            for name in frozen_task['trusted_template_files']:
                if name in ('reference.spice','contract.json'):continue
                if (run/'trusted'/name).read_bytes()!=(Path(frozen_task['trusted_template'])/name).read_bytes():
                    raise ValueError('Mechanical control uses another evaluator/benchmark snapshot: '+task['target']+'/'+name)
            sources=source_contents(private/'capsules'/point['configuration_id']/'source',manifest['source_files'],binary=True)
            checked=inspect_point({'run_directory':str(run)},point,sources,read(run/'configuration.json'))
            intent=compare_device_intent((run/'evidence/extracted_lvs.spice').read_text(),(run/'trusted/reference.spice').read_text())
            if checked['S2'] is not True or checked['execution_integrity']!='valid' or not intent['is_clean']:
                raise ValueError('Raw independent qualification evidence does not establish S2 and exact intent')
            verified[task['target']]=True
            bindings.append({'target':task['target'],'task_id':task['task_id'],'episode_directory':str(private.parent),
                'run_directory':str(run),'independent_device_terminal_graph_match':True,'full_physical_control':True})
    if set(verified)!=targets:raise ValueError('Missing actual mechanical controls: '+','.join(sorted(targets-set(verified))))
    return bindings


def validate_inputs(manifest,summaries,feasibility_path,registry):
    if manifest['status']!='DRAFT_E1_RUNNER' or manifest['formal_dispatch'] is not False:
        raise ValueError('Freeze a new, unrun E1 protocol snapshot')
    if manifest['methods']!=['G0','G1','G2'] or manifest['trials']!=5:raise ValueError('The fixed E1 matrix is24×3×5')
    packet_root=path(manifest['packet_root']);catalog=read(packet_root/'public/catalog.json')
    if len(catalog['tasks'])!=24 or Counter(row['stratum'] for row in catalog['tasks'])!={'reuse':12,'composition':12}:
        raise ValueError('The actual matched task catalog does not match the prospective design')
    preflight=read(ROOT/'results/derived/e1_packet_initial_preflight.json')
    if preflight['packets']!=72 or preflight['all_fit'] is not True:raise ValueError('All72 complete initial packets must fit the shared budget')
    if Path(preflight['preparation']).resolve()!=packet_root.resolve():raise ValueError('Token preflight belongs to another packet root')
    assignments={row['lineage_id']:row['split'] for row in registry['lineages']}
    if split_errors(registry):raise ValueError('Source assignments violate the shared lineage/topology split')
    for row in catalog['tasks']:
        task=read(packet_root/'private'/row['task_id']/'task.json')
        if assignments.get(task['target_logic_id'])!='test':raise ValueError('E1 target is not assigned exclusively to evaluation')
        if Counter(p['role'] for p in task['configurations'])!={'anchor':1,'development':8,'hidden':16}:
            raise ValueError('Each actual task requires its fixed1+8+16 domain')
        if not task.get('trusted_template') or not task.get('trusted_template_files'):
            raise ValueError('Each task needs an exact independent evaluator snapshot')
        for point in task['configurations']:validate_contract(point['contract'])
        for method in manifest['methods']:
            packet=read(packet_root/'public'/task['task_id']/(method+'.json'))
            if set(packet)!=PACKET_FIELDS or packet['task_id']!=task['task_id']:raise ValueError('Unmatched or nonwhitelisted policy packet')
    feasibility=read(feasibility_path)
    if feasibility['scope']!='schematic_only_not_S1_S2' or feasibility['status']!='COMPLETE':
        raise ValueError('Independent circuit feasibility qualification is not complete')
    feasible={row['target']:row for row in feasibility['targets']}
    if set(feasible)!={row['target'] for row in catalog['tasks']}:raise ValueError('Circuit qualification does not cover the actual target logics')
    if any(any(row[key]!=25 for key in ('declared_configurations','complete_configurations','meet_specifications')) for row in feasible.values()):
        raise ValueError('An intended circuit/domain has incomplete or infeasible prelayout specifications; resolve the development domain before freezing')
    controls=mechanical_controls(summaries,catalog,packet_root)
    return packet_root,catalog,preflight,feasibility,controls


def permission_amendment(filename,manifest,packet_root):
    record=read(filename);prior=read(path(record['prior_manifest']))
    if record['kind']!='working_copy_directory_permission_only' or prior['status']!='FROZEN_E1':
        raise ValueError('Only the documented actual capsule-directory repair is admitted here')
    changed=[name for name,expected in prior['implementation_sha256'].items() if digest(ROOT/name)!=expected]
    if changed!=['scripts/materialize_e1_packets.py']:
        raise ValueError('An E1 permission amendment cannot alter another live implementation file')
    before=(path(record['prior_manifest']).parent/'implementation/scripts/materialize_e1_packets.py').read_text()
    old='        shutil.copytree(pack,source,dirs_exist_ok=True)\n'
    new=old+'        source.chmod(0o755)  # The private working copy must permit a new generator; the frozen pack stays readonly.\n'
    if before.count(old)!=1 or (ROOT/'scripts/materialize_e1_packets.py').read_text()!=before.replace(old,new):
        raise ValueError('The repair must be exactly the working-copy root chmod after copytree')
    for name in ('methods','trials','budget','visible_history_policy','runtime'):
        if manifest[name]!=prior[name]:raise ValueError('The permission repair cannot change '+name)
    for task in prior['task_ids']:
        for method in prior['methods']:
            relative=Path('public')/task/(method+'.json')
            if (packet_root/relative).read_bytes()!=(Path(prior['packet_root'])/relative).read_bytes():
                raise ValueError('The permission repair cannot change a visible policy input')
    return record


def freeze(manifest_path,summaries,feasibility_path,registry_path,output,revision,check_only=False,amendment=None):
    if not re.fullmatch('[0-9a-f]{7,40}',revision):raise ValueError('Bind the actual committed implementation revision')
    manifest=read(manifest_path);registry=read(registry_path)
    packet_root,catalog,preflight,feasibility,controls=validate_inputs(manifest,summaries,feasibility_path,registry)
    amendment_record=permission_amendment(amendment,manifest,packet_root) if amendment else None
    if check_only:return {'status':'READY_FOR_E1_FREEZE','tasks':24,'episodes':360,'new_model_calls':0,'new_physical_calls':0}
    output=Path(output).resolve()
    if output.exists():raise ValueError('Never overwrite an existing protocol freeze')
    output.mkdir(parents=True,mode=0o700);new_root=output/'packets';shutil.copytree(packet_root,new_root)
    for filename in (new_root/'private').rglob('*.json'):
        filename.chmod(0o644)
        save(filename,rebase(read(filename),packet_root.resolve(),new_root))
    tasks=[]
    for row in catalog['tasks']:
        filename=new_root/'private'/row['task_id']/'task.json';task=read(filename)
        task.update(formal_admission=True,status='FROZEN_E1_TASK');save(filename,task)
        tasks.append({'task_id':row['task_id'],'target':row['target'],'stratum':row['stratum'],
            'source_group':row['logical_group'],'merged_source_group':row['merge_sensitivity_group'],
            'parent_lineage':task['target_logic_id'],'shared_domain_id':row['shared_domain_id']})
        for method in manifest['methods']:
            relative=Path('public')/row['task_id']/(method+'.json')
            if (new_root/relative).read_bytes()!=(packet_root/relative).read_bytes():
                raise ValueError('Freezing must not change the matched visible policy inputs')
    frozen_catalog={**catalog,'status':'FROZEN_E1_TASK_CATALOG','formal_admission':True}
    (new_root/'public/catalog.json').chmod(0o644);save(new_root/'public/catalog.json',frozen_catalog)
    implementation=output/'implementation';implementation.mkdir()
    identity={}
    for name in LIVE_IMPLEMENTATION+['docs/e1_protocol.md','scripts/freeze_e1.py']:
        target=implementation/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,target);identity[name]=digest(target)
    model=read(path(manifest['model_config']));model.update(status='frozen_E1_policy',visible_history_policy=manifest['visible_history_policy'])
    save(output/'model_config.json',model);save(output/'token_preflight.json',preflight)
    save(output/'circuit_feasibility.json',feasibility);save(output/'mechanical_controls.json',controls)
    previous=read(ROOT/'data/splits/registry.json')
    old_assignments={row['lineage_id']:row['split'] for row in previous['lineages']}
    if any({row['lineage_id']:row['split'] for row in registry['lineages']}.get(key)!=value for key,value in old_assignments.items()):
        raise ValueError('E1 cannot change already frozen train/validation/evaluation source assignments')
    save(output/'prior_global_registry.json',previous)
    frozen_at=datetime.now(timezone.utc).isoformat()
    registry.update(status='frozen',freeze_scope='unchanged_source_assignments_plus_E1_'+output.name,
        frozen_at_utc=frozen_at,main_benchmark_protocol_status='E1_frozen_other_experiments_draft',
        formal_tasks=[{'task_id':row['task_id'],'experiment':'E1','split':'test','parent_lineage':row['parent_lineage']} for row in tasks])
    save(output/'registry.json',registry)
    frozen={**manifest,'status':'FROZEN_E1','formal_dispatch':True,'phase':'formal_E1','freeze_id':output.name,
        'backend_manifest_path':str(output/'manifest.json'),
        'frozen_at_utc':frozen_at,'packet_root':str(new_root),'task_catalog':str(new_root/'public/catalog.json'),
        'task_ids':[row['task_id'] for row in tasks],'tasks':tasks,'model_config':str(output/'model_config.json'),
        'source_revision':revision,'implementation_sha256':{name:identity[name] for name in LIVE_IMPLEMENTATION},
        'frozen_registry':str(output/'registry.json'),'freeze_blockers':[],
        'qualification':{'mechanical':str(output/'mechanical_controls.json'),'schematic':str(output/'circuit_feasibility.json')},
        'dispatch_order_seed':20261018,'GPT_sampling_seed':'unavailable; fresh independent trial identifiers only',
        'primary_contrasts':['G1-G0','G2-G1'],'analysis':{'stratify_by':'reuse/composition','cluster_bootstrap_replicates':2000,'bootstrap_seed':20261018}}
    save(output/'manifest.json',frozen)
    if amendment_record:
        frozen['protocol_amendment']=amendment_record
        save(output/'manifest.json',frozen);save(output/'protocol_amendment.json',amendment_record)
    artifacts={str(p.relative_to(output)):digest(p) for p in sorted(output.rglob('*')) if p.is_file()}
    save(output/'freeze_identity.json',{'scope':'Immutable E1 protocol/task/evaluator/code/model-config bytes before formal dispatch','files_sha256':artifacts})
    save(ROOT/'data/splits/registry.json',registry)
    for filename in sorted(output.rglob('*'),reverse=True):filename.chmod(0o555 if filename.is_dir() else 0o444)
    output.chmod(0o555)
    return {'status':'FROZEN_E1','manifest':str(output/'manifest.json'),'tasks':24,'planned_episodes':360,'new_model_calls':0,'new_physical_calls':0}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--mechanical-summary',type=Path,action='append',required=True);p.add_argument('--feasibility-report',type=Path,required=True)
    p.add_argument('--registry',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--code-revision',required=True);p.add_argument('--check-only',action='store_true')
    p.add_argument('--amendment',type=Path)
    a=p.parse_args();print(json.dumps(freeze(a.manifest,a.mechanical_summary,a.feasibility_report,a.registry,a.output,a.code_revision,a.check_only,a.amendment)))


if __name__=='__main__':main()
