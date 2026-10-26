#!/usr/bin/env python3
"""Draft, check and freeze the amended Claude action-level cohort E1-C2 (amendment A6) on the server.

  draft                     write runtime/protocol_freezes/E1_scope_v2_16k_claude_v2_DRAFT for the bounded pilot
  freeze --pilot SUMMARY    verify the returned pilot, then write the read-only cohort freeze
  check  --manifest M       re-derive the declared matrix from a manifest

No model call and no physical call. The parent GPT freeze and the E1-C freeze are only read.
"""
import argparse
import copy
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.opus_cohort import common, common_v2  # noqa: E402
from scripts.opus_cohort import freeze_cohorts_opus as v1  # noqa: E402
from scripts.opus_cohort.common import digest, now, read, save  # noqa: E402
from src.opus_cli_adapter_v2 import SYSTEM_PROMPT_V2, SYSTEM_PROMPT_VERSION  # noqa: E402
from src.opus_cli_adapter import SYSTEM_PROMPT as SYSTEM_PROMPT_V1  # noqa: E402

FREEZES = v1.FREEZES
PILOT_RULE = v1.PILOT_RULE


def implementation_bindings_v2(parent):
    bindings = dict(parent['implementation_sha256'])
    for name, expected in bindings.items():
        if digest(ROOT / name) != expected:
            raise ValueError('Frozen parent implementation differs from live source: ' + name)
    for name in common_v2.NEW_IMPLEMENTATION_V2:
        if name in bindings:
            raise ValueError('A cohort file collides with a parent binding: ' + name)
        bindings[name] = digest(ROOT / name)
    predecessor = read(FREEZES / common_v2.PREDECESSOR / 'manifest.json')
    for name in common.NEW_IMPLEMENTATION:
        if bindings[name] != predecessor['implementation_sha256'][name]:
            raise ValueError('An E1-C bound file changed; E1-C2 must inherit it byte for byte: ' + name)
    return bindings


def model_config_v2(status):
    config = v1.model_config(status)
    config.update(system_prompt_version=SYSTEM_PROMPT_VERSION, system_prompt_text=SYSTEM_PROMPT_V2,
                  system_prompt_text_v1=SYSTEM_PROMPT_V1, adapter='src/opus_cli_adapter_v2.py',
                  amendment=common_v2.AMENDMENT_V2)
    return config


def cohort_fields_v2(parent_path, parent, out, status, formal):
    fields = {'status': status, 'formal_dispatch': formal, 'freeze_id': out.name, 'frozen_at_utc': now(),
              'backend_manifest_path': str(out / 'manifest.json'), 'model_config': str(out / 'model_config.json'),
              'parent_freeze_id': common.PARENT['E1'], 'parent_manifest_path': str(parent_path), 'parent_manifest_sha256': digest(parent_path),
              'predecessor_cohort': {'freeze_id': common_v2.PREDECESSOR, 'manifest': str(FREEZES / common_v2.PREDECESSOR / 'manifest.json'),
                                     'role': 'E1-C without format guidance; its recorded episodes stay a separate partial matrix (paused 2026-10-20 02:11 UTC)'},
              'policy_backend': common.POLICY_BACKEND, 'policy_model': common.POLICY_MODEL, 'cohort_label': common_v2.COHORT_LABEL_V2,
              'system_prompt_version': SYSTEM_PROMPT_VERSION, 'minimum_tier': common.MINIMUM, 'protocol_amendment': common_v2.AMENDMENT_V2,
              'implementation_sha256': implementation_bindings_v2(parent), 'trials': common.MINIMUM['e1_trials'], 'declared_episodes': common.E1_DECLARED,
              'format_guidance': ('The fixed system prompt adds: one-sentence summary; the whole action within the 1,024-token shared budget; '
                                  'strict unified diff with exact hunk counts and three context lines before and after each change.'),
              'cohort_rule': ('Same tasks, anchors, visible and hidden configurations, references, benches, budgets, selection rules and '
                              'gateway as the parent freeze and as E1-C; only the policy prompt text differs (amendment A6).'),
              'formal_cohort_rule': 'Fresh 144 matched trial identities in a separate suite/index; no parent or E1-C trial is carried or repeated.',
              'cohort_analysis_rule': 'Only this cohort-specific complete index enters its task-paired analysis; E1-C is reported alongside as the no-guidance condition.'}
    return fields


def draft():
    parent_path, parent = v1.parent_manifest('E1')
    out = FREEZES / (common_v2.FREEZE_V2 + '_DRAFT')
    if out.exists():
        raise ValueError('Never overwrite an existing cohort draft: ' + str(out))
    out.mkdir(mode=0o755)
    manifest = {**copy.deepcopy(parent), **cohort_fields_v2(parent_path, parent, out, 'DRAFT_E1_RUNNER', False),
                'phase': 'development_E1_claude_v2_pilot', 'pilot_rule': PILOT_RULE}
    save(out / 'model_config.json', model_config_v2('DRAFT_E1_CLAUDE_V2_PILOT_POLICY'))
    save(out / 'manifest.json', manifest)
    v1.receipt('E1', 'A6_DRAFT', {'draft': str(out / 'manifest.json'), 'new_model_calls': 0, 'new_physical_calls': 0})
    return {'status': manifest['status'], 'manifest': str(out / 'manifest.json'), 'new_model_calls': 0, 'new_physical_calls': 0}


