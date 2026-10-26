"""Supplementary tables from recorded E2 pools and public E3 aggregates.

No selection, simulation, tolerance fitting, or inferred physical measurements.
The existing E3 primary analysis remains the source of the paired cluster CI.
"""
from collections import Counter, defaultdict
from datetime import datetime
import math
from statistics import mean

from src.e1_analysis import paired_cluster_effect
from src.e3_analysis import analyze as primary_e3
from src.fidelity_analysis import rank_diagnostics


FEATURES = ('physical_mask_bbox_area_um2', 'union_rectilinear_proxy_um', 'R_sum_times_C_sum_s')
PREDICTORS = ('nominal_tt_ugb_Hz', 'prediction_ugb_Hz')


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def regression_summary(rows, declared):
    """Public original-pass aggregate; independent of uninstalled E4 analysis.

    Same original-pass/unknown denominator as src.e4_analysis, without importing
    the separate E4 implementation on the frozen E3/E2 execution host.
    """
    passed = regressed = selected_unknown = original_unknown = joined = 0
    for row in rows:
        join = row.get('regression_join')
        if join is None:
            original_unknown += 16
            continue
        if (join['task_id'] != row['task_id'] or join['method'] != row['method']
                or str(join['trial_id']) != str(row['trial_id'])):
            raise ValueError('Original baseline aggregate belongs to another episode')
        group = join['groups']['hidden']
        values = [group[name] for name in ('original_verified_S2', 'verified_regressions',
            'selected_unknown_on_original_passes', 'original_unknown')]
        p, r, s, u = values
        if (group['declared_configurations'] != 16 or any(type(v) is not int or v < 0 for v in values)
                or r+s > p or p+u > 16):
            raise ValueError('Original-pass aggregate contradicts the sixteen-point denominator')
        passed += p; regressed += r; selected_unknown += s; original_unknown += u; joined += 1
    original_unknown += (declared-len(rows))*16
    complete = joined == declared and original_unknown == 0 and selected_unknown == 0
    denominator = passed+original_unknown
    return {'joined_episodes': joined, 'unavailable_joins': declared-joined, 'original_verified_S2': passed,
        'verified_regressions': regressed, 'unknown_original_configurations': original_unknown,
        'selected_unknown_on_original_passes': selected_unknown,
        'hidden_regression_rate': regressed/passed if complete and passed else None,
        'status': 'COMPLETE' if complete else 'UNAVAILABLE_OR_INCOMPLETE_ORIGINAL_BASELINE_JOIN',
        'full_matrix_regression_identification_bounds_given_at_least_one_original_pass':
            [regressed/denominator, (regressed+selected_unknown+original_unknown)/denominator] if denominator else None,
        'bounds_are_confidence_intervals': False, 'zero_original_pass_denominator': 'undefined; never substituted with zero'}


def e2_rule_scope(rule, manifest):
    if (rule.get('candidate_denominator') != manifest['candidate_pool_size']
            or rule['near_frontier']['fraction'] != .2 or rule['top_k']['fraction'] != .2):
        raise ValueError('Analysis declaration does not match the fixed E2 pool/subset')
    if any(rule['numeric_ties'][key] != 0 for key in (
            'prediction_absolute_tolerance', 'actual_absolute_tolerance', 'relative_tolerance')):
        raise ValueError('This declaration uses exact numeric ties, not a fitted tolerance')
    if rule.get('status') != 'FROZEN_E2_ANALYSIS_PLAN':
        return 'EXPLORATORY_UNSEALED_ANALYSIS_RULE'
    if (not rule.get('sealed_at_utc') or not rule.get('pause_evidence')
            or rule.get('execution_freeze_id') != manifest['freeze_id']):
        raise ValueError('Prospective declaration is not bound to this execution freeze')
    return 'PROSPECTIVE_SEPARATE_ANALYSIS_AMENDMENT'


def _index(rows, key):
    result = {}
    for row in rows:
        ident = row[key]
        if ident in result:
            raise ValueError('Duplicate recorded identity: '+str(ident))
        result[ident] = row
    return result


