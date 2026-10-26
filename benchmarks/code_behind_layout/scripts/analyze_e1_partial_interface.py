#!/usr/bin/env python3
"""Close the paused interface-v1 cohort without turning its partial matrix into a benchmark."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.analyze_e5_costs import e1_snapshot, read, summarize_policy, summarize_stages
from src.e5_costs import observed


def identity(row):
    return row['task_id'], row['method'], str(row['trial_id'])


def rate(positive, known, declared):
    if not 0 <= positive <= known <= declared:
        raise ValueError('Outcome counts must retain their known and declared denominators')
    return {'verified_positive': positive, 'known_outcomes': known, 'declared_denominator': declared,
        'unknown_outcomes': declared-known, 'conditional_known_rate': positive/known if known else None,
        'identification_bounds': [positive/declared, (positive+declared-known)/declared] if declared else None}


def endpoints(rows, declared):
    search = [r for r in rows if r['search_status'] in ('COMPLETED', 'BUDGET_EXHAUSTED', 'MODEL_FAILURE')]
    verified = sum(r['first_verified_times_seconds']['S2'] is not None and
        0 <= r['first_verified_times_seconds']['S2'] <= r['search_budget_seconds'] for r in search)
    anchors = [r['final_anchor']['S2'] for r in rows if r['final_anchor']['complete'] is True]
    hidden_known = sum(r['hidden']['known'] for r in rows)
    hidden_positive = sum(r['hidden']['S2_passed'] for r in rows)
    hidden_per_trial = {r['hidden']['declared'] for r in rows}
    if hidden_per_trial not in (set(), {16}):
        raise ValueError('This cohort declares sixteen hidden configurations per trial')
    return {'within_budget_search_S2': rate(verified, len(search), declared),
        'final_frozen_source_anchor_S2': rate(sum(anchors), len(anchors), declared),
        'hidden_configuration_S2': rate(hidden_positive, hidden_known, declared*16),
        'hidden_configuration_S2_among_dispatched': rate(hidden_positive, hidden_known, len(rows)*16),
        'scope': 'Identification bounds permit either outcome for unknown rows; they are not confidence intervals. Configuration counts do not create independent circuits.'}


def cohort_group(row, legacy):
    if identity(row) in legacy:
        return 'retained_original_three'
    if row['failure_mode'] == 'source_read_outside_packet':
        return 'later_manifest_read_failures'
    if row['physical_stages'].get('search', {}).get('physical_calls', 0):
        return 'real_construction_trajectories'
    return 'other_later_search'


def summarize_rows(rows, policies):
    invocations = {name for row in rows for name in row['policy_records']}
    raw = [r for r in policies if r['invocation'] in invocations]
    if len(raw) != len(invocations):
        raise ValueError('Every supplied invocation must resolve to its actual PID record')
    return {'episodes': len(rows), 'failure_modes': dict(Counter(r['failure_mode'] for r in rows)),
        'search_statuses': dict(Counter(r['search_status'] for r in rows)),
        'decision_step_attempts': sum(r['recorded_step_attempts'] for r in rows),
        'raw_action_counts': dict(Counter(action for r in raw if r['action'] for action in [r['action']['action']])),
        'recoverable_gateway_errors': dict(Counter(error for r in rows for error in r['recoverable_gateway_errors'])),
        'context_rejections_without_model_invocation': [v for r in rows for v in r['context_rejections_without_model_invocation']],
        'policy': summarize_policy(raw), 'physical_stages': summarize_stages(rows),
        'archive_CPU_seconds': observed((r['archive'] or {}).get('archive_CPU_seconds') for r in rows),
        'archive_wall_seconds_sum': observed((r['archive'] or {}).get('archive_wall_seconds') for r in rows),
        'observed_outcomes': endpoints(rows, len(rows)),
        'episode_identities': [list(identity(r)) for r in rows]}


def analyze(filename):
    suite = read(filename)
    if suite['status'] != 'PAUSED' or suite.get('coordinator_pid') is not None or any(
            j['status'] not in ('RECORDED', 'NOT_RUN') for j in suite['jobs']):
        raise ValueError('A closed partial report requires a paused, drained suite with no active/unresolved child')
    if not any(j['status'] == 'NOT_RUN' for j in suite['jobs']):
        raise ValueError('Use the full benchmark analysis for a complete matrix')
    ledger = e1_snapshot(filename)
    ledger['generic_matrix_completion_status'] = ledger['status']
    ledger['status'] = 'CLOSED_PARTIAL_MATRIX'
    manifest = read(suite['manifest'])
    legacy = {identity(r) for r in suite['protocol_amendment']['retained_prior_trials']}
    tasks = {r['task_id']: r for r in manifest['tasks']}
    for row in ledger['episodes']:
        actual = read(row['episode'])
        directory = Path(row['episode']).parent
        session = read(directory/'session.json')
        row['recoverable_gateway_errors'] = [h['observation']['error'] for h in session['history']
            if isinstance(h.get('observation'), dict) and 'error' in h['observation']]
        row['context_rejections_without_model_invocation'] = [
            {'token_budget_record': str(path), 'actual_token_budget': read(path)}
            for path in directory.glob('decisions/*/decision_*/token_budget.json')
            if not (path.parent/'invocation.json').exists() and read(path).get('fits_with_full_output_reserve') is False]
        row.update({k: actual[k] for k in ('stratum', 'source_group', 'merged_source_group',
            'search_budget_seconds', 'first_verified_times_seconds')})
        if any(row[k] != tasks[row['task_id']][k] for k in ('stratum', 'source_group', 'merged_source_group')):
            raise ValueError('A public episode differs from the frozen task assignment')
        if row['failure_mode'] == 'source_read_outside_packet':
            actions = [read(Path(r).parent/'action.json') for r in row['policy_records']]
            if len(actions) != 1 or actions[0]['action'] != 'read_source' or actions[0]['path'] != '/library/manifest.json':
                raise ValueError('The observed manifest-error class must be demonstrated by the actual action')
        row['provenance_group'] = cohort_group(row, legacy)
    rows = ledger['episodes'];policies = ledger['observed_model_invocations']
    groups = {name: summarize_rows([r for r in rows if r['provenance_group'] == name], policies)
        for name in sorted({r['provenance_group'] for r in rows})}
    if len([r for r in rows if identity(r) in legacy]) != len(legacy):
        raise ValueError('Every retained original trial must remain in the final account')
    methods = {method: endpoints([r for r in rows if r['method'] == method],
        sum(j['method'] == method for j in suite['jobs'])) for method in manifest['methods']}
    for method in methods:
        methods[method]['observed_costs'] = summarize_rows([r for r in rows if r['method'] == method], policies)
    strata = {stratum: endpoints([r for r in rows if r['stratum'] == stratum],
        sum(tasks[j['task_id']]['stratum'] == stratum for j in suite['jobs']))
        for stratum in sorted({r['stratum'] for r in tasks.values()})}
    trajectories = [{k: r[k] for k in ('task_id', 'method', 'trial_id', 'stratum', 'source_group',
        'merged_source_group', 'episode', 'search_status', 'failure_mode', 'first_verified_times_seconds',
        'final_anchor', 'hidden', 'physical_stages', 'recorded_step_attempts', 'recorded_policy_model_calls')}
        for r in rows if r['physical_stages'].get('search', {}).get('physical_calls', 0)]
    archives = [r['archive'] for r in rows]
    if not all(r and r['status'] == 'COMPRESSED_RAW_RETAINED' and r['hidden_evidence_exported'] is False for r in archives):
        raise ValueError('Every completed old episode must retain its original private raw archive')
    return {'status': 'CLOSED_PARTIAL_INTERFACE_V1', 'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'Final account of the paused original interface cohort, not a complete E1 representation comparison. Prospective scope_v2_16k results are excluded.',
        'suite_state': str(filename), 'freeze_id': suite['freeze_id'],
        'terminal_suite_update_utc': suite['updated_at_utc'], 'dispatch_status_counts': ledger['dispatch_status_counts'],
        'declared_episodes': ledger['declared_episodes'], 'dispatched_episodes': len(rows),
        'group_counts': {'declared_source_groups': len({r['source_group'] for r in tasks.values()}),
            'declared_merged_source_groups': len({r['merged_source_group'] for r in tasks.values()}),
            'observed_source_groups': len({r['source_group'] for r in rows}),
            'observed_merged_source_groups': len({r['merged_source_group'] for r in rows})},
        'preserved_intermediate_snapshots': [
            'results/raw/e1_suite_cost_snapshot_20261019T051640Z.json',
            'results/raw/e1_partial_interface_v1_cost_snapshot_20261019T053648Z.json'],
        'original_recorded_statuses_unchanged': True, 'automatic_retries': 0,
        'groups': groups, 'methods': methods, 'strata': strata, 'all_episodes': endpoints(rows, len(suite['jobs'])),
        'real_construction_trajectories': trajectories, 'ledger': ledger,
        'private_storage': {'archives': len(archives), 'compressed_bytes': sum(r['archive_bytes'] for r in archives),
            'original_uncompressed_regular_file_bytes': sum(r['regular_file_bytes'] for r in archives),
            'raw_hidden_values_exported': False},
        'deployment': {'status': 'NO_OBSERVED_MATCHED_DEPLOYMENT_STREAM', 'break_even': None},
        'dollar_cost': None, 'research_total_resource_cost': None,
        'limitations': [
            'The documentation ambiguity and the 8k context limit affect the intended representation comparison; all observed actions and original failures remain recorded.',
            'All three observed S2 construction trajectories are reuse cases with an allowed complete generator; they do not establish composition success.',
            'Two terminal MODEL_FAILURE episodes had already obtained verified S2 before a later context rejection; endpoint evidence is retained.',
            '334 NOT_RUN slots remain unknown outcomes. No fully task-paired five-trial comparison is complete, so no clustered confidence interval or representation effect is inferred.',
            'Only public trusted aggregates are read. Hidden configuration vectors and measurements stay on the private endpoint.',
            'CPU covers the recorded child/capsule/archive scopes; provider GPU/queue, complete engineering/research resources and dollars are unknown. Wall sums overlap.',
            'Common-tokenizer output counts missing for rejected outputs remain null; provider usage categories retain their original meaning and cannot be added indiscriminately.']}


def text_report(report):
    ledger = report['ledger'];policy = ledger['recorded_policy']
    lines = [report['status'], report['scope'], '',
        f"Matrix: {report['dispatched_episodes']}/360 dispatched; 334 NOT_RUN retained; automatic retries: 0.",
        'Disjoint provenance groups:']
    for name, row in report['groups'].items():
        stages = row['physical_stages'];calls = '/'.join(str(stages[k]['physical_calls'])
            for k in ('search', 'post_freeze_diagnostic', 'hidden'))
        lines.append(f"  {name}: {row['episodes']} trials; {row['policy']['actual_model_cli_invocations']} CLI calls; search/post/hidden point calls={calls}; modes={row['failure_modes']}")
    lines += ['', 'Actual public outcomes by method (known-conditional and full120 bounds):']
    for name, row in report['methods'].items():
        s = row['within_budget_search_S2'];h = row['hidden_configuration_S2']
        lines.append(f"  {name}: search S2 {s['verified_positive']}/{s['known_outcomes']}; full120 bounds={s['identification_bounds']}; hidden {h['verified_positive']}/{h['known_outcomes']} known, full1920 bounds={h['identification_bounds']}")
    lines += ['', f"Model: {policy['actual_model_cli_invocations']} positive-PID invocations, "
        f"{sum(r['recorded_step_attempts'] for r in ledger['episodes'])} decision attempts; "
        f"CLI wall sum={policy['CLI_wall_seconds']['complete_total']:.6f}s (not elapsed wall).",
        f"Provider usage as reported: {json.dumps(policy['provider_usage_fields_as_reported'], sort_keys=True)}",
        f"Common-tokenizer prompt: {policy['logged_prompt_tokens_common_tokenizer']}; output: {policy['logged_completion_tokens_including_EOS']}.",
        'The three construction trajectories each first requested all nine visible points; each request was rejected before physics, then the policy used anchor plus two points within its actual three-point budget.',
        '', 'Recorded backend costs (CPU seconds; point-call count includes failed calls):']
    for name, row in ledger['recorded_episode_costs_by_stage'].items():
        lines.append(f"  {name}: {row['physical_calls']} calls; child={row['complete_child_CPU_seconds']['complete_total']}; capsule={row['capsule_preparation_CPU_seconds']['complete_total']}; stage wall sum={row['stage_wall_seconds_sum']['complete_total']}")
    lines += [f"  Archive CPU={ledger['archive_CPU_seconds']['complete_total']}; total child+capsule+archive CPU={ledger['recorded_backend_CPU_seconds_capsule_child_archive']['complete_total']}.",
        '', 'Limitations:'] + [f'  {line}' for line in report['limitations']]
    return '\n'.join(lines)+'\n'


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--suite-state', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--text-output', type=Path, required=True)
    a = p.parse_args();result = analyze(a.suite_state)
    for output in (a.output, a.text_output):output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    a.text_output.write_text(text_report(result))
    print(json.dumps({'output': str(a.output), 'status': result['status'],
        'dispatch_status_counts': result['dispatch_status_counts'],
        'groups': {name: row['episodes'] for name, row in result['groups'].items()}}))
