"""Exactly three missing default E2 source/N/bench controls, development only.

Each source runs once at its original s1 parameters and unpatched base layout.
This is not a candidate stream, a sizing search or an automatic retry. The new
telescopic stage cohort is managed separately and is never launched here.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import json
from pathlib import Path
import resource
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.e2_execution import Pool
from scripts.e2_stage_prepare import build
from scripts.e2_four_source import raw_run,save,read
from scripts.archive_e2_run import archive
from src.domain_runner import inspect_point,source_contents

IDS=['five_t_s1','compact_miller_s1','fvf_s1']
SNAPSHOT=['scripts/e2_default_source_controls.py','scripts/e2_execution.py',
    'scripts/e2_stage_prepare.py','scripts/e2_cached_evaluator.py','scripts/e2_spice_process_profile.py',
    'src/candidate_executor.py','src/device_intent.py','src/spice_validation.py']


def control(manifest,pool,output):
    controller=Pool(manifest,pool,output,'full_oracle',False)
    controller.state.update(scope='development_exact_default_source_N_control_NOT_CANDIDATE_POOL',
        declared_new_GDS_max=1,declared_new_full_max=1,source_or_parameters_modified=False)
    controller.save();point=controller.point
    report={'pool_id':pool['pool_id'],'status':'RUNNING','S2_established':False,
        'fixed_parameters':point['parameters'],'source':pool['source_dir'],
        'fixed_point':pool['point'],'fixed_trusted_bench':pool['full_trusted'],
        'source_patch_applied':False,'new_formal_labels':0,'automatic_retry':False}
    generated=None
    try:
        template=controller.out/'geometry_only_trusted'
        files=build('geometry',template,top=pool['top_cell'])
        generation=controller.execute(pool['source_dir'],pool['source_paths'],template,files,
            'geometry','source_to_geometry',-1)
        generated=Path(generation['run_directory']);report['generation']=generation
        save(controller.out/'control.json',report)
        if not (generation.get('physical_result') or {}).get('requested_fidelity_complete'):
            raise ValueError('The exact base source generation/geometry control did not complete')
        if source_contents(generated/'source',pool['source_paths'],binary=True)!=source_contents(pool['source_dir'],pool['source_paths'],binary=True):
            raise ValueError('Actual generation changed the complete fixed source closure')
        gds=generated/'accepted/candidate.gds'
        candidate={'stream_index':-1,'gds':str(gds),'geometry':generation['physical_result']['geometry'],
            'source_generation_and_geometry_run':str(generated),'source_scope':'unpatched_default_control'}
        controller.state['accepted']=[candidate];controller.save()
        full=controller.full(candidate);report['full']=full
        report['actual_cost_stages']={'generation':generation['cost'],'physical':full['physical']['cost'],
            'full':None if full['full_electrical'] is None else full['full_electrical']['cost']}
        if not full['full_electrical']:
            raise ValueError('The exact base source did not reach a complete independent positive physical acquisition')
        run=Path(full['full_electrical']['run_directory'])
        with raw_run(run) as actual:
            names=read(actual/'manifest.json')['source_files']
            checked=inspect_point({'run_directory':str(actual)},point,
                source_contents(actual/'source',names,binary=True),{'parameters':point['parameters']},gold_control_check=False)
        report['raw_checked']=checked
        report['S2_established']=bool(checked['S2'] and checked['analysis_complete'])
        report['status']='COMPLETE_S2' if report['S2_established'] else 'ACTUAL_COMPLETED_SPEC_FAILURE' if checked['analysis_complete'] else 'UNKNOWN_RETAINED_NO_RETRY'
        report['admission_binding']={'pool_id':pool['pool_id'],'run_directory':str(run),
            'source_generation_run':str(generated),'mask_gds':str(gds)}
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as error:
        report.update(status='UNKNOWN_OR_PHYSICAL_REJECTION_RETAINED_NO_RETRY',error=type(error).__name__+': '+str(error))
    finally:
        if generated is not None and (generated/'manifest.json').is_file():
            report['generation_raw_archive']=archive(generated,retain_accepted_gds=True)
        report['completed_at_utc']=datetime.now(timezone.utc).isoformat()
        save(controller.out/'control.json',report)
    return report


def run(manifest_path,output,workers):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic();before=resource.getrusage(resource.RUSAGE_SELF);children=resource.getrusage(resource.RUSAGE_CHILDREN)
    manifest=read(manifest_path);pools=[p for p in manifest['pools'] if p['pool_id'] in IDS]
    if [p['pool_id'] for p in pools]!=IDS or any(p['sizing_id']!='s1' for p in pools):
        raise ValueError('This finite control has exactly the three original default identities')
    save(output/'plan.json',{'scope':__doc__,'manifest':str(Path(manifest_path).resolve()),'pool_ids':IDS,
        'planned_default_controls':3,'maximum_new_GDS':3,'maximum_new_full':3,'workers':workers,
        'each_container_CPUs':2,'each_container_memory_GiB':8,'actual_busy_plus2_max':24,'used_RAM_GiB_max':190,
        'diskfree_GiB_min':4,'root_approved_reason':'Six nondefaults passed raw audit; default research controls had different source; FVF default had no captured generator binding',
        'telescopic_control_invocations':0,'source_N_bench_and_layout_constants_changed':False,
        'formal_trials':0,'new_training_data':0,'automatic_retry':False})
    snapshot=output/'implementation_snapshot'
    for name in SNAPSHOT:
        path=snapshot/name;path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,path)
    try:
        def task(pool):return control(manifest,pool,output/pool['pool_id'])
        with ThreadPoolExecutor(max_workers=workers) as executor:rows=list(executor.map(task,pools))
        result={'scope':'Actual three missing unpatched default E2 source/N/bench controls; not formal',
            'planned':3,'terminal_records':len(rows),'all_three_positive':len(rows)==3 and all(r['S2_established'] for r in rows),
            'controls':rows,'new_formal_labels':0,'automatic_retry':False}
        save(output/'summary.json',result)
        return {'summary':str(output/'summary.json'),'all_three_positive':result['all_three_positive'],'terminal_records':len(rows)}
    finally:
        after=resource.getrusage(resource.RUSAGE_SELF);child_after=resource.getrusage(resource.RUSAGE_CHILDREN)
        save(output/'controller_resource_usage.json',{'wall_seconds':time.monotonic()-started,
            'self_CPU_seconds':after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
            'waited_host_tool_child_CPU_seconds':child_after.ru_utime+child_after.ru_stime-children.ru_utime-children.ru_stime,
            'scope':'Actual hostcontroller and waited patch/mask/docker-client; each trusted container records its own childCPU; no allocatedCPU estimates'})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',type=int,choices=[1,2],default=1);args=parser.parse_args()
    print(json.dumps(run(args.manifest,args.output,args.workers),allow_nan=False),flush=True)
