"""Shared declarations for the Claude policy cohorts E1-C and E3-C.

Approved on 2026-10-19 (docs/protocol_amendments_20261019.md, A1-A3, Minimum tier). Every file
bound by the GPT freezes stays byte-identical. These wrappers replace the policy adapter object
at run time, declare the Minimum-tier matrices, and drive the frozen episode scripts against a
cohort freeze whose model_config names the Claude CLI command-line backend.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

POLICY_BACKEND = 'claude_cli'
POLICY_MODEL = 'claude-opus-5-5'
PARENT = {'E3': 'E3_primary_v2', 'E1': 'E1_scope_v2_16k'}
FREEZE = {'E3': 'E3_primary_v2_claude', 'E1': 'E1_scope_v2_16k_claude'}
COHORT_LABEL = {'E3': 'E3-C', 'E1': 'E1-C'}
FROZEN_STATUS = {'E3': 'FROZEN_E3', 'E1': 'FROZEN_E1'}
MINIMUM = {'e3_trials': 3, 'e1_trials': 2, 'parameter_tasks': 4, 'signal_tasks': 4,
           'local_tasks': 8, 'local_inference_trials': 1, 'local_seed_slots': [41, 73, 109]}
E3_PARTS = ('gpt', 'parameter', 'signals', 'local')
E3_DECLARED = {'gpt': 288, 'parameter': 24, 'signals': 24, 'local': 104}
E1_DECLARED = 144
AMENDMENT = 'docs/protocol_amendments_20261019.md'
# Code bound by the Claude cohort freezes in addition to the parent bindings. The model
# configuration itself is copied into each freeze directory, so it is not bound here.
NEW_IMPLEMENTATION = (
    'src/opus_cli_adapter.py',
    'scripts/opus_cohort/__init__.py', 'scripts/opus_cohort/common.py',
    'scripts/opus_cohort/e3_episode_opus.py', 'scripts/opus_cohort/e3_parameter_episode_opus.py',
    'scripts/opus_cohort/e1_scope_runner_opus.py', 'scripts/opus_cohort/run_e3_suite_opus.py',
    'scripts/opus_cohort/run_e1_scope_suite_opus.py', 'scripts/opus_cohort/freeze_cohorts_opus.py',
    'scripts/opus_cohort/pilot_opus_policy.py')


def now():
    return datetime.now(timezone.utc).isoformat()


def read(filename):
    return json.loads(Path(filename).read_text())


def save(filename, value):
    filename = Path(filename)
    filename.parent.mkdir(parents=True, exist_ok=True)
    temporary = filename.with_name(filename.name + '.pending')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temporary.replace(filename)


def digest(filename):
    return hashlib.sha256(Path(filename).read_bytes()).hexdigest()


def install_claude_adapter():
    """Make every `GptDecisionAdapter` lookup resolve to the Claude CLI adapter in this process."""
    import src.model_adapter as model_adapter
    from src.opus_cli_adapter import ClaudeCLIDecisionAdapter
    model_adapter.GptDecisionAdapter = ClaudeCLIDecisionAdapter
    runner = sys.modules.get('scripts.e1_scope_runner')
    if runner is not None:
        runner.GptDecisionAdapter = ClaudeCLIDecisionAdapter
    return ClaudeCLIDecisionAdapter


def require_claude_manifest(manifest, kind, formal=True):
    if manifest.get('policy_backend') != POLICY_BACKEND or manifest.get('policy_model') != POLICY_MODEL:
        raise ValueError('Not a Claude policy cohort manifest')
    if manifest.get('parent_freeze_id') != PARENT[kind] or manifest.get('cohort_label') != COHORT_LABEL[kind]:
        raise ValueError('Cohort manifest does not descend from the frozen parent protocol ' + PARENT[kind])
    if manifest.get('minimum_tier') != MINIMUM:
        raise ValueError('Cohort manifest does not declare the approved Minimum tier')
    if formal and (manifest.get('freeze_id') != FREEZE[kind] or manifest.get('status') != FROZEN_STATUS[kind]
                   or manifest.get('formal_dispatch') is not True):
        raise ValueError('Formal Claude cohort dispatch requires the read-only cohort freeze ' + FREEZE[kind])


def minimum_subset(task_ids, seed, count):
    """Declared prospective rule: a seeded sample of the parent's common task subset."""
    return sorted(random.Random(seed).sample(sorted(task_ids), count))


