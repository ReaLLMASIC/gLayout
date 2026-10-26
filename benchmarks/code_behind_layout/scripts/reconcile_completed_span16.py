"""Independent final span16 accounting; never rewrites its raw/state/labels."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def read(path):return json.loads(Path(path).read_text())


def reconciled_cell_status(raw,cell):
    """Only the demonstrated returned-oversize accounting defect is corrected."""
    if (raw['status']=='STUDENT_BUDGET_REJECTED_BEFORE_PHYSICS'
            and cell['status'] in ('NOT_RUN','ORIGINAL_NOT_RUN_PROPOSAL_WINDOW_ENDED')):
        if cell.get('candidate_file') or cell.get('points'):raise ValueError('Rejected output has physical evidence; preserve as inconsistency')
        return raw['status']
    return cell['status']


def final_report(physical_root,proposal_root):
    physical_root=Path(physical_root).resolve();proposal_root=Path(proposal_root).resolve()
    for p in [physical_root,proposal_root]:p.relative_to(ROOT/'runs')
    # No report or temporary output is created before both actual terminal records exist.
    original_completion=read(physical_root/'completion.json');proposal_completion=read(proposal_root/'completion.json')
    state=read(physical_root/'state.json');acceptance=read(physical_root/'acceptance.json')
    if state.get('coordinator_pid') is not None or state['status'] in ('RUNNING','WAITING_FOR_FROZEN_PROPOSALS'):
        raise ValueError('The physical consumer has not actually ended')
    if original_completion['status']!=state['status']:raise ValueError('Original state/completion terminal statuses differ')
    if proposal_completion.get('returned_attempts')!=16 or proposal_completion.get('not_run')!=0:
        raise ValueError('This reconciliation is specific to the observed sixteen returned attempts')
    matrix=read(proposal_root/'matrix.json');plan=read(proposal_root/'collection.json')
    expected=[(c['initial_state_id'],trial) for c in plan['contexts'] for trial in range(1,9)]
    if len(expected)!=16 or [(c['initial_state_id'],c['trial_id']) for c in matrix]!=expected:
        raise ValueError('Keep the original fixed sixteen proposal slots')
    cells={(c['initial_state_id'],c['trial_id']):c for c in state['cells']}
    if set(cells)!=set(expected):raise ValueError('Physical cells differ from original proposal slots')
    records=[];costs=[];enrolled=[];eligible=[];corrections=[]
    for raw in matrix:
        key=raw['initial_state_id'],raw['trial_id'];cell=cells[key]
        work=proposal_root/key[0]/('trial_'+str(key[1]));attempt=read(work/'attempt.json');response=read(work/'response.json')
        if attempt.get('usage')!=response.get('usage') or attempt.get('inference_id')!=response.get('inference_id'):
            raise ValueError('Actual raw model usage/identity binding differs')
        status=reconciled_cell_status(raw,cell)
        entry={'initial_state_id':key[0],'trial_id':key[1],'original_raw_status':raw['status'],
            'original_consumer_status':cell['status'],'reconciled_status':status,
            'inference_id':attempt.get('inference_id'),'actual_model_usage':attempt.get('usage'),
            'student_budget':attempt.get('student_budget'),'points':cell.get('points',[])}
        if status!=cell['status']:corrections.append({k:entry[k] for k in ['initial_state_id','trial_id','original_consumer_status','reconciled_status']})
        if raw['status']=='COMPILED_STUDENT_FIT_PROPOSAL_ONLY':eligible.append(key)
        if cell.get('candidate_file'):
            row=read(physical_root/cell['candidate_file']);compiled=read(work/'compiled.json')
            if row['candidate_source']!=compiled['candidate_source'] or row['candidate_patch']!=compiled['patch']:
                raise ValueError('A physical candidate differs from its actual compiled proposal')
            entry['candidate_id']=row['candidate_id'];enrolled.append((key,row))
            for point in cell.get('points',[]):
                cost=physical_root/Path(cell['candidate_file']).parent/'points'/point['configuration_id']/'actual_cost.json'
                costs.append({'candidate_id':row['candidate_id'],'configuration_id':point['configuration_id'],
                    'point_status':point['status'],'actual_cost':read(cost) if cost.exists() else None})
        records.append(entry)
    if set(eligible)!={key for key,_ in enrolled} or len(enrolled)!=11:
        raise ValueError('The demonstrated exact eleven eligible/enrolled IDs no longer match')
    from src.training import TrustedPhysicalStore,admit_candidates
    registry=read(physical_root/'effective_registry.json');store=TrustedPhysicalStore(ROOT,registry);admitted=[];rejections=[]
    for key,row in enrolled:
        cell=cells[key]
        if not cell.get('points') or any(p['status']!='COMPLETE' for p in cell['points']):continue
        try:admitted.extend(admit_candidates([row],registry,store))
        except (ValueError,OSError,KeyError) as exc:rejections.append({'candidate_id':row['candidate_id'],'error':str(exc)})
    actual_datasets={}
    for method in ['T1','T2','T3','T4']:
        path=physical_root/(method+'.jsonl');rows=[json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
        actual_datasets[method]={'existing_file':str(path),'exists':path.exists(),'rows':len(rows),
            'sample_ids':[row.get('raw_sample',row).get('sample_id') for row in rows],
            'initial_state_ids':sorted({row.get('raw_sample',row)['initial_state_id'] for row in rows})}
    def total_usage(field):
        values=[(r['actual_model_usage'] or {}).get('public_cli_usage',{}).get(field) for r in records]
        return {'known_sum':sum(v for v in values if isinstance(v,(int,float))), 'missing_attempts':sum(v is None for v in values)}
    return {'status':'INDEPENDENT_FINAL_FUNNEL_RECONCILIATION','at_utc':datetime.now(timezone.utc).isoformat(),
        'original_physical_completion':original_completion,'original_proposal_completion':proposal_completion,
        'original_declared_proposals':16,'returned_raw_proposals':len(records),'original_raw_status_counts':dict(Counter(r['original_raw_status'] for r in records)),
        'reconciled_consumer_status_counts':dict(Counter(r['reconciled_status'] for r in records)),
        'accounting_corrections_only':corrections,'all_eleven_eligible_candidates_enrolled_with_identical_source_and_patch':True,
        'actual_physical_point_status_counts':dict(Counter(p['status'] for c in state['cells'] for p in c.get('points',[]))),
        'all_sixteen_attempts_with_original_usage':records,'actual_physical_point_costs':costs,
        'public_provider_usage_sum':{k:total_usage(k) for k in ['input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens']},
        'provider_usage_scope':'Sum each actual attempt final public_cli_usage once; all raw events retained per attempt. No monetary billing or native provider-context claim is inferred.',
        'current_Store_readmission':{'complete_domain_candidates_read':len(admitted)+len(rejections),'admitted_candidate_ids':[r['candidate_id'] for r in admitted],'quarantines':rejections},
        'existing_original_datasets_only':actual_datasets,'original_student_selection':read(physical_root/'student_selection.json') if (physical_root/'student_selection.json').exists() else None,
        'new_training_labels_generated':False,'old_state_raw_completion_labels_modified':False,'new_model_calls':0,'new_EDA_calls':0,
        'counting':'Corrected accounting does not add a candidate/context, reclassify a physical failure, regenerate a label, or repair the original frozen loop. Existing usable samples remain subject to cross-cohort dedup.'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['physical-root','proposal-root','output']:p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();output=a.output.resolve();output.relative_to(ROOT/'results/derived')
    if output.exists():raise ValueError('Use a new independent reconciliation file')
    report=final_report(a.physical_root,a.proposal_root)
    with output.open('x') as stream:json.dump(report,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({k:report[k] for k in ['status','accounting_corrections_only','actual_physical_point_status_counts','public_provider_usage_sum','existing_original_datasets_only']},indent=2))
