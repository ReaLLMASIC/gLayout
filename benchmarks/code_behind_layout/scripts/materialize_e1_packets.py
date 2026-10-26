#!/usr/bin/env python3
"""Materialize draft matched E1 families on the trusted execution host.

No policy is launched. Exact hidden tables and source bindings remain private.
The capsule consumer regenerates its generic PCells for the actual current z.
"""
import argparse
import ast
import copy
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
if not (ROOT/'src').is_dir() and Path('/work/src').is_dir():ROOT=Path('/work')
sys.path.insert(0,str(ROOT))
from src.e1_packets import bind_reference,empty_scaffold,policy_packet
HOST_ROOT=Path('/srv/code-behind-layout')


def local(path):
    path=Path(path)
    try:return ROOT/path.relative_to(HOST_ROOT)
    except ValueError:return path if path.is_absolute() else ROOT/path


def host(path):
    return str(HOST_ROOT/Path(path).resolve().relative_to(ROOT.resolve()))


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def effective_pdk(pdk):
    """Empty/None pair placeholders impose no rule; keep every actual rule."""
    return {**pdk,'rules':{a:{b:value for b,value in row.items() if value}
        for a,row in pdk['rules'].items() if any(row.values())}}


def ota_analysis_contracts(kind):
    """Exact analysis shapes/axes retained by the original 2pF OTA benches."""
    return {'op':{'kind':'op','columns':6 if kind=='five_t' else 8,'expected_rows':1},
        'ac':{'kind':'ac','columns':3,'start':10,'end':1e9,'points':401,'scale':'log'},
        'tran':{'kind':'transient','columns':3,'start':0,'end':4e-6,'required_windows':[[1.8e-6,1.99e-6]]},
        'dc':{'kind':'dc','columns':5,'start':.9 if kind=='five_t' else .95,'end':1.3 if kind=='five_t' else 1.15,
            'points':9 if kind=='five_t' else 5,'scale':'linear'}}


def generic_pack(destination):
    """Copy common primitives/routes without any higher-level placement assembly."""
    vendor=ROOT/'vendor/glayout/src/glayout';common=destination/'glayout';common.mkdir(parents=True)
    for directory in ('pdk','primitives','routing','spice','util','provenance'):
        shutil.copytree(vendor/directory,common/directory,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    text=(vendor/'__init__.py').read_text();lines=text.splitlines(keepends=True);tree=ast.parse(text)
    remove=set()
    for node in tree.body:
        if ((isinstance(node,ast.ImportFrom) and (node.module or '').startswith('placement.')) or
            (isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='__all__' for t in node.targets))):
            remove.update(range(node.lineno-1,node.end_lineno))
    (common/'__init__.py').write_text(''.join(line for i,line in enumerate(lines) if i not in remove))
    return sorted(str(p.relative_to(destination)) for p in destination.rglob('*') if p.is_file())


def application(kind,task):
    if kind in ('five_t','compact_miller'):return task['bench']['original_application']
    if kind=='mirror':return task['bench']
    if kind in ('common_source_stage','resistive_diff'):
        name='common_source' if kind=='common_source_stage' else kind
        return json.loads((ROOT/'results/derived'/f'{name}_independent_development.json').read_text())['bench']
    if kind=='stacked_switch':
        d=json.loads((ROOT/'results/derived/stacked_switch_independent_development.json').read_text())
        return {k:d[k] for k in ('supply_V','temperature_C','load_ohm','load_F')}
    # Literal application values from the retained independent characterization.
    base={'supply_V':1.8,'temperature_C':27,'bias_current_A':10e-6}
    return {**base,**({'reference_current_A':10e-6,'output_clamp_V':1.2,'reference_step_A':[8e-6,10e-6]}
        if kind=='cascode_mirror' else {'input_DC_V':1.2,'load_F':1e-12,'input_step_V':[1.19,1.21]})}


def role_table(points,sized_index):
    """Explicitly shared domain, fixed per-trial roles, three different anchors."""
    if len(points)!=25 or len({p['configuration_id'] for p in points})!=25:raise ValueError('Expected 25 unique source configurations')
    start=(0,8,16)[sized_index];order=[(start+i)%25 for i in range(25)];result=[]
    for position,index in enumerate(order):
        point=copy.deepcopy(points[index]);point['shared_domain_configuration_id']=point['configuration_id']
        point['configuration_id']='anchor' if position==0 else ('dev_%02d'%position if position<9 else 'hidden_%02d'%(position-8))
        point['role']='anchor' if position==0 else ('development' if position<9 else 'hidden')
        result.append(point)
    return result


