#!/usr/bin/env python3
"""Actual parameter-search consumer for the prospective E3 comparison.

P edits only layout_parameters.json. The trusted renderer reconstructs the
complete layout module from its immutable original, and the ordinary E3 point
gateway performs full physical checks. GPT uses simulation feedback and its
recorded experience; this is ICPI-inspired, not a reproduction of ICPI.
"""
import argparse
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import difflib
import fcntl
import json
from pathlib import Path
import random
import shlex
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.e3_episode import Gateway, initialize, now, project, read, save, verify
from scripts.e1_matched_runner import SSH, REMOTE, policy_statistics
from scripts.e3_task_prepare import make_working_directories_writable
from src.candidate_executor import apply_source_patch
from src.e3_parameters import interface, render
from src.model_adapter import check_utc_budget, validate_action

CONTROL = 'layout_parameters.json'
STRATEGIES = ('random', 'gpt_feedback')
RANDOM_RULE = 'anchor_then_retained_checks_then_one_new_selected_configuration_before_next_draw_v1'


def canonical(controls):
    return json.dumps(controls, indent=2, allow_nan=False)+'\n'


def parse_controls(text):
    def unique(pairs):
        values = {}
        for key, value in pairs:
            if key in values:
                raise ValueError('Duplicate parameter name: '+key)
            values[key] = value
        return values
    result = json.loads(text, object_pairs_hook=unique)
    if not isinstance(result, dict):
        raise ValueError('The complete parameter file must be a JSON object')
    return result


def action(kind, **fields):
    result = dict(action=kind, path='', patch='', configuration_ids=[], fidelity='', summary='')
    result.update(fields)
    return result


def patch_action(before, after, summary):
    patch = ''.join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile='a/'+CONTROL, tofile='b/'+CONTROL))
    return action('propose_patch', patch=patch, summary=summary)


def draw_controls(domain, seed, index):
    """One reproducible draw over the whole declared grid, without an oracle."""
    generator = random.Random(seed+1009*index)
    result = {}
    for name, rule in domain['parameters'].items():
        step = Decimal(str(rule['step']))
        low = int((Decimal(str(rule['min']))/step).to_integral_value(rounding=ROUND_CEILING))
        high = int((Decimal(str(rule['max']))/step).to_integral_value(rounding=ROUND_FLOOR))
        if low > high:
            raise ValueError('Empty declared parameter grid')
        result[name] = float(step*generator.randint(low, high))
    return result


def validate_baseline(manifest, strategy):
    baseline = manifest['parameter_baseline']
    if (strategy not in STRATEGIES or strategy not in baseline['strategies'] or
            baseline['configuration_selector'] not in ('A', 'R', 'B', 'C') or
            baseline['interface'] != 'prospective_expanded_layout_grid_v1'):
        raise ValueError('The parameter strategy, selector and expanded interface must be explicit')
    return baseline


def binding(task):
    stored = task['expanded_parameter_baseline']
    pdk = read(stored['frozen_PDK_rules'])
    domain = interface(task['target'], pdk)
    if stored['version'] != domain['version'] or stored['parameters'] != domain['parameters']:
        raise ValueError('The frozen parameter interface differs from its actual PDK rules')
    original = Path(stored['immutable_original_module']).read_text()
    return domain, pdk, original


