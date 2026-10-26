"""Prepare a train-only collection DRAFT after all nine fresh controls qualify.

No registry, source assignment, existing collection or raw result is modified.
This preparation does not freeze, dispatch, label or train anything.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.train_pair_nf_physical_qualification import inspect_result, read, save
from scripts.audit_train_pair_nf_rc import audit as audit_full_rc


def prepare(qualification, output):
    qualification = Path(qualification).resolve()
    state = read(qualification / 'state.json')
    plan = read(Path(state['preparation']) / 'plan.json')
    points, records = plan['configurations'], state['records']
    if (state['status'] != 'COMPLETED_FIXED_NINE_PHYSICAL_ATTEMPTS'
            or len(points) != 9 or len(records) != 9 or state['not_started']
            or [row['configuration_id'] for row in records] != [p['configuration_id'] for p in points]):
        raise ValueError('The full original nine-point qualification must terminate before collection preparation')
    trusted_root = Path(plan['trusted_bundle'])
    trusted = {str(path.relative_to(trusted_root)): path.read_text()
               for path in sorted(trusted_root.rglob('*')) if path.is_file()}
    audits = []
    for point, row in zip(points, records):
        # Re-read the host snapshots, raw reports, exact per-finger reference and
        # every required SPICE analysis through the current admission predicate.
        checked = inspect_result(row['result'], point, plan, trusted)
        if not checked['S2'] or not checked.get('point_evaluation_complete'):
            raise ValueError('Every predeclared point must pass current full physical qualification')
        audits.append(checked)
    rc_audit = audit_full_rc(qualification)
    if rc_audit['matching_points'] != 9 or rc_audit['quarantined_points']:
        raise ValueError('All nine unsimplified RC models must retain independent device graphs and bench port order')
    parent = read(plan['parent_frozen_registry'])
    lineage, = [row for row in parent['lineages'] if row['lineage_id'] == plan['parent_lineage']]
    if lineage['split'] != 'train':
        raise ValueError('The immutable compiler source assignment must remain train-only')
    editable = ['textbook_sharing/layout.py', 'glayout/sharing/enumeration.py']
    source = Path(plan['source_pack'])
    state = {'initial_state_id': 'original_compiler_matched_nf',
        'task_id': points[0]['contract']['task_id'], 'parent_lineage': plan['parent_lineage'],
        'origin': 'natural', 'editable_paths': editable,
        'base_source': {name: (source / name).read_text() for name in editable},
        'ancestry': {'kind': 'unmodified_public_compiler', 'source_revision': lineage['source_commit'],
            'source_pack': str(source), 'circuit_input_id': plan['circuit_id'],
            'same_program_AST_and_lineage_as_existing_compiler': True,
            'development_qualification_is_feasibility_only_not_formal_baseline': True}}
    metadata = {'status': 'DRAFT_AFTER_ACTUAL_NINE_POINT_CURRENT_GATE_QUALIFICATION',
        'prepared_at_utc': datetime.now(timezone.utc).isoformat(), 'circuit_id': plan['circuit_id'],
        'parent_lineage': plan['parent_lineage'], 'source_revision': lineage['source_commit'],
        'source_pack': str(source), 'source_files': plan['source_files'], 'editable_paths': editable,
        'trusted_bundle': str(trusted_root), 'trusted_files': sorted(trusted), 'configurations': points,
        'qualification_path': str(qualification / 'state.json'), 'qualification_device_and_analysis_audits': audits,
        'full_RC_device_graph_audits': rc_audit,
        'initial_states': [state], 'independent_programs_added': 0, 'independent_lineages_added': 0,
        'maximum_new_task_contexts': 1, 'planned_fresh_proposals': 8,
        'sampling': {'backend': 'isolated_gpt_cli', 'model': 'gpt-6.1-sol', 'reasoning_effort': 'high',
            'proposal_format': 'ordinary_ACTION_JSON', 'fresh_trials': list(range(1, 9)),
            'seed': None, 'native_tools': False, 'max_context_tokens': 16384,
            'max_new_tokens': 1024, 'timeout_seconds': 240, 'shared_global_slots': 2},
        'selection_version': 'equivalent_best_earliest_actual_trial_v2',
        'must_precede_dispatch': ['Prospective exact request/interface/registry/reference/label/budget freeze',
            'Pinned tokenizer preflight with complete source/API/contract and all fresh baseline feedback',
            'Fresh formal_train baseline9/gold controls; development qualification cannot be relabelled',
            'Unique existing coordinator and shared2 transport; one2CPU/8GiB physical worker'],
        'old_raw_or_frozen_collections_changed': False, 'new_model_calls': 0,
        'new_physical_calls': 0, 'training_rows_admitted': 0, 'formal_training_runs': 0}
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    save(output / 'preparation.json', metadata)
    (output / 'initial_states.jsonl').write_text(json.dumps(state, ensure_ascii=False) + '\n')
    return {'status': metadata['status'], 'preparation': str(output / 'preparation.json'),
            'new_model_calls': 0, 'new_physical_calls': 0, 'qualified_domain_points': 9}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qualification', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.qualification, args.output)), flush=True)
