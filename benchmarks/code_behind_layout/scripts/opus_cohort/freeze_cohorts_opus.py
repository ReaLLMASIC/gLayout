#!/usr/bin/env python3
"""Draft, check and freeze the Claude policy cohorts E1-C and E3-C without touching any frozen file.

Run from the repository root on the server (runtime/GLdev/bin/python) for draft and freeze:
  draft  --kind E3|E1            write runtime/protocol_freezes/<FREEZE>_DRAFT for the bounded pilot
  freeze --kind E3|E1 --pilot P  verify the returned pilot, then write the read-only cohort freeze
  check  --kind E3|E1 --manifest M   re-derive the declared matrix from a manifest and print sizes

A draft or freeze makes no model call and no physical call. The parent freeze directory is only
read: packets, hidden configurations, risk model, qualification and baseline plans stay where
they are and are referenced by their parent paths. Hidden configuration contents are never read.
"""
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.opus_cohort import common  # noqa: E402
from scripts.opus_cohort.common import (AMENDMENT, COHORT_LABEL, FREEZE, FROZEN_STATUS, MINIMUM,  # noqa: E402
                                          NEW_IMPLEMENTATION, PARENT, POLICY_BACKEND, POLICY_MODEL,
                                          digest, minimum_subset, now, read, save)

FREEZES = ROOT / 'runtime/protocol_freezes'
LOCAL_MODEL_CONFIG = ROOT / 'configs/models/claude_opus55_16k.json'
E3_PILOT_BUDGET = {'wall_seconds': 900, 'decisions': 2, 'patches': 1, 'full_evaluations': 1,
                   'maximum_context_tokens': 16384, 'maximum_output_tokens': 1024}
PILOT_RULE = ('Bounded development interface control: at most two Claude decisions and one visible full '
              'evaluation per session, no hidden or post-freeze call, raw CLI envelopes retained.')


def parent_manifest(kind):
    path = FREEZES / PARENT[kind] / 'manifest.json'
    manifest = read(path)
    if manifest['status'] != FROZEN_STATUS[kind] or manifest['formal_dispatch'] is not True or path.stat().st_mode & 0o222:
        raise ValueError('Parent freeze is not the read-only formal protocol: ' + str(path))
    return path, manifest


def implementation_bindings(parent):
    """Parent bindings must still hold byte for byte; the cohort adds its own new files."""
    bindings = dict(parent['implementation_sha256'])
    for name, expected in bindings.items():
        if digest(ROOT / name) != expected:
            raise ValueError('Frozen parent implementation differs from live source: ' + name)
    for name in NEW_IMPLEMENTATION:
        if name in bindings:
            raise ValueError('A cohort file collides with a parent binding: ' + name)
        bindings[name] = digest(ROOT / name)
    return bindings


def model_config(status):
    config = read(LOCAL_MODEL_CONFIG)
    if (config['backend'] != POLICY_BACKEND or config['model'] != POLICY_MODEL or config['max_context_tokens'] != 16384
            or config['max_new_tokens'] != 1024 or config.get('tools_disabled') is not True):
        raise ValueError('The local Claude model configuration is not the declared bounded policy')
    config.update(status=status, visible_history_policy='current_source_and_feedback_v1')
    return config


