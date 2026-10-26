"""Structured E3 policy gateway; hidden execution begins only after source sealing.

The common main comparison uses actual full checks (F0). C's separate F3
ablation is not silently mixed into this A/R/B/C selector comparison.
"""
import argparse
import copy
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.e3_task_prepare import capsule
from scripts.e3_physical_point import evaluate
from scripts.e1_matched_runner import SSH, REMOTE, policy_statistics
from src.candidate_executor import apply_source_patch
from src.e3_episode_state import EpisodeState
from src.e3_feedback import compact as compact_feedback
from src.e3_feedback import public_checked
from src.model_adapter import check_utc_budget, validate_action


def now():
    return datetime.now(timezone.utc)


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    temporary = path.with_name(path.name+'.pending')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')
    temporary.replace(path)


def project(path):
    return Path(path) if Path(path).is_absolute() else ROOT/path


def verify(manifest):
    if manifest['status'] not in ('FROZEN_E3', 'FROZEN_E3_FIDELITY_METHOD'):
        return
    bindings = manifest.get('implementation_sha256')
    if not bindings:
        raise RuntimeError('Frozen E3 has no implementation binding')
    for name, expected in bindings.items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Frozen E3 live implementation differs: '+name)


def policy_packet(original, manifest, method, deadline):
    packet = copy.deepcopy(original)
    packet['documents']['status'] = 'complete_source_editing_task'
    packet['documents']['action_gateway'] = {
        'read_source_paths': sorted(packet['visible_sources']),
        'read_source_scope': 'Only these complete visible sources may be read. Runtime library/configuration paths are read by candidate code during execution; they are not gateway read_source paths. Their public schemas are already supplied in this packet.'}
    budget = manifest['budget']
    packet['budget'] = {**budget, 'deadline_utc': deadline,
        'physical_evaluations': budget['full_evaluations']}
    packet['documents']['controlled_verification'] = {
        'method': method, 'fidelity': 'pex_spice',
        'selection': 'Gateway chooses next_configuration. Request exactly that one ID; no hidden ID is visible.',
        'retention': 'After every edit recheck anchor, then all previously observed failures and passes before a new configuration.',
        'A': 'Only anchor per source revision; leave unneeded validation budget unspent.',
        'source_selection': 'All retained points S2, then observed visible S2 count, then worst objective over that same retained configuration set, then earliest source; otherwise original-source fallback.'}
    packet['documents']['physical_feedback_encoding'] = (
        'corner_metric_table stores each metric name/unit once and all original numeric measurements in matching order for every corner; no metric, corner or precision is discarded. '
        'checked contains verification/status/reason fields. Full parser inventories, host filenames and raw reports remain on the backend.')
    return packet


def require_release(manifest, episode=None, baseline=False):
    """Formal hidden work starts only after the shared global sealing release."""
    if manifest.get('status') not in ('FROZEN_E3', 'FROZEN_E3_FIDELITY_METHOD'):
        return None
    filename = project(manifest['hidden_release_file'])
    if not filename.is_file() or filename.stat().st_mode & 0o222:
        raise RuntimeError('Global hidden evaluation release is absent or not frozen readonly')
    release = read(filename)
    if (release.get('status') != 'FROZEN_E3_EVALUATION_RELEASE' or
            release.get('freeze_id') != manifest.get('main_freeze_id', manifest['freeze_id']) or
            release.get('all_declared_searches_sealed') is not True or
            release.get('all_models_frozen') is not True):
        raise RuntimeError('The shared source/model sealing release does not match this E3 freeze')
    if (manifest['status'] == 'FROZEN_E3_FIDELITY_METHOD' and
            release.get('fidelity_freeze_id') != manifest['freeze_id']):
        raise RuntimeError('The shared release does not bind this F3 fidelity freeze')
    if baseline:
        if release['original_baseline_plan'] != manifest['original_baseline_plan']:
            raise RuntimeError('The released original baseline plan differs')
        return release
    episode = project(episode).resolve()
    matches = [row for row in release['sealed_searches'] if Path(row['episode_directory']).resolve() == episode]
    if len(matches) != 1:
        raise RuntimeError('This source was not part of the global release')
    value = read(episode/'private/state.json')
    task = read(episode/'private/task.json')
    if not value['sealed']:
        raise RuntimeError('Release cannot open an unsealed source')
    source = episode/'private'/('revisions/%03d/source' % value['selection']['revision'])
    actual = {name: hashlib.sha256((source/name).read_bytes()).hexdigest() for name in task['source_files']}
    if actual != matches[0]['selected_source_sha256']:
        raise RuntimeError('The sealed source differs from the source in the global release')
    return release