def start(request):
    started, cpu = time.monotonic(), time.process_time()
    manifest = read(project(request['manifest']))
    strategy = request['strategy']
    baseline = validate_baseline(manifest, strategy)
    result = initialize({**request, 'method': baseline['configuration_selector']})
    private = Path(result['episode_directory'])/'private'
    task = read(private/'task.json')
    domain, pdk, original = binding(task)
    if len(task['editable_paths']) != 1:
        raise ValueError('The current parameter renderer binds one complete editable module')
    expected = render(task['target'], original, task['parameter_controls'], pdk)
    if (private/'revisions/000/source'/task['editable_paths'][0]).read_text() != expected:
        raise ValueError('The declared controls do not exactly express the actual initial source')
    control_dir = private/'control_revisions/000'
    control_dir.mkdir(parents=True)
    (control_dir/CONTROL).write_text(canonical(task['parameter_controls']))
    packet = result['packet']
    packet.update(goal='Optimize the existing layout using only the declared layout parameters. Preserve the independent circuit and all electrical constraints.',
        allowed_paths=[CONTROL], visible_sources={CONTROL: canonical(task['parameter_controls'])})
    packet['documents'].setdefault('action_gateway', {}).update(
        read_source_paths=list(packet['visible_sources']),
        read_source_scope='Only these exact visible-source keys may be requested. Candidate runtime/library/configuration paths are not read_source paths; their complete API schemas are supplied in documents.')
    packet['documents'].update(
        parameter_baseline={
            'strategy': strategy, 'configuration_selector': baseline['configuration_selector'],
            'interface': domain, 'physical_evaluation': 'The same actual full E3 verification at each selected visible configuration.',
            'immutable_sizing': 'N(z), device dimensions, ports, PDK, renderer, and simulation settings cannot be edited.',
            'method_scope': 'ICPI-inspired simulation-feedback parameter search; not an ICPI reproduction.'},
        readonly_layout_program={'complete_immutable_original_module': original,
            'purpose': 'Every candidate is reconstructed from this exact complete module by the frozen layout-site renderer.'},
        patch_format='Ordinary unified diff only for a/layout_parameters.json and b/layout_parameters.json; supply every declared numeric key.',
        CLI='The backend validates bounds/grid and renders the complete module. Only candidate.gds crosses the isolated physical boundary.',
        experience_policy='Use the actual previous physical results, failures, and parameter proposals in this session. No unobserved outcome is a simulation result.')
    save(private/'packet.json', packet)
    state = read(private/'state.json')
    state.update(parameter_strategy=strategy, parameter_selector=baseline['configuration_selector'],
        phase='formal_E3_P' if request.get('formal', False) else 'development_E3_P',
        policy_variant='GPT' if strategy == 'gpt_feedback' else 'random', training_seed=None, evaluation_seed_slot=None,
        parameter_draw_index=0, parameter_seed=request['selection_seed'],
        parameter_attempts=[], parameter_prior_retained={"0": []},
        initial_sources={CONTROL: canonical(task['parameter_controls'])},
        parameter_interface_cost={'binding_wall_seconds': time.monotonic()-started,
            'binding_process_CPU_seconds': time.process_time()-cpu,
            'renderer_wall_seconds': 0., 'renderer_process_CPU_seconds': 0.,
            'engineering_design_seconds': None,
            'engineering_design_scope': 'Interface/renderer implementation is research engineering. Its prior authoring time was not instrumented; no zero-cost claim.',
            'implementation_sources': ['scripts/e3_parameter_episode.py', 'src/e3_parameters.py', 'src/e3_task_prepare.py']})
    save(private/'state.json', state)
    result['packet'] = packet
    return result


