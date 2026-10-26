"""Report actual train collection yield and the measured scaling bottleneck."""
import ast
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
MODULES = ['textbook_sharing/layout.py', 'glayout/sharing/enumeration.py']


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def program(sources, original):
    complete = {**original, **sources}
    result = []
    for name in MODULES:
        text = complete[name]
        try:
            identity = ('AST', ast.dump(ast.parse(text), include_attributes=False))
        except (SyntaxError, ValueError):
            identity = ('unparsed_exact_source', text)
        result.append((name, identity))
    return tuple(result)


def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def admission_inventory(directories):
    """Count already readmitted rows; do not rerun or replace the physical gate.

    Different diffs reaching the same exact AST pair are one comparison. Circuit
    and complete initial program define the conservative independent context;
    physical-domain identities additionally separate preference consistency.
    The v1 and v2 selection cohorts are never pooled as additional examples.
    """
    pools, cohorts = [], {}
    for directory in sorted({Path(value).resolve() for value in directories}):
        admission = read(directory / 'physical_readmission.json')
        selection = read(directory / 'student_selection.json')
        if not admission or admission.get('status') != 'RE_ADMITTED_FROM_RAW':
            pools.append({'directory': str(directory), 'status': 'NOT_RE_ADMITTED_OR_QUARANTINED'})
            continue
        if not selection or not selection.get('raw_evidence_re_admitted'):
            raise ValueError('Readmitted student selection metadata is absent: ' + str(directory))
        raw_root = Path(selection['raw_collection_root'])
        manifest = read(raw_root / 'collection_manifest.json')
        registry = read(raw_root / 'effective_registry.json')
        original = {name: (Path(manifest['source_pack']) / name).read_text() for name in MODULES}
        points = registry['configurations']
        circuits = {point['parameters']['circuit']['circuit_id'] for point in points}
        if len(circuits) != 1:
            raise ValueError('An admitted pool must declare one actual circuit: ' + str(raw_root))
        cid = next(iter(circuits))
        rule = read(Path(selection.get('selection_rule') or manifest['label_rule_path']))
        if not rule or rule.get('status') != 'frozen':
            raise ValueError('The real frozen selection rule is unavailable: ' + str(directory))
        cohort_name = rule.get('sft_selection', {}).get('version', 'unique_best_v1')
        cohort = cohorts.setdefault(cohort_name, {'sft': set(), 'pairs': set(), 'orientations': {},
            'initial_programs': set(), 'final_programs': set(), 'physical_contexts': set(),
            'method_rows': Counter(), 'same_terminal_pairs_excluded': set(), 'same_program_sft_excluded': 0})
        candidates = {row['candidate_id']: row for row in jsonl(raw_root / 'candidates.jsonl')}
        domain = json.dumps([point['parameters'] for point in points], sort_keys=True, separators=(',', ':'))
        usable = {}
        for method in ('T1', 'T2', 'T3', 'T4'):
            rows = jsonl(directory / (method + '.jsonl'))
            usable[method] = len(rows)
            cohort['method_rows'][method] += len(rows)
            for sample in rows:
                raw = sample['raw_sample']
                if raw.get('source_role') != 'formal_train':
                    raise ValueError('Only admitted train rows belong in this inventory')
                context = json.loads(raw['context'])
                base = context['base_source']
                initial = program(base, original)
                key = (cid, initial)
                physical_key = (key, domain, json.dumps(context['visible_contract']['contract'], sort_keys=True))
                cohort['initial_programs'].add(initial)
                cohort['physical_contexts'].add(physical_key)
                def terminal(candidate_id, patch):
                    candidate = candidates[candidate_id]
                    if (candidate['candidate_patch'] != patch or candidate['base_source'] != base or
                        candidate['initial_state_id'] != raw['initial_state_id']):
                        raise ValueError('Derived target differs from its actual admitted candidate/source binding')
                    return program(candidate['candidate_source'], original)
                if method in ('T1', 'T2'):
                    end = terminal(raw['candidate_id'], raw['patch'])
                    cohort['final_programs'].add(end)
                    if end == initial:
                        cohort['same_program_sft_excluded'] += 1
                    else:
                        cohort['sft'].add(key)
                else:
                    chosen = terminal(raw['chosen_candidate_id'], raw['chosen'])
                    rejected = terminal(raw['rejected_candidate_id'], raw['rejected'])
                    pair = (key, frozenset((chosen, rejected)))
                    cohort['final_programs'].update((chosen, rejected))
                    if chosen == rejected:
                        cohort['same_terminal_pairs_excluded'].add(pair)
                        continue
                    cohort['pairs'].add(pair)
                    direction = cohort['orientations'].setdefault((physical_key, pair[1]), {'T3': set(), 'T4': set()})
                    direction[method].add((chosen, rejected))
        pools.append({'directory': str(directory), 'raw_collection_root': str(raw_root),
            'status': admission['status'], 'selection_cohort': cohort_name, 'circuit_id': cid,
            'usable_rows_by_method': usable, 'collection_scope': selection.get('collection_scope'),
            'raw_completion': read(raw_root / 'completion.json')})
    counts = {}
    for name, group in cohorts.items():
        opposite = sum(any((b, a) in values['T4'] for a, b in values['T3'])
                       for values in group['orientations'].values())
        inconsistent = sum(any(len(values[method]) > 1 for method in ('T3', 'T4'))
                           for values in group['orientations'].values())
        counts[name] = {'unique_useful_student_initial_contexts_after_current_gate': len(group['sft']),
            'unique_usable_DPO_pairs_after_current_gate': len(group['pairs']),
            'unique_usable_DPO_initial_contexts_after_current_gate': len({pair[0] for pair in group['pairs']}),
            'unique_admitted_initial_full_programs': len(group['initial_programs']),
            'unique_admitted_terminal_full_programs': len(group['final_programs']),
            'unique_visible_physical_problem_contexts': len(group['physical_contexts']),
            'Point_Family_opposite_pairs_by_physical_problem': opposite,
            'pairs_with_multiple_observed_preferences_within_one_method': inconsistent,
            'same_terminal_AST_pairs_excluded': len(group['same_terminal_pairs_excluded']),
            'same_initial_terminal_AST_SFT_rows_excluded': group['same_program_sft_excluded'],
            'raw_usable_rows_by_method_before_cross_pool_dedup': dict(group['method_rows'])}
    return {'status': 'ACTUAL_READMITTED_DATA_INVENTORY_NO_NEW_PHYSICS',
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'selection_cohorts': counts, 'derived_pools': pools,
        'identity': 'Circuit plus both complete initial module ASTs; unordered pair of actual candidate terminal module ASTs. Literal constants/names/docstrings retained; unparsed Python uses exact text. Preference consistency additionally binds public physical contract/domain.',
        'v1_and_v2_counts_are_alternatives_not_additional_data': True,
        'counts_are_already_derived_admitted_rows_not_a_fresh_physical_audit': True,
        'new_model_calls': 0, 'new_physical_calls': 0, 'formal_training_runs': 0}


