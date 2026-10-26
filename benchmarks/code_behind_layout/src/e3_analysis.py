"""Paired E3 hidden coverage with explicit incomplete matrix denominators."""
from collections import Counter, defaultdict
from statistics import mean

from src.e1_analysis import paired_cluster_effect

METHODS = ('A', 'R', 'B', 'C')


def analyze(manifest, episodes, replicates=2000, seed=20261019):
    tasks = {row['task_id']: row for row in manifest['tasks']}
    trials = manifest['trials']
    if len(tasks) != 24 or set(manifest['methods']) != set(METHODS) or trials != 5:
        raise ValueError('The declared main E3 matrix is24tasks by4methods by5trials')
    records = {}
    for row in episodes:
        if row.get('policy_variant', 'GPT') != 'GPT':
            raise ValueError('Local trained-model episodes cannot be pooled into the GPT A/R/B/C contrast')
        if row.get('selector_variant', 'main') != 'main' or row.get('fidelity_policy', 'F0_actual_full_each_selected_configuration') != 'F0_actual_full_each_selected_configuration':
            raise ValueError('Signal/fidelity ablations cannot be pooled into the main GPT comparison')
        ident, method, trial = row['task_id'], row['method'], str(row['trial_id'])
        key = ident, method, trial
        if ident not in tasks or method not in METHODS or trial not in {'1', '2', '3', '4', '5'}:
            raise ValueError('Episode outside the frozen E3 matrix')
        if key in records:
            raise ValueError('Duplicate E3 trial; a repeat cannot increase independent sample size')
        for name in ('source_group', 'merged_source_group'):
            if row[name] != tasks[ident][name]:
                raise ValueError('Episode ancestry differs from the declared task')
        total, passed, unknown = row['hidden_domain_size'], row['hidden_S2_verified'], row['hidden_incomplete']
        if (total != 16 or any(type(v) is not int for v in (passed, unknown))
                or not 0 <= passed <= 16-unknown <= 16):
            raise ValueError('Hidden observations must retain the actual16-point denominator')
        records[key] = row
    methods = {}
    for method in METHODS:
        found = [r for (task, name, trial), r in records.items() if name == method]
        missing = len(tasks)*trials-len(found)
        passes = sum(r['hidden_S2_verified'] for r in found)
        unknown = sum(r['hidden_incomplete'] for r in found)+16*missing
        denominator = len(tasks)*trials*16
        methods[method] = {'declared_episodes': len(tasks)*trials, 'recorded_episodes': len(found),
            'NOT_RUN_episodes': missing, 'declared_hidden_configurations': denominator,
            'verified_hidden_S2': passes, 'unknown_or_NOT_RUN_configurations': unknown,
            'full_matrix_coverage_identification_bounds': [passes/denominator, (passes+unknown)/denominator],
            'hidden_S2_coverage': passes/denominator if unknown == 0 else None,
            'statuses': dict(Counter(r['status'] for r in found)),
            'regression_status': 'PENDING_BASELINE_JOIN' if any(r.get('baseline_regression_status') != 'COMPLETE'
                for r in found) or missing else 'AVAILABLE_FOR_SEPARATE_BASELINE_ANALYSIS'}
    paired = []
    for ident, task in tasks.items():
        values = {method: [records.get((ident, method, str(trial))) for trial in range(1, trials+1)]
                  for method in METHODS}
        if not all(row is not None and row['hidden_incomplete'] == 0 for rows in values.values() for row in rows):
            continue
        paired.append({'task_id': ident, 'source_group': task['source_group'],
            'merged_source_group': task['merged_source_group'],
            'method_S2_rates': {method: mean(row['hidden_S2_verified']/16 for row in rows)
                                for method, rows in values.items()}})
    complete = len(paired) == len(tasks)
    effects = []
    if complete:
        for left, right in (('C', 'R'), ('C', 'B')):
            for group in ('source_group', 'merged_source_group'):
                effects.append(paired_cluster_effect(paired, left, right, group, replicates, seed))
    distributions = defaultdict(list)
    for row in paired:
        distributions[row['source_group']].append(row)
    return {'scope': 'Formal E3 fixed matrix hidden S2 coverage; point/trial counts are not independent circuits',
        'declared_episodes': 480, 'recorded_episodes': len(records), 'methods': methods,
        'fully_paired_tasks': len(paired), 'primary_analysis_complete': complete,
        'primary_contrasts': effects, 'per_source_group': dict(distributions),
        'missing_policy': 'NOT_RUN and incomplete points remain unknown. Identification bounds are not confidence intervals.',
        'uncertainty_unit': 'Task-paired five-trial means with whole source-group bootstrap; primary8 and merged7 groups'}