def e2_candidates(state):
    """Read current Pool.state.json, retaining absent/unknown full measurements."""
    accepted = _index(state['accepted'], 'stream_index')
    full = _index(state['full_evaluations'], 'stream_index')
    if set(full)-set(accepted):
        raise ValueError('Full measurement is outside the accepted geometry pool')
    rows = []
    for ident, geometry in accepted.items():
        record = full.get(ident)
        complete = record is not None and record.get('complete') is True
        if record is not None and type(record.get('complete')) is not bool:
            raise ValueError('A full attempt must explicitly retain completeness')
        if record and (type(record.get('S2')) is not bool or (record['S2'] and not complete)):
            raise ValueError('An incomplete attempt cannot establish S2')
        actual = record.get('worst_ugb_Hz') if complete else None
        if actual is not None and (not finite(actual) or actual <= 0):
            raise ValueError('Actual UGB must be a finite positive measured value')
        if record and record['S2'] and actual is None:
            raise ValueError('S2 delivery requires its actual UGB')
        row = {'stream_index': ident, **{key: geometry['geometry'].get(key) for key in FEATURES[:2]},
            'complete': complete, 'S1': record.get('S1') if record else None,
            'S2': bool(record and record['S2']), 'worst_ugb_Hz': actual,
            'full_attempted': record is not None, 'corner_metrics': {}}
        physical = state.get('physical_observations', {}).get(str(ident), {})
        row['R_sum_times_C_sum_s'] = (physical.get('post_PEX_features') or {}).get('R_sum_times_C_sum_s')
        nominal = state.get('nominal_observations', {}).get(str(ident), {})
        row['prediction_ugb_Hz'] = (nominal.get('prediction') or {}).get('prediction_ugb_Hz')
        nraw = (nominal.get('nominal_execution') or {}).get('physical_result') or {}
        if nominal.get('nominal_complete') is True:
            row['nominal_tt_ugb_Hz'] = (nraw.get('nominal') or {}).get('metrics', {}).get('tt_ugb_Hz')
            row['nominal_acquisition'] = 'independently_recorded_nominal_stage'
        if record:
            raw = (record.get('full_electrical') or {}).get('physical_result') or {}
            corners = (raw.get('observation') or {}).get('corners') or {}
            row['corner_metrics'] = {corner: value.get('metrics', {}) for corner, value in corners.items()}
            if complete and 'nominal_tt_ugb_Hz' not in row:
                metric = row['corner_metrics'].get('tt', {}).get('ugb', {})
                if metric.get('unit') == 'Hz' and finite(metric.get('value')):
                    row['nominal_tt_ugb_Hz'] = metric['value']
                    row['nominal_acquisition'] = 'TT_trace_inside_full_measurement_not_a_cheap_acquisition'
        for name in FEATURES+PREDICTORS:
            if row.get(name) is not None and not finite(row[name]):
                raise ValueError('Nonfinite acquired feature: '+name)
        rows.append(row)
    return rows


def _rank_table(rows, name, oracle_complete, rule_scope):
    matched = [row for row in rows if row['worst_ugb_Hz'] is not None and finite(row.get(name))]
    result = {'declared_subset_candidates': len(rows), 'matched_measured_pairs': len(matched),
        'unmatched_candidates': len(rows)-len(matched),
        'status': 'COMPLETE_ORACLE_CONDITIONAL_MEASURED_PAIRS' if oracle_complete else 'PARTIAL_CONDITIONAL_MEASURED_PAIRS',
        'inference_scope': 'WITHIN_COMPLETE_RECORDED_ORACLE_POOL' if oracle_complete
            else 'EXPLORATORY_COMPLETE_CASE_SUBSET_NOT_FULL_POOL_PRIMARY',
        'formal_primary_available': oracle_complete and len(matched) >= 2
            and rule_scope == 'PROSPECTIVE_SEPARATE_ANALYSIS_AMENDMENT'}
    if len(matched) < 2:
        return {**result, 'status': 'INSUFFICIENT_MEASURED_PAIRS', 'statistics': None}
    # A negative cheap feature orients the ranking toward smaller geometry/RC.
    diagnostic = rank_diagnostics([(-row[name] if name in FEATURES else row[name]) for row in matched],
        [row['worst_ugb_Hz'] for row in matched], prediction_absolute_tolerance=0,
        actual_absolute_tolerance=0, relative_tolerance=0)
    if name in FEATURES:
        diagnostic = {key: diagnostic[key] for key in ('n', 'spearman_exact_ties', 'kendall_tau_b_declared_ties')}
        result['interpretation'] = 'Descriptive association of smaller feature with larger UGB; not UGB prediction error'
    else:
        result['interpretation'] = 'Same-unit saved UGB estimate versus actual worst-corner UGB'
    result['statistics'] = diagnostic
    result['print_precision_sensitivity'] = {'status': 'UNAVAILABLE',
        'reason': 'No candidate-specific half-ULP intervals propagated through its exact frozen measurement function supplied'}
    return result


