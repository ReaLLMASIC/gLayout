"""Read-only current-gate/AST accounting of the completed matched96 T0 pool."""
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.training_pilot_status import program,MODULES
from src.training import TrustedPhysicalStore,admit_candidates


def read(p):return json.loads(Path(p).read_text())
def jsonl(p):return [json.loads(v) for v in Path(p).read_text().splitlines() if v.strip()] if Path(p).exists() else []


def originals(registry,row):
    lineage=next(v for v in registry['lineages'] if v['lineage_id']==row['parent_lineage'])
    return {name:(Path(lineage['frozen_source_pack'])/name).read_text() for name in MODULES}


def circuit_id(registry,context):
    task=context['visible_contract']['task_id']
    points=[v for v in registry['configurations'] if v['contract']['task_id']==task]
    values={v['parameters']['circuit']['circuit_id'] for v in points}
    if len(values)!=1:raise ValueError('A selected sample must have one actual circuit/physical task')
    return next(iter(values)),points


def pool(root,directory=None):
    root=Path(root);directory=Path(directory or root);registry=read(root/'effective_registry.json')
    candidates={r['candidate_id']:r for r in jsonl(root/'candidates.jsonl')}
    result={'SFT':set(),'pairs':set(),'pair_contexts':set(),'initial_ASTs':set(),'terminal_ASTs':set(),
        'method_rows':Counter(),'records':[],'orientations':{}}
    for method in ['T1','T2','T3','T4']:
        rows=jsonl(directory/(method+'.jsonl'));result['method_rows'][method]=len(rows)
        for sample in rows:
            raw=sample['raw_sample'];context=json.loads(raw['context']);cid,points=circuit_id(registry,context)
            first_id=raw.get('candidate_id',raw.get('chosen_candidate_id'));original=originals(registry,candidates[first_id])
            initial=program(context['base_source'],original);key=(cid,initial);result['initial_ASTs'].add(initial)
            def terminal(candidate_id,patch):
                c=candidates[candidate_id]
                if c['candidate_patch']!=patch or c['base_source']!=context['base_source'] or c['initial_state_id']!=raw['initial_state_id']:
                    raise ValueError('A selected row differs from actual source/candidate/patch binding')
                return program(c['candidate_source'],original)
            if method in ['T1','T2']:
                end=terminal(raw['candidate_id'],raw['patch']);result['terminal_ASTs'].add(end)
                if end!=initial:result['SFT'].add(key)
                result['records'].append({'method':method,'initial_state_id':raw['initial_state_id'],'candidate_ids':[raw['candidate_id']],'same_initial_terminal_AST':end==initial})
            else:
                a=terminal(raw['chosen_candidate_id'],raw['chosen']);b=terminal(raw['rejected_candidate_id'],raw['rejected'])
                pair=(key,frozenset((a,b)));result['terminal_ASTs'].update((a,b))
                if a!=b:result['pairs'].add(pair);result['pair_contexts'].add(key)
                physical=(pair,json.dumps([v['parameters'] for v in points],sort_keys=True),json.dumps(context['visible_contract']['contract'],sort_keys=True))
                orientations=result['orientations'].setdefault(physical,{'T3':set(),'T4':set()});orientations[method].add((a,b))
                result['records'].append({'method':method,'initial_state_id':raw['initial_state_id'],'candidate_ids':[raw['chosen_candidate_id'],raw['rejected_candidate_id']],
                    'same_terminal_AST':a==b,'_pair':pair,'_chosen':a,'_rejected':b,'_key':key})
    return result,candidates,registry


