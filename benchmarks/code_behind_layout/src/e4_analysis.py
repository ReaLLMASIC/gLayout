"""Paired E4 inference means with distinct source and actual training-seed units."""
from collections import Counter,defaultdict
import random
from statistics import mean,variance

from src.e1_analysis import _quantile

VARIANTS=('T0','T1','T2','T3','T4')
SLOTS=(41,73,109)
TRIALS=('1','2','3')
PRIMARY=(('T4','T3'),('T2','T1'))


def validate_plan(manifest):
    tasks={row['task_id']:row for row in manifest['tasks']}
    if (len(tasks)!=24 or len(manifest['tasks'])!=24 or len(manifest['variants'])!=5 or set(manifest['variants'])!=set(VARIANTS)
        or manifest['evaluation_seed_slots']!=list(SLOTS) or manifest['inference_trials']!=3
        or manifest['verification_method'] not in ('A','R','B','C')):
        raise ValueError('E4 declares24tasks by5variants by3matched slots by3inference trials')
    if len({t['source_group'] for t in tasks.values()})!=8 or len({t['merged_source_group'] for t in tasks.values()})!=7:
        raise ValueError('The declared source ancestry must retain primary8 and merged7 groups')
    closure=defaultdict(set)
    for task in tasks.values():
        if any(not isinstance(task[key],str) or not task[key] for key in ('source_group','merged_source_group')):
            raise ValueError('Each task needs its declared source ancestry')
        closure[task['source_group']].add(task['merged_source_group'])
    if any(len(values)!=1 for values in closure.values()):raise ValueError('Merged sensitivity cannot split an original source group')
    return tasks


def hidden_counts(row):
    keys=('hidden_domain_size','hidden_S2_verified','hidden_incomplete')
    if row.get('hidden_results_exposed_to_policy') is True:raise ValueError('Hidden feedback was exposed to a tested policy')
    if not any(key in row for key in keys):return 0,16
    if not all(key in row for key in keys):raise ValueError('Partial hidden summary cannot establish its denominator')
    total,passed,unknown=(row[key] for key in keys)
    if (total!=16 or any(type(v) is not int for v in (passed,unknown)) or not 0<=passed<=16-unknown<=16):
        raise ValueError('Hidden observations must retain all16 declared points')
    return passed,unknown


def group_bootstrap(task_seed_effects,tasks,group_key,replicates,seed):
    """Cross source-cluster and seed resampling; one common seed draw for pairs.

    Three inference trials were averaged first. Conditional source-only and
    seed-only sensitivities are not additive ANOVA variance components.
    """
    grouped=defaultdict(list)
    for task in task_seed_effects:grouped[tasks[task][group_key]].append(task)
    names=sorted(grouped);ids=sorted(task_seed_effects);rng=random.Random(seed)
    source_draws=[];seed_draws=[];joint_draws=[]
    for _ in range(replicates):
        selected_tasks=[task for group in [rng.choice(names) for _ in names] for task in grouped[group]]
        selected_seeds=[rng.choice(SLOTS) for _ in SLOTS]
        source_draws.append(mean(task_seed_effects[task][slot] for task in selected_tasks for slot in SLOTS))
        seed_draws.append(mean(task_seed_effects[task][slot] for task in ids for slot in selected_seeds))
        joint_draws.append(mean(task_seed_effects[task][slot] for task in selected_tasks for slot in selected_seeds))
    return {'grouping':group_key,'source_groups':len(names),'tasks':len(ids),'actual_training_seeds':list(SLOTS),
        'task_mean_difference':mean(value for slots in task_seed_effects.values() for value in slots.values()),
        'joint_source_and_training_seed_percentile_95_CI':[_quantile(joint_draws,.025),_quantile(joint_draws,.975)],
        'conditional_source_only_bootstrap_variance':variance(source_draws),
        'conditional_training_seed_only_bootstrap_variance':variance(seed_draws),
        'joint_bootstrap_variance':variance(joint_draws),'bootstrap_replicates':replicates,'bootstrap_seed':seed,
        'sampling':'Whole source groups and one common3-slot seed resample shared by both paired methods and every task; trial means fixed',
        'variance_note':'Conditional sensitivities; interaction remains in the joint distribution. These are not additive variance components.'}


