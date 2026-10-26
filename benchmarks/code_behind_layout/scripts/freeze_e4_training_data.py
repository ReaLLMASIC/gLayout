"""Pool physically admitted textbook candidates into the formal E4 training data and freeze the training manifest.

Pools are declared in a JSON file (see --pools). Every pool names a collection output root, its candidate file, its
effective registry and the frozen label rule, plus the deterministic proposal order of that pool (rule ids or trial
ids) and explicit exclusions. Candidates of all pools that share one initial state form one common candidate pool for
that state; the frozen Point/Family rules then yield exactly one T1/T2 target per state (equivalent-best earliest in the
declared pooled order) and every unambiguous T3/T4 pair, through the unchanged TrustedPhysicalStore admission and the
student interface mapping (16k context, 1024 output). Natural and injected states are reported separately. The output
directory receives T1..T4.jsonl, the trusted evidence manifest, the selection report, the pooled registry, a pool report
and training_manifest.json (status frozen, methods T1..T4, seeds 41/73/109). Nothing in any collection is modified.

    runtime/training-venv/bin/python scripts/freeze_e4_training_data.py --pools configs/training/e4_pools.json --output data/training/e4_textbook_v1 [--dry-run]
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from src import training as legacy
from src.training import TrustedPhysicalStore, admit_candidates, frozen_train_registry, sample_identity
from src.training_selection_v2 import VERSION as SELECTION_VERSION, build_matched_samples_v2
from src.student_interface import CONTEXT_VERSION, derive_matched_samples, interface_definition

MAX_POOLED = 32
KIND_PRIORITY = {'rule_collection': 0, 'multistate_collection': 0, 'span_acceptance': 1}  # one deterministic pool and one teacher pool may meet in a state


def read(p): return json.loads(Path(p).read_text())
def save(p, v): Path(p).write_text(json.dumps(v, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def merge_registries(registries):
    lineages = {}; points = {}; variants = {}
    for registry in registries:
        for row in registry['lineages']:
            if row['lineage_id'] in lineages and lineages[row['lineage_id']] != row: raise ValueError('Shared lineage differs between pools')
            lineages[row['lineage_id']] = row
        for row in registry['configurations']:
            previous = points.get(row['configuration_id'])
            if previous is not None and previous != row:
                # The same frozen domain point appears in several collections; its contract, parameters, reference and
                # lineage must agree. Only the collection-bound gold control and the evaluator snapshot (bench revision)
                # may differ; admission is therefore performed per pool against that pool's own registry (below).
                strip = lambda r: {k: v for k, v in r.items() if k not in ('gold_control', 'trusted_evaluator_files')}
                if strip(previous) != strip(row): raise ValueError('Configuration differs between pools: ' + row['configuration_id'])
                variants[row['configuration_id']] = variants.get(row['configuration_id'], 1) + 1; continue
            points[row['configuration_id']] = row
    return {'status': 'frozen', 'lineages': list(lineages.values()), 'configurations': list(points.values()),
            'topology_holdouts': sorted({v for r in registries for v in r.get('topology_holdouts', [])}),
            'configuration_evaluator_variants': variants, 'admission_scope': 'per collection against its own frozen registry and evaluator snapshot'}


def merge_label_rules(rules):
    """One pooled rule: the union of per-domain area objectives under identical tolerances and family aggregation."""
    first = rules[0]; shared = ('coverage_absolute_tolerance', 'family_quality_aggregation', 'status')
    if any({k: r.get(k) for k in shared} != {k: first.get(k) for k in shared} for r in rules): raise ValueError('Pools differ in shared label-rule settings')
    objectives = {}
    for r in rules:
        for name, definition in r['objectives'].items():
            if objectives.get(name, definition) != definition: raise ValueError('Conflicting objective definition: ' + name)
            objectives[name] = definition
    settings = {json.dumps({k: v for k, v in d.items() if k not in ('metric', 'unit', 'direction')}, sort_keys=True) for d in objectives.values()}
    if len(settings) != 1 or len({(d['metric'], d['unit'], d['direction']) for d in objectives.values()}) != 1: raise ValueError('All domains must share one objective metric and one tolerance set')
    return {**first, 'objectives': objectives, 'version': 'e4_pooled_textbook_area_v1', 'parent_rule_versions': sorted(r['version'] for r in rules)}


def pooled_rule(parent_rule):
    if parent_rule.get('status') != 'frozen' or not parent_rule.get('version'): raise ValueError('Pools need frozen parent label rules')
    base = {k: v for k, v in parent_rule.items() if k not in ('sft_selection', 'parent_rule_version')}
    return {**base, 'version': parent_rule['version'] + '__' + SELECTION_VERSION, 'parent_rule_version': parent_rule['version'],
            'sft_selection': {'version': SELECTION_VERSION, 'actual_trial_field': 'pooled_order', 'declared_trial_order': list(range(MAX_POOLED)),
                              'change_scope': 'Equivalent-best SFT representative = earliest candidate in the pooled proposal order (deterministic rule pools before teacher pools, then each pool\'s own declared rule/trial order); feasibility and thresholds unchanged'}}


def load_pool(index, pool):
    root = ROOT / pool['root']; rows = [json.loads(l) for l in (root / pool['candidates']).read_text().splitlines() if l.strip()]
    registry = read(root / pool.get('registry', 'effective_registry.json')); label = read(ROOT / pool['label_rule']) if not Path(pool['label_rule']).is_absolute() else read(pool['label_rule'])
    order = list(pool['declared_order']); field = pool['order_field']; relative = pool.get('evidence_relative_to_root', True)
    excluded = []; kept = []
    for row in rows:
        why = None
        if row['candidate_id'] in pool.get('exclude_candidates', []): why = 'declared exclusion (audit)'
        elif row.get('proposal_generation', {}).get('rule_id') in pool.get('exclude_rules', []): why = 'excluded rule ' + row['proposal_generation']['rule_id']
        if why: excluded.append({'candidate_id': row['candidate_id'], 'reason': why}); continue
        value = row.get('proposal_generation', {}).get(field)
        matches = [i for i, item in enumerate(order) if type(item) is type(value) and item == value]
        if len(matches) != 1: raise ValueError('Candidate lacks its declared proposal order value: ' + row['candidate_id'])
        row = json.loads(json.dumps(row)); row['proposal_generation']['pooled_order'] = KIND_PRIORITY[pool['kind']] * 16 + matches[0]
        if relative:
            for outcome in row['outcomes']:
                for key in ('evidence_path', 'baseline_evidence_path'):
                    outcome[key] = str((root / outcome[key]).resolve().relative_to(ROOT))
        row['pool_id'] = pool['id']; kept.append(row)
    return {'id': pool['id'], 'kind': pool['kind'], 'rows': kept, 'excluded': excluded, 'registry': registry, 'label_rule': label, 'order_width': len(order)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pools', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--training-config', type=Path, default=ROOT / 'configs/training/formal_16k.json')
    p.add_argument('--context-calibration', type=Path, default=ROOT / 'results/derived/gpu16384_actual_calibration.json')
    p.add_argument('--validation-task', type=Path, default=ROOT / 'runtime/e4_validation_tasks/mirror_source_open_qualified_v1/task.json', help='qualified read-only validation task appended to the pooled registry (one shared registry for training and checkpoint validation)')
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args(); declaration = read(a.pools)
    if any(len(pool['declared_order']) > 16 or pool['kind'] not in KIND_PRIORITY for pool in declaration['pools']): raise ValueError('Each pool declares at most sixteen ordered proposals of a known kind')
    pools = [load_pool(i, pool) for i, pool in enumerate(declaration['pools'])]
    seen = {}
    for pool in pools:
        for row in pool['rows']:
            key = (row['initial_state_id'], row['proposal_generation']['pooled_order'])
            if key in seen: raise ValueError('Two pools of the same kind claim one proposal slot of a state: ' + row['initial_state_id'] + ' from ' + seen[key] + ' and ' + pool['id'])
            seen[key] = pool['id']
    registry = merge_registries([pool['registry'] for pool in pools]); frozen_train_registry(registry)
    rule = pooled_rule(merge_label_rules([pool['label_rule'] for pool in pools]))
    admitted = []; quarantined = []
    for pool in pools:
        store = TrustedPhysicalStore(ROOT, pool['registry'])  # each pool's evidence is read against its own frozen registry/evaluator snapshot
        for row in pool['rows']:
            try: admitted.extend(admit_candidates([row], pool['registry'], store))
            except (ValueError, OSError, KeyError) as exc: quarantined.append({'pool': pool['id'], 'candidate_id': row['candidate_id'], 'error': str(exc)[:300]})
    # A state reached by a deterministic pool and by a teacher pool carries two visible contracts (ordinary packet vs
    # teacher-mapped packet), which the frozen label code refuses to mix; such states form one group per pool, the
    # teacher group suffixed. Each group still yields at most one T1/T2 target and its own pairs.
    kinds = {}
    for row in admitted: kinds.setdefault(row['initial_state_id'], set()).add(KIND_PRIORITY[next(p_['kind'] for p_ in pools if p_['id'] == row['pool_id'])])
    mixed = sorted(k for k, v in kinds.items() if len(v) > 1)
    for row in admitted:
        if row['initial_state_id'] in mixed and KIND_PRIORITY[next(p_['kind'] for p_ in pools if p_['id'] == row['pool_id'])] == 1:
            row['initial_state_id'] = row['initial_state_id'] + '__teacher'
    states = {}
    for row in admitted: states.setdefault(row['initial_state_id'], []).append(row)
    groups, selection = build_matched_samples_v2(admitted, rule, legacy) if admitted else ({k: [] for k in ('T1', 'T2', 'T3', 'T4')}, {'initial_states': 0, 'samples': {}})
    from transformers import AutoTokenizer
    snapshot = read(ROOT / 'configs/training/backbone_cache.json')['snapshot']
    tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True, trust_remote_code=False)
    mapped, budgets = derive_matched_samples(groups, tokenizer, 16384, interface_version=CONTEXT_VERSION)
    origin = {row['initial_state_id']: row['origin'] for row in admitted}
    by_origin = {o: {m: sum(1 for r in mapped[m] if origin.get(r['raw_sample']['initial_state_id']) == o) for m in mapped} for o in ('natural', 'injected')}
    unique_terminal = len({legacy_source_identity(row['candidate_source']) for row in admitted}); unique_initial = len({legacy_source_identity(row['base_source']) for row in admitted})
    report = {'generated_at_utc': datetime.now(timezone.utc).isoformat(), 'pools': [{'id': p_['id'], 'kind': p_['kind'], 'candidates': len(p_['rows']), 'excluded': p_['excluded']} for p_ in pools],
              'quarantined_not_labelled': quarantined, 'admitted_candidates': len(admitted), 'initial_states_with_candidates': len(states), 'states_with_two_proposer_pools': mixed,
              'physical_selection': {k: v for k, v in selection.items() if k != 'SFT_choices'}, 'student_budget_selection': budgets,
              'usable_samples_by_method': {m: len(r) for m, r in mapped.items()}, 'by_origin': by_origin,
              'unique_initial_program_ASTs': unique_initial, 'unique_terminal_program_ASTs': unique_terminal, 'label_rule': rule}
    print(json.dumps({k: report[k] for k in ('admitted_candidates', 'initial_states_with_candidates', 'usable_samples_by_method', 'by_origin', 'unique_initial_program_ASTs', 'unique_terminal_program_ASTs')}, ensure_ascii=False))
    if quarantined: print(json.dumps({'quarantined': quarantined[:10]}, ensure_ascii=False)[:1500])
    if a.dry_run: return
    out = a.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    for method, rows in mapped.items(): (out / (method + '.jsonl')).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    save(out / 'pooled_registry_train_only.json', registry); save(out / 'label_rule.json', rule); save(out / 'pool_report.json', report); save(out / 'sft_choices.json', selection.get('SFT_choices', []))
    # One shared registry for every formal training run and the checkpoint-validation plan: the pooled train registry
    # plus the nine frozen validation points, finalized here as the canonical append (status frozen, one SHA).
    from src.e4_validation import prepare_joint_registry
    prepare_joint_registry(out / 'pooled_registry_train_only.json', a.validation_task, out / 'joint_registry')
    joint = read(out / 'joint_registry/registry.json')
    joint.update(status='frozen', canonical_append_review={'at_utc': datetime.now(timezone.utc).isoformat(), 'reviewed': 'coordinator: nine validation-only points of the qualified read-only task appended; train lineage assignments and configurations unchanged; this file is the single split registry of the training manifest and the validation plan'},
                 formal_training_or_checkpoint_selection_allowed=True, final_training_data_registry_still_pending=False)
    frozen_train_registry(joint); save(out / 'pooled_registry.json', joint)
    samples = [r['raw_sample'] for rows in mapped.values() for r in rows]
    save(out / 'trusted_evidence_manifest.json', {'status': 'admitted', 'role': 'formal_train', 'evidence_root': str(ROOT), 'registry_sha256': sha(out / 'pooled_registry.json'),
                                                   'admitted_sample_ids': [r['sample_id'] for r in samples], 'sample_sha256': {r['sample_id']: sample_identity(r) for r in samples},
                                                   'pools': [p_['id'] for p_ in pools], 'admission': 'TrustedPhysicalStore over the pooled frozen registry; quarantined candidates are not labels'})
    definition = interface_definition(CONTEXT_VERSION, 16384, 1024)
    save(out / 'selection_report.json', {'student_interface_version': definition['version'], 'max_context_tokens': 16384, 'max_new_tokens': 1024, 'history_policy': definition.get('history_policy'),
                                          'usable_samples_by_method': report['usable_samples_by_method'], 'student_budget_selection': budgets, 'physical_selection_version': SELECTION_VERSION})
    config = read(a.training_config)
    if config.get('status') != 'frozen' or config.get('formal_data_ready') is not True or config.get('max_sequence_length') != 16384: raise ValueError('Use the frozen 16k formal training configuration')
    shutil.copyfile(a.training_config, out / 'training_config.json'); shutil.copyfile(a.context_calibration, out / 'context_calibration.json')
    manifest = {'status': 'frozen', 'role': 'formal_training', 'frozen_at_utc': datetime.now(timezone.utc).isoformat(), 'training_config': 'training_config.json', 'split_registry': 'pooled_registry.json',
                'trusted_evidence_manifest': 'trusted_evidence_manifest.json', 'context_calibration': 'context_calibration.json', 'backbone_snapshot': snapshot, 'seeds': config['seeds'],
                'student_interface': {**definition, 'usable_samples_by_method': report['usable_samples_by_method'], 'selection_report': 'selection_report.json'},
                'methods': {'T1': {'samples': 'T1.jsonl', 'selected_checkpoints': {}}, 'T2': {'samples': 'T2.jsonl'}, 'T3': {'samples': 'T3.jsonl', 'starting_t1_checkpoints': {}}, 'T4': {'samples': 'T4.jsonl', 'starting_t1_checkpoints': {}}},
                'formal_training_runs': 0, 'formal_training_examples': sum(report['usable_samples_by_method'].values()), 'pool_report': 'pool_report.json', 'pools_declaration': str(a.pools.resolve())}
    save(out / 'training_manifest.json', manifest)
    save(out / 'freeze_identity.json', {q.name: sha(q) for q in sorted(out.iterdir()) if q.is_file() and q.name != 'freeze_identity.json'})
    for q in out.iterdir(): q.chmod(0o444)
    out.chmod(0o555)
    print(json.dumps({'output': str(out), 'manifest': 'training_manifest.json', 'usable_samples_by_method': report['usable_samples_by_method']}))


def legacy_source_identity(source):
    from scripts.collect_training import source_identity
    return source_identity(source, True)


if __name__ == '__main__': main()
