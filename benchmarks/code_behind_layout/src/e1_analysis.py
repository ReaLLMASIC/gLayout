"""Task-paired E1 summaries with source-group uncertainty and bounded search time."""
from collections import defaultdict
import math
import random
from statistics import mean

METHODS=('G0','G1','G2')
TIERS=('S0','S1','S2')
SEARCH_TERMINAL={'COMPLETED','BUDGET_EXHAUSTED','MODEL_FAILURE'}


def validate_episode(row):
    if row['method'] not in METHODS or row['stratum'] not in ('reuse','composition'):
        raise ValueError('Unknown controlled E1 method/stratum')
    if not row['source_group'] or not row['merged_source_group']:
        raise ValueError('Actual source ancestry and merge sensitivity groups are required')
    budget=row['search_budget_seconds']
    if not isinstance(budget,(int,float)) or not math.isfinite(budget) or budget<=0:
        raise ValueError('A positive frozen search budget is required')
    times=row['first_verified_times_seconds']
    if set(times)!=set(TIERS):raise ValueError('Every tier must retain a first-time value or explicit null')
    for value in times.values():
        if value is not None and (not math.isfinite(value) or not 0<=value<=budget):
            raise ValueError('Only actual verification events within the search deadline count')
    for low,high in zip(TIERS,TIERS[1:]):
        if times[high] is not None and (times[low] is None or times[high]<times[low]):
            raise ValueError('Verified tier times must retain prerequisite evidence')
    hidden=row['hidden']
    if not 0<=hidden['S2_passed']<=hidden['known']<=hidden['declared'] or hidden['declared']!=16:
        raise ValueError('Hidden results must retain the declared sixteen-point denominator')
    if not isinstance(row['final_anchor']['complete'],bool):raise ValueError('Final-source evaluation completeness must be explicit')
    if row['final_anchor']['complete']:
        if any(type(row['final_anchor'][tier]) is not bool for tier in TIERS):
            raise ValueError('Final-source tiers must be actual booleans when complete')
        if any(row['final_anchor'][high] and not row['final_anchor'][low] for low,high in zip(TIERS,TIERS[1:])):
            raise ValueError('Final-source tiers must preserve prerequisites')
    return row


def _quantile(values,fraction):
    values=sorted(values);index=(len(values)-1)*fraction;low=int(index);high=min(low+1,len(values)-1)
    return values[low]+(values[high]-values[low])*(index-low)


def paired_cluster_effect(tasks,left,right,group_key,replicates=2000,seed=20261018):
    """Resample entire source groups; trial/configuration counts are not circuits."""
    if not tasks:return None
    grouped=defaultdict(list)
    for row in tasks:grouped[row[group_key]].append(row['method_S2_rates'][left]-row['method_S2_rates'][right])
    effect=mean(value for values in grouped.values() for value in values)
    interval=None
    if len(grouped)>=2:
        rng=random.Random(seed);names=sorted(grouped);draws=[]
        for _ in range(replicates):
            sampled=[rng.choice(names) for _ in names]
            draws.append(mean(value for name in sampled for value in grouped[name]))
        interval=[_quantile(draws,.025),_quantile(draws,.975)]
    return {'contrast':left+' - '+right,'task_mean_difference':effect,'source_groups':len(grouped),
        'tasks':len(tasks),'cluster_percentile_95_CI':interval,'bootstrap_replicates':replicates if interval else 0,
        'bootstrap_seed':seed,'grouping':group_key}