def _top_k(rows, name, fraction, oracle_complete):
    k = math.ceil(fraction*len(rows))
    feasible = [row for row in rows if row['S2'] and row['complete']]
    if not oracle_complete:
        return {'status': 'INCOMPLETE_ORACLE', 'k': k, 'recall': None}
    if not feasible:
        return {'status': 'NO_FEASIBLE_ORACLE', 'k': k, 'recall': None}
    if any(not finite(row.get(name)) for row in rows):
        return {'status': 'SCORE_UNAVAILABLE_FOR_ACCEPTED_CANDIDATES', 'k': k, 'recall': None}
    predicted = sorted(rows, key=lambda r: (r[name] if name in FEATURES else -r[name], r['stream_index']))[:k]
    actual = sorted(feasible, key=lambda r: (-r['worst_ugb_Hz'], r['stream_index']))[:k]
    hits = len({r['stream_index'] for r in predicted} & {r['stream_index'] for r in actual})
    return {'status': 'COMPLETE', 'k': k, 'feasible_target_count': len(actual),
        'hits': hits, 'recall': hits/len(actual), 'predicted_indices': [r['stream_index'] for r in predicted],
        'actual_target_indices': [r['stream_index'] for r in actual]}


def e2_costs(state):
    """Deduplicate execution references; component mask/SPICE CPU is not added twice."""
    runs = {}
    def visit(value):
        if isinstance(value, dict):
            if 'run_directory' in value:
                name, cost = value['run_directory'], value.get('cost')
                if name in runs and runs[name] != cost:
                    raise ValueError('Repeated physical run has inconsistent actual costs')
                runs[name] = cost
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(state)
    cpu = wall = 0.; missing_cpu = missing_wall = 0
    stage_counts = Counter(); missing_runs = 0
    for stages in runs.values():
        if stages is None:
            missing_runs += 1
            continue
        for name, stage in stages.items():
            stage_counts[name] += 1
            for key, variable in (('waited_child_CPU_seconds', 'cpu'), ('wall_seconds', 'wall')):
                value = stage.get(key)
                if value is not None and (not finite(value) or value < 0):
                    raise ValueError('Actual cost must be finite and nonnegative')
                if variable == 'cpu':
                    if value is None: missing_cpu += 1
                    else: cpu += value
                else:
                    if value is None: missing_wall += 1
                    else: wall += value
    return {'distinct_execution_runs': len(runs), 'recorded_container_stages': dict(stage_counts),
        'known_waited_child_CPU_seconds': cpu, 'missing_CPU_stage_records': missing_cpu,
        'missing_execution_cost_records': missing_runs,
        'complete_waited_child_CPU_seconds': cpu if missing_cpu == 0 and missing_runs == 0 else None,
        'known_stage_wall_seconds_sum': wall, 'missing_wall_stage_records': missing_wall,
        'queue_wait_seconds_sum': sum(row['queue_wait_seconds'] for row in state.get('dispatch_events', [])),
        'accounting_note': 'Stage wall is a sum, not elapsed experiment wall. Host controller usage is separate. Mask/archive/SPICE components overlap their host/container totals.'}