def initialize(request, expected_fidelity='F0_actual_full_each_selected_configuration'):
    manifest = read(project(request['manifest']))
    formal = request.get('formal', False)
    expected_status = ('FROZEN_E3_FIDELITY_METHOD' if
        expected_fidelity == 'F3_actual_nominal_promote_shared_PEX' else 'FROZEN_E3')
    if formal and not (manifest['status'] == expected_status and manifest['formal_dispatch'] is True):
        raise ValueError('Formal E3 needs its own complete prospective protocol freeze')
    if manifest['fidelity_policy'] != expected_fidelity:
        raise ValueError('The main A/R/B/C comparison uses one fixed fidelity policy')
    verify(manifest)
    ident, method = request['task_id'], request['method']
    if ident not in manifest['task_ids'] or method not in ('A', 'R', 'B', 'C'):
        raise ValueError('Task/method outside the declared E3 matrix')
    variant = request.get('policy_variant', 'GPT')
    selector_variant = request.get('selector_variant', 'main')
    weights = manifest.get('risk_weights')
    if selector_variant != 'main':
        if method != 'C' or variant != 'GPT' or selector_variant not in manifest.get('selector_ablation_weights', {}):
            raise ValueError('Only a prospectively declared C signal ablation may change selector weights')
        weights = manifest['selector_ablation_weights'][selector_variant]
    slot = request.get('evaluation_seed_slot', 41)
    trial = str(request.get('trial_id', 'development'))
    allowed_trials = {'1', '2', '3', '4', '5'} if variant == 'GPT' else {'1', '2', '3'}
    if formal and (trial not in allowed_trials or
            request['selection_seed'] != manifest['selection_seeds'][int(trial)-1]):
        raise ValueError('Formal trial identity and configuration-selection seed must match the frozen matrix')
    preparation = project(manifest['preparation'])
    task_path = preparation/'private'/ident/'task.json'
    task = read(task_path)
    if formal and not task.get('formal_admission'):
        raise ValueError('Editing state lacks actual physical/shortfall admission')
    if method == 'C':
        # The artifact/predictor must be completed from train/validation before
        # this gate can open. Caller-provided or hidden outcome scores are refused.
        from src.e3_risk_model import load_frozen_predictor
        artifact = read(project(manifest['risk_model']))
        if formal and artifact.get('formal_C_ready') is not True:
            raise ValueError('C needs its actual selector control and prospectively frozen rule artifact')
        load_frozen_predictor(project(manifest['risk_model']))
    public = [p for p in task['configurations'] if p['role'] != 'hidden']
    state = EpisodeState(method, public, request['selection_seed'],
        task['configurations'][0]['contract']['objective']['direction'], weights)
    budget = manifest['budget']
    required = {'wall_seconds', 'decisions', 'patches', 'full_evaluations',
                'maximum_context_tokens', 'maximum_output_tokens'}
    if set(budget) != required or any(type(value) is not int or value <= 0 for value in budget.values()):
        raise ValueError('Freeze explicit positive E3 budgets after actual calibration')
    if budget['maximum_output_tokens'] != 1024:
        raise ValueError('Common ordinary action output budget is1024 including EOS')
    stamp = now().strftime('%Y%m%dT%H%M%S%fZ_')+uuid.uuid4().hex[:8]
    out = ROOT/('runs/formal/E3' if formal else 'runs/development/E3_episodes')/stamp
    private = out/'private'
    private.mkdir(parents=True, mode=0o700)
    (out/'public').mkdir()
    save(private/'manifest.json', manifest)
    save(private/'task.json', task)
    source = private/'revisions/000/source'
    source.parent.mkdir(parents=True)
    capsule(task_path, source)
    deadline = now()+timedelta(seconds=budget['wall_seconds'])
    packet = policy_packet(read(preparation/'public'/ident/'packet.json'), manifest, method, deadline.isoformat())
    save(private/'packet.json', packet)
    if variant == 'GPT':
        model = read(project(manifest['model_config']))
    else:
        if method != 'C' or not formal:
            raise ValueError('The local E4 comparison uses the frozen C algorithm and actual formal model artifacts')
        from src.e3_policy_models import resolve
        model = resolve(manifest, ROOT, variant, slot, SSH, REMOTE)
    model['visible_history_policy'] = 'current_source_and_feedback_v1'
    state.value.update(episode_directory=str(out), task_path=str(task_path), formal_trial=formal,
        trial_id=trial, phase='formal_E3' if formal else 'development_E3',
        policy_variant=variant, training_seed=None if variant in ('GPT', 'T0') else slot,
        evaluation_seed_slot=None if variant == 'GPT' else slot,
        selector_variant=selector_variant, policy_model_identity=model.get('model_identity'),
        status='RUNNING', created_at_utc=now().isoformat(), deadline_utc=deadline.isoformat(),
        decisions=0, patch_attempts=0, full_evaluations=0, in_flight=None,
        physical_events=[], resource_waits=[], post_freeze_started=False,
        contract=packet['contract'],
        contracts_by_configuration={p['configuration_id']: p['contract'] for p in public},
        initial_sources={name: (source/name).read_text() for name in task['editable_paths']})
    save(private/'state.json', state.value)
    return {'episode_directory': str(out), 'packet': packet, 'model_config': model,
        'implementation_sha256': manifest.get('implementation_sha256')}


