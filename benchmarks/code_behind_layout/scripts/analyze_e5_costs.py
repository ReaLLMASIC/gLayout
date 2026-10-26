#!/usr/bin/env python3
"""Read actual E1/E3/I/training cost records; preserve missing and failed work."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1];sys.path.insert(0, str(ROOT))
from scripts.analyze_e1 import analyze as analyze_e1
from src.e5_costs import observed, physical_stages, quality_matched_reuse


def read(filename):return json.loads(Path(filename).read_text())


def optional(filename):
    try:return read(filename)
    except (FileNotFoundError, json.JSONDecodeError):return None


def policy_records(directory):
    """Count actual positive CLI PIDs once, using their own raw event streams."""
    rows = []
    for filename in sorted(directory.glob('decisions/*/decision_*/invocation.json')):
        invocation = optional(filename)
        if invocation is None or type(invocation.get('pid')) is not int or invocation['pid'] <= 0:
            continue
        work = filename.parent;usage = []
        events = work/'events.jsonl'
        for line in events.read_text().splitlines() if events.is_file() else []:
            try:event = json.loads(line)
            except json.JSONDecodeError:continue  # a running stream may end mid-line
            if event.get('type') == 'turn.completed' and isinstance(event.get('usage'), dict):usage.append(event['usage'])
        tokens = optional(work/'token_budget.json') or {}
        rows.append({'invocation': str(filename), 'pid': invocation['pid'], 'status': invocation['status'],
            'wall_seconds': invocation.get('wall_seconds'), 'utc_elapsed_seconds': invocation.get('utc_elapsed_seconds'),
            'UTC_minus_monotonic_gap_seconds': invocation.get('observed_utc_monotonic_gap_seconds'),
            'provider_usage': usage if usage else None,
            'logged_prompt_tokens_common_tokenizer': tokens.get('prompt_tokens'),
            'logged_completion_tokens_including_EOS': tokens.get('completion_tokens_including_EOS'),
            'queue_seconds': None, 'provider_GPU_seconds': None, 'billable_dollars': None,
            'action': optional(work/'action.json')})
    return rows


def summarize_policy(rows):
    usage = [r['provider_usage'] for r in rows]
    names = sorted({key for values in usage if values for row in values for key in row})
    return {'actual_model_cli_invocations': len(rows), 'CLI_wall_seconds': observed(r['wall_seconds'] for r in rows),
        'logged_prompt_tokens_common_tokenizer': observed(r['logged_prompt_tokens_common_tokenizer'] for r in rows),
        'logged_completion_tokens_including_EOS': observed(r['logged_completion_tokens_including_EOS'] for r in rows),
        'provider_usage_fields_as_reported': {name: observed(
            sum(row[name] for row in values) if values and all(type(row.get(name)) is int for row in values) else None
            for values in usage) for name in names},
        'invocations_without_provider_usage': sum(value is None for value in usage),
        'queue_seconds': None, 'provider_GPU_seconds': None, 'billable_dollars': None,
        'scope': 'Provider categories retain their supplied meaning; cached/reasoning counts may be subsets and are not added together. Logged text tokens are a different common-tokenizer measure; neither establishes prices.'}


def failure_mode(directory, episode):
    error = optional(directory/'policy_error.json')
    text = error.get('error', '') if error else ''
    if 'Source read is outside the task packet' in text:return 'source_read_outside_packet'
    if 'shared action budget' in text:return 'shared_output_budget_rejection'
    if 'exceeds' in text and 'context' in text:return 'context_budget_rejection'
    if optional(directory/'backend_error.json'):return 'backend_transport_or_infrastructure'
    return 'other_recorded_model_failure' if episode.get('analysis_search_status') == 'MODEL_FAILURE' else episode['status']


def summarize_stages(rows):
    grouped = defaultdict(list)
    for row in rows:
        for stage, data in row['physical_stages'].items():grouped[stage].append(data)
    return {name: {'physical_calls': sum(r['physical_calls'] for r in values),
        'observed_child_CPU_seconds': observed(r['observed_child_CPU_seconds'] for r in values),
        'complete_child_CPU_seconds': observed(r['complete_child_CPU_seconds'] for r in values),
        'missing_CPU_records': sum(r['missing_CPU_records'] for r in values if r['missing_CPU_records'] is not None),
        'unresolved_calls': sum(r['unresolved_calls'] for r in values),
        'records_without_missing_CPU_count': sum(r['missing_CPU_records'] is None for r in values),
        'capsule_preparation_CPU_seconds': observed(r['capsule_preparation_CPU_seconds'] for r in values),
        'stage_wall_seconds_sum': observed(r['stage_wall_seconds'] for r in values),
        'capsule_preparation_wall_seconds_sum': observed(r['capsule_preparation_wall_seconds'] for r in values),
        'primitive_geometry_already_in_capsule_not_added_again': True} for name, values in grouped.items()}


def e1_snapshot(filename):
    suite = read(filename);manifest = read(suite['manifest']);jobs = suite['jobs']
    expected = {(task, method, str(trial)) for task in manifest['task_ids'] for method in manifest['methods']
        for trial in range(1, manifest['trials']+1)}
    actual = [(j['task_id'], j['method'], str(j['trial_id'])) for j in jobs]
    if len(actual) != len(set(actual)) or set(actual) != expected or len(expected) != 360:
        raise ValueError('The actual E1 suite must retain its full360 unique identities')
    rows = [];index = [];policies = [];pending_policies = [];modes = Counter();missing_active_scopes = 0
    for job in jobs:
        directory = Path(job['local_output_directory']) if job.get('local_output_directory') else None
        if directory is None and job.get('dispatch_record'):
            client = optional(job['dispatch_record'])
            if client:
                if (client['task_id'], client['method'], str(client['trial_id'])) != (job['task_id'], job['method'], str(job['trial_id'])):
                    raise ValueError('Live child directory belongs to a different actual trial')
                directory = Path(client['local_output_directory'])
        raw_policy = policy_records(directory) if directory else []
        if job['status'] != 'RECORDED':
            pending_policies.extend(raw_policy)
            if job['status'] != 'NOT_RUN' and directory is None:missing_active_scopes += 1
            continue
        source = Path(job['episode_json']);episode = read(source)
        if ((episode['task_id'], episode['method'], str(episode['trial_id'])) !=
                (job['task_id'], job['method'], str(job['trial_id'])) or episode['phase'] != 'formal_E1'):
            raise ValueError('A recorded E1 episode differs from its real dispatch identity/phase')
        policy_error = optional(directory/'policy_error.json');mode = failure_mode(directory, episode);modes[mode] += 1
        rows.append({'task_id': job['task_id'], 'method': job['method'], 'trial_id': str(job['trial_id']),
            'episode': str(source), 'original_freeze_id': job.get('original_freeze_id', suite['freeze_id']),
            'dispatch_status': job['status'], 'search_status': episode.get('analysis_search_status', episode['status']),
            'failure_mode': mode, 'policy_error': policy_error,
            'search_observed_wall_seconds': episode.get('observed_search_wall_seconds'),
            'physical_stages': physical_stages(episode['costs_by_stage']),
            'archive': job.get('evidence_archive'), 'policy_records': [r['invocation'] for r in raw_policy],
            'recorded_policy_model_calls': episode['costs_by_stage'].get('policy', {}).get('model_cli_invocations'),
            'recorded_step_attempts': episode['costs_by_stage'].get('policy', {}).get('decision_step_attempts'),
            'final_anchor': episode['final_anchor'], 'hidden': episode['hidden']})
        policies.extend(raw_policy);index.append({'task_id': job['task_id'], 'method': job['method'],
            'trial_id': str(job['trial_id']), 'episode_json': str(source)})
    if len({r['invocation'] for r in policies+pending_policies}) != len(policies+pending_policies):
        raise ValueError('A model invocation would be counted twice')
    return {'status': 'IN_PROGRESS' if any(j['status'] != 'RECORDED' for j in jobs) else 'COMPLETE_MATRIX',
        'suite_state': str(filename), 'snapshot_updated_at_utc': suite['updated_at_utc'], 'freeze_id': suite['freeze_id'],
        'protocol_amendment': suite.get('protocol_amendment'), 'declared_episodes': 360,
        'dispatch_status_counts': dict(Counter(j['status'] for j in jobs)), 'recorded_failure_modes': dict(modes),
        'search_status_counts': dict(Counter(r['search_status'] for r in rows)),
        'recorded_episode_costs_by_stage': summarize_stages(rows),
        'recorded_policy': summarize_policy(policies), 'inprogress_policy_observations': summarize_policy(pending_policies),
        'active_episodes_without_local_raw_scope': missing_active_scopes,
        'unrecorded_episode_resource_totals_remain_unknown': len(jobs)-len(rows),
        'recorded_policy_invocation_reconciliation': {
            'observed_raw_PID_records': len(policies),
            'trusted_episode_model_call_counts': observed(r['recorded_policy_model_calls'] for r in rows)},
        'recorded_search_wall_seconds_sum': observed(r['search_observed_wall_seconds'] for r in rows),
        'archive_CPU_seconds': observed((r['archive'] or {}).get('archive_CPU_seconds') for r in rows),
        'archive_wall_seconds': observed((r['archive'] or {}).get('archive_wall_seconds') for r in rows),
        'recorded_backend_CPU_seconds_capsule_child_archive': observed(
            [value for r in rows for stage in r['physical_stages'].values()
                for value in [stage['complete_child_CPU_seconds'], stage['capsule_preparation_CPU_seconds']]]+
            [(r['archive'] or {}).get('archive_CPU_seconds') for r in rows]),
        'configured_simultaneous_episodes': suite['maximum_simultaneous_episodes'],
        'observed_global_peak_CPU_or_GPU_concurrency': None, 'scheduler_queue_time_seconds': None,
        'statistical_progress': analyze_e1(manifest, index), 'episodes': rows,
        'observed_model_invocations': policies+pending_policies,
        'scope': 'Actual local snapshot; failures and earlier amended trials are retained once. NOT_RUN/RUNNING remain unknown. Stage/CLI wall sums overlap and are not elapsed study wall or provider queue.'}


def training_attempts(filenames):
    rows = []
    for filename in filenames:
        row = read(filename)
        if row['method'] == 'T0':raise ValueError('T0 is one base model, never a trained seed')
        rows.append({'source': str(filename), 'method': row['method'], 'training_seed': row['seed'],
            'status': row['status'], 'wall_seconds': row.get('wall_seconds'),
            'self_CPU_seconds': row['cpu_user_seconds']+row['cpu_system_seconds']
                if all(type(row.get(k)) in (int, float) for k in ('cpu_user_seconds', 'cpu_system_seconds')) else None,
            'GPU_allocated_seconds': row.get('gpu_allocated_seconds'), 'resume': row.get('resume'),
            'phase': row.get('phase', 'unknown_from_attempt_record')})
    if len({str(Path(r['source']).resolve()) for r in rows}) != len(rows):raise ValueError('A training attempt is duplicated')
    return {'attempts': rows, 'attempt_status_counts': dict(Counter(r['status'] for r in rows)),
        'GPU_allocated_seconds': observed(r['GPU_allocated_seconds'] for r in rows),
        'self_CPU_seconds': observed(r['self_CPU_seconds'] for r in rows),
        'observed_wall_seconds_sum': observed(r['wall_seconds'] for r in rows),
        'selected_formal_model_count': None,
        'scope': 'Every supplied actual attempt, including failure/resume, counted once. Allocated GPU wall differs from GPU busy time. Attempt completion alone does not establish a selected/frozen model.'}


def episode_costs(filenames):
    rows = []
    for filename in filenames:
        raw = read(filename)
        rows.append({'source': str(filename), 'phase': raw['phase'], 'task_id': raw['task_id'],
            'method': raw['method'], 'trial_id': raw['trial_id'], 'policy_variant': raw.get('policy_variant'),
            'evaluation_seed_slot': raw.get('evaluation_seed_slot'),
            'selector_variant': raw.get('selector_variant', 'main'), 'fidelity_policy': raw.get('fidelity_policy'),
            'physical_stages': physical_stages(raw['costs_by_stage'])})
    identities = [(r['phase'], r['task_id'], r['method'], r['trial_id'], r['policy_variant'],
        r['evaluation_seed_slot'], r['selector_variant'], r['fidelity_policy']) for r in rows]
    if len(identities) != len(set(identities)):
        raise ValueError('Do not add overlapping search/final records for the same E3 episode')
    return {'records': rows, 'by_stage': summarize_stages(rows),
        'scope': 'Pass one final episode per actual backend identity, not its overlapping search and final reports.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--e1-suite-state', type=Path, required=True);parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--training-attempt', type=Path, action='append', default=[])
    parser.add_argument('--e3-episode', type=Path, action='append', default=[])
    parser.add_argument('--instance-summary', type=Path, action='append', default=[])
    parser.add_argument('--deployment-comparison', type=Path)
    args = parser.parse_args()
    instances = []
    for name in args.instance_summary:
        raw = read(name)
        instances.append({'source': str(name), 'status': raw['status'], 'arrivals_completed': raw['arrivals_completed'],
            'cumulative_costs': raw['cumulative_costs']})
    report = {'scope': 'E5 intermediate observed ledger, not a final cost-effectiveness conclusion',
        'generated_at_utc': datetime.now(timezone.utc).isoformat(), 'E1': e1_snapshot(args.e1_suite_state),
        'training': training_attempts(args.training_attempt), 'E3': episode_costs(args.e3_episode), 'I': instances,
        'deployment': quality_matched_reuse(read(args.deployment_comparison)) if args.deployment_comparison else {
            'status': 'NO_OBSERVED_MATCHED_DEPLOYMENT_STREAM', 'break_even': None},
        'dollar_cost': None, 'engineering_agent_time_seconds': None,
        'research_total_resource_cost': None,
        'limitations': 'This ledger is a partial measured scope. Missing telemetry, in-flight work, provider resources, data/filtering/tuning and engineering time are not zero. No exact dollars or complete research total can be inferred. Hidden/oracle research work is separate from deployment marginal cost.'}
    args.output.parent.mkdir(parents=True, exist_ok=True);args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'output': str(args.output), 'status': report['E1']['status'],
        'dispatch_status_counts': report['E1']['dispatch_status_counts'], 'deployment': report['deployment']['status']}))