def e2_pool_table(manifest, pool, state, rule):
    rule_scope = e2_rule_scope(rule, manifest)
    if state['phase'] != 'formal_E2' or state['pool_id'] != pool['pool_id']:
        raise ValueError('Analysis requires the exact formal pool identity')
    if state.get('oracle_labels_read') is not False:
        raise ValueError('Actual online execution cannot have read oracle labels')
    rows = e2_candidates(state)
    declared = manifest['candidate_pool_size']
    if len(rows) > declared:
        raise ValueError('Accepted pool exceeds its fixed denominator')
    oracle_complete = (state['method'] == 'full_oracle' and len(rows) == declared
        and all(row['complete'] for row in rows))
    if any(not finite(row.get(FEATURES[0])) for row in rows):
        raise ValueError('Near-frontier requires the actual area of every accepted geometry')
    near = sorted(rows, key=lambda r: (r[FEATURES[0]], r['stream_index']))[:math.ceil(len(rows)*rule['near_frontier']['fraction'])]
    attempts = state['attempts']
    if len(_index(attempts, 'stream_index')) > 256:
        raise ValueError('Generation attempts exceed the frozen stream')
    curve = []; best = None
    for i, result in enumerate(state['full_evaluations'], 1):
        if result['complete'] and result['S2']:
            best = max(best, result['worst_ugb_Hz']) if best is not None else result['worst_ugb_Hz']
        curve.append({'actual_full_query_attempts': i, 'stream_index': result['stream_index'],
            'complete': result['complete'], 'S2': result['S2'], 'best_verified_feasible_ugb_Hz': best})
    names = FEATURES+PREDICTORS
    feasible = [r['worst_ugb_Hz'] for r in rows if r['S2']]
    return {'pool_id': state['pool_id'], 'source_family': pool['source_family'], 'sizing_id': pool['sizing_id'],
        'method': state['method'], 'execution_scope': state['scope'],
        'analysis_rule_scope': rule_scope, 'status': state['status'], 'declared_candidates': declared,
        'accepted_geometry_candidates': len(rows), 'unfilled_candidate_slots': declared-len(rows),
        'generation_attempts': len(attempts), 'generation_failures': sum(not a['generation_succeeded'] for a in attempts),
        'duplicate_attempts': sum(a.get('duplicate') is not None for a in attempts),
        'full_attempts': len(state['full_evaluations']), 'complete_full_results': sum(r['complete'] for r in rows),
        'known_infeasible_full_results': sum(r['complete'] and not r['S2'] for r in rows),
        'complete_physical_rejections': sum(r['complete'] and r['S1'] is False for r in rows),
        'complete_electrical_rejections': sum(r['complete'] and r['S1'] is True and not r['S2'] for r in rows),
        'unknown_or_NOT_RUN_candidates': declared-sum(r['complete'] for r in rows),
        'verified_feasible': sum(r['S2'] for r in rows), 'oracle_complete': oracle_complete,
        'finite_pool_oracle_defined': oracle_complete and bool(feasible),
        'finite_pool_best_feasible_ugb_Hz': max(feasible) if oracle_complete and feasible else None,
        'broad_pool': {name: _rank_table(rows, name, oracle_complete, rule_scope) for name in names},
        'near_frontier_indices': [r['stream_index'] for r in near],
        'near_frontier': {name: _rank_table(near, name, oracle_complete, rule_scope) for name in names},
        'top_k_recall': {name: _top_k(rows, name, rule['top_k']['fraction'], oracle_complete) for name in names},
        'same_N_prelayout': {'status': 'CONSTANT_WITHIN_FIXED_SIZED_NETLIST_NO_LAYOUT_RANK', 'rank_statistics': None},
        'query_budget_curve': curve, 'wall_budget_curve': {'status': 'UNAVAILABLE_NO_PER_QUERY_RETURN_TIMESTAMPS'},
        'actual_costs': e2_costs(state), 'candidates': rows}