class Gateway:
    def __init__(self, out):
        self.out = project(out)
        self.private = self.out/'private'
        self.manifest = read(self.private/'manifest.json')
        verify(self.manifest)
        self.task = read(self.private/'task.json')
        self.packet = read(self.private/'packet.json')
        self.state = EpisodeState.restore(read(self.private/'state.json'))
        if self.state.value['in_flight']:
            raise RuntimeError('Retained physical call is unresolved; reconcile it instead of repeating')

    def source(self, revision=None):
        if revision is None:
            revision = self.state.value['revision']
        return self.private/('revisions/%03d/source' % revision)

    def sources(self):
        return {name: (self.source()/name).read_text() for name in self.task['editable_paths']}

    def write(self):
        save(self.private/'state.json', self.state.value)

    def predictions(self):
        if self.state.value['method'] != 'C':
            return None
        from src.e3_risk_model import load_frozen_predictor
        predictor = load_frozen_predictor(project(self.manifest['risk_model']))
        return predictor.predict(self.sources(), self.state.value,
            {p['configuration_id']: p['parameters'] for p in self.task['configurations'] if p['role'] != 'hidden'})

    def next(self):
        return self.state.next_configuration(self.predictions())

    def current(self):
        return {'current_sources': self.sources(), 'next_configuration': self.next(),
            'revision': self.state.value['revision'], 'full_evaluations': self.state.value['full_evaluations'],
            'remaining_full_evaluations': self.manifest['budget']['full_evaluations']-self.state.value['full_evaluations']}

    def physical(self, ident, revision, stage):
        value = self.state.value
        if stage == 'search':
            check_utc_budget(self.packet)
            if value['sealed'] or value['full_evaluations'] >= self.manifest['budget']['full_evaluations']:
                raise ValueError('Search source sealed or full-check budget exhausted')
        from scripts.e3_generation_qualify import gate
        if shutil.disk_usage(ROOT).free < 4*1024**3:
            raise RuntimeError('Research storage below4GiB; no new physical point dispatched')
        waiting = {'stage': stage, 'started_at_utc': now().isoformat(), 'status': 'WAITING'}
        value.setdefault('resource_waits', []).append(waiting)
        began = time.monotonic()
        self.write()
        try:
            remaining = check_utc_budget(self.packet) if stage == 'search' else None
            waiting.update(gate(timeout=min(600, remaining) if remaining is not None else 600), status='OPEN')
            if stage == 'search':
                check_utc_budget(self.packet)
        except Exception as error:
            waiting.update(status='NOT_DISPATCHED', error=type(error).__name__+': '+str(error))
            raise
        finally:
            waiting.update(ended_at_utc=now().isoformat(), actual_wait_wall_seconds=time.monotonic()-began)
            self.write()
        if stage == 'search':
            value['full_evaluations'] += 1
        event = {'configuration_id': ident, 'revision': revision, 'stage': stage,
            'started_at_utc': now().isoformat(), 'status': 'RUNNING'}
        value['in_flight'] = event
        value['physical_events'].append(event)
        self.write()
        folder = self.private/('points/%04d_%s' % (len(value['physical_events']), ident))
        row = evaluate(self.private/'task.json', ident, folder, self.source(revision),
            deadline=value['deadline_utc'] if stage == 'search' else None, formal=value['formal_trial'])
        event.update(status='RETURNED', ended_at_utc=now().isoformat(), point_record=str(folder/'point.json'),
            execution_integrity=row['checked']['execution_integrity'])
        value['in_flight'] = None
        if row['checked']['execution_integrity'] != 'valid':
            value['status'] = ('BUDGET_EXHAUSTED' if row['checked']['execution_integrity'] == 'budget_exhausted'
                else 'INCOMPLETE_UNKNOWN')
        self.write()
        return row

    def action(self, action):
        value = self.state.value
        check_utc_budget(self.packet)
        if value['sealed'] or value['status'] != 'RUNNING':
            raise ValueError('Episode search is closed')
        if value['decisions'] >= self.manifest['budget']['decisions']:
            raise ValueError('Decision budget exhausted')
        value['decisions'] += 1
        self.write()
        validate_action(action, self.packet)
        kind = action['action']
        if kind == 'read_source':
            return {'path': action['path'], 'content': self.sources()[action['path']]}
        if kind == 'finish':
            value['status'] = 'SEARCH_FINISHED'
            self.write()
            return {'search_finished': True}
        if kind == 'propose_patch':
            if value['anchor'] not in value['revisions'][0]['results']:
                raise ValueError('Acquire actual original anchor feedback before the first edit')
            if value['patch_attempts'] >= self.manifest['budget']['patches']:
                raise ValueError('Candidate patch budget exhausted')
            value['patch_attempts'] += 1
            self.write()
            target = self.private/('revisions/%03d/source' % (value['revision']+1))
            target.parent.mkdir()
            shutil.copytree(self.source(), target)
            try:
                apply_source_patch(target, action['patch'], self.task['editable_paths'])
                if all((target/name).read_bytes() == (self.source()/name).read_bytes() for name in self.task['editable_paths']):
                    raise ValueError('Patch does not change the complete editable source')
            except Exception:
                shutil.rmtree(target.parent)
                raise
            save(target.parent/'action.json', action)
            self.state.new_revision()
            self.write()
            return {'patch_applied': True, 'revision': value['revision'], 'next_configuration': self.next()}
        if kind == 'request_evaluation':
            ident = self.next()
            if ident is None:
                raise ValueError('No further configuration required for this source; edit or finish')
            if action['configuration_ids'] != [ident] or action['fidelity'] != 'pex_spice':
                raise ValueError('Controlled next check is '+ident+' at pex_spice')
            row = self.physical(ident, value['revision'], 'search')
            if row['checked']['execution_integrity'] == 'valid':
                self.state.observe(row)
                self.write()
            return {'configuration_id': ident, 'revision': value['revision'],
                'checked': public_checked(row['checked']), 'objective': row['objective'],
                'episode_status': value['status'],
                'physical_feedback': compact_feedback(row['physical_feedback']),
                'next_configuration': self.next() if value['status'] == 'RUNNING' else None}
        raise ValueError('Unknown structured action')

    def seal(self, status, usage):
        value = self.state.value
        selection = self.state.select_source()
        value.update(status=status, policy_statistics=usage, sealed_at_utc=now().isoformat())
        self.write()
        save(self.out/'public/search.json', {'task_id': self.task['task_id'], 'method': value['method'],
            'trial_id': value.get('trial_id', 'development'), 'phase': value.get('phase', 'development_E3'),
            'policy_variant': value.get('policy_variant', 'GPT'), 'training_seed': value.get('training_seed'),
            'evaluation_seed_slot': value.get('evaluation_seed_slot'),
            'selector_variant': value.get('selector_variant', 'main'),
            'policy_model_identity': value.get('policy_model_identity'),
            'status': status, 'selection': selection, 'full_evaluations': value['full_evaluations'],
            'decisions': value['decisions'], 'formal_trial': value['formal_trial'], 'policy_statistics': usage,
            'source_group': self.task['logical_group'], 'merged_source_group': self.task['merge_sensitivity_group'],
            'costs_by_stage': self.costs(), 'resource_waits': value.get('resource_waits', [])})
        return read(self.out/'public/search.json')

    def costs(self):
        stages = {}
        for event in self.state.value['physical_events']:
            stage = 'search' if event['stage'] == 'search' else ('hidden' if event['stage'].endswith('_hidden') else 'post_freeze_diagnostic')
            total = stages.setdefault(stage, {'physical_calls': 0, 'stage_wall_seconds': 0.,
                'waited_child_CPU_seconds': 0., 'missing_CPU_records': 0, 'unresolved_calls': 0})
            total['physical_calls'] += 1
            if event['status'] != 'RETURNED':
                total['unresolved_calls'] += 1
                continue
            point = read(event['point_record'])
            run = Path(point['run_directory'])
            manifest = read(run/'manifest.json')
            for name in ('candidate', 'trusted'):
                if name not in manifest:
                    continue
                total['stage_wall_seconds'] += manifest[name]['wall_seconds']
                usage = run/(name+'_stage/resource_usage.json')
                if usage.exists():
                    raw = read(usage)
                    total['waited_child_CPU_seconds'] += raw['child_user_cpu_seconds']+raw['child_system_cpu_seconds']
                else:
                    total['missing_CPU_records'] += 1
        return stages

    def post_freeze(self):
        value = self.state.value
        if not value['sealed'] or value['post_freeze_started']:
            raise ValueError('Post-freeze evaluation requires a sealed source and runs once')
        if value['formal_trial']:
            require_release(self.manifest, self.out)
        value['post_freeze_started'] = True
        self.write()
        if value['status'] == 'INCOMPLETE_UNKNOWN':
            report = {**read(self.out/'public/search.json'), 'hidden_domain_size': 16,
                'hidden_S2_verified': 0, 'hidden_S1_verified': 0, 'hidden_incomplete': 16,
                'post_freeze_complete': False, 'hidden_results_exposed_to_policy': False,
                'hidden_point_records_exported': False,
                'reason': 'Affected episode paused for incomplete physical/transport execution; no hidden calls dispatched'}
            save(self.out/'public/episode.json', report)
            return report
        revision = value['selection']['revision']
        rows = []
        # Fresh diagnostics are outside policy search. No hidden result returns
        # to the model, and unknown is retained without an automatic repeat.
        for point in self.task['configurations']:
            row = self.physical(point['configuration_id'], revision, 'post_freeze_'+point['role'])
            rows.append({'configuration_id': point['configuration_id'], 'role': point['role'],
                'checked': row['checked'], 'objective': row['objective']})
            save(self.private/'post_freeze_points.json', rows)
            if row['checked']['execution_integrity'] != 'valid':
                break
        known_hidden = sum(row['role'] == 'hidden' and row['checked']['execution_integrity'] == 'valid' for row in rows)
        report = {**read(self.out/'public/search.json'),
            'visible_selected_source_evaluation': [row for row in rows if row['role'] != 'hidden'],
            'hidden_domain_size': 16, 'hidden_S2_verified': sum(row['role'] == 'hidden' and row['checked']['S2'] for row in rows),
            'hidden_S1_verified': sum(row['role'] == 'hidden' and row['checked']['S1'] for row in rows),
            'hidden_incomplete': 16-known_hidden,
            'post_freeze_points_attempted': len(rows),
            'post_freeze_points_NOT_RUN': len(self.task['configurations'])-len(rows),
            'post_freeze_complete': len(rows) == len(self.task['configurations']) and all(
                row['checked']['execution_integrity'] == 'valid' for row in rows),
            'hidden_results_exposed_to_policy': False, 'hidden_point_records_exported': False,
            'baseline_regression_status': 'PENDING_SEPARATE_IMMUTABLE_BASELINE_JOIN',
            'costs_by_stage': self.costs(), 'resource_waits': value.get('resource_waits', [])}
        save(self.out/'public/episode.json', report)
        return report


