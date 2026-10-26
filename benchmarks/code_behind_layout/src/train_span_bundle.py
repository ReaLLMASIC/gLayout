"""Read the prospective two-context, sixteen-proposal span collection freeze."""
import hashlib
import json
from pathlib import Path

from src.train_span_proposer import MODE, ROLE, VERSION


def read(path): return json.loads(Path(path).read_text())


def validate_tokenizer(directory, bundle):
    inventory = read(Path(bundle) / 'tokenizer_inventory.json')
    for name, digest in inventory['files_sha256'].items():
        if hashlib.sha256((Path(directory) / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Tokenizer bytes differ from the actual budget preflight: ' + name)


def load_bundle(path):
    path = Path(path).resolve(); root = path.parent; manifest = read(path)
    identity = read(root / 'freeze_identity.json')
    if 'collection.json' not in identity: raise ValueError('Collection manifest is not frozen')
    for file in [root, *root.rglob('*')]:
        if file.stat().st_mode & 0o222:
            raise ValueError('Frozen span bundle contains a writable file or directory: ' + str(file.relative_to(root)))
    for name, digest in identity.items():
        file = root / name
        if (not file.resolve().is_relative_to(root) or file.is_symlink() or not file.is_file()
                or hashlib.sha256(file.read_bytes()).hexdigest() != digest):
            raise ValueError('Frozen span interface/context differs: ' + name)
    sampling = {'backend': 'isolated_gpt_cli', 'model': 'gpt-6.1-sol', 'reasoning_effort': 'high',
        'mode': MODE, 'trials': list(range(1, 9)), 'seed': None, 'proposal_workers': 2,
        'max_new_tokens': 3072, 'max_context_tokens': 16384, 'timeout_seconds': 240}
    if (manifest.get('status') != 'frozen' or manifest.get('role') != 'train_proposal_collection'
            or manifest.get('source_role') != ROLE or manifest.get('teacher_interface_version') != VERSION
            or manifest.get('sampling') != sampling or len(manifest.get('contexts', [])) != 2
            or manifest.get('planned_proposals') != 16 or manifest.get('independent_contexts_added') != 0
            or manifest.get('endpoint') != 'http://127.0.0.1:8116/spans/decision'
            or manifest.get('student_preselection') != {'interface_version': 'ordinary_policy_action_context_v2',
                'max_new_tokens': 1024, 'max_context_tokens': 16384, 'stage': 'before_physics'}):
        raise ValueError('Only the fixed prospective literal-span pilot is supported')
    expected = [('c01_planning_trajectories_context_v2', 'planning_c01_program_038'),
                ('c02_planning_trajectories_context_v2', 'planning_c02_program_039')]
    if [(c['parent_collection_id'], c['initial_state_id']) for c in manifest['contexts']] != expected:
        raise ValueError('Span pilot context assignment differs')
    for context in manifest['contexts']:
        for key in ('original_request', 'teacher_request', 'student_request', 'mapping_proof', 'initial_state', 'baseline_results', 'effective_registry', 'parent_collection', 'label_rule'):
            if context[key] not in identity: raise ValueError('Unfrozen context artifact: ' + key)
        if not read(root / context['mapping_proof']).get('teacher_and_original_map_to_identical_ordinary_request'):
            raise ValueError('Student output-instruction mapping was not proven')
    if 'baseline_audit.json' not in identity or 'tokenizer_inventory.json' not in identity or not read(root / 'baseline_audit.json').get('all_eighteen_points_complete'):
        raise ValueError('Actual current-gate baseline proof is required before freezing')
    return manifest