def regression_summary(rows,declared):
    passes=regressions=unknown_selected=unknown_original=0;joined=0
    for row in rows:
        join=row.get('regression_join')
        if join is None:unknown_original+=16;continue
        if (join.get('task_id')!=row['task_id'] or str(join.get('trial_id'))!=str(row['trial_id'])
            or join.get('method')!=row['method']):raise ValueError('Original baseline join belongs to another episode')
        group=join['groups']['hidden']
        values=[group[k] for k in ['original_verified_S2','verified_regressions','selected_unknown_on_original_passes','original_unknown']]
        p,r,s,u=values
        if (group['declared_configurations']!=16 or any(type(v) is not int or v<0 for v in values)
            or r+s>p or p+u>16):raise ValueError('Regression summary contradicts its16-point original denominator')
        passes+=p;regressions+=r;unknown_selected+=s;unknown_original+=u;joined+=1
    unknown_original+=(declared-len(rows))*16
    denominator=passes+unknown_original;complete=joined==declared and not unknown_original and not unknown_selected
    return {'joined_episodes':joined,'unavailable_joins':declared-joined,'original_verified_S2':passes,
        'verified_regressions':regressions,'unknown_original_configurations':unknown_original,
        'selected_unknown_on_original_passes':unknown_selected,
        'hidden_regression_rate':regressions/passes if complete and passes else None,
        'status':'COMPLETE' if complete else 'UNAVAILABLE_OR_INCOMPLETE_ORIGINAL_BASELINE_JOIN',
        'full_matrix_regression_identification_bounds_given_at_least_one_original_pass':
            [regressions/denominator,(regressions+unknown_selected+unknown_original)/denominator] if denominator else None,
        'bounds_are_confidence_intervals':False,'zero_original_pass_denominator':'undefined; never substituted with zero'}


def method_summary(records,task_ids,variant):
    declared=len(task_ids)*9;rows=[row for (task,name,slot,trial),row in records.items() if task in task_ids and name==variant]
    counts=[hidden_counts(row) for row in rows];passed=sum(p for p,_ in counts)
    unknown=sum(u for _,u in counts)+(declared-len(rows))*16;denominator=declared*16
    slot_means={str(slot):mean(hidden_counts(row)[0]/16 for row in rows if row['evaluation_seed_slot']==slot)
                if len([r for r in rows if r['evaluation_seed_slot']==slot])==len(task_ids)*3
                and all(hidden_counts(r)[1]==0 for r in rows if r['evaluation_seed_slot']==slot) else None for slot in SLOTS}
    return {'declared_episodes':declared,'recorded_episodes':len(rows),'NOT_RUN_episodes':declared-len(rows),
        'declared_hidden_configuration_trials':denominator,'verified_hidden_S2':passed,'unknown_or_NOT_RUN_configurations':unknown,
        'coverage_identification_bounds':[passed/denominator,(passed+unknown)/denominator],
        'hidden_S2_coverage':passed/denominator if unknown==0 else None,'statuses':dict(Counter(row['status'] for row in rows)),
        'actual_model_count':1 if variant=='T0' else 3,'actual_training_seeds':[] if variant=='T0' else list(SLOTS),
        'matched_evaluation_slot_means':slot_means,
        'descriptive_actual_training_seed_mean_variance':variance(slot_means.values()) if variant!='T0' and all(v is not None for v in slot_means.values()) else None,
        'T0_slot_note':'One common backbone; slots are matched evaluation scheduling, not independent trained models' if variant=='T0' else None,
        'original_hidden_regression':regression_summary(rows,declared)}


def validation_plateaus(models):
    if models is None:return {'status':'UNAVAILABLE','models':[]}
    if models.get('status')!='FROZEN_E4_METHODS' or models.get('formal_training_runs')!=12:
        raise ValueError('Validation selection provenance requires the actual E4 method freeze')
    rows=[]
    for variant in VARIANTS[1:]:
        for slot in SLOTS:
            selected=models['variants'][variant]['seeds'][str(slot)];evaluations=selected.get('checkpoint_evaluations',[])
            scores=[item['mean_task_S2_fraction'] for item in evaluations]
            rows.append({'variant':variant,'training_seed':slot,'checkpoints':len(scores),
                'score_range':[min(scores),max(scores)] if scores else None,
                'selection_plateau':len(scores)>1 and min(scores)==max(scores) if scores else None,
                'selected_checkpoint':selected['selected_checkpoint'],
                'status':'MULTIPLE_CHECKPOINTS' if len(scores)>1 else 'SINGLE_CHECKPOINT_NO_SELECTION_COMPARISON' if scores else 'UNAVAILABLE'})
    return {'status':'READ_FROM_FROZEN_VALIDATION_PROVENANCE','models':rows,'selection_rule_changed':False}