def e2_online_comparison(manifest, pool, oracle, online, same_masks):
    """Post hoc signed gap between independent measurements, not pool replay.

    same_masks reads retained GDS. It does not establish weighted RC or external
    electrical equivalence across the two independently extracted executions.
    """
    if (oracle['method'] != 'full_oracle' or online['method'] == 'full_oracle'
            or any(s['phase'] != 'formal_E2' or s['pool_id'] != pool['pool_id'] for s in (oracle, online))
            or online['scope'] != 'independently_executed_online' or online['oracle_labels_read'] is not False):
        raise ValueError('Independent online versus finite-pool oracle identities are required')
    left, right = (_index(s['accepted'], 'stream_index') for s in (oracle, online))
    orows, actual = e2_candidates(oracle), e2_candidates(online)
    qualifiers = {
        'quality_difference_interpretation': 'observed_cross_extraction_quality_gap',
        'deterministic_counterfactual_regret_established': False,
        'weighted_RC_equivalence_established': False,
        'declared_candidates': manifest['candidate_pool_size'],
        'oracle_accepted_candidates': len(left), 'online_accepted_candidates': len(right),
        'oracle_unknown_or_NOT_RUN': manifest['candidate_pool_size']-sum(r['complete'] for r in orows)}
    if set(left) != set(right) or len(left) != manifest['candidate_pool_size']:
        return {**qualifiers, 'status': 'INCOMPLETE_OR_DIFFERENT_ACCEPTED_POOL', 'regret_Hz': None}
    for ident in sorted(left):
        if not same_masks(left[ident]['gds'], right[ident]['gds']):
            raise ValueError('Actual online and oracle masks differ for accepted stream index '+str(ident))
    complete = all(r['complete'] for r in orows)
    feasible = [r['worst_ugb_Hz'] for r in orows if r['S2']]
    delivered = [r['worst_ugb_Hz'] for r in actual if r['S2']]
    best = max(delivered) if delivered else None
    reference = max(feasible) if complete and feasible else None
    return {**qualifiers, 'status': 'COMPLETE_ORACLE' if complete else 'INCOMPLETE_ORACLE',
        'comparison_scope': 'POST_SEAL_REAL_ONLINE_VERSUS_FINITE_POOL_ORACLE_NOT_OFFLINE_REPLAY',
        'accepted_mask_equality_checked': len(left), 'online_full_attempts': len(online['full_evaluations']),
        'online_unknown_or_NOT_RUN': sum(not r['complete'] for r in actual),
        'online_best_verified_feasible_ugb_Hz': best, 'finite_pool_best_feasible_ugb_Hz': reference,
        'regret_Hz': reference-best if reference is not None and best is not None else None,
        'no_feasible_oracle': complete and not feasible,
        'note': 'Independent numeric measurements are preserved. The signed difference is not clamped. Mask equality alone does not establish a single deterministic oracle or nonnegative counterfactual regret.'}