def analyze_episodes(rows,expected_trials=5,replicates=2000,seed=20261018):
    rows=[validate_episode(row) for row in rows];seen=set();by_task=defaultdict(list)
    if len({row['search_budget_seconds'] for row in rows})>1:
        raise ValueError('Controlled methods must share the same frozen search budget')
    for row in rows:
        key=(row['task_id'],row['method'],row['trial_id'])
        if key in seen:raise ValueError('An episode cannot appear twice in the statistical input')
        seen.add(key);by_task[row['task_id']].append(row)
    task_rows=[];methods={}
    for name in METHODS:
        all_method=[row for row in rows if row['method']==name]
        usable=[row for row in all_method if row['status'] in SEARCH_TERMINAL]
        budgets={row['search_budget_seconds'] for row in all_method}
        if len(budgets)>1:raise ValueError('Do not pool different search budgets as one controlled comparison')
        budget=next(iter(budgets),None)
        tier_results={}
        for tier in TIERS:
            times=[row['first_verified_times_seconds'][tier] for row in usable]
            all_verified=sum(row['first_verified_times_seconds'][tier] is not None for row in all_method)
            unresolved_without_verification=sum(row['status'] not in SEARCH_TERMINAL and row['first_verified_times_seconds'][tier] is None for row in all_method)
            grid=sorted({0,budget,*[t for t in times if t is not None]}) if budget else []
            tier_results[tier]={'searches':len(times),'verified_within_budget':sum(t is not None for t in times),
                'success_rate':mean(t is not None for t in times) if times else None,
                'restricted_mean_time_seconds':mean(t if t is not None else budget for t in times) if times else None,
                'full_declared_denominator':len(all_method),'observed_verifications_all_statuses':all_verified,
                'unresolved_without_verification':unresolved_without_verification,
                'full_matrix_success_rate_identification_bounds':[all_verified/len(all_method),
                    (all_verified+unresolved_without_verification)/len(all_method)] if all_method else None,
                'success_curve':[{'seconds':t,'probability':mean(v is not None and v<=t for v in times)} for t in grid] if times else []}
        final=[row for row in usable if row['final_anchor']['complete']]
        methods[name]={'recorded_episodes':len(all_method),'completed_searches':len(usable),
            'unresolved_or_not_run':len(all_method)-len(usable),'search_budget_seconds':budget,
            'tiers':tier_results,'final_anchor_complete':len(final),
            'final_anchor_S2_rate':mean(row['final_anchor']['S2'] for row in final) if final else None,
            'hidden_complete_episodes':sum(row['hidden']['known']==16 for row in usable),
            'hidden_S2_coverage':mean(row['hidden']['S2_passed']/16 for row in usable) if usable and all(row['hidden']['known']==16 for row in usable) else None}
    for task_id,items in sorted(by_task.items()):
        for key in ('stratum','source_group','merged_source_group'):
            if len({row[key] for row in items})!=1:raise ValueError('Task ancestry/stratum cannot depend on method or trial')
        groups={name:[r for r in items if r['method']==name and r['status'] in SEARCH_TERMINAL] for name in METHODS}
        if any(len(values)>expected_trials for values in groups.values()):raise ValueError('More trials than the frozen analysis plan')
        if all(len(values)==expected_trials for values in groups.values()):
            task_rows.append({'task_id':task_id,**{key:items[0][key] for key in ('stratum','source_group','merged_source_group')},
                'method_S2_rates':{name:mean(row['first_verified_times_seconds']['S2'] is not None for row in values) for name,values in groups.items()}})
    contrasts={}
    for stratum in ('reuse','composition'):
        complete_tasks=[row for row in task_rows if row['stratum']==stratum]
        declared_tasks=[task for task,values in by_task.items() if values[0]['stratum']==stratum]
        ready=bool(declared_tasks) and len(complete_tasks)==len(declared_tasks)
        contrasts[stratum]={'declared_tasks_in_input':len(declared_tasks),'fully_paired_tasks':len(complete_tasks),
            'primary_analysis_complete_for_input':ready,'effects':[]}
        if ready:
            for left,right in (('G1','G0'),('G2','G1'),('G2','G0')):
                for group in ('source_group','merged_source_group'):
                    contrasts[stratum]['effects'].append(paired_cluster_effect(complete_tasks,left,right,group,replicates,seed))
    return {'scope':'Within-budget trusted feedback after complete-call host inspection; not internal tier-stage times. Final frozen-source anchor and hidden transfer reported separately',
        'expected_trials_per_task_method':expected_trials,'episode_records':len(rows),'task_records':len(by_task),
        'methods':methods,'strata':contrasts,'complete_paired_tasks':task_rows,
        'unresolved_policy':'NOT_RUN and infrastructure/incomplete episodes remain unresolved; do not convert to candidate failures. Full-matrix rate bounds retain every declared row, count already observed verification, and allow unverified unresolved rows either outcome. Conditional completed-search rates are separately labelled.',
        'uncertainty_unit':'Task-paired effects with whole source-group bootstrap; configuration and inference repeats are not independent circuits.'}