def claude_e3_plan(manifest, part):
    """Minimum-tier E3-C matrix with the parent's job schema, identity fields and shuffle style."""
    require_claude_manifest(manifest, 'E3')
    if part not in E3_PARTS:
        raise ValueError('Unknown Claude cohort E3 part')
    tasks = manifest['task_ids']
    trials = manifest['trials']
    if len(tasks) != 24 or len(set(tasks)) != 24 or trials != MINIMUM['e3_trials']:
        raise ValueError('E3-C uses the parent 24 tasks at three trials')
    seeds = manifest['selection_seeds']
    seed = manifest['dispatch_order_seed']
    rng = random.Random(seed)
    jobs = []
    if part == 'gpt':
        blocks = [(task, trial) for task in sorted(tasks) for trial in range(1, trials + 1)]
        rng.shuffle(blocks)
        for task, trial in blocks:
            methods = ['A', 'R', 'B', 'C']
            rng.shuffle(methods)
            for method in methods:
                jobs.append(dict(task_id=task, method=method, trial_id=str(trial), policy_variant='GPT',
                                 selection_seed=seeds[trial - 1], evaluation_seed_slot=None))
    elif part == 'parameter':
        selected = manifest['parameter_task_ids_minimum']
        if selected != minimum_subset(manifest['parameter_task_ids'], seed, MINIMUM['parameter_tasks']):
            raise ValueError('Declared P subset differs from the prospective seeded rule')
        blocks = [(task, trial) for task in sorted(selected) for trial in range(1, trials + 1)]
        rng.shuffle(blocks)
        for task, trial in blocks:
            strategies = list(manifest['parameter_baseline']['strategies'])
            rng.shuffle(strategies)
            for strategy in strategies:
                jobs.append(dict(task_id=task, method='P_' + strategy, strategy=strategy, trial_id=str(trial),
                                 policy_variant='GPT' if strategy == 'gpt_feedback' else 'random',
                                 selection_seed=seeds[trial - 1], evaluation_seed_slot=None))
    elif part == 'signals':
        selected = manifest['signal_task_ids_minimum']
        variants = manifest['selector_ablation_weights']
        if (selected != minimum_subset(manifest['signal_task_ids'], seed, MINIMUM['signal_tasks'])
                or set(variants) != {'without_distance', 'without_margin'}):
            raise ValueError('Declared signal-ablation subset differs from the prospective seeded rule')
        blocks = [(task, trial) for task in sorted(selected) for trial in range(1, trials + 1)]
        rng.shuffle(blocks)
        for task, trial in blocks:
            selectors = sorted(variants)
            rng.shuffle(selectors)
            for selector in selectors:
                jobs.append(dict(task_id=task, method='C', trial_id=str(trial), policy_variant='GPT',
                                 selector_variant=selector, selection_seed=seeds[trial - 1], evaluation_seed_slot=None))
    else:
        selected = manifest['local_task_ids_minimum']
        if selected != sorted(manifest['parameter_task_ids']) or len(selected) != MINIMUM['local_tasks']:
            raise ValueError('Local-model searches use the parent common eight-task subset')
        blocks = [(task, slot) for task in sorted(selected) for slot in MINIMUM['local_seed_slots']]
        rng.shuffle(blocks)
        for task, slot in blocks:
            # A3: one inference trial. T0 is a single common backbone, dispatched once per task.
            variants = ['T1', 'T2', 'T3', 'T4'] + (['T0'] if slot == MINIMUM['local_seed_slots'][0] else [])
            rng.shuffle(variants)
            for variant in variants:
                jobs.append(dict(task_id=task, method='C', trial_id='1', policy_variant=variant,
                                 selection_seed=seeds[0], evaluation_seed_slot=slot))
    for row in jobs:
        row.setdefault('selector_variant', 'main')
        row.update(part=part, status='NOT_RUN', job_id='_'.join(str(row[key]) for key in
                   ('task_id', 'method', 'policy_variant', 'selector_variant', 'evaluation_seed_slot', 'trial_id')))
    if len(jobs) != E3_DECLARED[part] or len({row['job_id'] for row in jobs}) != len(jobs):
        raise ValueError('E3-C declared matrix size differs for part ' + part)
    return jobs


