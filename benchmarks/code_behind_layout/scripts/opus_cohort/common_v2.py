"""Declarations for the amended Claude action-level cohort E1-C2 (amendment A6: format guidance only).

Same 24 tasks, hidden sets, budgets, gateway and Minimum-tier matrix as E1-C; only the policy's fixed
system prompt gains format rules. Frozen files of E1-C and E3-C stay byte-identical; this cohort binds
them plus its own new files.
"""
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.opus_cohort import common  # noqa: E402

FREEZE_V2 = 'E1_scope_v2_16k_claude_v2'
COHORT_LABEL_V2 = 'E1-C2'
PREDECESSOR = common.FREEZE['E1']
AMENDMENT_V2 = 'docs/protocol_amendments_20261019.md A6 (format guidance in the fixed system prompt)'
SYSTEM_PROMPT_VERSION = 'format_guidance_v2'
NEW_IMPLEMENTATION_V2 = common.NEW_IMPLEMENTATION + (
    'src/opus_cli_adapter_v2.py', 'scripts/opus_cohort/common_v2.py',
    'scripts/opus_cohort/e1_scope_runner_opus_v2.py', 'scripts/opus_cohort/run_e1_scope_suite_opus_v2.py',
    'scripts/opus_cohort/pilot_opus_policy_v2.py', 'scripts/opus_cohort/freeze_cohorts_opus_v2.py')


def install_claude_adapter_v2():
    import src.model_adapter as model_adapter
    from src.opus_cli_adapter_v2 import ClaudeCLIDecisionAdapterV2
    model_adapter.GptDecisionAdapter = ClaudeCLIDecisionAdapterV2
    runner = sys.modules.get('scripts.e1_scope_runner')
    if runner is not None:
        runner.GptDecisionAdapter = ClaudeCLIDecisionAdapterV2
    return ClaudeCLIDecisionAdapterV2


def require_claude_manifest_v2(manifest, formal=True):
    if manifest.get('policy_backend') != common.POLICY_BACKEND or manifest.get('policy_model') != common.POLICY_MODEL:
        raise ValueError('Not a Claude policy cohort manifest')
    if manifest.get('parent_freeze_id') != common.PARENT['E1'] or manifest.get('cohort_label') != COHORT_LABEL_V2:
        raise ValueError('Cohort manifest is not the amended E1-C2 cohort of the frozen parent protocol')
    if manifest.get('minimum_tier') != common.MINIMUM or manifest.get('system_prompt_version') != SYSTEM_PROMPT_VERSION:
        raise ValueError('E1-C2 manifest does not declare the Minimum tier and the format-guidance prompt')
    if 'A6' not in str(manifest.get('protocol_amendment', '')):
        raise ValueError('E1-C2 manifest does not cite amendment A6')
    if formal and (manifest.get('freeze_id') != FREEZE_V2 or manifest.get('status') != 'FROZEN_E1' or manifest.get('formal_dispatch') is not True):
        raise ValueError('Formal E1-C2 dispatch requires the read-only cohort freeze ' + FREEZE_V2)


def claude_e1_plan_v2(manifest):
    """Same Minimum-tier matrix and shuffle as E1-C: 24 tasks x G0/G1/G2 x two fresh trials."""
    require_claude_manifest_v2(manifest)
    from scripts.prepare_e1_scope_cohort import BUDGET, COHORT
    if manifest.get('cohort_id') != COHORT or manifest['budget'] != BUDGET:
        raise ValueError('E1-C2 keeps the frozen 16k scope cohort interface and budget')
    trials = manifest['trials']
    if trials != common.MINIMUM['e1_trials'] or len(manifest['task_ids']) != 24:
        raise ValueError('E1-C2 uses the parent 24 tasks at two trials')
    rng = random.Random(manifest['dispatch_order_seed'])
    blocks = [(task, trial) for task in sorted(manifest['task_ids']) for trial in range(1, trials + 1)]
    rng.shuffle(blocks)
    jobs = []
    for task, trial in blocks:
        methods = list(manifest['methods'])
        rng.shuffle(methods)
        jobs.extend({'task_id': task, 'method': method, 'trial_id': str(trial), 'status': 'NOT_RUN', 'cohort_id': COHORT} for method in methods)
    if len(jobs) != common.E1_DECLARED:
        raise ValueError('E1-C2 declared matrix size differs')
    return jobs
