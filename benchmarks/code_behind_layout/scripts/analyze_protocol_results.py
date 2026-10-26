"""Explicit-index E2 tables and E3 public strata/regression/search-time tables.

Software-only analysis; never dispatches a model, physical point or hidden oracle.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.protocol_result_tables import e2_pool_table, e2_online_comparison, e3_supplement, e3_search_events, e3_budget_curves


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False)+'\n')


def index(path):
    """Indexes are explicit JSONL records; no globs can mix cohorts."""
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def load_episodes(path, manifest):
    episodes = []
    for entry in index(path):
        row = read(entry['episode_json'])
        if row.get('formal_trial') is not True or str(row['trial_id']) != str(entry['trial_id']):
            raise ValueError('Index/report trial mismatch or development result')
        if not all(key in row for key in ('hidden_domain_size', 'hidden_S2_verified', 'hidden_incomplete')):
            if any(key in row for key in ('hidden_domain_size', 'hidden_S2_verified', 'hidden_incomplete')):
                raise ValueError('Partial hidden summary cannot establish a denominator')
            # A sealed search before the shared release supplies no hidden results.
            row.update(hidden_domain_size=16, hidden_S2_verified=0, hidden_incomplete=16,
                hidden_summary_status='NOT_EVALUATED_UNKNOWN')
        if entry.get('regression_json'):
            join = read(entry['regression_json'])
            if (join['episode_directory'] != entry['episode_directory']
                    or join['sealed_source_revision'] != row['selection']['revision']
                    or join['task_id'] != row['task_id'] or join['method'] != row['method']
                    or str(join['trial_id']) != str(row['trial_id'])):
                raise ValueError('Regression join is not bound to the actual sealed episode/source')
            row['regression_join'] = join
        episodes.append(row)
    return episodes


def e2(manifest_path, rule_path, state_index):
    manifest, rule = read(manifest_path), read(rule_path)
    if manifest['status'] != 'FROZEN' or manifest.get('formal_execution_allowed') is not True:
        raise ValueError('E2 formal tables require the actual execution freeze')
    pools = {p['pool_id']: p for p in manifest['pools']}
    expected = {(p['pool_id'], method) for p in pools.values() for method in
        (('full_oracle', 'fixed_area', 'adaptive_geometry', 'fixed_rc_product', 'f3_calibrated')
            if p['online_selected'] else ('full_oracle',))}
    states = {}; tables = []
    for entry in index(state_index):
        path = Path(entry['state_json']); state = read(path)
        execution = read(entry.get('execution_json', path.parent.parent/'execution.json'))
        if (Path(execution['manifest']).resolve() != Path(manifest_path).resolve()
                or execution.get('formal') is not True or execution['method'] != state['method']
                or state['pool_id'] not in execution['pool_ids']):
            raise ValueError('Pool state is not linked to this frozen execution')
        key = state['pool_id'], state['method']
        if key in states or key not in expected:
            raise ValueError('Duplicate or undeclared pool/method state')
        states[key] = state
        tables.append(e2_pool_table(manifest, pools[key[0]], state, rule))
    comparisons = []
    for (pool_id, method), online in states.items():
        if method == 'full_oracle':
            continue
        oracle = states.get((pool_id, 'full_oracle'))
        if oracle is None:
            comparisons.append({'pool_id': pool_id, 'method': method, 'status': 'ORACLE_NOT_SUPPLIED',
                'regret_Hz': None, 'quality_difference_interpretation': 'observed_cross_extraction_quality_gap',
                'deterministic_counterfactual_regret_established': False,
                'declared_candidates': manifest['candidate_pool_size'],
                'oracle_unknown_or_NOT_RUN': manifest['candidate_pool_size']})
            continue
        excluded = [r['geometry']['canonical_masks']['excluded_layer_datatypes'] for s in (oracle, online) for r in s['accepted']]
        if excluded and any(value != excluded[0] for value in excluded):
            raise ValueError('Frozen mask annotation exclusions differ between executions')
        def equal(first, second):
            from src.e2_mask_geometry import read_masks, same_masks
            return same_masks(read_masks(Path(first), excluded[0] if excluded else ()),
                read_masks(Path(second), excluded[0] if excluded else ()))
        comparisons.append({'pool_id': pool_id, 'method': method,
            **e2_online_comparison(manifest, pools[pool_id], oracle, online, equal)})
    return {'scope': 'Recorded E2 finite-pool/independent online executions; not a retrospective online-saving claim',
        'freeze_id': manifest['freeze_id'], 'analysis_id': rule['analysis_id'],
        'declaration_blinding_disclosure': 'The separate statistics amendment was electrical-outcome blind, not geometry blind: geometry progress/metadata (about11-12 accepted per method) had been read. At sealing all five methods had zero PEX, nominal and full acquisitions. The sealed no_formal_results_read_for_this_draft literal is narrower in its substantiated meaning; original bytes are preserved.',
        'declared_pool_method_executions': len(expected), 'recorded_pool_method_executions': len(states),
        'NOT_RUN': [{'pool_id': p, 'method': m} for p, m in sorted(expected-set(states))],
        'pool_tables': tables, 'real_online_comparisons': comparisons,
        'offline_replay': {'status': 'NOT_COMPUTED_BY_THIS_CONSUMER',
            'interpretation': 'pool_bound_replay_of_one_recorded_oracle',
            'note': 'Do not substitute oracle-backed retrospective replay for the independently measured online runs.'}}


def export_e3_metadata(manifest_path):
    """Read frozen ancestry/qualification only; output no configuration tables."""
    manifest = read(manifest_path)
    if manifest['status'] != 'FROZEN_E3' or Path(manifest_path).stat().st_mode & 0o222:
        raise ValueError('Metadata export requires the actual readonly E3 freeze')
    inspection = read(Path(manifest['qualification'])/'raw_reinspection.json')
    witnesses = {r['task_id']: r for r in inspection['witnesses']}
    tasks = []
    for declared in manifest['tasks']:
        filename = Path(manifest['preparation'])/'private'/declared['task_id']/'task.json'
        task = read(filename)
        if (task['status'] != 'FROZEN_E3_TASK' or task['formal_admission'] is not True
                or task['task_id'] != declared['task_id']
                or task['logical_group'] != declared['source_group']
                or task['merge_sensitivity_group'] != declared['merged_source_group']
                or filename.stat().st_mode & 0o222):
            raise ValueError('Task metadata is not from the declared readonly frozen task')
        ancestry = task['ancestry']
        tasks.append({**declared, 'origin': ancestry['origin'],
            'injected_defect': ancestry.get('injected_defect'),
            'production_natural_bug_claimed': ancestry.get('production_natural_bug_claimed'),
            'initial_category': witnesses[task['task_id']]['classification'],
            'initial_shortfall_witness_established': witnesses[task['task_id']]['qualifies_shortfall'],
            'OOD': task.get('ood_status', 'unknown'), 'topology': task.get('topology_family', 'unknown'),
            'metadata_source': str(filename), 'qualification_source': str(Path(manifest['qualification'])/'raw_reinspection.json')})
    return {'status': 'FROZEN_E3_PUBLIC_TASK_METADATA', 'freeze_id': manifest['freeze_id'],
        'tasks': tasks, 'hidden_parameters_exported': False, 'hidden_measurements_exported': False,
        'note': 'Origin/injection and initial qualification describe frozen development inputs, not formal policy outcomes.'}


def export_e3_searches(manifest_path, episode_index):
    manifest = read(manifest_path)
    if manifest['status'] != 'FROZEN_E3':
        raise ValueError('Search events require the actual E3 freeze')
    results = []
    for entry in index(episode_index):
        directory = Path(entry['episode_directory'])
        binding = read(directory/'private/manifest.json')
        if binding['freeze_id'] != manifest['freeze_id'] or binding['implementation_sha256'] != manifest['implementation_sha256']:
            raise ValueError('Search episode belongs to another frozen implementation')
        state = read(directory/'private/state.json')
        report = read(directory/'public/search.json')
        if report['formal_trial'] is not True or str(report['trial_id']) != str(entry['trial_id']):
            raise ValueError('Search index/report mismatch or development episode')
        # Do not read any point whose event stage is post-freeze/hidden.
        points = {e['point_record']: read(e['point_record']) for e in state['physical_events']
            if e['stage'] == 'search' and e['status'] == 'RETURNED'}
        results.append(e3_search_events(state, points, report, manifest['budget']['wall_seconds']))
    return {'status': 'ACTUAL_E3_VISIBLE_SEARCH_EVENT_EXPORT', 'freeze_id': manifest['freeze_id'],
        'searches': results, 'hidden_point_records_exported': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    pool = sub.add_parser('e2'); pool.add_argument('--rule', type=Path, required=True); pool.add_argument('--pool-index', type=Path, required=True)
    e3 = sub.add_parser('e3'); e3.add_argument('--episode-index', type=Path, required=True); e3.add_argument('--metadata', type=Path); e3.add_argument('--search-events', type=Path)
    sub.add_parser('export-e3-metadata')
    events = sub.add_parser('export-e3-search-events'); events.add_argument('--episode-index', type=Path, required=True)
    for command in (pool, e3, sub.choices['export-e3-metadata'], events):
        command.add_argument('--manifest', type=Path, required=True); command.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'e2':
        result = e2(args.manifest, args.rule, args.pool_index)
    elif args.command == 'export-e3-metadata':
        result = export_e3_metadata(args.manifest)
    elif args.command == 'export-e3-search-events':
        result = export_e3_searches(args.manifest, args.episode_index)
    else:
        manifest = read(args.manifest)
        if manifest['status'] != 'FROZEN_E3':
            raise ValueError('Formal E3 analysis requires its actual freeze')
        result = e3_supplement(manifest, load_episodes(args.episode_index, manifest), read(args.metadata) if args.metadata else None)
        if args.search_events:
            events = read(args.search_events)
            if events['status'] != 'ACTUAL_E3_VISIBLE_SEARCH_EVENT_EXPORT' or events['freeze_id'] != manifest['freeze_id']:
                raise ValueError('Search timing index belongs to another cohort')
            result['search_budget_curves'] = e3_budget_curves(manifest, events['searches'])
        else:
            result['search_budget_curves'] = {'status': 'UNAVAILABLE_ACTUAL_SEARCH_EVENT_INDEX_NOT_SUPPLIED'}
    write(args.output, result)
    print(json.dumps({'status': 'SOFTWARE_ANALYSIS_WRITTEN', 'output': str(args.output), 'new_model_or_EDA_calls': 0}))


if __name__ == '__main__':
    main()