def claude_e3_command(job, manifest, record):
    """Child command per job. Frontier-policy parts run through the Claude wrappers; local-model
    parts run the frozen episode script unchanged because they never touch the frontier adapter."""
    common = ['--manifest', manifest['backend_manifest_path'], '--task', job['task_id'],
              '--trial', job['trial_id'], '--formal', '--dispatch-record', str(record)]
    if job['part'] == 'parameter':
        return [sys.executable, str(ROOT / 'scripts/opus_cohort/e3_parameter_episode_opus.py'), *common,
                '--strategy', job['strategy'], '--selection-seed', str(job['selection_seed'])]
    if job['part'] == 'local':
        return [sys.executable, str(ROOT / 'scripts/e3_episode.py'), *common, '--method', 'C',
                '--selection-seed', str(job['selection_seed']), '--variant', job['policy_variant'], '--search-only',
                '--training-seed', str(job['evaluation_seed_slot'])]
    result = [sys.executable, str(ROOT / 'scripts/opus_cohort/e3_episode_opus.py'), *common,
              '--method', job['method'], '--selection-seed', str(job['selection_seed']),
              '--variant', job['policy_variant'], '--search-only']
    if job['part'] == 'signals':
        result += ['--selector-variant', job['selector_variant']]
    return result


def claude_e1_plan(manifest):
    """Minimum-tier E1-C matrix: 24 tasks x G0/G1/G2 x two fresh trials, parent shuffle style."""
    require_claude_manifest(manifest, 'E1')
    from scripts.prepare_e1_scope_cohort import BUDGET, COHORT
    if manifest.get('cohort_id') != COHORT or manifest['budget'] != BUDGET:
        raise ValueError('E1-C keeps the frozen 16k scope cohort interface and budget')
    trials = manifest['trials']
    if trials != MINIMUM['e1_trials'] or len(manifest['task_ids']) != 24:
        raise ValueError('E1-C uses the parent 24 tasks at two trials')
    rng = random.Random(manifest['dispatch_order_seed'])
    blocks = [(task, trial) for task in sorted(manifest['task_ids']) for trial in range(1, trials + 1)]
    rng.shuffle(blocks)
    jobs = []
    for task, trial in blocks:
        methods = list(manifest['methods'])
        rng.shuffle(methods)
        jobs.extend({'task_id': task, 'method': method, 'trial_id': str(trial), 'status': 'NOT_RUN',
                     'cohort_id': COHORT} for method in methods)
    if len(jobs) != E1_DECLARED:
        raise ValueError('E1-C declared matrix size differs')
    return jobs


def annotate_dispatch_record(record_path, wrapper):
    """Add the true policy identity to a child's dispatch record after the frozen runner wrote it."""
    if record_path and Path(record_path).is_file():
        record = read(record_path)
        record.update(policy_backend=POLICY_BACKEND, policy_model=POLICY_MODEL,
                      policy_wrapper=str(Path(wrapper).resolve().relative_to(ROOT)))
        save(record_path, record)
