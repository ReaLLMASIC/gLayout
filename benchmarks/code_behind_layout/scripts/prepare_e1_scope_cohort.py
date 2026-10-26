#!/usr/bin/env python3
"""Prepare a separate16k E1 interface cohort without editing the old freeze."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1];sys.path.insert(0, str(ROOT))
from scripts.e1_scope_proposal_preflight import proposed_request
from scripts.freeze_e1 import rebase
from src.model_adapter import PACKET_FIELDS

COHORT = 'scope_v2_16k'
BUDGET = {'wall_seconds': 1200, 'decisions': 10, 'physical_evaluations': 3,
    'maximum_context_tokens': 16384, 'maximum_output_tokens': 1024}


def read(filename):return json.loads(Path(filename).read_text())


def save(filename, value):
    filename = Path(filename);filename.parent.mkdir(parents=True, exist_ok=True)
    filename.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def packet(original, method, proposal):
    result = proposed_request({'task_packet': original, 'visible_history': []}, method, proposal)['task_packet']
    if set(result) != PACKET_FIELDS:raise ValueError('The matched packet whitelist changed')
    result['budget'] = {**BUDGET, 'deadline_utc': None}
    result['documents'].update(cohort_id=COHORT, status='PROSPECTIVE_E1_SCOPE_PACKET')
    result['documents']['history_policy']['limits'] = '16384 total common-tokenizer tokens including1024 output reserve. Reject overflow without truncating current source, physical feedback or core PDK rules.'
    return result


def prepare(prior_manifest, proposal_path, output):
    prior_manifest = Path(prior_manifest).resolve();prior = read(prior_manifest)
    if prior['status'] != 'FROZEN_E1' or prior['formal_dispatch'] is not True or prior_manifest.stat().st_mode & 0o222:
        raise ValueError('Start from the actual readonly prior E1 freeze; never a partial or mutable task draft')
    if prior['budget'] != {**BUDGET, 'maximum_context_tokens': 8192}:
        raise ValueError('This prospective cohort changes only the old shared context from8192 to16384')
    output = Path(output).resolve()
    if output.exists():raise ValueError('Never overwrite an existing scope preparation')
    old_root = Path(prior['packet_root']).resolve();new_root = output/'packets'
    proposal = read(proposal_path);shutil.copytree(old_root, new_root)
    for directory in [new_root, *(p for p in new_root.rglob('*') if p.is_dir())]:
        directory.chmod(directory.stat().st_mode | 0o700)
    for filename in (new_root/'private').rglob('*.json'):
        value = rebase(read(filename), old_root, new_root);filename.chmod(0o644);save(filename, value)
    catalog = read(new_root/'public/catalog.json')
    if len(catalog['tasks']) != 24:raise ValueError('The new cohort retains the actual24 tasks')
    changed = []
    for task in catalog['tasks']:
        task_file = new_root/'private'/task['task_id']/'task.json';private = read(task_file)
        private.update(status='DRAFT_E1_SCOPE_TASK', formal_admission=False, cohort_id=COHORT);save(task_file, private)
        for method in ('G0', 'G1', 'G2'):
            relative = Path('public')/task['task_id']/(method+'.json')
            original = read(old_root/relative);new = packet(original, method, proposal)
            (new_root/relative).chmod(0o644);save(new_root/relative, new)
            changed.append({'task_id': task['task_id'], 'method': method, 'relative_packet': str(relative)})
    catalog.update(status='DRAFT_E1_SCOPE_TASK_CATALOG', formal_admission=False, cohort_id=COHORT)
    (new_root/'public/catalog.json').chmod(0o644);save(new_root/'public/catalog.json', catalog)
    model = read(prior['model_config']);model.update(status='DRAFT_E1_SCOPE_POLICY', max_context_tokens=16384, max_new_tokens=1024)
    save(output/'model_config.json', model);save(output/'scope_proposal.json', proposal)
    manifest = {**copy.deepcopy(prior), 'status': 'DRAFT_E1_RUNNER', 'formal_dispatch': False,
        'phase': 'development_E1_scope', 'cohort_id': COHORT, 'interface_version': COHORT,
        'prior_interface_manifest': str(prior_manifest), 'prior_interface_freeze_id': prior['freeze_id'],
        'prior_interface_role': 'partial_interface_v1_preserve_all_records_and_NOT_RUN',
        'packet_root': str(new_root), 'task_catalog': str(new_root/'public/catalog.json'),
        'model_config': str(output/'model_config.json'), 'budget': BUDGET,
        'scope_proposal': str(output/'scope_proposal.json'), 'backend_manifest_path': str(output/'manifest.json'),
        'formal_cohort_rule': 'New fresh360 matched trial identities in a separate suite/index; no old trial carried or repeated into this cohort.',
        'freeze_blockers': ['All72 initial and real-feedback history capacity preflight',
            'Three fresh bounded actual policy interface trials, no hidden calls', 'Committed complete implementation binding and independent readonly freeze']}
    for name in ('freeze_id', 'frozen_at_utc', 'implementation_sha256', 'source_revision', 'protocol_amendment'):
        manifest.pop(name, None)
    save(output/'manifest.json', manifest)
    report = {'status': 'DRAFT_E1_SCOPE_PREPARED', 'cohort_id': COHORT, 'manifest': str(output/'manifest.json'),
        'prior_manifest': str(prior_manifest), 'packet_count': len(changed), 'changed_packets': changed,
        'unchanged': 'Sized reference/PDK/decks/contracts/72task-method assignments/current scaffold/API permissions; only documentation and shared context change.',
        'old_frozen_files_changed': False, 'new_model_calls': 0, 'new_physical_calls': 0}
    save(output/'preparation.json', report);return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__);p.add_argument('--prior-manifest', type=Path, required=True)
    p.add_argument('--proposal', type=Path, required=True);p.add_argument('--output', type=Path, required=True);a = p.parse_args()
    print(json.dumps({k: v for k, v in prepare(a.prior_manifest, a.proposal, a.output).items() if k != 'changed_packets'}))
