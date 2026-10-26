"""One separately assigned ratio source and eight prospective train proposals."""
import hashlib
import json
from pathlib import Path

from src.train_span_proposer import MODE, ROLE, VERSION

BUNDLE_VERSION = 'ratio_source_natural_v3_literal_span8_v1'
SID = 'ratio_natural_source_v3'
LINEAGE = 'research_train_ratio_current_source_array_v1'
EDITABLE = 'src/train_generators/ratio_source.py'
ORDER = [f'ratio_cs_k{k}_r{r}' for k in (2, 4, 8) for r in (1, 2, 4)]


def read(path): return json.loads(Path(path).read_text())


def validate_tokenizer(directory, bundle):
    for name, digest in read(Path(bundle) / 'tokenizer_inventory.json')['files_sha256'].items():
        if hashlib.sha256((Path(directory) / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Pinned ratio tokenizer differs: ' + name)


def load_bundle(path, require_frozen=True):
    path = Path(path).resolve(); root = path.parent; manifest = read(path)
    if require_frozen:
        identity = read(root / 'freeze_identity.json')
        if 'collection.json' not in identity: raise ValueError('Ratio proposal collection is not frozen')
        for file in [root, *root.rglob('*')]:
            if file.is_symlink() or file.stat().st_mode & 0o222:
                raise ValueError('Ratio freeze must be readonly and unlinked')
        for name, digest in identity.items():
            file = root / name
            if (not file.resolve().is_relative_to(root) or not file.is_file()
                    or hashlib.sha256(file.read_bytes()).hexdigest() != digest):
                raise ValueError('Frozen ratio bytes changed: ' + name)
    sampling = {'backend': 'isolated_gpt_cli', 'model': 'gpt-6.1-sol', 'reasoning_effort': 'high',
        'mode': MODE, 'trials': list(range(1, 9)), 'seed': None, 'proposal_workers': 2,
        'max_new_tokens': 3072, 'max_context_tokens': 16384, 'timeout_seconds': 240}
    if (manifest.get('status') != ('frozen' if require_frozen else 'DRAFT_NO_MODEL_CALLS')
            or manifest.get('role') != 'train_proposal_collection' or manifest.get('source_role') != ROLE
            or manifest.get('ratio_bundle_version') != BUNDLE_VERSION
            or manifest.get('teacher_interface_version') != VERSION or manifest.get('sampling') != sampling
            or manifest.get('planned_proposals') != 8 or manifest.get('maximum_dispatch_hours') != 8
            or manifest.get('endpoint') != 'http://127.0.0.1:8116/spans/decision'
            or manifest.get('shared_global_inference_slots') != 2
            or manifest.get('student_preselection') != {'interface_version': 'ordinary_policy_action_context_v2',
                'max_new_tokens': 1024, 'max_context_tokens': 16384, 'stage': 'before_physics'}):
        raise ValueError('Only the fixed ratio single-context eight-trial train collection is supported')
    entries = manifest.get('contexts', [])
    if len(entries) != 1 or entries[0]['initial_state_id'] != SID or entries[0]['parent_lineage'] != LINEAGE:
        raise ValueError('Do not substitute or duplicate ratio source contexts')
    entry = entries[0]; initial = read(root / entry['initial_state'])
    registry = read(root / entry['effective_registry'])
    if ([p['configuration_id'] for p in registry['configurations']] != ORDER
            or initial['origin'] != 'natural' or set(initial['base_source']) != {EDITABLE}
            or initial['parent_lineage'] != LINEAGE):
        raise ValueError('Retain the complete natural source and fixed nine-point domain')
    assignment, = [r for r in registry['lineages'] if r['lineage_id'] == LINEAGE]
    if assignment['split'] != 'train': raise ValueError('Ratio is a train-only source')
    caller = (root / entry['readonly_entrypoint']).read_text()
    for key in ['original_request', 'teacher_request', 'student_request']:
        task = read(root / entry[key])['task_packet']
        if (task['allowed_paths'] != [EDITABLE] or task['visible_sources'] != initial['base_source']
                or task['documents']['frozen_generator_entrypoint_source'] != caller):
            raise ValueError('Teacher and ordinary student must see the same complete source and immutable caller')
    if not read(root / entry['mapping_proof']).get('teacher_and_original_map_to_identical_ordinary_request'):
        raise ValueError('Ratio teacher-to-ordinary mapping is unproved')
    audit = read(root / 'baseline_audit.json')
    if (audit.get('phase') != 'formal_train' or audit.get('all_nine_points_complete') is not True
            or len(audit.get('records', [])) != 9 or any(not r.get('S2') or not r.get('full_RC_device_graph_clean')
                for r in audit['records'])):
        raise ValueError('All nine fresh formal baselines and exact full-RC device graphs are required')
    flight = read(root / 'teacher_context_preflight.json')
    if (flight.get('actual_fresh_formal_feedback') is not True or flight.get('source_or_contract_truncated') is not False
            or any(not row['fits_with_full_output_reserve'] for row in flight['token_counts'].values())):
        raise ValueError('Complete actual feedback must fit teacher and ordinary student budgets')
    return manifest