def main(args):
    derived_directories = [Path(path) for path in args.admission_directory]
    if args.admission_index:
        derived_directories += [Path(path) for path in read(args.admission_index)['derived_directories']]
    if args.admissions_only:
        if not derived_directories:
            raise ValueError('Select the actual admitted directories explicitly')
        report = admission_inventory(derived_directories)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
        print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
        return
    collections = []
    program_groups, initial_contexts, final_programs = {}, set(), set()
    actual_programs, actual_contexts = set(), set()
    all_stage_wall, all_stage_cpu, raw_bytes = [], [], 0
    next_states = []
    for path in sorted((ROOT / 'runtime/train_collections').glob('*/collection.json')):
        manifest = read(path)
        if manifest['collection_id'].endswith('_student_readmission_v1'):
            continue
        registry = read(Path(manifest['registry_path']))
        original = {name: (Path(manifest['source_pack']) / name).read_text() for name in MODULES}
        cid = registry['configurations'][0]['parameters']['circuit']['circuit_id']
        states = [json.loads(line) for line in Path(manifest['initial_states_path']).read_text().splitlines() if line.strip()]
        source_states = {state['initial_state_id']: state for state in states}
        output = Path(manifest['output_root'])
        attempts = read(output / 'attempts.json', [])
        completion = read(output / 'completion.json')
        model_attempts = [a for a in attempts if a.get('inference_id')]
        tokens = Counter()
        for attempt in model_attempts:
            usage = attempt.get('usage') or {}
            if 'public_cli_usage' in usage:
                for key, value in (usage.get('public_cli_usage') or {}).items():
                    if isinstance(value, (int, float)):
                        tokens['GPT_public_' + key] += value
            else:
                for key in ['input_tokens', 'output_tokens', 'cuda_stream_elapsed_seconds', 'generation_wall_seconds']:
                    if isinstance(usage.get(key), (int, float)):
                        tokens['Qwen_' + key] += usage[key]
        for state in states:
            identity = program(state['base_source'], original)
            program_groups.setdefault(identity, []).append({'collection': manifest['collection_id'], 'state': state['initial_state_id'], 'circuit': cid})
            initial_contexts.add((cid, identity))
            if (output / state['initial_state_id'] / 'baseline_results.json').exists():
                actual_programs.add(identity)
                actual_contexts.add((cid, identity))
        candidate_rows = [json.loads(line) for line in (output / 'candidates.jsonl').read_text().splitlines() if line.strip()] if (output / 'candidates.jsonl').exists() else []
        for row in candidate_rows:
            identity = program(row['candidate_source'], original)
            final_programs.add(identity)
            base = source_states[row['initial_state_id']]
            if identity != program(base['base_source'], original):
                next_states.append({'parent_collection': manifest['collection_id'], 'candidate_id': row['candidate_id'],
                    'parent_initial_state_id': row['initial_state_id'], 'circuit_id': cid,
                    'candidate_row_path': str(output / 'candidates.jsonl'), 'origin': 'naturally_generated_candidate',
                    'actual_complete_domain_points': len(row['outcomes']),
                    '_program_identity': identity,
                    'not_yet_frozen_or_labelled': True})
        physical = list((output / 'physical').glob('*/manifest.json'))
        wall, cpu, missing_usage = [], [], 0
        for run in physical:
            physical_manifest = read(run)
            point_wall = 0
            for stage, directory in [('candidate', 'candidate_stage'), ('trusted', 'trusted_stage')]:
                point_wall += (physical_manifest.get(stage) or {}).get('wall_seconds', 0)
                usage = read(run.parent / directory / 'resource_usage.json')
                if usage:
                    cpu.append(usage['child_user_cpu_seconds'] + usage['child_system_cpu_seconds'])
                elif physical_manifest.get(stage):
                    missing_usage += 1
            wall.append(point_wall)
        # Count file sizes without reading/log-copying active physical evidence.
        bytes_here = sum(p.stat().st_size for p in output.rglob('*') if p.is_file()) if output.exists() else 0
        raw_bytes += bytes_here
        all_stage_wall.extend(wall)
        all_stage_cpu.extend(cpu)
        re_admission = Path(str(output) + '_student_readmission_v1')
        admission = read(re_admission / 'physical_readmission.json')
        usable = {}
        if admission and admission['status'] == 'RE_ADMITTED_FROM_RAW':
            derived_directories.append(re_admission)
            for method in ['T1', 'T2', 'T3', 'T4']:
                rows = [json.loads(line) for line in (re_admission / (method + '.jsonl')).read_text().splitlines() if line.strip()]
                usable[method] = len(rows)
        collections.append({'collection': manifest['collection_id'], 'manifest': str(path), 'circuit_id': cid,
            'source_lineage': states[0]['parent_lineage'], 'planned_initial_states': len(states),
            'planned_proposals': len(states) * 8, 'actual_attempt_records': len(attempts),
            'actual_distinct_inference_ids': len({a['inference_id'] for a in model_attempts}),
            'attempt_statuses': dict(Counter(a['status'] for a in attempts)),
            'completion': completion, 'candidate_sources_with_full_9point_records': len(candidate_rows),
            'physical_run_manifests': len(physical), 'completed_physical_point_walls_seconds': wall,
            'waited_child_cpu_seconds': sum(cpu), 'stages_with_unavailable_cpu': missing_usage,
            'raw_directory_bytes': bytes_here, 'actual_usage': dict(tokens),
            'current_gate_student_usable_counts': usable,
            'admission_state': admission['status'] if admission else 'NOT_RE_ADMITTED_OR_INCOMPLETE',
            'exact_execute_command': ['runtime/training-venv/bin/python', 'scripts/run_frozen_training_collection.py' if manifest.get('frozen_collector_entrypoint') else 'scripts/collect_training.py', '--manifest', str(path), '--execute']})
    for candidate in next_states:
        candidate['not_already_in_any_frozen_initial_program_pool'] = candidate.pop('_program_identity') not in program_groups
    complete = [c for c in collections if c['completion']]
    completed_inferences = sum(c['actual_distinct_inference_ids'] for c in complete)
    median_wall = statistics.median(all_stage_wall) if all_stage_wall else None
    total_points = 1000 * 9 * (1 + 8)
    inventory = admission_inventory(derived_directories)
    # Report the original rule as the primary pilot count; v2 remains a separate
    # train-only sensitivity cohort instead of increasing the data denominator.
    primary = inventory['selection_cohorts'].get('unique_best_v1', {})
    useful_count = primary.get('unique_useful_student_initial_contexts_after_current_gate', 0)
    pair_count = primary.get('unique_usable_DPO_pairs_after_current_gate', 0)
    report = {'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'Measured collection pipeline pilot; main benchmark and formal model training are incomplete',
        'planned_unique_initial_full_programs': len(program_groups),
        'actually_started_unique_initial_full_programs': len(actual_programs),
        'planned_unique_initial_circuit_program_contexts': len(initial_contexts),
        'actually_started_unique_initial_circuit_program_contexts': len(actual_contexts),
        'unique_physical_candidate_final_full_programs': len(final_programs),
        'unique_useful_student_initial_contexts_after_current_gate': useful_count,
        'unique_usable_DPO_pairs_after_current_gate': pair_count,
        'unique_usable_DPO_initial_contexts_after_current_gate': primary.get('unique_usable_DPO_initial_contexts_after_current_gate', 0),
        'admitted_data_inventory': inventory,
        'completed_or_paused_collection_actual_model_requests': completed_inferences,
        'all_actual_model_requests_including_inflight_collections': sum(c['actual_distinct_inference_ids'] for c in collections),
        'source_lineages': len({c['source_lineage'] for c in collections}),
        'formal_model_training_runs': 0,
        'collections': collections, 'natural_candidate_initial_state_inventory': next_states,
        'actual_physical_costs': {'returned_physical_run_samples_including_failures': len(all_stage_wall),
            'median_candidate_plus_trusted_stage_wall_seconds': median_wall,
            'waited_child_cpu_seconds': sum(all_stage_cpu), 'raw_directory_bytes': raw_bytes},
        '1000_useful_SFT_context_scale': {'target_useful_independent_initial_task_contexts': 1000,
            'observed_current_usable_contexts': useful_count, 'remaining': 1000 - useful_count,
            '8_proposals_each_at_100percent_initial_state_success': 8000,
            'baseline_plus_8_unique_candidates_9point_upper_work_envelope': total_points,
            'stage_wall_hours_at_current_measured_median_before_parallelism': total_points * median_wall / 3600 if median_wall else None,
            'not_a_completion_time_or_success_rate_forecast': True,
            'reason': 'Teacher duplicates, noops, patch invalidity, interface limits and physical ties dominate the observed yield. One repaired source is insufficient to estimate independent-state success probability. DPO pairs and copied geometry points are not independent SFT states.'},
        'next_dispatch_rule': 'The unique coordinator adopts current collectors without restarting them. GPT stage order is C01 ACTION8→C07 ACTION8→C08 minimal→three natural C05 ACTION initial states, with a shared two-slot transport and actual CPU/RAM dispatch gates. Original C05 partial24/8/16 plan is retained. No artificial inverse fault injection or repeated source/patch pairs.',
        'program_identity_definition': 'Two complete modules merged with the exact frozen original for noneditable members, ast.dump(include_attributes=False) preserving literals/names/docstrings; invalid Python uses exact original text. No numeric normalization.'}
    out = args.output
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key not in ['collections', 'natural_candidate_initial_state_inventory']}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admission-directory', action='append', default=[])
    parser.add_argument('--admission-index', type=Path)
    parser.add_argument('--admissions-only', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'results/derived/training_pilot_actual_yield.json')
    main(parser.parse_args())