def cohort_fields(kind, parent_path, parent, out, status, formal):
    seed = parent['dispatch_order_seed']
    fields = {'status': status, 'formal_dispatch': formal, 'freeze_id': out.name, 'frozen_at_utc': now(),
              'backend_manifest_path': str(out / 'manifest.json'), 'model_config': str(out / 'model_config.json'),
              'parent_freeze_id': PARENT[kind], 'parent_manifest_path': str(parent_path), 'parent_manifest_sha256': digest(parent_path),
              'policy_backend': POLICY_BACKEND, 'policy_model': POLICY_MODEL, 'cohort_label': COHORT_LABEL[kind],
              'minimum_tier': MINIMUM, 'protocol_amendment': AMENDMENT, 'implementation_sha256': implementation_bindings(parent),
              'cohort_rule': ('Same tasks, anchors, visible and hidden configurations, references, benches, budgets, '
                              'selection rules and gateway as the parent freeze; only the policy backend, the adapter '
                              'implementation and the Minimum-tier matrix differ. Parent trials stay a separate matrix.')}
    if kind == 'E3':
        fields.update(trials=MINIMUM['e3_trials'],
                      parameter_task_ids_minimum=minimum_subset(parent['parameter_task_ids'], seed, MINIMUM['parameter_tasks']),
                      signal_task_ids_minimum=minimum_subset(parent['signal_task_ids'], seed, MINIMUM['signal_tasks']),
                      local_task_ids_minimum=sorted(parent['parameter_task_ids']),
                      subset_rule='random.Random(dispatch_order_seed).sample(sorted(parent common subset), 4); local-model searches use the parent common eight-task subset',
                      e4_evaluation={**parent['e4_evaluation'], 'inference_trials': MINIMUM['local_inference_trials']},
                      global_release_parts=list(common.E3_PARTS), global_release_requires_fidelity_freeze=False,
                      hidden_release_file=str(ROOT / 'runtime/evaluation_releases' / ('E3_' + out.name + '.json')),
                      hidden_evaluation=('Deferred per cohort (amendment A2): released once every declared E3-C search is sealed '
                                         'and the E4 training data, split registry and recipe are frozen.'),
                      declared_searches=dict(common.E3_DECLARED))
    else:
        fields.update(trials=MINIMUM['e1_trials'], declared_episodes=common.E1_DECLARED,
                      formal_cohort_rule='Fresh 144 matched trial identities in a separate suite/index; no parent trial is carried or repeated.',
                      cohort_analysis_rule='Only this cohort-specific complete index enters its task-paired analysis.')
    return fields


def draft(kind):
    parent_path, parent = parent_manifest(kind)
    out = FREEZES / (FREEZE[kind] + '_DRAFT')
    if out.exists():
        raise ValueError('Never overwrite an existing cohort draft: ' + str(out))
    out.mkdir(mode=0o755)
    status = {'E3': 'DRAFT_E3_CLAUDE_PILOT', 'E1': 'DRAFT_E1_RUNNER'}[kind]
    manifest = {**copy.deepcopy(parent), **cohort_fields(kind, parent_path, parent, out, status, False),
                'phase': 'development_%s_claude_pilot' % kind, 'pilot_rule': PILOT_RULE}
    if kind == 'E3':
        manifest['budget'] = E3_PILOT_BUDGET
        manifest['formal_budget'] = parent['budget']
    save(out / 'model_config.json', model_config('DRAFT_%s_CLAUDE_PILOT_POLICY' % kind))
    save(out / 'manifest.json', manifest)
    receipt(kind, 'A1_DRAFT', {'draft': str(out / 'manifest.json'), 'new_model_calls': 0, 'new_physical_calls': 0})
    return {'status': manifest['status'], 'manifest': str(out / 'manifest.json'), 'new_model_calls': 0, 'new_physical_calls': 0}