def reuse_api(kind):
    if kind in ('mirror','five_t','compact_miller'):
        invocation='from component_build import build; build(configuration["parameters"], Path("/tmp/reused.gds")); shutil.copyfile("/tmp/reused.gds", output_path)'
    else:
        invocation=('from src.generators.'+kind+' import build; generated=build(Path("/tmp/reuse"),configuration["parameters"]); '
            'copy the returned GDS path to output_path')
    return {'invocation':invocation,'parameters':'Use the immutable current configuration parameters unchanged.',
        'scope':'The complete existing target block is explicitly available in this reuse stratum.',
        'temporary_outputs':'Write temporary auxiliary files only below /tmp; emit the final GDS at the declared output path.'}


def materialize(bindings):
    from glayout import sky130
    from scripts.e1_pcell_prepare import prepare
    from scripts.independent_task_baseline import contracts
    started=time.monotonic();cpu=time.process_time()
    output=ROOT/'runtime/task_preparation'/('e1_matched_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    private=output/'private';private.mkdir(parents=True,mode=0o700);public=output/'public';public.mkdir()
    pdk={'layers':{name:sky130.get_glayer(name) for name in sky130.glayers},'rules':sky130.grules,
        'units':'um','grid_um':.005,
        'device_definitions':{
            'MOS':'D/G/S/B SKY130 1.8V standard NFET/PFET. W is each active finger width, L is gate length; fingers are parallel unit devices. NFET uses n+ diffusion in the p-type body, PFET uses p+ diffusion in nwell. Poly crosses active; source/drain contacts and body ties use the supplied full enclosure/contact/spacing rules. No implicit dummy devices are allowed.',
            'MIM':'sky130_fd_pr__cap_mim_m3_1: P is the upper conductor (generic met5), N is the lower conductor (generic met4); capmet marks the dielectric plate area. W/L are the independent reference plate dimensions. Use the full PDK minimum width/enclosure/spacing rules.'}}
    pdk=effective_pdk(pdk)
    save(public/'pdk.json',pdk);save(private/'layer_aliases.json',sky130.glayers)
    generic=private/'common_G2';common_files=generic_pack(generic)
    summary=[];overlap=[];generation=[]
    targets=bindings['targets']
    if len(targets)!=8 or len({r['target'] for r in targets})!=8:raise ValueError('Expected eight actual target logics')
    for target_index,binding in enumerate(targets):
        kind=binding['target'];template=local(binding['template']);original=json.loads(template.read_text());original_pack=local(original['source_pack'])
        source=private/kind/'reuse_source_pack';source.parent.mkdir(parents=True)
        shutil.copytree(original_pack,source,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        source_files=sorted(str(p.relative_to(source)) for p in source.rglob('*') if p.is_file())
        for sized_index in range(3):
            task_id='draft_E1_'+kind+'_s%02d'%(sized_index+1);folder=private/task_id;folder.mkdir()
            points=role_table(original['configurations'],sized_index)
            stratum=('reuse' if (target_index+sized_index)%2==0 else 'composition')
            for point in points:
                ref=local(point['reference_file']);newref=folder/'references'/(point['configuration_id']+'.spice');newref.parent.mkdir(exist_ok=True)
                shutil.copyfile(ref,newref);point['reference_file']=host(newref)
                point['reference_id']=task_id+'_'+point['configuration_id']
                point['contract'].update(task_id=task_id,configuration_id=point['configuration_id'],reference_id=point['reference_id'],immutable_parameters=point['parameters'])
                if kind in ('cascode_mirror','source_follower','stacked_switch','common_source_stage','resistive_diff'):
                    point['contract']['analysis_contracts']=contracts(kind)
                elif kind in ('five_t','compact_miller'):
                    point['contract']['analysis_contracts']=ota_analysis_contracts(kind)
                    if not any(s['name']=='original_development_predicate' for s in point['contract']['specifications']):
                        point['contract']['specifications'].append({'name':'original_development_predicate','unit':'1','min':1,'max':1})
                # Binding checks all 25 references without creating hidden libraries on a policy host.
                headers=[line.split() for line in newref.read_text().splitlines() if line.lower().startswith('.subckt ')]
                top=headers[0][1];bind_reference(newref.read_text(),top,point['reference_id'])
            anchor=points[0];top=[line.split()[1] for line in local(anchor['reference_file']).read_text().splitlines() if line.lower().startswith('.subckt ')][0]
            task={'status':'DRAFT_MATCHED_E1_FAMILY_NOT_ADMITTED','task_id':task_id,'target':kind,'top_cell':top,'stratum':stratum,
                'target_logic_id':original['parent_lineage'],'logical_group':binding['logical_group'],'merge_sensitivity_group':binding['merge_sensitivity_group'],
                'shared_domain_id':bindings.get('domain_version','draft_v1')+'_shared25_'+kind,'source_template':host(template),'source_pack':host(source),'source_files':source_files,
                'generic_G2_pack':host(generic),'generic_G2_files':common_files,'reuse_api':reuse_api(kind),'configurations':points,
                'application':application(kind,original),'anchor_contract':anchor['contract'],'visible_configurations':points[:9],
                'editable_paths':['generator.py'],'entrypoint':'generator.py','formal_admission':False,'formal_trials':0,'training_examples':0,
                'qualification':{'primitive_interface':'Two actual generic MOS/MIM composition controls passed fullDRC/LVS/device-intent; not an entire target oracle.',
                    'full25_target_S2':None,'source_template_qualification':original.get('qualification',original.get('default_qualification'))}}
            save(folder/'task.json',task)
            library=folder/'anchor_library';result=prepare(local(anchor['reference_file']),top,anchor['reference_id'],library)
            generation.append({'task_id':task_id,**result['generation_cost']})
            for method in ('G0','G1','G2'):
                packet=policy_packet(task,method,pdk=pdk,anchor_graph=result['graph'],anchor_primitives=result['cells'],reuse_api=reuse_api(kind))
                save(public/task_id/(method+'.json'),packet)
            relation={'task_id':task_id,'shared_domain_id':task['shared_domain_id'],'anchor_shared_id':points[0]['shared_domain_configuration_id'],
                'point_roles':[{k:p[k] for k in ('configuration_id','shared_domain_configuration_id','role')} for p in points]}
            overlap.append(relation)
            summary.append({'task_id':task_id,'target':kind,'stratum':stratum,'logical_group':binding['logical_group'],
                'merge_sensitivity_group':binding['merge_sensitivity_group'],'shared_domain_id':task['shared_domain_id'],
                'anchor_parameters':anchor['parameters'],'primitive_count':len(result['cells']),
                'MOS_access_ports':16,'MIM_access_ports':8 if result['graph']['MIM_count'] else None,
                'formal_admission':False,'full25_target_S2':None})
            print(json.dumps({'materialized':task_id,'stratum':stratum,'generic_primitive_types':len(result['cells'])}),flush=True)
    save(private/'shared_domain_relationships.json',overlap)
    save(private/'source_bindings.json',bindings)
    result={'status':'DRAFT_NOT_FORMAL','output':host(output),'task_count':len(summary),'packet_count':len(summary)*3,
        'target_logics':8,'primary_groups':8,'merged_sensitivity_groups':7,
        'strata':{s:sum(r['stratum']==s for r in summary) for s in ('reuse','composition')},
        'configurations_per_task':{'anchor':1,'development':8,'hidden':16},
        'domain_relationship':'Each target has three role rotations of the same 25 configurations, explicitly linked in the private overlap table. Task/configuration repetitions do not increase independent target counts.',
        'capsule_consumer':'scripts/materialize_e1_packets.py --capsule TASK_JSON --configuration ID --method G0|G1|G2 --output NEW_DIR (trusted backend only)',
        'current_state_consumer':'Every adapter.step must read all complete current editable files from its trusted workspace and pass current_sources; visible_history_policy=current_source_and_feedback_v1.',
        'hidden_exported':False,'formal_trials':0,'training_examples':0,'tasks':summary,
        'generation_cost':{'wall_seconds':time.monotonic()-started,'process_CPU_seconds':time.process_time()-cpu,
            'primitive_library_costs':generation,'GPU_seconds':0}}
    save(public/'catalog.json',result);save(output/'summary.json',result)
    return result


def capsule(task_path,configuration_id,method,output):
    """Backend-only point selection; private task tables never enter policy requests."""
    from glayout import sky130
    from scripts.e1_pcell_prepare import prepare
    task=json.loads(local(task_path).read_text());point=next(p for p in task['configurations'] if p['configuration_id']==configuration_id)
    output=local(output);output.mkdir(parents=True,exist_ok=False);source=output/'source';source.mkdir()
    if method=='G2':
        pack=local(task['source_pack'] if task['stratum']=='reuse' else task['generic_G2_pack'])
        shutil.copytree(pack,source,dirs_exist_ok=True)
        source.chmod(0o755)  # The private working copy must permit a new generator; the frozen pack stays readonly.
    if (source/'generator.py').exists():(source/'generator.py').chmod(0o644)
    (source/'generator.py').write_text(empty_scaffold(task['top_cell']))
    graph=bind_reference(local(point['reference_file']).read_text(),task['top_cell'],point['reference_id'])
    result=None
    if method!='G0':result=prepare(local(point['reference_file']),task['top_cell'],point['reference_id'],output/'library')
    configuration={'parameters':point['parameters'],'graph':graph,
        'pdk_rules':{'layers':{name:sky130.get_glayer(name) for name in sky130.glayers},'rules':sky130.grules}}
    save(output/'configuration.json',configuration)
    manifest={'phase':'development_E1_matched_capsule','task_id':task['task_id'],'method':method,'stratum':task['stratum'],
        'configuration_id':configuration_id,'role':point['role'],'reference_id':point['reference_id'],'source_dir':host(source),
        'source_paths':sorted(str(p.relative_to(source)) for p in source.rglob('*') if p.is_file()),
        'library_dir':host(output/'library') if result else None,'library_paths':sorted(p.name for p in (output/'library').iterdir()) if result else [],
        'configuration_file':host(output/'configuration.json'),'trusted_reference_file':point['reference_file'],'contract':point['contract'],
        'editable_paths':['generator.py'],'library_generation_cost':result['generation_cost'] if result else None,
        'hidden_feedback_policy':'Hidden execution occurs after source sealing; candidate stdout/stderr and per-point outcomes remain on the trusted backend and never return to policy.',
        'formal_admission':False}
    save(output/'backend_manifest.json',manifest)
    return {'capsule':host(output),'task_id':task['task_id'],'method':method,'source_file_count':len(manifest['source_paths'])}


def refresh_public(preparation):
    """Rebuild unfrozen packet documents from existing actual primitive artifacts."""
    preparation=local(preparation);catalog=json.loads((preparation/'summary.json').read_text())
    if catalog['status']!='DRAFT_NOT_FORMAL' or catalog['formal_trials']!=0:raise ValueError('Only unrun draft packets can be rebuilt')
    pdk=effective_pdk(json.loads((preparation/'public/pdk.json').read_text()))
    from src.e1_benchmarks import build_trusted
    for record in catalog['tasks']:
        folder=preparation/'private'/record['task_id'];task=json.loads((folder/'task.json').read_text())
        if task['target'] in ('five_t','compact_miller'):
            analysis=ota_analysis_contracts(task['target'])
            for point in task['configurations']:point['contract']['analysis_contracts']=analysis
            for point in task['visible_configurations']:point['contract']['analysis_contracts']=analysis
            task['anchor_contract']['analysis_contracts']=analysis
        task['reuse_api']=reuse_api(task['target'])
        template=folder/'trusted_template'
        if not task.get('trusted_template'):
            files=build_trusted(task,task['configurations'][0],template)
            task.update(trusted_template=host(template),trusted_template_files=files)
        save(folder/'task.json',task)
        actual=json.loads((folder/'anchor_library/manifest.json').read_text())
        for method in ('G0','G1','G2'):
            save(preparation/'public'/task['task_id']/(method+'.json'),policy_packet(task,method,pdk=pdk,
                anchor_graph=actual['graph'],anchor_primitives=actual['cells'],reuse_api=task['reuse_api']))
    save(preparation/'public/pdk.json',pdk)
    return {'preparation':host(preparation),'packets_rebuilt':catalog['packet_count'],'physical_or_policy_calls':0,
        'rule_compaction':'Removed only empty/None pair placeholders; every effective rule retained'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--bindings',type=Path);mode.add_argument('--capsule',type=Path)
    mode.add_argument('--refresh-public',type=Path)
    p.add_argument('--configuration');p.add_argument('--method',choices=['G0','G1','G2']);p.add_argument('--output',type=Path)
    a=p.parse_args()
    if a.bindings:result=materialize(json.loads(local(a.bindings).read_text()))
    elif a.refresh_public:result=refresh_public(a.refresh_public)
    else:
        if not all((a.configuration,a.method,a.output)):p.error('Capsule requires configuration, method and output')
        result=capsule(a.capsule,a.configuration,a.method,a.output)
    print(json.dumps(result),flush=True)
