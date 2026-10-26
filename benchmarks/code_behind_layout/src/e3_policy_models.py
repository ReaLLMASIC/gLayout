"""Resolve a frozen local evaluation method without rereading large weights per episode."""
import hashlib
import json
from pathlib import Path
import shlex


def resolve(manifest, root, variant, slot, ssh, remote):
    if variant not in ('T0', 'T1', 'T2', 'T3', 'T4') or slot not in (41, 73, 109):
        raise ValueError('Local E4 evaluation requires a declared method and matched seed slot')
    filename = Path(manifest['e4_methods_manifest'])
    if not filename.is_absolute():
        filename = Path(root)/filename
    if not filename.is_file() or filename.stat().st_mode & 0o222:
        raise ValueError('Actual readonly E4 method freeze is not available yet')
    raw = filename.read_bytes();methods = json.loads(raw)
    if methods.get('status') != 'FROZEN_E4_METHODS' or methods.get('formal_training_runs') != 12:
        raise ValueError('Engineering calibration cannot serve as a formal trained method')
    if methods.get('base_revision') != '381fc969f78efac66bc87ff7ddeadb7e73c218a7':
        raise ValueError('The local backbone differs from the shared frozen reference')
    interface = methods['student_interface']
    if (interface['max_context_tokens'] != manifest['budget']['maximum_context_tokens'] or
            interface['max_new_tokens'] != manifest['budget']['maximum_output_tokens']):
        raise ValueError('GPT and local methods must have the same actual context/output budget')
    selected = None if variant == 'T0' else methods['variants'][variant]['seeds'][str(slot)]
    identity = {'variant': variant, 'training_seed': None if variant == 'T0' else slot,
        'evaluation_seed_slot': slot, 'methods_manifest_sha256': hashlib.sha256(raw).hexdigest(),
        'adapter_sha256': None if selected is None else selected['adapter_sha256']}
    command = (shlex.quote(remote+'/runtime/training-venv/bin/python')+
        ' scripts/request_frozen_policy.py --training-seed '+str(slot)+
        ' --methods-sha256 '+identity['methods_manifest_sha256']+
        ' --adapter-sha256 '+(identity['adapter_sha256'] or 'none')+
        ' --endpoint http://127.0.0.1:8117/decision')
    return {'backend': 'frozen_local_action_service', 'variant': variant,
        'training_seed': identity['training_seed'], 'evaluation_seed_slot': slot,
        'max_context_tokens': interface['max_context_tokens'], 'max_new_tokens': 1024,
        'visible_history_policy': 'current_source_and_feedback_v1',
        'timeout_seconds_per_decision': 600, 'model_identity': identity,
        'request_command': list(ssh)+['cd '+shlex.quote(remote)+' && '+command]}