def runtime_differences(pilot, bindings):
    differences = {}
    for job in pilot['jobs']:
        episode = job.get('episode_directory')
        state_path = ROOT / 'runs' / Path(episode).relative_to(ROOT / 'runs') / 'private/state.json' if episode else None
        if state_path is None or not state_path.is_file():
            continue
        snapshot = read(state_path).get('execution_implementation_sha256') or {}
        for name, expected in bindings.items():
            if name in snapshot and snapshot[name] != expected:
                differences.setdefault(name, []).append(job['method'])
    allowed = {'scripts/opus_cohort/freeze_cohorts_opus_v2.py'}
    if set(differences) - allowed:
        raise ValueError('A bound runtime file changed between the pilot and the freeze: ' + ', '.join(sorted(set(differences) - allowed)))
    return {'files_changed_after_pilot': differences, 'allowed': sorted(allowed)}


def freeze(pilot_path, check_only=False):
    parent_path, parent = v1.parent_manifest('E1')
    draft_path = FREEZES / (common_v2.FREEZE_V2 + '_DRAFT') / 'manifest.json'
    draft_manifest = read(draft_path)
    if draft_manifest.get('parent_manifest_sha256') != digest(parent_path) or draft_manifest.get('system_prompt_version') != SYSTEM_PROMPT_VERSION:
        raise ValueError('The pilot draft does not descend from the current parent freeze with the format-guidance prompt')
    summary = read(pilot_path)
    if summary.get('system_prompt_version') != SYSTEM_PROMPT_VERSION or summary.get('cohort_label') != common_v2.COHORT_LABEL_V2:
        raise ValueError('The pilot did not run the E1-C2 format-guidance prompt')
    pilot = v1.inspect_pilot('E1', pilot_path, draft_path)
    out = FREEZES / common_v2.FREEZE_V2
    if out.exists():
        raise ValueError('Never overwrite an independent protocol freeze: ' + str(out))
    fields = cohort_fields_v2(parent_path, parent, out, 'FROZEN_E1', True)
    differences = runtime_differences(pilot, fields['implementation_sha256'])
    manifest = {**copy.deepcopy(parent), **fields, 'phase': parent['phase'], 'pilot_evidence': str(out / 'pilot_evidence'),
                'pilot_reinspection': pilot, 'pilot_runtime_differences': differences, 'freeze_blockers': []}
    sizes = {'episodes': len(common_v2.claude_e1_plan_v2(dict(manifest)))}
    if check_only:
        return {'status': 'READY_FOR_E1_CLAUDE_V2_FREEZE', 'declared': sizes, 'new_model_calls': 0, 'new_physical_calls': 0}
    out.mkdir(mode=0o700)
    shutil.copytree(Path(pilot_path).resolve().parent, out / 'pilot_evidence')
    for name in common_v2.NEW_IMPLEMENTATION_V2:
        destination = out / 'implementation' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    save(out / 'model_config.json', model_config_v2('FROZEN_E1_CLAUDE_V2_POLICY'))
    save(out / 'parent_freeze.json', {'parent_freeze_id': common.PARENT['E1'], 'parent_manifest_path': str(parent_path),
                                      'parent_manifest_sha256': digest(parent_path), 'predecessor_cohort': common_v2.PREDECESSOR,
                                      'parent_directory_untouched': True})
    save(out / 'manifest.json', manifest)
    save(out / 'freeze_identity.json', {'files_sha256': {str(p.relative_to(out)): digest(p) for p in sorted(out.rglob('*')) if p.is_file()}})
    for filename in sorted(out.rglob('*'), reverse=True):
        filename.chmod(0o555 if filename.is_dir() else 0o444)
    out.chmod(0o555)
    v1.receipt('E1', 'A6_FREEZE', {'freeze': str(out / 'manifest.json'), 'declared': sizes, 'new_model_calls': 0, 'new_physical_calls': 0})
    return {'status': 'FROZEN_E1', 'cohort': common_v2.COHORT_LABEL_V2, 'manifest': str(out / 'manifest.json'),
            'declared': sizes, 'new_model_calls': 0, 'new_physical_calls': 0}


def check(manifest_path):
    manifest = read(manifest_path)
    prospective = {**manifest, 'status': 'FROZEN_E1', 'formal_dispatch': True, 'freeze_id': common_v2.FREEZE_V2}
    jobs = common_v2.claude_e1_plan_v2(prospective)
    return {'declared': {'episodes': len(jobs)}, 'first_jobs': [(j['task_id'], j['method'], j['trial_id']) for j in jobs[:4]],
            'system_prompt_version': manifest.get('system_prompt_version')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('draft')
    f = sub.add_parser('freeze')
    f.add_argument('--pilot', type=Path, required=True)
    f.add_argument('--check-only', action='store_true')
    c = sub.add_parser('check')
    c.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'draft':
        print(json.dumps(draft(), indent=2))
    elif args.command == 'freeze':
        print(json.dumps(freeze(args.pilot, args.check_only), indent=2))
    else:
        print(json.dumps(check(args.manifest), indent=2))
