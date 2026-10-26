"""Prepare/preflight, audit real baselines, then freeze the separate span pilot. No model calls."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path.cwd().resolve(); sys.path.insert(0, str(ROOT))
from src.train_span_proposer import MODE, ROLE, VERSION, SCHEMA, teacher_request, proposal_prompt, mapping_proof
from src.model_adapter import prompt_token_budget
from src.local_model_adapter import decision_prompt

REMOTE = Path('/srv/code-behind-layout')
SELECTED = [('c01_planning_trajectories_context_v2', 'planning_c01_program_038'),
            ('c02_planning_trajectories_context_v2', 'planning_c02_program_039')]


def read(path): return json.loads(Path(path).read_text())
def save(path, value): Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(materialization, output, tokenizer_path):
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(tokenizer_path), local_files_only=True, trust_remote_code=False)
    if tokenizer.eos_token_id != 151645: raise ValueError('Unexpected pinned Qwen EOS')
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    interface = output / 'interface'; (interface / 'src').mkdir(parents=True)
    modules = ['train_span_proposer', 'train_span_cli', 'train_span_bundle', 'model_adapter',
        'local_model_adapter', 'policy_state', 'student_interface', 'training', 'measurement', 'report_parsers', 'spice_validation']
    (interface / 'src/__init__.py').write_text('')
    for name in modules: shutil.copyfile(ROOT / 'src' / (name + '.py'), interface / 'src' / (name + '.py'))
    for source, target in [('serve_train_span_teacher.py', 'broker.py'), ('collect_train_span_proposals.py', 'collector.py'), ('freeze_train_span_teacher.py', 'freezer.py')]:
        shutil.copyfile(ROOT / 'scripts' / source, interface / target)
    save(interface / 'span_schema.json', SCHEMA)
    save(output / 'tokenizer_inventory.json', {'revision': '381fc969f78efac66bc87ff7ddeadb7e73c218a7',
        'eos_token_id': 151645, 'files_sha256': {name: sha(Path(tokenizer_path) / name)
        for name in ['vocab.json', 'merges.txt', 'tokenizer.json', 'tokenizer_config.json']}})
    contexts = []; preflights = []
    for pool, sid in SELECTED:
        parent = ROOT / 'runtime/train_collections' / pool; raw = Path(materialization) / 'runs/train_collection' / pool
        state, = [json.loads(line) for line in (parent / 'initial_states.jsonl').read_text().splitlines() if json.loads(line)['initial_state_id'] == sid]
        original = {'task_packet': read(raw / sid / 'task_packet.json'), 'visible_history': read(raw / sid / 'visible_history.json')}
        if (state['base_source'] != original['task_packet']['visible_sources'] or state['origin'] != 'natural'
                or set(original['task_packet']['allowed_paths']) != set(state['base_source'])):
            raise ValueError('Actual complete source differs from its naturally produced initial state')
        parent_manifest = read(parent / 'collection.json'); registry = read(raw / 'effective_registry.json')
        assignment, = [lineage for lineage in registry['lineages'] if lineage['lineage_id'] == state['parent_lineage']]
        points = [p for p in registry['configurations'] if p['configuration_id'] in original['task_packet']['visible_configurations']]
        if (parent_manifest['status'] != 'frozen' or assignment['split'] != 'train' or len(points) != 9
                or any(p['split'] != 'train' or p['contract']['task_id'] != state['task_id'] for p in points)):
            raise ValueError('All existing source and nine circuit/reference points must be frozen train-only')
        request = teacher_request(original); proof = mapping_proof(original, request)
        directory = output / 'contexts' / sid; directory.mkdir(parents=True)
        values = {'original_request': original, 'teacher_request': request, 'student_request': proof.pop('ordinary_request'),
            'mapping_proof': proof, 'initial_state': state, 'baseline_results': read(raw / sid / 'baseline_results.json'),
            'effective_registry': registry, 'parent_collection': parent_manifest, 'label_rule': read(parent / 'label_rule.json')}
        record = {'initial_state_id': sid, 'parent_collection_id': pool, 'parent_lineage': state['parent_lineage'],
            'parent_actual_baseline_path': str(REMOTE / 'runs/train_collection' / pool / sid / 'baseline_results.json')}
        for name, value in values.items():
            file = directory / (name + '.json'); save(file, value); record[name] = str(file.relative_to(output))
        contexts.append(record)
        teacher = prompt_token_budget(tokenizer, proposal_prompt(request), {'max_context_tokens': 16384, 'max_new_tokens': 3072})
        student = prompt_token_budget(tokenizer, decision_prompt(values['student_request']), {'max_context_tokens': 16384, 'max_new_tokens': 1024})
        preflights.append({'initial_state_id': sid, 'teacher': teacher, 'student': student, 'actual_complete_baseline_feedback_included': True,
            'mapping_verified': True, 'model_inferences': 0})
    if not all(p[k]['fits_with_full_output_reserve'] for p in preflights for k in ('teacher', 'student')):
        raise ValueError('Complete source/API/physical contract/actual feedback exceeds frozen reserve')
    manifest = {'schema_version': 1, 'status': 'DRAFT_NO_MODEL_CALLS', 'role': 'train_proposal_collection',
        'collection_id': 'c01_c02_literal_span_teacher_v1', 'teacher_interface_version': VERSION, 'source_role': ROLE,
        'contexts': contexts, 'planned_proposals': 16, 'independent_contexts_added': 0, 'source_lineages': 1,
        'sampling': {'backend': 'isolated_gpt_cli', 'model': 'gpt-6.1-sol', 'reasoning_effort': 'high', 'mode': MODE,
            'trials': list(range(1, 9)), 'seed': None, 'proposal_workers': 2, 'max_new_tokens': 3072, 'max_context_tokens': 16384, 'timeout_seconds': 240},
        'student_preselection': {'interface_version': 'ordinary_policy_action_context_v2', 'max_new_tokens': 1024, 'max_context_tokens': 16384, 'stage': 'before_physics'},
        'endpoint': 'http://127.0.0.1:8116/spans/decision', 'broker_endpoint': 'http://127.0.0.1:8122/decision',
        'output_root': str(REMOTE / 'runs/train_proposals/c01_c02_literal_span_teacher_v1'),
        'budget_tokenizer_revision': '381fc969f78efac66bc87ff7ddeadb7e73c218a7',
        'maximum_dispatch_hours': 4, 'prepared_at_utc': datetime.now(timezone.utc).isoformat(),
        'shared_global_inference_slots': 2, 'physical_runs_in_this_collection': 0, 'training_rows_in_this_collection': 0,
        'admission': 'Proposal-only. A separate predeclared physical consumer must bind base/source/compiler proof and existing nine baseline controls, run all nine points, and re-admit through current trusted/device/student gates. No old patch repair or result relabeling.'}
    save(output / 'collection.json', manifest); save(output / 'teacher_context_preflight.json', preflights)
    return {'status': manifest['status'], 'collection': str(output / 'collection.json'), 'preflights': preflights, 'missing_before_freeze': ['Current raw baseline evidence audit18', 'Root review before model dispatch'], 'new_model_calls': 0}


def audit_baselines(collection):
    from src.training import TrustedPhysicalStore
    collection = Path(collection).resolve(); root = collection.parent; manifest = read(collection); records = []
    for context in manifest['contexts']:
        state = read(root / context['initial_state']); registry = read(root / context['effective_registry'])
        request = read(root / context['original_request']); baselines = read(root / context['baseline_results'])
        assignment, = [row for row in registry['lineages'] if row['lineage_id'] == state['parent_lineage']]
        ids = request['task_packet']['visible_configurations']
        if set(ids) != set(baselines) or len(ids) != 9: raise ValueError('Nine actual baseline runs must match the immutable domain')
        for identifier in ids:
            point, = [row for row in registry['configurations'] if row['configuration_id'] == identifier]
            point = {**point, **{key: assignment[key] for key in ['editable_paths', 'frozen_source_pack', 'frozen_source_files']},
                     'lineage_editable_paths': assignment['editable_paths'], 'editable_paths': list(state['base_source'])}
            run = Path(baselines[identifier]['run_directory'])
            raw_manifest = read(run / 'manifest.json')
            if raw_manifest.get('phase') != 'formal_train': raise ValueError('Development evidence cannot be relabelled')
            checked = TrustedPhysicalStore._inspect_execution_run(run, point, state['base_source'])
            if not checked.get('point_evaluation_complete'): raise ValueError('Raw baseline audit did not establish complete evaluation')
            records.append({'initial_state_id': state['initial_state_id'], 'configuration_id': identifier, 'run_directory': str(run),
                'checked': checked, 'raw_manifest_sha256': sha(run / 'manifest.json')})
    input_names = [context[key] for context in manifest['contexts']
                   for key in ('original_request', 'initial_state', 'baseline_results', 'effective_registry')]
    result = {'status': 'ACTUAL_CURRENT_GATE_RAW_BASELINE_AUDIT', 'audited_at_utc': datetime.now(timezone.utc).isoformat(),
        'all_eighteen_points_complete': len(records) == 18, 'records': records, 'gate_source_sha256': sha(ROOT / 'src/training.py'),
        'input_files_sha256': {name: sha(root / name) for name in input_names},
        'new_physical_calls': 0, 'new_model_calls': 0, 'new_training_examples': 0}
    save(root / 'baseline_audit.json', result); return result


def freeze(collection):
    collection = Path(collection).resolve(); root = collection.parent; manifest = read(collection)
    if manifest['status'] != 'DRAFT_NO_MODEL_CALLS': raise ValueError('Only the reviewed prospective draft may be frozen once')
    audit = read(root / 'baseline_audit.json')
    if not audit.get('all_eighteen_points_complete') or len(audit.get('records', [])) != 18:
        raise ValueError('Actual full eighteen-point baseline evidence is required')
    for name, digest in audit['input_files_sha256'].items():
        if sha(root / name) != digest: raise ValueError('Baseline audit input changed before freeze')
    manifest.update(status='frozen', frozen_at_utc=datetime.now(timezone.utc).isoformat())
    save(collection, manifest)
    files = sorted(p for p in root.rglob('*') if p.is_file() and p.name != 'freeze_identity.json' and '__pycache__' not in p.parts)
    save(root / 'freeze_identity.json', {str(p.relative_to(root)): sha(p) for p in files})
    for path in root.rglob('*'):
        if path.is_file(): path.chmod(0o444)
    for path in sorted((p for p in root.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        path.chmod(0o555)
    root.chmod(0o555)
    from src.train_span_bundle import load_bundle
    load_bundle(collection)
    return {'status': 'FROZEN_PROPOSAL_ONLY_NO_MODEL_CALLS', 'collection': str(collection), 'planned_proposals': 16, 'model_calls': 0}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--materialization', type=Path); p.add_argument('--output', type=Path); p.add_argument('--tokenizer', type=Path)
    p.add_argument('--collection', type=Path)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', action='store_true'); group.add_argument('--audit-baselines', action='store_true'); group.add_argument('--freeze', action='store_true')
    a = p.parse_args()
    if a.prepare: result = prepare(a.materialization, a.output, a.tokenizer)
    elif a.audit_baselines: result = audit_baselines(a.collection)
    else: result = freeze(a.collection)
    print(json.dumps(result, indent=2, allow_nan=False), flush=True)