def union(pools,field):return set().union(*(p[field] for p in pools)) if pools else set()


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    output=args.output.resolve();output.relative_to(ROOT/'results/derived')
    if output.exists():raise ValueError('Use a new independent audit path')
    top=ROOT/'runs/train_collection';current=top/'matched_t0_planning_physical_v1';terminal=read(current/'completion.json')
    if terminal['status']!='COMPLETE':raise ValueError('Matched T0 has not actually completed')
    new,candidates,registry=pool(current);store=TrustedPhysicalStore(ROOT,registry);admitted=admit_candidates(list(candidates.values()),registry,store)
    if len(admitted)!=10:raise ValueError('The actual matched pool no longer has its ten verified complete candidates')
    old=[]
    for directory in read(ROOT/'results/derived/training_admission_inventory_all_v2_index_DRAFT.json')['derived_directories']:
        selection=read(Path(directory)/'student_selection.json');admission=read(Path(directory)/'physical_readmission.json')
        if admission['status']!='RE_ADMITTED_FROM_RAW' or not selection['raw_evidence_re_admitted']:raise ValueError('Old v2 pool is not the actual readmitted cohort')
        value,_,_=pool(selection['raw_collection_root'],directory);old.append(value)
    span_root=top/'literal_span_GPT_physical_v1';span,span_candidates,span_registry=pool(span_root)
    span_state=read(span_root/'state.json');enrolled_overlaps=[]
    for cell in span_state['cells']:
        if cell.get('candidate_file'):
            row=read(span_root/cell['candidate_file']);span_candidates[row['candidate_id']]=row
    for record in new['records']:
        if record['method']!='T3':continue
        matches={}
        for identifier,candidate in span_candidates.items():
            context={'visible_contract':candidate['visible_contract']};cid,_=circuit_id(span_registry,context)
            original=originals(span_registry,candidate);key=(cid,program(candidate['base_source'],original));end=program(candidate['candidate_source'],original)
            if key==record['_key'] and end in record['_pair'][1]:matches[identifier]='chosen_AST' if end==record['_chosen'] else 'rejected_AST'
        enrolled_overlaps.append({'initial_state_id':record['initial_state_id'],'T0_candidate_ids':record['candidate_ids'],'span_enrolled_same_context_terminal_ASTs':matches})
    raw=ROOT/'runs/train_proposals/matched_t0_planning_context_v1';matrix=read(raw/'matrix.json');state=read(current/'state.json');lookup={(v['initial_state_id'],v['seed']):v for v in state['cells']}
    raw_completion=read(raw/'completion.json')
    if len(matrix)!=96 or len(lookup)!=96 or raw_completion['returned_attempts']!=96 or raw_completion['remaining_not_run']!=0:raise ValueError('Retain original96 complete slots')
    attempts=[];missed=[];physical_costs=[]
    for row in matrix:
        cell=lookup[(row['initial_state_id'],row['seed'])];path=Path(row['attempt_path']);attempt=read(path);response=read(path.parent/'response.json')
        if attempt.get('usage')!=response.get('usage'):raise ValueError('Actual sampler usage differs from raw response')
        if row['status'] not in ['NOT_RUN','DISPATCHED'] and (cell['status']=='NOT_RUN' or cell['status'].startswith('ORIGINAL_NOT_RUN')):missed.append((row['initial_state_id'],row['seed']))
        attempts.append({k:attempt.get(k) for k in ['initial_state_id','seed','status','inference_id','usage','model','error','started_at_utc','ended_at_utc']}|
            {'raw_attempt_path':str(path),'consumer_status':cell['status']})
        if cell.get('candidate_file'):
            for point in cell.get('points',[]):
                cost=current/Path(cell['candidate_file']).parent/'points'/point['configuration_id']/'actual_cost.json'
                physical_costs.append({'initial_state_id':cell['initial_state_id'],'seed':cell['seed'],'configuration_id':point['configuration_id'],
                    'point_status':point['status'],'actual_cost':read(cost) if cost.exists() else None})
    old_pairs=union(old,'pairs');old_sft=union(old,'SFT');span_pairs=span['pairs'];increment=new['pairs']-old_pairs-span_pairs
    def clean(record):return {k:v for k,v in record.items() if not k.startswith('_')}
    report={'status':'ACTUAL_MATCHED_T0_CURRENT_GATE_FULL_AST_INCREMENT_AUDIT','at_utc':datetime.now(timezone.utc).isoformat(),
        'new_current_Store_readmitted_candidates':len(admitted),'original96_returned_status_counts':dict(Counter(r['status'] for r in matrix)),
        'no_late_scan_omission':{'exact_raw_and_consumer_slots':96,'returned_but_consumer_NOT_RUN':missed,'known_executable_raw':10,
            'admitted_complete_domain_candidates':10,'actual_point_status_counts':terminal['point_status_counts']},
        'old_all_v2':{'SFT_contexts':len(old_sft),'DPO_pairs':len(old_pairs),'DPO_contexts':len(union(old,'pair_contexts'))},
        'T0_existing_student_rows':dict(new['method_rows']),'T0_matched_unique_DPO_pairs':len(new['pairs']),
        'T0_pairs_already_in_old_all_v2':len(new['pairs']&old_pairs),'T0_pairs_already_in_actual_span_labels':len(new['pairs']&span_pairs),
        'T0_actual_increment':{'SFT_contexts':len(new['SFT']-old_sft-span['SFT']),'DPO_pairs':len(increment),
            'DPO_contexts':len({p[0] for p in increment}-union(old,'pair_contexts')-span['pair_contexts'])},
        'union_old_all_v2_plus_completed_T0':{'SFT_contexts':len(old_sft|new['SFT']),'DPO_pairs':len(old_pairs|new['pairs']),
            'DPO_contexts':len(union(old,'pair_contexts')|new['pair_contexts']),
            'unique_initial_full_ASTs':len(union(old,'initial_ASTs')|new['initial_ASTs']),
            'unique_selected_terminal_full_ASTs':len(union(old,'terminal_ASTs')|new['terminal_ASTs'])},
        'T0_selected_pair_records':[clean(r)|{'already_in_old_all_v2':r['_pair'] in old_pairs,'already_in_actual_span_labels':r['_pair'] in span_pairs} for r in new['records'] if r['method']=='T3'],
        'Point_Family_opposite_pairs_in_T0':sum(any((b,a) in v['T4'] for a,b in v['T3']) for v in new['orientations'].values()),
        'span_observation':{'consumer_status':span_state['status'],'completion_exists':(span_root/'completion.json').exists(),'existing_student_rows':dict(span['method_rows']),
            'source_overlap_is_not_duplicate_label':enrolled_overlaps,'unfinished_span_labels_not_imputed':True},
        'all96_actual_attempt_usage_including81failures':attempts,'all90_actual_physical_cost_records':physical_costs,
        'missing_actual_usage_attempts':sum(not v['usage'] for v in attempts),
        'GPU_OOM_infrastructure_unknown_attempts':sum('OutOfMemoryError' in (v.get('error') or '') for v in attempts),
        'raw_failure_classification':'Original matrix failure statuses retained; GPU OOM is infrastructure unknown, never a policy failure or training negative.',
        'raw_completion':raw_completion,'physical_completion':terminal,
        'identity':'Same existing inventory definition: circuit + both full initial module ASTs, unordered pair of both actual terminal full module ASTs. Literals/names/docstrings retained; invalid Python uses exact text. Physical contract/domain additionally binds preference comparisons.',
        'new_labels_derived':False,'old_rows_changed':False,'new_model_calls':0,'new_EDA_calls':0,'formal_trained_models':0}
    with output.open('x') as stream:json.dump(report,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({k:report[k] for k in ['status','no_late_scan_omission','old_all_v2','T0_existing_student_rows','T0_actual_increment','union_old_all_v2_plus_completed_T0','Point_Family_opposite_pairs_in_T0','missing_actual_usage_attempts']},indent=2))


if __name__=='__main__':main()
