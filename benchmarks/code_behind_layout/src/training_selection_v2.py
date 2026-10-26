"""The sole v2 change: choose an actual earliest trial among equivalent SFT bests.

Physical admission, Point/Family feasibility, tolerances, meaningful baseline
improvement and all DPO preferences retain their original definitions.
"""
import copy

VERSION='equivalent_best_earliest_actual_trial_v2'


def make_rule(parent,sampling):
    if parent.get('status')!='frozen' or not parent.get('version'):
        raise ValueError('Start from the real frozen parent label rule')
    if 'sft_selection' in parent:raise ValueError('This change must start from the original unique-best v1 rule')
    mode=sampling['mode']
    if mode in ('train_collection_source_gpt','train_collection_action_gpt'):
        field='trial_id';order=sampling['trials']
    elif mode=='train_collection_rules':field='rule_id';order=sampling['rule_ids']
    elif mode in ('train_collection','train_collection_source'):field='seed';order=sampling['seeds']
    else:raise ValueError('The frozen proposer has no supported actual trial order')
    if len(order)!=8 or len(set(order))!=8:raise ValueError('Retain the eight declared real proposal identifiers')
    return {**copy.deepcopy(parent),'version':parent['version']+'__'+VERSION,
        'parent_rule_version':parent['version'],
        'sft_selection':{'version':VERSION,'actual_trial_field':field,'declared_trial_order':list(order),
            'change_scope':'Only equivalent-best SFT representative selection; original feasibility and comparison thresholds unchanged'}}


def proposal_order(row,rule):
    selection=rule['sft_selection'];value=row.get('proposal_generation',{}).get(selection['actual_trial_field'])
    order=selection['declared_trial_order']
    # Match types as well as values; bool is not an observed integer trial.
    matches=[i for i,item in enumerate(order) if type(item) is type(value) and item==value]
    if len(matches)!=1:raise ValueError('Candidate lacks its actual frozen proposal-trial identity')
    return matches[0]


def build_matched_samples_v2(candidates,rule,legacy=None):
    if legacy is None:from src import training as legacy
    if rule.get('sft_selection',{}).get('version')!=VERSION:
        raise ValueError('Use the explicitly frozen equivalent-best v2 label rule')
    # This produces exactly the original DPO comparisons on the common pool.
    datasets,old_report=legacy.build_matched_samples(candidates,rule)
    datasets['T1']=[];datasets['T2']=[];groups={};choices=[];ambiguous=0
    for row in candidates:groups.setdefault(row['initial_state_id'],[]).append(row)
    for state,all_rows in sorted(groups.items()):
        rows=[];patches=set()
        for row in all_rows:
            if row['candidate_patch'] in patches:continue
            patches.add(row['candidate_patch']);rows.append(row)
        trial_indices=[proposal_order(row,rule) for row in rows]
        if len(set(trial_indices))!=len(trial_indices):raise ValueError('One state cannot contain multiple candidates claiming the same actual trial')
        comparison=legacy.state_label_rule(rows,rule);winners={};state_choices={}
        for method,scope in (('T1','point'),('T2','family')):
            # Intentionally identical to the original method-specific scope.
            eligible=[row for row in rows if row['verified']['anchor']['S2']
                and (scope=='point' or all(item['S1'] for item in row['verified']['family']))
                and legacy.compare_outcomes(row['verified'],row['verified']['baseline'],scope,comparison)==1]
            best=[row for row in eligible if all(other is row or
                legacy.compare_outcomes(row['verified'],other['verified'],scope,comparison)>=0 for other in eligible)]
            if not best:continue
            # Every member is explicitly equivalent to every other member.
            if any(legacy.compare_outcomes(a['verified'],b['verified'],scope,comparison)!=0
                   for i,a in enumerate(best) for b in best[i+1:]):
                raise ValueError('An SFT equivalence set contains a declared preference')
            winner=min(best,key=lambda row:proposal_order(row,rule));winners[method]=winner
            state_choices[method]={'selected_candidate_id':winner['candidate_id'],
                'actual_trial_value':winner['proposal_generation'][rule['sft_selection']['actual_trial_field']],
                'equivalent_best_candidates':[row['candidate_id'] for row in sorted(best,key=lambda row:proposal_order(row,rule))],
                'all_selected_candidates_meaningfully_improve_real_baseline':True,'feasibility_scope':scope}
        if set(winners)=={'T1','T2'}:
            first=rows[0];common={'initial_state_id':state,'parent_lineage':first['parent_lineage'],
                'source_role':'formal_train','origin':first['origin'],'context':legacy.patch_context(first),
                'label_rule_version':rule['version'],'objective_id':first['verified']['anchor']['objective_definition']['id']}
            for method,winner in winners.items():
                datasets[method].append({**common,'sample_id':method+':'+state,'patch':winner['candidate_patch'],
                    'candidate_id':winner['candidate_id'],'trusted_evidence_ids':winner['verified']['tool_log_ids']})
        else:ambiguous+=1
        choices.append({'initial_state_id':state,'paired_SFT_emitted':set(winners)=={'T1','T2'},'methods':state_choices})
    return datasets,{**old_report,'ambiguous_sft_states':ambiguous,
        'label_rule_version':rule['version'],'selection_version':VERSION,
        'v1_ambiguous_sft_states_same_pool':old_report['ambiguous_sft_states'],'SFT_choices':choices,
        'DPO_ties_promoted':False,'feasibility_changed':False,'tolerance_or_minimum_effect_changed':False,
        'samples':{method:len(rows) for method,rows in datasets.items()}}
