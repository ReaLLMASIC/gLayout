"""Export a new ratio-only span8 DRAFT; never modify the NF or old span bundles."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts.prepare_ratio_source_train_baselines import read, save, token_preflight
from scripts.run_ratio_source_train_baselines import load, check_result
from scripts.prepare_ratio_training_draft import validate_completion
from src.train_ratio_span_bundle import BUNDLE_VERSION, SID, LINEAGE, load_bundle
from src.train_span_proposer import MODE, ROLE, VERSION, SCHEMA
from src.training import frozen_train_registry


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def collector_source(source):
    """The concrete collector's dispatch and span compiler stay unchanged."""
    replacements = {
        "'planned_proposals': 16": "'planned_proposals': 8",
        'len(attempts) == 16': 'len(attempts) == 8',
        "'initial_contexts_reused': 2, 'independent_contexts_added': 0":
            "'initial_contexts_reused': 1, 'independent_contexts_added': 0"}
    for old, new in replacements.items():
        expected = 2 if old == "'planned_proposals': 16" else 1
        if source.count(old) != expected: raise ValueError('Review changed producer accounting before ratio export')
        source = source.replace(old, new)
    return source


def prepare(draft_path, output, tokenizer_path):
    draft_path = Path(draft_path).resolve(); draft = read(draft_path); base = draft_path.parent
    if draft['status'] != 'DRAFT_RATIO_TRAIN_TASK_AFTER_FRESH9_NOT_A_COLLECTION_FREEZE':
        raise ValueError('Use only the actual fresh9 materialized ratio DRAFT')
    plan, registry, initial = load(draft['baseline_plan']); actual = Path(plan['output_root'])
    validate_completion(read(actual / 'completion.json'), plan['fixed_order'])
    baselines = read(base / 'baseline_results.json'); records = []
    caller = (Path(plan['source_pack']) / 'generator.py').read_bytes()
    if caller != (base / 'readonly_generator.py').read_bytes(): raise ValueError('Actual ratio caller differs')
    for point in registry['configurations']:
        result = baselines[point['configuration_id']]; checked = check_result(result, point, registry, initial, plan)
        if (Path(result['run_directory']) / 'source/generator.py').read_bytes() != caller:
            raise ValueError('Actual fresh baseline executed another caller')
        records.append({'configuration_id': point['configuration_id'], 'run_directory': result['run_directory'],
            'S2': checked['S2'], 'full_RC_device_graph_clean': checked['full_RC_device_graph_audit']['is_clean']})
    ordinary = read(base / 'ordinary_request.json'); flight, teacher = token_preflight(ordinary)
    if teacher != read(base / 'teacher_request.json'): raise ValueError('The ratio teacher input changed after actual control')
    current = read(ROOT / 'data/splits/registry.json'); old = {r['lineage_id']: r for r in registry['lineages']}
    for row in current['lineages']:
        if row['lineage_id'] == LINEAGE: raise ValueError('Ratio is already globally assigned; review rather than append twice')
        if row['lineage_id'] in old and row['split'] != old[row['lineage_id']]['split']:
            raise ValueError('Prior source split changed during baseline qualification')
    ratio, = [row for row in registry['lineages'] if row['lineage_id'] == LINEAGE]
    registry['lineages'] = current['lineages'] + [ratio]
    frozen_train_registry(registry)
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    interface = output / 'interface'; (interface / 'src').mkdir(parents=True)
    (interface / 'src/__init__.py').write_text('')
    for name in ['train_span_proposer', 'train_span_cli', 'model_adapter', 'local_model_adapter',
                 'policy_state', 'student_interface', 'training', 'measurement', 'report_parsers', 'spice_validation']:
        shutil.copyfile(ROOT / 'src' / (name + '.py'), interface / 'src' / (name + '.py'))
    shutil.copyfile(ROOT / 'src/train_ratio_span_bundle.py', interface / 'src/train_span_bundle.py')
    shutil.copyfile(ROOT / 'scripts/serve_train_span_teacher.py', interface / 'broker.py')
    (interface / 'collector.py').write_text(collector_source((ROOT / 'scripts/collect_train_span_proposals.py').read_text()))
    shutil.copyfile(Path(__file__), interface / 'freezer.py'); save(interface / 'span_schema.json', SCHEMA)
    save(output / 'tokenizer_inventory.json', {'revision': '381fc969f78efac66bc87ff7ddeadb7e73c218a7',
        'eos_token_id': 151645, 'files_sha256': {name: sha(Path(tokenizer_path) / name)
            for name in ['vocab.json', 'merges.txt', 'tokenizer.json', 'tokenizer_config.json']}})
    parent_id = 'ratio_source_fresh9_v1'; context = {'initial_state_id': SID, 'parent_lineage': LINEAGE,
        'parent_collection_id': parent_id, 'readonly_entrypoint': 'readonly_generator.py'}
    (output / context['readonly_entrypoint']).write_bytes(caller)
    runtime = {'collection_id': parent_id, 'pdk_revision': plan['PDK_revision'],
        'source_pack': plan['source_pack'], 'source_files': plan['source_files'],
        'trusted_bundle': plan['trusted_bundle'], 'container_image': plan['container_image'],
        'magic_runtime': plan['magic_runtime'], 'baseline_plan': draft['baseline_plan'],
        'actual_baseline_root': str(actual), 'sampling': {'mode': 'train_collection_action_gpt', 'trials': list(range(1, 9))}}
    label = read(base / 'label_rule_DRAFT.json')
    label.update(status='frozen', version='Ratio_area_v1', coverage_absolute_tolerance=0.,
        family_quality_aggregation='arithmetic_mean_of_same_unit_per_configuration_worst_corner_objectives')
    values = {'original_request': ordinary, 'teacher_request': teacher, 'student_request': read(base / 'student_request.json'),
        'mapping_proof': read(base / 'teacher_to_ordinary_mapping.json'), 'initial_state': initial,
        'baseline_results': baselines, 'effective_registry': registry, 'parent_collection': runtime, 'label_rule': label}
    for name, value in values.items():
        context[name] = name + '.json'; save(output / context[name], value)
    save(output / 'baseline_audit.json', {'phase': 'formal_train', 'all_nine_points_complete': True,
        'records': records, 'audited_at_utc': datetime.now(timezone.utc).isoformat(),
        'new_model_calls': 0, 'new_physical_calls': 0})
    save(output / 'teacher_context_preflight.json', {**flight, 'actual_fresh_formal_feedback': True})
    save(output / 'source_assignment_DRAFT.json', {'prior_lineage_rows': current['lineages'], 'new_train_assignment': ratio,
        'prior_assignments_preserved_exactly': registry['lineages'][:-1] == current['lineages'],
        'global_registry_modified': False, 'new_initial_source_ASTs': 1, 'new_source_lineages_proposed': 1,
        'topology_holdout_claimed': False, 'ancestry': initial['ancestry']})
    manifest = {'status': 'DRAFT_NO_MODEL_CALLS', 'role': 'train_proposal_collection',
        'collection_id': 'ratio_source_literal_span8_v1', 'ratio_bundle_version': BUNDLE_VERSION,
        'teacher_interface_version': VERSION, 'source_role': ROLE, 'contexts': [context],
        'planned_proposals': 8, 'independent_contexts_added': 0, 'initial_contexts_reused': 1,
        'sampling': {'backend': 'isolated_gpt_cli', 'model': 'gpt-6.1-sol', 'reasoning_effort': 'high',
            'mode': MODE, 'trials': list(range(1, 9)), 'seed': None, 'proposal_workers': 2,
            'max_new_tokens': 3072, 'max_context_tokens': 16384, 'timeout_seconds': 240},
        'student_preselection': {'interface_version': 'ordinary_policy_action_context_v2',
            'max_new_tokens': 1024, 'max_context_tokens': 16384, 'stage': 'before_physics'},
        'endpoint': 'http://127.0.0.1:8116/spans/decision', 'broker_endpoint': 'http://127.0.0.1:8122/decision',
        'output_root': str(ROOT / 'runs/train_proposals/ratio_source_literal_span8_v1'),
        'maximum_dispatch_hours': 8, 'shared_global_inference_slots': 2, 'physical_runs_in_this_collection': 0,
        'training_rows_in_this_collection': 0, 'prepared_at_utc': datetime.now(timezone.utc).isoformat(),
        'fresh_baseline_plan': draft['baseline_plan'], 'materialized_actual_draft': str(draft_path),
        'dispatch_condition': 'Root separately reviews/freezes both new bundles and drains/swaps only the8122 upstream. This export never reloads services or issues a model/physical call.'}
    save(output / 'collection.json', manifest); load_bundle(output / 'collection.json', require_frozen=False)
    return {'status': manifest['status'], 'collection': str(output / 'collection.json'), 'fresh_baselines_reaudited': 9,
        'token_counts': flight['token_counts'], 'new_model_calls': 0, 'new_physical_calls': 0}


def freeze(path):
    path = Path(path).resolve(); root = path.parent; manifest = load_bundle(path, require_frozen=False)
    manifest.update(status='frozen', frozen_at_utc=datetime.now(timezone.utc).isoformat()); save(path, manifest)
    save(root / 'freeze_identity.json', {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
        if p.is_file() and '__pycache__' not in p.parts})
    for p in sorted(root.rglob('*'), key=lambda p: len(p.parts), reverse=True): p.chmod(0o555 if p.is_dir() else 0o444)
    root.chmod(0o555); load_bundle(path)
    return {'status': 'FROZEN_RATIO_PROPOSAL_ONLY_NO_CALLS', 'collection': str(path), 'new_model_or_physical_calls': 0}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); modes = p.add_mutually_exclusive_group(required=True)
    modes.add_argument('--prepare', action='store_true'); modes.add_argument('--freeze', action='store_true')
    for name in ['draft', 'output', 'tokenizer', 'collection']: p.add_argument('--' + name, type=Path)
    a = p.parse_args(); print(json.dumps(prepare(a.draft, a.output, a.tokenizer) if a.prepare else freeze(a.collection), indent=2))