def e3_supplement(manifest, episodes, metadata=None):
    """Frozen strata and original-pass regression aggregates, retaining NOT_RUN."""
    replicates = manifest['analysis']['cluster_bootstrap_replicates']
    seed = manifest['analysis']['bootstrap_seed']
    primary = primary_e3(manifest, episodes, replicates, seed)
    tasks = _index(manifest['tasks'], 'task_id')
    if len({r['source_group'] for r in tasks.values()}) != 8 or len({r['merged_source_group'] for r in tasks.values()}) != 7:
        raise ValueError('E3 uncertainty retains eight logical and seven merged source groups')
    rows = {(r['task_id'], r['method'], str(r['trial_id'])): r for r in episodes}
    result = {'primary': primary, 'regression': {m: regression_summary(
        [r for r in episodes if r['method'] == m], len(tasks)*5) for m in ('A', 'R', 'B', 'C')},
        'strata': {'status': 'UNAVAILABLE_FROZEN_PUBLIC_METADATA_NOT_SUPPLIED'},
        'QoR_table': {'status': 'UNAVAILABLE_PUBLIC_HIDDEN_SUMMARY_HAS_COVERAGE_ONLY',
            'note': 'Area and UGB/area have different units. No hidden QoR vector or normalized improvement is inferred from coverage.'}}
    if metadata is None:
        return result
    tags = _index(metadata['tasks'], 'task_id')
    if (metadata.get('status') != 'FROZEN_E3_PUBLIC_TASK_METADATA'
            or metadata.get('freeze_id') != manifest['freeze_id'] or set(tags) != set(tasks)):
        raise ValueError('Strata require metadata exported from this actual frozen task set')
    for ident in tags:
        if any(tags[ident][k] != tasks[ident][k] for k in ('source_group', 'merged_source_group')):
            raise ValueError('Stratum metadata changed source ancestry')
        if tags[ident].get('injected_defect') is not None and type(tags[ident]['injected_defect']) is not bool:
            raise ValueError('Injection is an explicit frozen boolean, not a guessed source label')
    strata = {}
    for dimension in ('injection', 'initial_category', 'OOD', 'topology'):
        groups = defaultdict(set)
        for ident, tag in tags.items():
            if dimension == 'injection':
                value = {True: 'injected', False: 'non_injected', None: 'unknown'}[tag.get('injected_defect')]
            else:
                value = tag.get(dimension, 'unknown')
            groups[value].add(ident)
        if dimension == 'injection':
            groups.setdefault('injected', set()); groups.setdefault('non_injected', set())
        strata[dimension] = {}
        for label, ids in sorted(groups.items()):
            methods = {}; paired = []
            for method in ('A', 'R', 'B', 'C'):
                found = [r for (ident, m, _), r in rows.items() if ident in ids and m == method]
                n = len(ids)*5; p = sum(r['hidden_S2_verified'] for r in found)
                u = sum(r['hidden_incomplete'] for r in found)+(n-len(found))*16
                methods[method] = {'declared_episodes': n, 'recorded_episodes': len(found),
                    'NOT_RUN_episodes': n-len(found), 'verified_hidden_S2': p, 'unknown_or_NOT_RUN': u,
                    'coverage': p/(n*16) if n and not u else None,
                    'identification_bounds': [p/(n*16), (p+u)/(n*16)] if n else None}
            for ident in sorted(ids):
                records = {m: [rows.get((ident, m, str(t))) for t in range(1, 6)] for m in methods}
                if all(r is not None and r['hidden_incomplete'] == 0 for rs in records.values() for r in rs):
                    paired.append({**tasks[ident], 'method_S2_rates': {m: mean(r['hidden_S2_verified']/16 for r in rs)
                        for m, rs in records.items()}})
            effects = []
            if ids and len(paired) == len(ids):
                for left, right in (('C', 'R'), ('C', 'B')):
                    for group in ('source_group', 'merged_source_group'):
                        effects.append(paired_cluster_effect(paired, left, right, group, replicates, seed))
            strata[dimension][label] = {'tasks': sorted(ids), 'methods': methods,
                'fully_paired_tasks': len(paired), 'paired_cluster_contrasts': effects}
    result['strata'] = {'status': 'FROZEN_METADATA_ONLY', 'tables': strata,
        'note': 'Non-injected does not assert an uncurated production bug. Empty strata have no effect estimate. No OOD/topology label is inferred from names.'}
    return result