def inspect_pilot(kind, pilot_path, draft_manifest_path):
    summary = read(pilot_path)
    pilot_root = Path(pilot_path).resolve().parent
    if (summary.get('kind') != kind or summary.get('status') != 'FINITE_PILOT_RETURNED'
            or summary.get('policy_backend') != POLICY_BACKEND or summary.get('policy_model') != POLICY_MODEL
            or Path(summary.get('manifest_backend_path', '')) != draft_manifest_path or summary.get('hidden_calls') != 0):
        raise ValueError('The bounded Claude pilot did not return against this cohort draft')
    jobs = summary.get('jobs', [])
    expected_methods = {'E3': {'C', 'A'}, 'E1': {'G0', 'G1', 'G2'}}[kind]
    if {job['method'] for job in jobs} != expected_methods or len(jobs) != len(expected_methods):
        raise ValueError('The pilot must cover the declared interface methods once each')
    proofs = []
    for job in jobs:
        raw = pilot_root / 'policy' / job['method']
        if job.get('returncode') != 0 or job.get('hidden_calls') != 0 or not raw.is_dir():
            raise ValueError('A pilot session did not return cleanly with retained raw policy records: ' + job['method'])
        records = sorted(raw.glob('decisions/*/decision_*/invocation.json'))
        # A real reply is a CLI process that returned the provider envelope; the gateway may still reject its action
        # (over the shared output budget, invalid or non-JSON). Those rejections are interface observations, as in the
        # parent GPT pilot, and count as evidence that the bounded interface works end to end.
        real_reply = ('COMPLETED', 'REJECTED_SHARED_OUTPUT_BUDGET', 'REJECTED_INVALID_ACTION', 'REJECTED_NON_JSON_ACTION')
        replies = []
        for path in records:
            record = read(path)
            if type(record.get('pid')) is not int or record['pid'] <= 0 or record.get('backend') != POLICY_BACKEND:
                raise ValueError('A pilot decision lacks a real Claude CLI invocation: ' + str(path))
            if record.get('requested_model') != POLICY_MODEL or record.get('permission_denials') not in (None, []):
                raise ValueError('A pilot decision used another model or a permission path: ' + str(path))
            if record['status'] in real_reply:
                # --json-schema delivers the action through the CLI's internal structured-output turns (num_turns 2 or 3).
                allowed = (None, 1, 2, 3) if record.get('structured_output_present') else (None, 1)
                if record.get('num_turns') not in allowed or record.get('native_item_types') != [] or record.get('returncode') != 0:
                    raise ValueError('A pilot reply used native tools or did not return cleanly: ' + str(path))
                if not any('opus' in name for name in record.get('actual_models', [])):
                    raise ValueError('A pilot reply was not served by an Opus model: ' + str(path))
                replies.append({'path': str(path), 'status': record['status']})
        if len(records) > 2 or not replies:
            raise ValueError('Each pilot session needs one or two real decisions with at least one real Claude reply: ' + job['method'])
        proofs.append({'method': job['method'], 'invocations': [str(p) for p in records], 'real_replies': replies,
                       'episode_directory': job.get('episode_directory'), 'search_status': job.get('search_status'),
                       'actions_accepted': job.get('actions_accepted'), 'hidden_calls': 0})
    return {'summary': str(pilot_path), 'jobs': proofs, 'rule': PILOT_RULE}


def pilot_runtime_differences(kind, pilot, bindings):
    """Bound files whose hash at pilot time differs from the hash being frozen; only this freeze tool may differ."""
    differences = {}
    for job in pilot['jobs']:
        episode = job.get('episode_directory')
        state_path = ROOT / 'runs' / Path(episode).relative_to(ROOT / 'runs') / 'private/state.json' if episode else None
        if state_path is None or not state_path.is_file():
            continue
        state = read(state_path)
        snapshot = state.get('execution_implementation_sha256') or {}
        for name, expected in bindings.items():
            if name in snapshot and snapshot[name] != expected:
                differences.setdefault(name, []).append(job['method'])
    allowed = {'scripts/opus_cohort/freeze_cohorts_opus.py'}
    if set(differences) - allowed:
        raise ValueError('A bound runtime file changed between the pilot and the freeze: ' + ', '.join(sorted(set(differences) - allowed)))
    return {'files_changed_after_pilot': differences, 'allowed': sorted(allowed),
            'reason': 'The freeze tool itself was amended after the pilot (relaxed evidence rule, runtime-difference record); no runtime file changed.'}


