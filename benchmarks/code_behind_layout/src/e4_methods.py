"""Freeze actual E4 models after training and validation, before test searches.

This module does not train, select from token loss, run hidden evaluation, or
promote engineering calibration adapters. Its inputs are trusted host artifacts.
"""
from datetime import datetime,timezone
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

from src.student_interface import interface_definition
from src.training import TrustedPhysicalStore,frozen_train_registry

SEEDS=(41,73,109)
METHODS=('T1','T2','T3','T4')
REVISION='381fc969f78efac66bc87ff7ddeadb7e73c218a7'
SELECTION_RULE='mean_task_S2_fraction_then_earliest_update_v1'
IMPLEMENTATION_FILES=('src/e4_methods.py','src/student_interface.py','src/policy_state.py','src/local_model_adapter.py',
                      'src/model_adapter.py','src/training.py','scripts/train_policy.py','scripts/serve_frozen_policy.py',
                      'scripts/request_frozen_policy.py')


def read(path):return json.loads(Path(path).read_text())


def resolve(root,path):
    value=Path(path)
    return (value if value.is_absolute() else Path(root)/value).resolve()


def file_digest(path):
    """Bind selected weights without loading twelve adapters into host memory."""
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(4*1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def positive(value):return type(value) in (int,float) and math.isfinite(value) and value>0


def timestamp(value):
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:raise ValueError('Freeze times must include UTC offsets')
    return result


def checkpoint_files(directory):
    directory=Path(directory).resolve();marker=read(directory/'complete.json')
    if marker.get('optimizer_boundary') is not True or not positive(marker.get('updates')):
        raise ValueError('Selected checkpoint is not a completed formal optimizer boundary')
    names=('adapter/policy/adapter_config.json','adapter/policy/adapter_model.safetensors',
           'training_state.pt','tokenizer/tokenizer_config.json','metadata/training_manifest.json',
           'metadata/training_config.json','metadata/run.json','metadata/metrics.jsonl')
    for name in names:
        path=directory/name
        if path.is_symlink() or not path.is_file() or path.stat().st_size==0:
            raise ValueError('Actual adapter, optimizer/RNG, tokenizer or training provenance is missing: '+name)
    return marker


def validate_context_calibration(path,definition):
    """A tokenizer-only fit or successful shorter run cannot open a longer window."""
    value=read(path);length=definition['max_context_tokens'];stages=value.get('stages',[])
    sft=[s for s in stages if s.get('name')=='SFT_optimizer_update' and s.get('allocated_sequence_tokens')==length]
    dpo=[s for s in stages if s.get('name')=='DPO_'+str(length)+'_pair_optimizer_update']
    restores=[s for s in stages if s.get('name')=='actual_saved_adapter_optimizer_RNG_disk_restore']
    if (value.get('status')!='COMPLETED' or value.get('scope')!='development_gpu_algorithm_calibration_not_E4'
        or value.get('allocated_sequence_tokens')!=length or Path(value.get('snapshot','')).name!=REVISION
        or len(sft)!=1 or len(dpo)!=1 or len(restores)!=1):
        raise ValueError('The exact context window lacks completed actual SFT/DPO/restore calibration')
    if (not all(restores[0].get(key) is True for key in ['adapter_bitwise_equal','optimizer_state_bitwise_equal','next_CPU_and_CUDA_RNG_equal'])
        or dpo[0].get('frozen_reference_bitwise_unchanged') is not True
        or value.get('dpo_model_training') is not True or value.get('dpo_gradient_checkpointing') is not True):
        raise ValueError('Context calibration did not establish exact restore and a frozen DPO reference')
    for stage in (sft[0],dpo[0]):
        if (not positive(stage.get('wall_seconds')) or not positive(stage.get('peak_allocated_bytes'))
            or stage.get('prompt_tokens',0)<.9*length):
            raise ValueError('Context calibration must exercise a near-full real sequence and record GPU costs')
    return {'path':str(Path(path).resolve()),'sha256':file_digest(path),'allocated_sequence_tokens':length}


def inspect_formal_run(entry,root,definition,registry_digest):
    """Use the trainer's actual admission/resume identities, never a run count claim."""
    from scripts.train_policy import prepare
    method,seed=entry['method'],entry['seed'];directory=resolve(root,entry['run_directory'])
    manifest_path=resolve(root,entry['training_manifest'])
    manifest,config,_,rows,identities=prepare(SimpleNamespace(manifest=manifest_path,method=method,seed=seed,resume=None))
    run=read(directory/'run.json')
    if (run.get('status')!='TRAINING_COMPLETED_NOT_SELECTED' or run.get('method')!=method or run.get('seed')!=seed
        or run.get('identities')!=identities or identities['registry']!=registry_digest
        or any(not positive(run.get(key)) for key in ['updates','samples','wall_seconds','gpu_hours_allocated',
                                                      'completion_tokens','peak_cuda_allocated_bytes'])):
        raise ValueError('Engineering, incomplete or unbound training cannot count as a formal E4 run')
    if run['samples']!=len(rows) or any(run['student_interface'].get(k)!=v for k,v in definition.items()):
        raise ValueError('Actual training data/window differs from the frozen E4 student interface')
    if config.get('backbone')!='Qwen/Qwen2.5-Coder-32B-Instruct' or config.get('revision')!=REVISION:
        raise ValueError('E4 backbone differs from the pinned 32B model')
    if method in ('T1','T2') and run.get('reference_checkpoint') is not None:
        raise ValueError('SFT must initialize from the common backbone, without an unreported adapter')
    checkpoints=sorted(p for p in directory.glob('checkpoint-*') if p.is_dir())
    if not checkpoints:raise ValueError('A completed run has no actual checkpoints')
    for checkpoint in checkpoints:
        marker=checkpoint_files(checkpoint)
        if (checkpoint.name!='checkpoint-%07d'%marker['updates'] or marker['updates']>run['updates'] or marker.get('reference_checkpoint')!=run.get('reference_checkpoint')
            or read(checkpoint/'metadata/training_manifest.json')!=manifest
            or read(checkpoint/'metadata/training_config.json')!=config):
            raise ValueError('Checkpoint is not bound to this completed training run')
        saved=read(checkpoint/'metadata/run.json')
        if saved.get('identities')!=identities or saved.get('method')!=method or saved.get('seed')!=seed:
            raise ValueError('Checkpoint metadata belongs to another training run')
        adapter=read(checkpoint/'adapter/policy/adapter_config.json');lora=config['lora']
        if (adapter.get('peft_type')!='LORA' or adapter.get('r')!=lora['r'] or adapter.get('lora_alpha')!=lora['alpha']
            or set(adapter.get('target_modules',[]))!=set(lora['target_modules'])
            or Path(adapter.get('base_model_name_or_path','')).name!=REVISION):
            raise ValueError('Saved adapter architecture/backbone differs from the actual recipe')
    if not any(read(p/'complete.json')['updates']==run['updates'] for p in checkpoints):
        raise ValueError('Completed final optimizer boundary is absent')
    return {'method':method,'seed':seed,'run_directory':str(directory),'run':run,'config':config,
            'manifest':manifest,'training_manifest':str(manifest_path),'checkpoints':checkpoints}


def validate_selection(entry,training,root,registry,plan,plan_path):
    """Recompute validation-only selection from all saved checkpoints and raw tools."""
    path=resolve(root,entry['validation_selection']);selection=read(path)
    if (selection.get('status')!='COMPLETED_E4_VALIDATION_CHECKPOINT_SELECTION'
        or selection.get('method')!=entry['method'] or selection.get('seed')!=entry['seed']
        or selection.get('validation_plan_sha256')!=file_digest(plan_path)):
        raise ValueError('Completed validation checkpoint provenance is absent or unbound')
    points={(p['contract']['task_id'],p['configuration_id']):p for p in registry.get('configurations',[])
            if p.get('split')=='validation'}
    declared={(p['task_id'],p['configuration_id']) for p in plan['points']}
    if not declared or len(declared)!=len(plan['points']) or not declared.issubset(points):
        raise ValueError('Validation plan needs distinct frozen validation points')
    assignments=frozen_train_registry(registry)
    for key in declared:
        point=points[key]
        if assignments.get(point['parent_lineage'],{}).get('split')!='validation' or point.get('role')=='hidden':
            raise ValueError('Training, test or hidden labels cannot select E4 checkpoints')
    evaluations=selection.get('checkpoint_evaluations',[])
    checkpoints={str(p.resolve()):p for p in training['checkpoints']}
    if ({str(resolve(path.parent,row['checkpoint'])) for row in evaluations}!=set(checkpoints)
        or len(evaluations)!=len(checkpoints)):
        raise ValueError('Every saved checkpoint must have the same complete validation plan')
    scores=[];audit=[]
    for evaluation in evaluations:
        checkpoint=resolve(path.parent,evaluation['checkpoint']);adapter=checkpoint/'adapter/policy'
        digest=file_digest(adapter/'adapter_model.safetensors')
        if evaluation.get('adapter_sha256')!=digest:raise ValueError('Validation used another adapter')
        rows=evaluation.get('points',[])
        if {(r['task_id'],r['configuration_id']) for r in rows}!=declared or len(rows)!=len(declared):
            raise ValueError('Validation cannot drop failed configurations or change its denominator')
        task_sources=evaluation['task_sources'];task_ids={task for task,_ in declared}
        if set(task_sources)!=task_ids:raise ValueError('Validation needs one frozen source per task/checkpoint')
        fractions={task:[] for task in task_ids};point_audit=[]
        for row in rows:
            key=row['task_id'],row['configuration_id'];point=points[key];run=resolve(path.parent,row['run_directory'])
            manifest=read(run/'manifest.json');context=manifest.get('context',{})
            if (manifest.get('phase')!='development_E4_checkpoint_validation'
                or context.get('source_role')!='E4_validation_checkpoint_selection'
                or context.get('method')!=entry['method'] or context.get('training_seed')!=entry['seed']
                or context.get('model_adapter_sha256')!=digest
                or timestamp(manifest['candidate']['started_at_utc'])<timestamp(plan['frozen_at_utc'])):
                raise ValueError('Physical checkpoint validation lacks its model/phase/prospective plan binding')
            checked=TrustedPhysicalStore._inspect_execution_run(run,point,task_sources[row['task_id']])
            fractions[row['task_id']].append(int(checked['S2']))
            point_audit.append({'task_id':key[0],'configuration_id':key[1],'run_directory':str(run),
                                'S1':checked['S1'],'S2':checked['S2']})
        score=sum((Fraction(sum(values),len(values)) for values in fractions.values()),Fraction())/len(fractions)
        updates=read(checkpoint/'complete.json')['updates'];scores.append((score,-updates,str(checkpoint)))
        audit.append({'checkpoint':str(checkpoint),'adapter_sha256':digest,'updates':updates,
                      'mean_task_S2_fraction':float(score),'points':point_audit})
    best=max(scores);selected=resolve(root,entry['selected_checkpoint'])
    if str(selected)!=best[2] or resolve(path.parent,selection['selected_checkpoint'])!=selected:
        raise ValueError('Selected checkpoint contradicts the predeclared physical validation rule')
    return {'selection_path':str(path),'selection_sha256':file_digest(path),'selected_checkpoint':str(selected),
            'selected_adapter':str(selected/'adapter/policy'),'adapter_sha256':next(a['adapter_sha256'] for a in audit if a['checkpoint']==str(selected)),
            'adapter_config_sha256':file_digest(selected/'adapter/policy/adapter_config.json'),
            'checkpoint_evaluations':audit}


def build_methods_freeze(draft,root):
    """Return a real freeze only after all twelve training/selection gates pass."""
    if draft.get('status')!='DRAFT_E4_METHODS':raise ValueError('Expected an E4 methods draft')
    declared_interface=draft['student_interface']
    definition=interface_definition(declared_interface['version'],declared_interface['max_context_tokens'],declared_interface['max_new_tokens'])
    if declared_interface!=definition:raise ValueError('Freeze the exact implemented student/history interface')
    registry_path=resolve(root,draft['split_registry']);registry=read(registry_path);frozen_train_registry(registry)
    registry_digest=file_digest(registry_path);calibration=validate_context_calibration(resolve(root,draft['context_calibration']),definition)
    plan_path=resolve(root,draft['validation_plan']);plan=read(plan_path)
    if (plan.get('status')!='FROZEN_E4_VALIDATION_PLAN' or plan.get('selection_rule')!=SELECTION_RULE
        or plan.get('split_registry_sha256')!=registry_digest or plan_path.stat().st_mode&0o222):
        raise ValueError('Prospectively frozen readonly validation-only selection plan is required')
    entries=draft.get('formal_training_runs',[]);expected={(method,seed) for method in METHODS for seed in SEEDS}
    if len(entries)!=12 or {(r['method'],r['seed']) for r in entries}!=expected:
        raise ValueError('E4 requires twelve actual formal runs: T1--T4 at seeds41/73/109')
    if len({str(resolve(root,r['run_directory'])) for r in entries})!=12:
        raise ValueError('One training run cannot be counted as multiple variants or seeds')
    trained={};selected={}
    for entry in entries:
        key=entry['method'],entry['seed'];training=inspect_formal_run(entry,root,definition,registry_digest)
        trained[key]=training
        selected[key]=validate_selection(entry,training,root,registry,plan,plan_path)
    common=trained['T1',SEEDS[0]]
    if any(value['config']!=common['config'] or value['run']['identities']['datasets']!=common['run']['identities']['datasets']
           for value in trained.values()):
        raise ValueError('All methods/seeds must bind the same frozen recipe and matched dataset files')
    for seed in SEEDS:
        for left,right in [('T1','T2'),('T3','T4')]:
            a,b=trained[left,seed],trained[right,seed]
            if (a['config']!=b['config'] or any(a['run'][key]!=b['run'][key] for key in ['updates','samples','allocated_sequence_tokens_per_epoch'])
                or a['run']['identities']['registry']!=b['run']['identities']['registry']):
                raise ValueError('Matched methods did not use the same sources/recipe/update allocation')
        for method in ('T3','T4'):
            reference=selected['T1',seed]['selected_adapter'];run=trained[method,seed]['run']
            if run.get('reference_checkpoint')!=reference:
                raise ValueError('T3/T4 must share the actual validation-selected same-seed T1 adapter')
    settings=draft.get('decoding_settings')
    if settings!={'do_sample':False,'max_new_tokens':1024}:
        raise ValueError('Freeze the common greedy ordinary ACTION decoding settings')
    variants={'T0':{'base_revision':REVISION,'adapter':None,'actual_training_seeds':[],'actual_model_count':1,
                    'matched_evaluation_seed_slots':list(SEEDS)}}
    for method in METHODS:
        variants[method]={'training_seeds':list(SEEDS),'seeds':{str(seed):{
            'run_directory':trained[method,seed]['run_directory'],
            'training_manifest':trained[method,seed]['training_manifest'],**selected[method,seed]} for seed in SEEDS}}
    project=Path(__file__).resolve().parents[1]
    return {'status':'FROZEN_E4_METHODS','version':'e4_methods_v1','frozen_at_utc':datetime.now(timezone.utc).isoformat(),
        'backbone':'Qwen/Qwen2.5-Coder-32B-Instruct','base_revision':REVISION,
        'backbone_snapshot':common['manifest']['backbone_snapshot'],'tokenizer_revision':REVISION,
        'quantization':common['config']['quantization'],'adapter_architecture':common['config']['lora'],
        'formal_training_runs':12,'engineering_runs_counted':0,'training_seeds':list(SEEDS),
        'student_interface':definition,'decoding_settings':settings,'variants':variants,
        'split_registry':str(registry_path),'split_registry_sha256':registry_digest,
        'context_calibration':calibration,'validation_plan':str(plan_path),'validation_plan_sha256':file_digest(plan_path),
        'implementation_sha256':{name:file_digest(project/name) for name in IMPLEMENTATION_FILES},
        'hidden_evaluation_policy':'global_release_only_after_all_predeclared_searches_sealed_and_all_models_frozen',
        'hidden_evaluation_released':False}


def frozen_serving_method(path,variant,training_seed):
    """Resolve a future formal service adapter, without changing the old service.

    The service operator supplies this manifest path; policy actions cannot pick
    checkpoints. Hash verification replaces loading an unbound weight artifact.
    """
    path=Path(path).resolve();artifact=read(path)
    if (artifact.get('status')!='FROZEN_E4_METHODS' or artifact.get('formal_training_runs')!=12
        or path.stat().st_mode&0o222 or variant not in ('T0',)+METHODS or training_seed not in SEEDS):
        raise ValueError('Formal serving requires actual frozen E4 methods and a declared variant/seed')
    definition=interface_definition(artifact['student_interface']['version'],artifact['student_interface']['max_context_tokens'],
                                    artifact['student_interface']['max_new_tokens'])
    if definition!=artifact['student_interface'] or artifact.get('base_revision')!=REVISION:
        raise ValueError('Serving context/backbone differs from the frozen methods')
    project=Path(__file__).resolve().parents[1]
    if set(artifact.get('implementation_sha256',{}))!=set(IMPLEMENTATION_FILES):
        raise ValueError('Frozen E4 needs the complete training/inference implementation binding')
    for name,expected in artifact['implementation_sha256'].items():
        if file_digest(project/name)!=expected:raise ValueError('Frozen E4 inference/training implementation changed: '+name)
    adapter=None
    if variant!='T0':
        row=artifact['variants'][variant]['seeds'][str(training_seed)];adapter=Path(row['selected_adapter']).resolve()
        if file_digest(adapter/'adapter_model.safetensors')!=row['adapter_sha256']:
            raise ValueError('Actual serving adapter differs from the validation-selected frozen weights')
        if file_digest(adapter/'adapter_config.json')!=row['adapter_config_sha256']:
            raise ValueError('Actual serving adapter configuration differs from the frozen architecture')
    return {'variant':variant,'training_seed':None if variant=='T0' else training_seed,
            'evaluation_seed_slot':training_seed,'source_role':'E4_frozen_method',
            'base_revision':REVISION,'backbone_snapshot':artifact['backbone_snapshot'],
            'adapter_path':str(adapter) if adapter else None,'student_interface':definition,
            'decoding_settings':artifact['decoding_settings'],'quantization':artifact['quantization'],
            'visible_history_policy':definition.get('history_policy')}
