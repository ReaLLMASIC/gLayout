"""Actually exercise one qualified train-only trusted capsule before freeze."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.collect_training import packet, save
from src.candidate_executor import CandidateExecutor
from src.local_model_adapter import source_proposal_prompt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preparation',type=Path,required=True)
    parser.add_argument('--existing-smoke-directory',type=Path,help='Reuse this exact immutable capsule physical smoke only to recount its changed draft packet')
    args=parser.parse_args()
    prep=json.loads(args.preparation.read_text());cid=prep['circuit_id']
    if prep['status']!='DRAFT_READONLY_COLLECTION_CAPSULE_NOT_FROZEN':raise ValueError('Expected a new draft capsule')
    out=ROOT/'runs/development/additional_capsule_smoke'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');out.mkdir(parents=True)
    save(out/'preparation.json',prep)
    anchor=next(point for point in prep['configurations'] if point['role']=='anchor')
    if args.existing_smoke_directory:
        prior=args.existing_smoke_directory
        if json.loads((prior/'preparation.json').read_text())!=prep:raise ValueError('Physical smoke belongs to a different immutable capsule')
        result=json.loads((prior/'result.json').read_text())
    else:
        runner=CandidateExecutor(ROOT/'runtime/GLdev',out/'physical',ROOT/'runtime/magic-8.3.685',timeout=720)
        result=runner.execute(source_dir=prep['source_pack'],source_paths=prep['source_files'],entrypoint='generator.py',representation='G2',
            configuration=anchor['parameters'],trusted_dir=prep['trusted_bundle'],trusted_paths=prep['trusted_files'],fidelity='pex_spice',
            context={'source_role':'development_capsule_calibration','parent_lineage':prep['parent_lineage'],'configuration_id':anchor['configuration_id'],
                     'reference_id':anchor['reference_id'],'pdk_revision':'0fe599b2afb6708d281543108caf8310912f54af'},
            generation_timeout_seconds=240,evaluator_timeout_seconds=720)
    save(out/'result.json',result)
    physical=result.get('physical_result') or {}
    report={'preparation_path':str(args.preparation.resolve()),'result_path':str(out/'result.json'),'run_directory':result['run_directory'],
            'circuit_id':cid,'status':result['status'],'assessment':physical.get('assessment'),
            'point_evaluation_complete':physical.get('point_evaluation_complete',False),'phase':'development_boundary_calibration',
            'formal_training_rows':0}
    if args.existing_smoke_directory:report['unchanged_physical_smoke_reused_from']=str(args.existing_smoke_directory.resolve())
    save(out/'calibration.json',report)
    if not(physical.get('point_evaluation_complete') and physical.get('assessment',{}).get('S2')):
        print(json.dumps(report),flush=True);raise RuntimeError('New trusted evaluator did not establish a complete passing point')
    # These are actual measured qualification outcomes used only to size a draft
    # visible packet. Formal collection will obtain fresh baselines separately.
    qualification=json.loads(Path(prep['qualification_path']).read_text())['circuits'][cid]
    baseline={}
    for point in qualification['points']:
        if prep.get('qualification_control'):
            control=point['domain_id']+'__'+point['solver']+('__independent_inputs' if point['independent_transient_inputs'] else '')
            if control!=prep['qualification_control']:continue
        feasible=point.get('core_constraints_pass',point.get('qualified',False))
        baseline[point['configuration_id']]={'checked':{'S0':True,'S1':True,'S2':feasible,'failure_class':None},
            'result':{'status':'EVALUATED','physical_result':{'observation':{'corners':{corner:{'metrics':{'area':{'value':point['area_um2'],'unit':'um2'}}} for corner in point['corners']}}}}}
    state={'initial_state_id':cid.lower()+'_original_compiler_source_teacher_draft','parent_lineage':prep['parent_lineage'],
        'base_source':{name:(Path(prep['source_pack'])/name).read_text() for name in prep['editable_paths']}}
    manifest={'collection_id':cid.lower()+'_collection_draft','sampling':{'mode':'train_collection_source'}}
    points=[{**point,'domain_role':point['role']} for point in prep['configurations']]
    task,history=packet(manifest,state,points,baseline)
    request={'variant':'T0','mode':'train_collection_source','sampling':{'temperature':.7,'top_p':.95,'seed':101},
             'request':{'task_packet':task,'visible_history':history}}
    save(out/'request_example.json',request)
    from transformers import AutoTokenizer
    snapshot=json.loads((ROOT/'configs/training/backbone_cache.json').read_text())['snapshot']
    tokenizer=AutoTokenizer.from_pretrained(snapshot,local_files_only=True,trust_remote_code=False)
    prompt=source_proposal_prompt(request['request'])
    encoded=tokenizer.apply_chat_template([{'role':'user','content':prompt}],tokenize=True,add_generation_prompt=True,return_dict=True)
    count=len(encoded['input_ids']);report.update(input_tokens=count,output_reserve=3072,context_limit=8192,context_fits=count+3072<=8192,
        source_complete=True,source_bytes={name:len(text.encode()) for name,text in state['base_source'].items()},request_example=str(out/'request_example.json'),
        baseline_feedback_scope='actual development qualification; formal runner obtains new nine-point baselines')
    save(out/'calibration.json',report)
    print(json.dumps(report),flush=True)
    if not report['context_fits']:raise RuntimeError('Complete source plus complete contract exceeds context; do not truncate or freeze')


if __name__=='__main__':main()