def backend(request):
    if request['op'] == 'start':
        return initialize(request)
    out = project(request['episode_directory'])
    with (out/'private/backend.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        gateway = Gateway(out)
        if request['op'] == 'current':
            return gateway.current()
        if request['op'] == 'action':
            return gateway.action(request['action'])
        if request['op'] == 'seal':
            return gateway.seal(request['status'], request.get('policy_statistics'))
        if request['op'] == 'post_freeze':
            return gateway.post_freeze()
        raise ValueError('Unknown gateway operation')


def transport(request):
    command = SSH+['cd '+shlex.quote(REMOTE)+' && '+shlex.quote(REMOTE+'/runtime/GLdev/bin/python')+' scripts/e3_episode.py --backend']
    run = subprocess.run(command, input=json.dumps(request), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if run.returncode:
        raise RuntimeError('E3 transport failed: '+run.stderr[-1500:])
    envelope = json.loads(run.stdout)
    if envelope.get('error'):
        if envelope['error_type'] == 'TimeoutError':
            raise TimeoutError(envelope['error'])
        if envelope['error_type'] == 'ValueError':
            raise ValueError(envelope['error'])
        raise RuntimeError(envelope['error'])
    return envelope['result']


def run_policy(args, rpc=transport):
    from transformers import AutoTokenizer
    from src.model_adapter import GptDecisionAdapter
    initialized = rpc({'op': 'start', 'manifest': args.manifest, 'task_id': args.task,
        'method': args.method, 'selection_seed': args.selection_seed, 'trial_id': args.trial, 'formal': args.formal,
        'policy_variant': args.variant, 'evaluation_seed_slot': args.training_seed,
        'selector_variant': args.selector_variant})
    directory = initialized['episode_directory']
    out = ROOT/('runs/formal/E3_policy' if args.formal else 'runs/development/E3_policy')/Path(directory).name
    out.mkdir(parents=True)
    save(out/'backend.json', {'episode_directory': directory})
    if args.dispatch_record:
        save(args.dispatch_record, {'episode_directory': directory, 'local_output_directory': str(out),
            'task_id': args.task, 'method': args.method, 'trial_id': args.trial, 'formal': args.formal,
            'policy_variant': args.variant, 'evaluation_seed_slot': None if args.variant == 'GPT' else args.training_seed,
            'selector_variant': args.selector_variant,
            'training_seed': args.training_seed if args.variant in ('T1', 'T2', 'T3', 'T4') else None})
    if args.formal:
        verify({'status': 'FROZEN_E3', 'implementation_sha256': initialized['implementation_sha256']})
    tokenizer = AutoTokenizer.from_pretrained(ROOT/'runtime/policy_tokenizer', local_files_only=True, trust_remote_code=False)
    if args.variant == 'GPT':
        adapter = GptDecisionAdapter(out/'decisions', tokenizer=tokenizer)
    else:
        from src.local_model_adapter import LocalDecisionAdapter
        adapter = LocalDecisionAdapter(out/'decisions', initialized['model_config']['request_command'])
    session = adapter.start(initialized['packet'], initialized['model_config'])
    status = 'DECISION_BUDGET_EXHAUSTED'
    observation = {'status': 'initial'}
    try:
        for _ in range(initialized['packet']['budget']['decisions']):
            current = rpc({'op': 'current', 'episode_directory': directory})
            observation = {**observation, 'next_configuration': current['next_configuration']}
            action = adapter.step(session, observation, current_sources=current['current_sources'])
            try:
                observation = rpc({'op': 'action', 'episode_directory': directory, 'action': action})
            except ValueError as error:
                observation = {'error': str(error), 'next_configuration': current['next_configuration']}
            if action['action'] == 'finish':
                status = 'SEARCH_FINISHED'
                break
            if observation.get('checked', {}).get('execution_integrity') not in (None, 'valid'):
                status = observation['episode_status']
                break
    except TimeoutError:
        status = 'BUDGET_EXHAUSTED'
    except Exception as error:
        # Keep transport uncertainty separate from a model's invalid/overlong
        # action. A failed decision still leaves a reproducible source to test.
        status = ('CONTEXT_BUDGET_EXHAUSTED' if isinstance(error, ValueError) and
            str(error).startswith('Complete GPT source/history exceeds the shared context budget')
            else 'MODEL_FAILED' if isinstance(error, ValueError) else 'INCOMPLETE_UNKNOWN')
        save(out/'error.json', {'error': type(error).__name__+': '+str(error)})
    finally:
        session['closed'] = True
        save(out/'session.json', session)
        statistics = policy_statistics(session, out)
        if args.variant != 'GPT':
            statistics['actual_local_inference_usage'] = statistics.pop('actual_provider_usage')
            statistics['scope'] = 'Actual isolated client invocations and local inference-server telemetry; T0 uses one backbone. Server CUDA time and end-to-end wall are separate overlapping measures.'
        report = rpc({'op': 'seal', 'episode_directory': directory, 'status': status,
            'policy_statistics': statistics})
        save(out/'search.json', report)
    if args.formal or args.search_only:
        print(json.dumps({'status': 'SEARCH_SEALED_AWAITING_GLOBAL_RELEASE',
            'episode_directory': directory, 'search_report': str(out/'search.json'),
            'hidden_calls': 0}), flush=True)
        return
    report = rpc({'op': 'post_freeze', 'episode_directory': directory})
    save(out/'episode.json', report)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backend', action='store_true')
    p.add_argument('--manifest')
    p.add_argument('--task')
    p.add_argument('--method', choices=['A', 'R', 'B', 'C'])
    p.add_argument('--selection-seed', type=int, default=41)
    p.add_argument('--trial', default='development')
    p.add_argument('--variant', choices=['GPT', 'T0', 'T1', 'T2', 'T3', 'T4'], default='GPT')
    p.add_argument('--training-seed', type=int, choices=[41, 73, 109], default=41)
    p.add_argument('--selector-variant', choices=['main', 'without_distance', 'without_margin'], default='main')
    p.add_argument('--dispatch-record', type=Path)
    p.add_argument('--search-only', action='store_true', help='Development control without diagnostic or hidden calls; formal searches always defer evaluation')
    p.add_argument('--formal', action='store_true')
    a = p.parse_args()
    if a.backend:
        try:
            print(json.dumps({'result': backend(json.load(sys.stdin))}), flush=True)
        except Exception as error:
            print(json.dumps({'error': str(error), 'error_type': type(error).__name__}), flush=True)
    else:
        if not (a.manifest and a.task and a.method):
            p.error('Policy execution requires manifest, task and method')
        run_policy(a)