def task_tags(task,key):
    if key=='topology':
        tags=task.get('topology_families') or ([task['topology_family']] if task.get('topology_family') else [])
        if not isinstance(tags,list) or any(not isinstance(t,str) or not t for t in tags):raise ValueError('Topology tags must be explicit frozen names')
        return tags or ['unknown']
    if 'ood_status' in task:
        if task['ood_status'] not in ('in_domain','out_of_domain','unknown'):raise ValueError('Unknown frozen OOD status')
        return [task['ood_status']]
    flags=[task[k] for k in ('ood','is_ood') if k in task]
    if flags:
        if any(type(v) is not bool for v in flags) or len(set(flags))!=1:raise ValueError('Conflicting frozen OOD flags')
        return ['out_of_domain' if flags[0] else 'in_domain']
    return ['unknown']


def analyze(manifest,episodes,models_manifest=None,replicates=2000,seed=20261019):
    tasks=validate_plan(manifest)
    if type(replicates) is not int or replicates<2:raise ValueError('At least two deterministic bootstrap replicates are required')
    records={}
    for row in episodes:
        variant=row['policy_variant'];slot=row['evaluation_seed_slot'];trial=str(row['trial_id']);task=row['task_id']
        if (task not in tasks or variant not in VARIANTS or type(slot) is not int or slot not in SLOTS or trial not in TRIALS
            or row['method']!=manifest['verification_method']):raise ValueError('Episode outside the predeclared E4 policy matrix')
        if row.get('training_seed')!=(None if variant=='T0' else slot):raise ValueError('T0 slots are not trained models; other variants require their actual matching seed')
        if any(row[k]!=tasks[task][k] for k in ('source_group','merged_source_group')):raise ValueError('Episode source ancestry differs from the fixed task')
        key=task,variant,slot,trial
        if key in records:raise ValueError('Duplicate E4 episode cannot increase sample size')
        hidden_counts(row);records[key]=row
    methods={variant:method_summary(records,set(tasks),variant) for variant in VARIANTS};effects=[]
    for left,right in PRIMARY:
        task_seed_effects={};trial_variances=[]
        for task in tasks:
            keys=[(task,variant,slot,trial) for variant in (left,right) for slot in SLOTS for trial in TRIALS]
            if not all(key in records and hidden_counts(records[key])[1]==0 for key in keys):continue
            task_seed_effects[task]={}
            for slot in SLOTS:
                differences=[(hidden_counts(records[task,left,slot,trial])[0]-hidden_counts(records[task,right,slot,trial])[0])/16 for trial in TRIALS]
                task_seed_effects[task][slot]=mean(differences);trial_variances.append(variance(differences))
        complete=len(task_seed_effects)==24
        lb,ub=methods[left]['coverage_identification_bounds'],methods[right]['coverage_identification_bounds']
        effect={'contrast':left+' - '+right,'fully_paired_tasks':len(task_seed_effects),'primary_paired_complete':complete,
            'effect_identification_bounds':[lb[0]-ub[1],lb[1]-ub[0]],'bounds_are_confidence_intervals':False,
            'task_seed_trial_mean_differences':{task:{str(s):v for s,v in slots.items()} for task,slots in task_seed_effects.items()},
            'descriptive_between_training_seed_mean_variance':variance(mean(values[slot] for values in task_seed_effects.values()) for slot in SLOTS) if complete else None,
            'descriptive_within_task_seed_paired_inference_trial_variance':mean(trial_variances) if complete else None,
            'hierarchical_bootstrap':[]}
        if complete:
            for group in ('source_group','merged_source_group'):
                effect['hierarchical_bootstrap'].append(group_bootstrap(task_seed_effects,tasks,group,replicates,seed))
        effects.append(effect)
    strata={}
    for kind in ('topology','OOD'):
        groups=defaultdict(set)
        for task,row in tasks.items():
            for tag in task_tags(row,kind):groups[tag].add(task)
        strata[kind]={tag:{'tasks':sorted(ids),'methods':{v:method_summary(records,ids,v) for v in VARIANTS}} for tag,ids in groups.items()}
    return {'scope':'Fixed1080E4matrix; task-paired3inference-trial means, actual training seeds distinct from source groups',
        'declared_episodes':1080,'recorded_episodes':len(records),'NOT_RUN_episodes':1080-len(records),'methods':methods,
        'full_matrix_hidden_complete':all(v['unknown_or_NOT_RUN_configurations']==0 for v in methods.values()),
        'primary_contrasts':effects,'strata':strata,'validation_checkpoint_selection':validation_plateaus(models_manifest),
        'unknown_policy':'Unknown and NOT_RUN retain declared denominators; identification bounds are not confidence intervals. Primary CI requires all24 tasks and all3seeds×3trials for both methods of that contrast.',
        'uncertainty_units':'Source8/merged7 whole clusters and3actual training seeds for primary contrasts; T0 has1backbone and9matched inference trials/task, no training-seed variance.',
        'stratum_note':'Only frozen explicit topology/OOD fields are used; missing flags stay unknown. Multi-topology tags can overlap.'}