def e3_search_events(state, points, report, budget_seconds):
    """Export only already-visible search observations; never post-freeze events."""
    start = datetime.fromisoformat(state['created_at_utc'])
    deadline = datetime.fromisoformat(state['deadline_utc'])
    if (report['method'] != state['method'] or str(report['trial_id']) != str(state.get('trial_id'))
            or report['formal_trial'] != state['formal_trial']):
        raise ValueError('Search state and public report identify different episodes')
    result = []; seen = set()
    for event in state['physical_events']:
        if event['stage'] != 'search':
            continue
        row = {'configuration_id': event['configuration_id'], 'revision': event['revision'], 'status': event['status'],
            'actual_point_attempts': len(result)+1, 'elapsed_seconds': None,
            'S0': None, 'S1': None, 'S2': None, 'objective': None}
        if event['status'] == 'RETURNED':
            path = event['point_record']
            if path in seen:
                raise ValueError('A physical point appears twice in search events')
            seen.add(path)
            point = points[path]
            if point['task_id'] != report['task_id'] or point['configuration_id'] != event['configuration_id']:
                raise ValueError('Search event belongs to another actual point')
            end = datetime.fromisoformat(event['ended_at_utc'])
            elapsed = (end-start).total_seconds()
            if elapsed < 0:
                raise ValueError('Actual return predates episode start')
            valid = point['checked']['execution_integrity'] == 'valid'
            objective = point['objective']
            if objective is not None and not finite(objective):
                raise ValueError('Nonfinite measured QoR')
            row.update(elapsed_seconds=elapsed, within_search_budget=end <= deadline,
                execution_integrity=point['checked']['execution_integrity'],
                **{tier: point['checked'][tier] if valid else None for tier in ('S0', 'S1', 'S2')},
                objective=objective if valid and point['checked']['S2'] else None,
                objective_definition=point['objective_definition'])
        result.append(row)
    return {'task_id': report['task_id'], 'method': state['method'], 'trial_id': state.get('trial_id'),
        'episode_status': state['status'], 'formal_trial': state['formal_trial'],
        'policy_variant': state.get('policy_variant', 'GPT'), 'selector_variant': state.get('selector_variant', 'main'),
        'search_budget_seconds': budget_seconds,
        'actual_deadline_relative_to_recorded_start_seconds': (deadline-start).total_seconds(),
        'scope': 'VISIBLE_SEARCH_ONLY_ACTUAL_HOST_REINSPECTION_RETURN_TIMES', 'events': result,
        'hidden_events_exported': 0, 'internal_stage_completion_times_inferred': False}


def e3_budget_curves(manifest, searches):
    """Success within search time, not hidden-domain coverage or final-source QoR."""
    tasks = _index(manifest['tasks'], 'task_id'); records = {}
    budget = manifest['budget']['wall_seconds']
    for row in searches:
        key = row['task_id'], row['method'], str(row['trial_id'])
        if (key[0] not in tasks or key[1] not in ('A', 'R', 'B', 'C') or key[2] not in ('1', '2', '3', '4', '5')
                or row['formal_trial'] is not True or row.get('policy_variant') != 'GPT'
                or row.get('selector_variant') != 'main' or row.get('hidden_events_exported') != 0
                or row['search_budget_seconds'] != budget or key in records):
            raise ValueError('Budget curve event index is outside the fixed main E3 matrix')
        records[key] = row
    methods = {}
    for method in ('A', 'R', 'B', 'C'):
        rows = [r for (_, m, _), r in records.items() if m == method]
        n = len(tasks)*5
        tiers = {}
        for tier in ('S0', 'S1', 'S2'):
            first = []; unresolved = n-len(rows)
            for row in rows:
                times = [e['elapsed_seconds'] for e in row['events'] if e.get(tier) is True
                    and e.get('within_search_budget') is True]
                first.append(min(times) if times else None)
                if (not times and (row['episode_status'] in ('INCOMPLETE_UNKNOWN', 'RUNNING')
                        or any(e['status'] != 'RETURNED' or e.get('execution_integrity') not in ('valid', 'budget_exhausted')
                            for e in row['events']))):
                    unresolved += 1
            grid = sorted({0., float(budget), *(v for v in first if v is not None)})
            tiers[tier] = {'first_verified_times_seconds': first,
                'unresolved_or_NOT_RUN_without_verified_feedback': unresolved,
                'curve': [{'seconds': t, 'verified': sum(v is not None and v <= t for v in first),
                    'declared_episodes': n,
                    'success_identification_bounds': [sum(v is not None and v <= t for v in first)/n,
                        (sum(v is not None and v <= t for v in first)+unresolved)/n]} for t in grid]}
        methods[method] = {'declared_episodes': n, 'recorded_searches': len(rows), 'tiers': tiers}
    return {'scope': 'Actual within-budget search feedback; repeated revisions do not establish final hidden coverage',
        'methods': methods, 'timing': 'Actual whole-call host reinspection return; no internal stage time inferred',
        'bounds_are_confidence_intervals': False}