class ParameterGateway(Gateway):
    def __init__(self, directory):
        super().__init__(directory)
        validate_baseline(self.manifest, self.state.value['parameter_strategy'])
        self.domain, self.pdk, self.original = binding(self.task)

    def control_dir(self, revision=None):
        revision = self.state.value['revision'] if revision is None else revision
        return self.private/('control_revisions/%03d' % revision)

    def sources(self):
        return {CONTROL: (self.control_dir()/CONTROL).read_text()}

    def predictions(self):
        if self.state.value['method'] != 'C':
            return None
        from src.e3_risk_model import load_frozen_predictor
        predictor = load_frozen_predictor(project(self.manifest['risk_model']))
        complete = {name: (self.source()/name).read_text() for name in self.task['editable_paths']}
        return predictor.predict(complete, self.state.value,
            {p['configuration_id']: p['parameters'] for p in self.task['configurations'] if p['role'] != 'hidden'})

    def action(self, proposal):
        if proposal['action'] != 'propose_patch':
            return super().action(proposal)
        value = self.state.value
        check_utc_budget(self.packet)
        if value['sealed'] or value['status'] != 'RUNNING':
            raise ValueError('Parameter search is closed')
        if value['decisions'] >= self.manifest['budget']['decisions']:
            raise ValueError('Decision budget exhausted')
        value['decisions'] += 1
        self.write()
        validate_action(proposal, self.packet)
        if value['anchor'] not in value['revisions'][0]['results']:
            raise ValueError('Acquire actual original anchor feedback before the first parameter edit')
        if value['patch_attempts'] >= self.manifest['budget']['patches']:
            raise ValueError('Parameter proposal budget exhausted')
        value['patch_attempts'] += 1
        attempt = {'action': proposal, 'status': 'STARTED', 'started_at_utc': now().isoformat()}
        value['parameter_attempts'].append(attempt)
        self.write()
        revision = value['revision']+1
        controls = self.control_dir(revision)
        target = self.private/('revisions/%03d/source' % revision)
        began, cpu = time.monotonic(), time.process_time()
        created_controls = created_source = False
        try:
            if controls.exists() or target.parent.exists():
                raise RuntimeError('An existing uncommitted revision needs reconciliation; it is never overwritten')
            controls.mkdir()
            created_controls = True
            (controls/CONTROL).write_text(self.sources()[CONTROL])
            apply_source_patch(controls, proposal['patch'], [CONTROL])
            if sorted(p.name for p in controls.iterdir()) != [CONTROL]:
                raise ValueError('Only the complete layout parameter file can change')
            candidate = parse_controls((controls/CONTROL).read_text())
            rendered = render(self.task['target'], self.original, candidate, self.pdk)
            if rendered == (self.source()/self.task['editable_paths'][0]).read_text():
                raise ValueError('Parameter proposal leaves the actual complete module unchanged')
            check_utc_budget(self.packet)
            target.parent.mkdir()
            created_source = True
            shutil.copytree(self.source(), target)
            make_working_directories_writable(target)
            module = target/self.task['editable_paths'][0]
            module.chmod(0o644)
            module.write_text(rendered)
            (controls/CONTROL).write_text(canonical(candidate))
            prior = sorted(set(value['counterexamples'])|set(value['required_passes']))
            self.state.new_revision()
            value['parameter_prior_retained'][str(revision)] = prior
            attempt.update(status='APPLIED', revision=revision, controls=candidate)
        except Exception as error:
            attempt.update(status='REJECTED', error=type(error).__name__+': '+str(error))
            if created_controls:
                shutil.rmtree(controls, ignore_errors=True)
            if created_source:
                shutil.rmtree(target.parent, ignore_errors=True)
            if isinstance(error, subprocess.CalledProcessError):
                raise ValueError('Parameter patch did not apply: '+error.stderr[-1500:]) from error
            raise
        finally:
            attempt.update(ended_at_utc=now().isoformat(), wall_seconds=time.monotonic()-began,
                process_CPU_seconds=time.process_time()-cpu)
            value['parameter_interface_cost']['renderer_wall_seconds'] += attempt['wall_seconds']
            value['parameter_interface_cost']['renderer_process_CPU_seconds'] += attempt['process_CPU_seconds']
            self.write()
        return {'patch_applied': True, 'revision': value['revision'],
            'parameters': candidate, 'next_configuration': self.next()}

    def random_action(self):
        value = self.state.value
        check_utc_budget(self.packet)
        if value['parameter_strategy'] != 'random':
            raise ValueError('Random proposals belong only to the declared random baseline')
        records = self.state.current()['results']
        ident = self.next()
        prior = set(value['parameter_prior_retained'][str(value['revision'])])|{value['anchor']}
        failed = any(not row['checked']['S2'] for row in records.values())
        has_one_new = bool(set(records)-prior)
        ready = failed or ident is None or (prior <= set(records) and has_one_new)
        if ready and value['patch_attempts'] < self.manifest['budget']['patches']:
            index = value['parameter_draw_index']
            controls = draw_controls(self.domain, value['parameter_seed'], index)
            value['parameter_draw_index'] += 1
            self.write()
            return patch_action(self.sources()[CONTROL], canonical(controls), 'One full-domain random layout-grid draw; no physical outcome used in the draw')
        if ident is not None:
            return action('request_evaluation', configuration_ids=[ident], fidelity='pex_spice',
                summary='Actual full verification of the shared selector chosen visible configuration')
        return action('finish', summary='No further legal parameter proposal or selected visible check remains')

    def seal(self, status, usage):
        result = super().seal(status, usage)
        selected = self.state.value['selection']['revision']
        result.update(method='P_'+self.state.value['parameter_strategy'],
            configuration_selector=self.state.value['parameter_selector'],
            parameter_interface=self.domain['version'], selected_parameters=parse_controls((self.control_dir(selected)/CONTROL).read_text()),
            random_rule=RANDOM_RULE if self.state.value['parameter_strategy'] == 'random' else None,
            interface_cost=self.state.value['parameter_interface_cost'],
            source_group=self.task['logical_group'], merged_source_group=self.task['merge_sensitivity_group'],
            method_scope='ICPI-inspired parameter search; no claim of reproducing ICPI',
            hidden_results_exposed_to_policy=False)
        save(self.out/'public/search.json', result)
        return result

    def post_freeze(self):
        raw = super().post_freeze()
        result = dict(raw)
        result.update(hidden={'declared': raw['hidden_domain_size'],
            'known': raw['hidden_domain_size']-raw['hidden_incomplete'],
            'S2_passed': raw['hidden_S2_verified']},
            costs_by_stage=self.costs(), hidden_results_exposed_to_policy=False,
            per_configuration_results='Trusted backend only; source was sealed before this one post-freeze pass')
        save(self.out/'public/parameter_episode.json', result)
        return result


