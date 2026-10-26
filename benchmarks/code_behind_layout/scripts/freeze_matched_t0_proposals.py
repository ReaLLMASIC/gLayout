"""Freeze one bounded96-proposal T0 branch from the twelve frozen GPT contexts."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.run_frozen_training_collection import load_definition
from scripts.serve_matched_t0_proposals import MODE,SEEDS,load_plan
from src.e4_methods import validate_context_calibration
from src.student_interface import CONTEXT_VERSION,interface_definition


def read(path):return json.loads(Path(path).read_text())
def save(path,value):Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')


def freeze(parent_plan,calibration):
    preparation=read(parent_plan)
    if (preparation.get('programs')!=6 or preparation.get('initial_context_count')!=12
        or preparation.get('planned_proposals')!=96 or preparation.get('model_calls')!=0 or preparation.get('physical_calls')!=0
        or preparation.get('sampling',{}).get('max_context_tokens')!=16384):
        raise ValueError('Use the approved complete twelve-context16k planning preparation')
    validate_context_calibration(calibration,interface_definition(CONTEXT_VERSION,16384))
    contexts=[];parents={}
    for context in preparation['contexts']:
        name=context['circuit_id'].lower()+'_planning_trajectories_context_v2'
        manifest_path=ROOT/'runtime/train_collections'/name/'collection.json'
        if name not in parents:
            manifest,_,states,_=load_definition(manifest_path)
            if (manifest['sampling']['max_context_tokens']!=16384 or manifest['sampling']['max_new_tokens']!=1024
                or manifest['sampling']['mode']!='train_collection_action_gpt'):
                raise ValueError('The matched parent must be the prospective16k ordinary-ACTION GPT collection')
            parents[name]={'manifest':manifest,'states':states,'path':str(manifest_path),
                'manifest_sha256':hashlib.sha256(manifest_path.read_bytes()).hexdigest()}
        parent=parents[name];matches=[s for s in parent['states'] if s['initial_state_id']==context['initial_state_id']]
        if len(matches)!=1 or matches[0]['base_source']!=context['full_source']:
            raise ValueError('The T0 branch cannot replace or add an initial source context')
        work=Path(parent['manifest']['output_root'])/context['initial_state_id']
        contexts.append({'initial_state_id':context['initial_state_id'],'program_id':context['program_id'],
            'circuit_id':context['circuit_id'],'parent_lineage':matches[0]['parent_lineage'],
            'parent_collection':name,'task_id':name+'__'+context['initial_state_id'],
            'base_source':context['full_source'],'materialized_task_packet':str(work/'task_packet.json'),
            'materialized_visible_history':str(work/'visible_history.json')})
    if len(contexts)!=12 or len({c['program_id'] for c in contexts})!=6 or len(parents)!=4:
        raise ValueError('Keep exactly six real programs, twelve task contexts and four qualified circuit families')
    output=ROOT/'runtime/train_collection_proposals/matched_t0_planning_context_v1';output.mkdir(parents=True,exist_ok=False)
    interface=output/'interface';(interface/'src').mkdir(parents=True)
    shutil.copyfile(ROOT/'scripts/serve_matched_t0_proposals.py',interface/'service.py')
    shutil.copyfile(ROOT/'scripts/collect_matched_t0_proposals.py',interface/'sampler.py')
    for name in ('model_adapter.py','local_model_adapter.py','policy_state.py'):
        shutil.copyfile(ROOT/'src'/name,interface/'src'/name)
    shutil.copyfile(calibration,output/'gpu_context_calibration.json')
    plan={'status':'frozen','role':'matched_T0_proposals_only','collection_id':output.name,'mode':MODE,
        'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'source_role':'base_model_formal_train_action_proposals',
        'max_context_tokens':16384,'max_new_tokens':1024,'timeout_seconds':240,
        'sampling':{'temperature':.7,'top_p':.95,'seeds':list(SEEDS)},'contexts':contexts,
        'parent_GPT_collections':{name:{k:v for k,v in item.items() if k in ('path','manifest_sha256')} for name,item in parents.items()},
        'context_calibration':str(output/'gpu_context_calibration.json'),
        'output_root':str(ROOT/'runs/train_proposals'/output.name),'maximum_dispatch_hours':8,
        'endpoint':'http://127.0.0.1:8119/decision','physical_jobs':0,'formal_trained_models':0,
        'planned_proposals':96,'distinct_task_contexts':12,'actual_source_programs':6,'source_lineages':1,
        'matching':'Each T0 seed receives the exact already materialized GPT packet and full actual baseline feedback; seed remains outside model content. No context IDs or wording are changed.',
        'gpu_maintenance':'Coordinator must block future oldT0 dispatch, drain actual8114 requests, preserve exact restart configuration, safely pause only its own8114, run8119 as the sole resident model, and restore8114 after this bounded branch.',
        'admission':'Proposal-only raw outputs are never training examples. Subsequent exact-source9point evaluation/current gate and student budget checks remain required.',
        'counting':'Additional proposal generator on the same12contexts; never24contexts, never12trainedmodels. Preserve invalid diffs, oversize/late outputs, noops and exact AST duplicates.',
        'source_AST_deduplication':'Exact ast.dump(include_attributes=False), including literals; parse failures use exact text identity. No patch repair or numeric normalization.',
        'matrix_completion':'NOT_RUN entries stay in the original96proposal denominator if matching GPT context is not materialized before8hours.'}
    save(output/'proposal_plan.json',plan)
    files=sorted(p for p in output.rglob('*') if p.is_file())
    save(output/'freeze_identity.json',{str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
    load_plan(output/'proposal_plan.json')
    for path in sorted(output.rglob('*'),reverse=True):path.chmod(0o555 if path.is_dir() else 0o444)
    output.chmod(0o555)
    return {'status':'FROZEN_MATCHED_T0_PROPOSALS_NOT_DISPATCHED','plan':str(output/'proposal_plan.json'),
        'contexts':12,'planned_proposals':96,'new_model_calls':0,'new_physical_calls':0,'new_training_examples':0}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--parent-plan',type=Path,required=True);p.add_argument('--calibration',type=Path,required=True);a=p.parse_args()
    print(json.dumps(freeze(a.parent_plan,a.calibration),indent=2))