def freeze(kind, pilot_path, check_only=False):
    parent_path, parent = parent_manifest(kind)
    draft_path = FREEZES / (FREEZE[kind] + '_DRAFT') / 'manifest.json'
    draft_manifest = read(draft_path)
    if draft_manifest.get('parent_manifest_sha256') != digest(parent_path) or draft_manifest.get('minimum_tier') != MINIMUM:
        raise ValueError('The pilot draft does not descend from the current parent freeze')
    pilot = inspect_pilot(kind, pilot_path, draft_path)
    out = FREEZES / FREEZE[kind]
    if out.exists():
        raise ValueError('Never overwrite an independent protocol freeze: ' + str(out))
    fields = cohort_fields(kind, parent_path, parent, out, FROZEN_STATUS[kind], True)
    runtime_differences = pilot_runtime_differences(kind, pilot, fields['implementation_sha256'])
    manifest = {**copy.deepcopy(parent), **fields, 'phase': parent['phase'], 'pilot_evidence': str(out / 'pilot_evidence'),
                'pilot_reinspection': pilot, 'pilot_runtime_differences': runtime_differences, 'freeze_blockers': []}
    prospective = dict(manifest)
    if kind == 'E3':
        sizes = {part: len(common.claude_e3_plan(prospective, part)) for part in common.E3_PARTS}
    else:
        sizes = {'episodes': len(common.claude_e1_plan(prospective))}
    if check_only:
        return {'status': 'READY_FOR_%s_CLAUDE_FREEZE' % kind, 'declared': sizes, 'new_model_calls': 0, 'new_physical_calls': 0}
    out.mkdir(mode=0o700)
    shutil.copytree(Path(pilot_path).resolve().parent, out / 'pilot_evidence')
    for name in NEW_IMPLEMENTATION:
        destination = out / 'implementation' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    save(out / 'model_config.json', model_config('FROZEN_%s_CLAUDE_POLICY' % kind))
    save(out / 'parent_freeze.json', {'parent_freeze_id': PARENT[kind], 'parent_manifest_path': str(parent_path),
                                      'parent_manifest_sha256': digest(parent_path), 'parent_directory_untouched': True})
    save(out / 'manifest.json', manifest)
    save(out / 'freeze_identity.json', {'files_sha256': {str(p.relative_to(out)): digest(p) for p in sorted(out.rglob('*')) if p.is_file()}})
    for filename in sorted(out.rglob('*'), reverse=True):
        filename.chmod(0o555 if filename.is_dir() else 0o444)
    out.chmod(0o555)
    receipt(kind, 'A1_FREEZE', {'freeze': str(out / 'manifest.json'), 'declared': sizes, 'new_model_calls': 0, 'new_physical_calls': 0})
    return {'status': FROZEN_STATUS[kind], 'cohort': COHORT_LABEL[kind], 'manifest': str(out / 'manifest.json'),
            'declared': sizes, 'new_model_calls': 0, 'new_physical_calls': 0}


def check(kind, manifest_path):
    manifest = read(manifest_path)
    prospective = {**manifest, 'status': FROZEN_STATUS[kind], 'formal_dispatch': True, 'freeze_id': FREEZE[kind]}
    if kind == 'E3':
        plans = {part: common.claude_e3_plan(prospective, part) for part in common.E3_PARTS}
        return {'declared': {part: len(jobs) for part, jobs in plans.items()},
                'first_jobs': {part: [job['job_id'] for job in jobs[:3]] for part, jobs in plans.items()},
                'parameter_task_ids_minimum': manifest.get('parameter_task_ids_minimum'),
                'signal_task_ids_minimum': manifest.get('signal_task_ids_minimum')}
    jobs = common.claude_e1_plan(prospective)
    return {'declared': {'episodes': len(jobs)}, 'first_jobs': [(j['task_id'], j['method'], j['trial_id']) for j in jobs[:4]]}


def receipt(kind, tag, payload):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder = ROOT / 'runtime/freeze_receipts' / ('%s_%s_%s' % (stamp, tag, kind))
    folder.mkdir(parents=True, exist_ok=False)
    save(folder / 'state.json', {'status': tag, 'kind': kind, 'cohort': COHORT_LABEL[kind], 'amendment': AMENDMENT,
                                 'at_utc': now(), **payload})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('draft', 'freeze', 'check'):
        p = sub.add_parser(name)
        p.add_argument('--kind', choices=('E3', 'E1'), required=True)
        if name == 'freeze':
            p.add_argument('--pilot', type=Path, required=True)
            p.add_argument('--check-only', action='store_true')
        if name == 'check':
            p.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'draft':
        print(json.dumps(draft(args.kind), indent=2))
    elif args.command == 'freeze':
        print(json.dumps(freeze(args.kind, args.pilot, args.check_only), indent=2))
    else:
        print(json.dumps(check(args.kind, args.manifest), indent=2))