def backend(request):
    if request['op'] == 'start':
        return start(request)
    out = project(request['episode_directory'])
    with (out/'private/backend.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        gateway = ParameterGateway(out)
        if request['op'] == 'random_action':
            return gateway.random_action()
        if request['op'] == 'current':
            return gateway.current()
        if request['op'] == 'action':
            return gateway.action(request['action'])
        if request['op'] == 'seal':
            return gateway.seal(request['status'], request.get('policy_statistics'))
        if request['op'] == 'post_freeze':
            return gateway.post_freeze()
        raise ValueError('Unknown parameter gateway operation')


def transport(request):
    command = SSH+['cd '+shlex.quote(REMOTE)+' && '+shlex.quote(REMOTE+'/runtime/GLdev/bin/python')+' scripts/e3_parameter_episode.py --backend']
    run = subprocess.run(command, input=json.dumps(request), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if run.returncode:
        raise RuntimeError('Parameter transport failed: '+run.stderr[-1500:])
    envelope = json.loads(run.stdout)
    if envelope.get('error'):
        kind = envelope['error_type']
        raise {'TimeoutError': TimeoutError, 'ValueError': ValueError}.get(kind, RuntimeError)(envelope['error'])
    return envelope['result']


def post_search(directory, output, search, formal):
    if formal:
        # The taskbook requires every tested source to be sealed before the
        # read-only test oracle is released. Backend post_freeze independently
        # enforces that release when the global coordinator later calls it.
        result = {**search, 'post_freeze_status': 'WAITING_GLOBAL_EVALUATION_RELEASE',
            'hidden_dispatched': False, 'episode_directory': directory}
        save(output/'sealed_search.json', result)
        return result
    result = transport({'op': 'post_freeze', 'episode_directory': directory})
    save(output/'episode.json', result)
    return result


def run_policy(args):
    from transformers import AutoTokenizer
    from src.model_adapter import GptDecisionAdapter
    initialized = transport({'op': 'start', 'manifest': args.manifest, 'task_id': args.task,
        'strategy': args.strategy, 'selection_seed': args.selection_seed, 'trial_id': args.trial, 'formal': args.formal})
    directory = initialized['episode_directory']
    out = ROOT/('runs/formal/E3_parameter_policy' if args.formal else 'runs/development/E3_parameter_policy')/Path(directory).name
    out.mkdir(parents=True)
    save(out/'backend.json', {'episode_directory': directory})
    if args.dispatch_record:
        save(Path(args.dispatch_record), {'episode_directory': directory, 'local_output_directory': str(out),
            'task_id': args.task, 'method': 'P_'+args.strategy, 'strategy': args.strategy,
            'trial_id': str(args.trial), 'formal': args.formal, 'policy_variant': 'GPT' if args.strategy == 'gpt_feedback' else 'random',
            'training_seed': None, 'evaluation_seed_slot': None, 'selector_variant': 'main'})
    frozen = {'status': 'FROZEN_E3' if args.formal else 'DRAFT',
        'implementation_sha256': initialized.get('implementation_sha256')}
    verify(frozen)
    tokenizer = AutoTokenizer.from_pretrained(ROOT/'runtime/policy_tokenizer', local_files_only=True, trust_remote_code=False)
    session = adapter = None
    if args.strategy == 'gpt_feedback':
        adapter = GptDecisionAdapter(out/'decisions', tokenizer=tokenizer)
        session = adapter.start(initialized['packet'], initialized['model_config'])
    observations = []
    status = 'DECISION_BUDGET_EXHAUSTED'
    observation = {'status': 'initial'}
    try:
        for _ in range(initialized['packet']['budget']['decisions']):
            verify(frozen)
            current = transport({'op': 'current', 'episode_directory': directory})
            observation = {**observation, 'next_configuration': current['next_configuration']}
            if adapter:
                try:
                    proposal = adapter.step(session, observation, current_sources=current['current_sources'])
                except TimeoutError:
                    raise
                except Exception as error:
                    status = 'MODEL_FAILED'
                    save(out/'policy_error.json', {'error': type(error).__name__+': '+str(error)})
                    break
            else:
                proposal = transport({'op': 'random_action', 'episode_directory': directory})
                count = len(tokenizer(json.dumps(proposal), add_special_tokens=False)['input_ids'])+1
                if count > initialized['packet']['budget']['maximum_output_tokens']:
                    raise ValueError('Generated random action exceeds the common action payload budget')
            event = {'action': proposal, 'observation_before': observation}
            observations.append(event)
            save(out/'actions.json', observations)
            try:
                observation = transport({'op': 'action', 'episode_directory': directory, 'action': proposal})
            except ValueError as error:
                observation = {'error': str(error), 'next_configuration': current['next_configuration']}
            event['observation_after'] = observation
            save(out/'actions.json', observations)
            if proposal['action'] == 'finish':
                status = 'SEARCH_FINISHED'
                break
            if observation.get('episode_status') in ('BUDGET_EXHAUSTED', 'INCOMPLETE_UNKNOWN'):
                status = observation['episode_status']
                break
            if observation.get('checked', {}).get('execution_integrity') not in (None, 'valid'):
                status = ('BUDGET_EXHAUSTED' if observation['checked']['execution_integrity'] == 'budget_exhausted'
                    else 'INCOMPLETE_UNKNOWN')
                break
    except TimeoutError:
        status = 'BUDGET_EXHAUSTED'
    except Exception as error:
        status = 'INCOMPLETE_UNKNOWN'
        save(out/'error.json', {'error': type(error).__name__+': '+str(error)})
    finally:
        if session:
            session['closed'] = True
            save(out/'session.json', session)
        usage = policy_statistics(session, out) if session else {
            'decision_step_attempts': len(observations), 'model_cli_invocations': 0,
            'public_provider_usage': [], 'random_seed': args.selection_seed,
            'random_rule': RANDOM_RULE, 'inference_GPU_seconds': 0}
        report = transport({'op': 'seal', 'episode_directory': directory, 'status': status, 'policy_statistics': usage})
        save(out/'search.json', report)
    report = post_search(directory, out, report, args.formal)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', action='store_true')
    parser.add_argument('--manifest');parser.add_argument('--task')
    parser.add_argument('--strategy', choices=STRATEGIES)
    parser.add_argument('--selection-seed', type=int, default=41)
    parser.add_argument('--trial', default='development')
    parser.add_argument('--formal', action='store_true')
    parser.add_argument('--dispatch-record', type=Path)
    args = parser.parse_args()
    if args.backend:
        try:
            print(json.dumps({'result': backend(json.load(sys.stdin))}), flush=True)
        except Exception as error:
            print(json.dumps({'error': str(error), 'error_type': type(error).__name__}), flush=True)
    else:
        if not (args.manifest and args.task and args.strategy):
            parser.error('Parameter execution requires manifest, task and strategy')
        run_policy(args)
