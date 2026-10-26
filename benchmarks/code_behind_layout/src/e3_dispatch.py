"""Fixed prospective search matrices for E3 and the matched E4 evaluation."""
import random

PARTS = ('gpt', 'parameter', 'local', 'signals', 'fidelity', 'instance')


def plan(manifest, part):
    if part not in PARTS:
        raise ValueError('Unknown E3 evaluation part')
    if manifest['status'] != 'FROZEN_E3' or manifest['formal_dispatch'] is not True:
        raise ValueError('Formal searches require the independent actual E3 freeze')
    tasks = manifest['task_ids']
    if len(tasks) != 24 or len(set(tasks)) != 24 or manifest['trials'] != 5:
        raise ValueError('The main E3 inventory has24tasks and5trials')
    rng = random.Random(manifest['dispatch_order_seed'])
    jobs = []
    if part == 'gpt':
        blocks = [(task, trial) for task in sorted(tasks) for trial in range(1, 6)]
        rng.shuffle(blocks)
        for task, trial in blocks:
            methods = ['A', 'R', 'B', 'C'];rng.shuffle(methods)
            for method in methods:
                jobs.append(dict(task_id=task, method=method, trial_id=str(trial), policy_variant='GPT',
                    selection_seed=manifest['selection_seeds'][trial-1], evaluation_seed_slot=None))
    elif part == 'parameter':
        selected = manifest['parameter_task_ids']
        if len(selected) < 8 or len(set(selected)) != len(selected) or not set(selected) <= set(tasks):
            raise ValueError('P needs its prospectively declared common subset of at least8tasks')
        blocks = [(task, trial) for task in sorted(selected) for trial in range(1, 6)]
        rng.shuffle(blocks)
        for task, trial in blocks:
            strategies = list(manifest['parameter_baseline']['strategies']);rng.shuffle(strategies)
            for strategy in strategies:
                jobs.append(dict(task_id=task, method='P_'+strategy, strategy=strategy, trial_id=str(trial),
                    policy_variant='GPT' if strategy == 'gpt_feedback' else 'random',
                    selection_seed=manifest['selection_seeds'][trial-1], evaluation_seed_slot=None))
    elif part == 'local':
        # T0 uses one common backbone. Its three slots are matching schedule
        # blocks, never three independently trained models.
        blocks = [(task, slot, trial) for task in sorted(tasks) for slot in (41, 73, 109) for trial in (1, 2, 3)]
        rng.shuffle(blocks)
        for task, slot, trial in blocks:
            variants = ['T0', 'T1', 'T2', 'T3', 'T4'];rng.shuffle(variants)
            for variant in variants:
                jobs.append(dict(task_id=task, method='C', trial_id=str(trial), policy_variant=variant,
                    selection_seed=manifest['selection_seeds'][trial-1], evaluation_seed_slot=slot))
    elif part == 'signals':
        selected = manifest['signal_task_ids']
        variants = manifest['selector_ablation_weights']
        if (len(selected) != 8 or len(set(selected)) != 8 or not set(selected) <= set(tasks)
                or set(variants) != {'without_distance', 'without_margin'}):
            raise ValueError('Signal ablations require the fixed eight-state, two-signal matrix')
        blocks = [(task, trial) for task in sorted(selected) for trial in range(1, 6)]
        rng.shuffle(blocks)
        for task, trial in blocks:
            selectors = sorted(variants);rng.shuffle(selectors)
            for selector in selectors:
                jobs.append(dict(task_id=task, method='C', trial_id=str(trial), policy_variant='GPT',
                    selector_variant=selector, selection_seed=manifest['selection_seeds'][trial-1],
                    evaluation_seed_slot=None))
    elif part == 'fidelity':
        selected = manifest['fidelity_task_ids']
        if len(selected) != 2 or len(set(selected)) != 2 or not set(selected) <= set(tasks):
            raise ValueError('F3 uses the fixed two OTA states and five matched trials')
        jobs = [dict(task_id=task, method='C', trial_id=str(trial), policy_variant='GPT',
            selection_seed=manifest['selection_seeds'][trial-1], evaluation_seed_slot=None)
            for task in sorted(selected) for trial in range(1, 6)]
        rng.shuffle(jobs)
    else:
        blocks = [(task, trial) for task in sorted(manifest['instance_task_ids'])
            for trial in range(1, manifest['instance_trials']+1)]
        rng.shuffle(blocks)
        jobs = [dict(task_id=task, method='I', trial_id=str(trial), policy_variant='GPT',
            selection_seed=None, evaluation_seed_slot=None) for task, trial in blocks]
    for row in jobs:
        row.setdefault('selector_variant', 'main')
        row.update(part=part, status='NOT_RUN', job_id='_'.join(str(row[key]) for key in
            ('task_id', 'method', 'policy_variant', 'selector_variant', 'evaluation_seed_slot', 'trial_id')))
    if len({row['job_id'] for row in jobs}) != len(jobs):
        raise ValueError('A declared search appears twice')
    return jobs


def identity(row):
    return (row.get('part'), row.get('task_id'), row.get('method'), row.get('policy_variant'),
        row.get('selector_variant', 'main'), row.get('evaluation_seed_slot'), row.get('trial_id'))
