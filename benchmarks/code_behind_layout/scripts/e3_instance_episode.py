#!/usr/bin/env python3
"""Instance I: independent arrival sessions, retained own library and exact cache.

Only the current configuration and past arrivals enter a policy packet. The
arrival order is snapshotted on the trusted backend before the first request.
Every served source is instance specific; no feedback returns to C or E4.
"""
import argparse
import copy
from datetime import timedelta
import fcntl
import json
import math
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.e3_episode import Gateway, now, project, read, require_release, save, verify
from scripts.e3_physical_point import trusted
from scripts.e3_task_prepare import capsule, make_working_directories_writable
from scripts.e1_matched_runner import SSH, REMOTE, policy_statistics
from src.candidate_executor import IMAGE, PREFIX, apply_source_patch
from src.domain_runner import inspect_point, source_contents
from src.device_intent import compare_device_intent
from src.e3_feedback import compact as compact_feedback, public_checked
from src.e1_packets import PUBLIC_CONTRACT_FIELDS, bind_reference, public_graph
from src.model_adapter import check_utc_budget, validate_action

VERSION = 'independent_arrivals_with_verified_library_exact_cache_v1'
WARM_START = 'nearest_previous_verified_configuration_then_latest'
CACHE = 'exact_source_configuration_reference_PDK_deck_tools_fidelity'
BUDGET_FIELDS = {'wall_seconds', 'decisions', 'patches', 'full_evaluations',
                 'maximum_context_tokens', 'maximum_output_tokens'}


def configuration_distance(first, second):
    """Use current/past values only; never normalize with future arrivals."""
    keys = sorted(set(first)|set(second))
    distances = []
    for key in keys:
        a, b = first.get(key), second.get(key)
        if type(a) in (int, float) and type(b) in (int, float) and math.isfinite(a) and math.isfinite(b):
            distances.append(abs(a-b)/max(abs(a), abs(b), 1e-30))
        else:
            distances.append(float(a != b))
    return sum(distances)/len(distances) if distances else 0.


def choose_library(entries, current):
    if not entries:
        return None
    return min(entries, key=lambda item: (configuration_distance(item['parameters'], current), -item['library_index']))


def instance_settings(manifest):
    settings = manifest['instance_baseline']
    if (settings['algorithm'] != VERSION or settings['warm_start'] != WARM_START or
            settings['cache'] != CACHE or settings['deployment_verification_maximum_physical_calls'] != 1):
        raise ValueError('Freeze the explicit instance/library/cache/deployment algorithm')
    budget = settings['budget']
    if (set(budget) != BUDGET_FIELDS or any(type(value) is not int or value <= 0 for value in budget.values())
            or budget['maximum_output_tokens'] != 1024):
        raise ValueError('Explicit positive instance budgets and the common1024 action output are required')
    return settings


def public_identifiers(value, task_id, reference_id):
    if isinstance(value, dict):
        return {key: ('current' if key == 'configuration_id' else task_id if key == 'task_id'
            else reference_id if key == 'reference_id' else public_identifiers(item, task_id, reference_id))
            for key, item in value.items()}
    if isinstance(value, list):
        return [public_identifiers(item, task_id, reference_id) for item in value]
    return value


def current_packet(base, task, point, sources, ordinal, history, library, budget, deadline):
    """Remove the family table and rebuild the intended graph for this one z."""
    result = copy.deepcopy(base)
    ident = task['task_id']+'_arrival_%04d' % ordinal
    reference_id = ident+'_reference'
    result.update(task_id=ident, goal='Serve only the currently arrived configuration. Preserve its independent circuit and all electrical limits; optimize its declared feasible-first objective.',
        allowed_paths=list(task['editable_paths']), visible_sources=dict(sources), visible_configurations=['current'],
        contract={key: copy.deepcopy(point['contract'][key]) for key in PUBLIC_CONTRACT_FIELDS if key in point['contract']},
        budget={**budget, 'physical_evaluations': budget['full_evaluations'], 'deadline_utc': deadline})
    result['contract'].update(task_id=ident, configuration_id='current', reference_id=reference_id)
    documents = result['documents']
    documents.setdefault('action_gateway', {}).update(read_source_paths=list(result['visible_sources']),
        read_source_scope='Only these exact visible-source keys may be requested. Candidate runtime/library/configuration paths are not read_source paths; their complete API schemas are supplied in documents.')
    for name in ('visible_sizings', 'family_relationship', 'parameter_baseline', 'controlled_verification'):
        documents.pop(name, None)
    graph = bind_reference(Path(point['reference_file']).read_text(), task['top_cell'], reference_id)
    documents['intended_anchor_graph'] = public_graph(graph)
    documents.update(current_configuration={'configuration_id': 'current', 'parameters': copy.deepcopy(point['parameters'])},
        physical_feedback_encoding='corner_metric_table stores every metric name/unit once with all corner values and state fields; the encoding is lossless_all_metrics_all_corners_v1.',
        instance_contract={'algorithm': VERSION, 'current_only': True,
            'search': 'Each arrival has an independent session and source revisions. Request only current at pex_spice; obtain current initial feedback before editing.',
            'library': WARM_START, 'cache': CACHE,
            'scope': 'This program serves only this instance; no result is sent to shared-code C or E4.'},
        past_arrivals={'fields': ['arrival_ordinal', 'parameters', 'status', 'complete', 'S2', 'objective'],
            'rows': [[copy.deepcopy(row.get(key)) for key in ('arrival_ordinal', 'parameters', 'status', 'complete', 'S2', 'objective')] for row in history],
            'scope': 'Every past arrival; complete raw costs, provider records and traces remain in the study ledger.'},
        verified_own_library={'fields': ['library_id', 'past_parameters', 'objective', 'origin_arrival'],
            'rows': [[row['library_id'], row['parameters'], row['objective'], row['arrival_ordinal']] for row in library]},
        library_access='All verified own programs remain stored. The frozen algorithm chooses an exact-cache source or the nearest previously verified configuration as the complete editable warm start. It never discards prior verified entries.')
    return result


def exact_bindings(run, expected_source, point, configuration, current_trusted):
    """Compare actual bytes; this does not accept a candidate pass declaration."""
    manifest = read(run/'manifest.json')
    if (manifest['fidelity'] != 'pex_spice' or set(manifest['source_files']) != set(expected_source)
            or source_contents(run/'source', manifest['source_files'], binary=True) != expected_source
            or read(run/'configuration.json') != configuration):
        return False
    names = sorted(str(path.relative_to(current_trusted)) for path in current_trusted.rglob('*') if path.is_file())
    if (set(names) != set(manifest['trusted_files']) or
            source_contents(run/'trusted', names, binary=True) != source_contents(current_trusted, names, binary=True)):
        return False
    context = manifest['context']
    if (context.get('pdk_revision') != '0fe599b2afb6708d281543108caf8310912f54af'
            or context.get('configuration_id') != point['configuration_id']
            or context.get('reference_id') != point['reference_id']):
        return False
    runtime = str((ROOT/'runtime/GLdev').resolve())+':'+PREFIX+':ro'
    magic = str((ROOT/'runtime/magic-8.3.685').resolve())+':/work/runtime/magic-8.3.685:ro'
    for name in ('candidate', 'trusted'):
        if name not in manifest:
            continue
        arguments = manifest[name]['argv']
        if IMAGE not in arguments or runtime not in arguments or (name == 'trusted' and magic not in arguments):
            return False
    return True


def verify_cached(point_record, expected_source, point, current_trusted):
    """A fresh host inspection, never a relabelled old physical execution."""
    run = Path(point_record['run_directory'])
    if (run/'evidence_archive.json').is_file():
        from scripts.archive_e3_evidence import restore_run
        restore_run(run)
    configuration = {'parameters': point['parameters']}
    if not exact_bindings(run, expected_source, point, configuration, current_trusted):
        return None
    checked = inspect_point({'run_directory': str(run)}, point, expected_source, configuration)
    if checked['execution_integrity'] != 'valid':
        return None
    quality = None
    if checked['S1']:
        graph = compare_device_intent((run/'evidence/extracted_lvs.spice').read_text(),
            (run/'trusted/reference.spice').read_text())
        if not graph['is_clean']:
            return None
    if checked['S2']:
        gds = run/'accepted/candidate.gds'
        if gds.is_symlink() or not gds.is_file() or gds.stat().st_size == 0:
            return None
        raw = read(run/'evidence/validation.json')
        definition = point['contract']['objective']
        measured = [raw['observation']['corners'][corner]['metrics'][definition['metric']]
            for corner in point['contract']['required_corners']]
        if any(row['unit'] != definition['unit'] or type(row['value']) not in (int, float)
                or not math.isfinite(row['value']) for row in measured):
            return None
        values = [row['value'] for row in measured]
        quality = min(values) if definition['direction'] == 'max' else max(values)
    result = dict(point_record)
    result.update(checked=checked, objective=quality, exact_cache_hit=True,
        original_run_directory=str(run), original_physical_phase=read(run/'manifest.json')['phase'])
    result['served_GDS_artifact'] = str(run/'accepted/candidate.gds') if checked['S0'] else None
    return result


def start_study(request):
    manifest = read(project(request['manifest']))
    settings = instance_settings(manifest)
    formal = request.get('formal', False)
    trial = str(request.get('trial_id', 'development'))
    if formal and trial not in {'1', '2', '3', '4', '5'}:
        raise ValueError('Formal instance trial identity must match the declared1..5 matrix')
    if formal and not (manifest['status'] == 'FROZEN_E3' and manifest['formal_dispatch'] is True):
        raise ValueError('Instance formal dispatch requires the separate actual E3 freeze')
    if formal:
        require_release(manifest, baseline=True)
    verify(manifest)
    if request['task_id'] not in manifest['task_ids']:
        raise ValueError('Instance task outside the manifest')
    task_path = project(manifest['preparation'])/'private'/request['task_id']/'task.json'
    task = read(task_path)
    if formal and not (task.get('formal_admission') is True and task['status'] == 'FROZEN_E3_TASK'):
        raise ValueError('Instance baseline needs the same admitted frozen task')
    order = read(project(settings['arrival_order']))
    if formal and project(settings['arrival_order']).stat().st_mode & 0o222:
        raise ValueError('Formal arrival order must already be a read-only frozen backend file')
    allowed = {point['configuration_id'] for point in task['configurations']}
    if (not isinstance(order, list) or not order or any(not isinstance(name, str) or name not in allowed for name in order)):
        raise ValueError('The backend arrival order must be a nonempty list of declared configuration IDs')
    stamp = now().strftime('%Y%m%dT%H%M%S%fZ_')+uuid.uuid4().hex[:8]
    out = ROOT/('runs/formal/E3_instance' if formal else 'runs/development/E3_instance')/stamp
    private = out/'private';private.mkdir(parents=True, mode=0o700);(out/'public').mkdir()
    save(private/'manifest.json', manifest);save(private/'task.json', task)
    save(private/'arrival_order.json', order);(private/'arrival_order.json').chmod(0o444)
    save(private/'state.json', {'status': 'RUNNING', 'created_at_utc': now().isoformat(),
        'formal_trial': formal, 'task_path': str(task_path), 'task_id': task['task_id'],
        'trial_id': trial, 'phase': 'formal_E3_I' if formal else 'development_E3_I',
        'policy_variant': 'GPT', 'training_seed': None, 'evaluation_seed_slot': None,
        'selection_seed': None, 'seed_scope': 'Fixed declared arrival order and deterministic warm-start/cache; no exposed GPT sampling seed',
        'arrived': 0, 'current_arrival': None, 'arrivals': [], 'verified_library': [],
        'algorithm': VERSION, 'feedback_to_C_or_E4': False})
    return {'study_directory': str(out), 'algorithm': VERSION, 'future_arrival_values_exposed': False}


class InstanceGateway(Gateway):
    def __init__(self, arrival):
        self.out = project(arrival);self.private = self.out/'private'
        self.manifest = read(self.private/'manifest.json');verify(self.manifest)
        self.manifest['budget'] = instance_settings(self.manifest)['budget']
        self.task = read(self.private/'task.json');self.packet = read(self.private/'packet.json')
        self.state = SimpleNamespace(value=read(self.private/'state.json'))
        self.point = read(self.private/'current_point.json')
        if self.state.value['in_flight']:
            raise RuntimeError('An instance physical call is unresolved; never repeat it silently')

    def next(self):
        return 'current'

    def current(self):
        return {'current_sources': self.sources(), 'configuration_id': 'current',
            'revision': self.state.value['revision'],
            'remaining_full_evaluations': self.manifest['budget']['full_evaluations']-self.state.value['full_evaluations']}

    def feedback(self, row, revision=None):
        result = public_identifiers({'checked': public_checked(row['checked']), 'objective': row['objective'],
            'physical_feedback': compact_feedback(row['physical_feedback'])}, self.packet['task_id'], self.packet['contract']['reference_id'])
        result.update(configuration_id='current', revision=self.state.value['revision'] if revision is None else revision,
            episode_status=self.state.value['status'], exact_cache_hit=row.get('exact_cache_hit', False))
        return result

    def cached(self, record, revision):
        began, cpu = time.monotonic(), time.process_time()
        event = {'stage': 'search' if not self.state.value['sealed'] else 'deployment_verification',
            'origin_run': record['run_directory'], 'status': 'CHECKING'}
        self.state.value['cache_events'].append(event)
        self.write()
        try:
            expected = source_contents(self.source(revision), self.task['source_files'], binary=True)
            result = verify_cached(record, expected, self.point, self.private/'current_trusted')
            event['status'] = 'HIT' if result else 'MISS'
            return result
        except (ValueError, KeyError, TypeError, OSError) as error:
            event.update(status='MISS', reason=type(error).__name__+': '+str(error))
            return None
        finally:
            event.update(wall_seconds=time.monotonic()-began, process_CPU_seconds=time.process_time()-cpu)
            self.write()

    def action(self, proposal):
        value = self.state.value
        check_utc_budget(self.packet)
        if value['sealed'] or value['status'] != 'RUNNING':
            raise ValueError('This instance session is closed')
        if value['decisions'] >= self.manifest['budget']['decisions']:
            raise ValueError('Instance decision budget exhausted')
        value['decisions'] += 1;self.write();validate_action(proposal, self.packet)
        kind = proposal['action']
        if kind == 'read_source':
            return {'path': proposal['path'], 'content': self.sources()[proposal['path']]}
        if kind == 'finish':
            value['status'] = 'SEARCH_FINISHED';self.write()
            return {'search_finished': True}
        if kind == 'propose_patch':
            if '0' not in value['results']:
                raise ValueError('Acquire actual current-instance initial feedback before the first edit')
            if value['patch_attempts'] >= self.manifest['budget']['patches']:
                raise ValueError('Instance patch budget exhausted')
            value['patch_attempts'] += 1;self.write()
            revision = value['revision']+1;target = self.private/('revisions/%03d/source' % revision)
            if target.parent.exists():
                raise RuntimeError('Retained uncommitted instance revision requires reconciliation')
            target.parent.mkdir();shutil.copytree(self.source(), target)
            make_working_directories_writable(target)
            try:
                apply_source_patch(target, proposal['patch'], self.task['editable_paths'])
                if all((target/name).read_bytes() == (self.source()/name).read_bytes() for name in self.task['editable_paths']):
                    raise ValueError('Patch leaves the actual complete source unchanged')
                check_utc_budget(self.packet)
            except Exception as error:
                shutil.rmtree(target.parent)
                if isinstance(error, subprocess.CalledProcessError):
                    raise ValueError('Instance patch failed: '+(error.stderr or '')[-1500:]) from error
                raise
            save(target.parent/'action.json', proposal);value['revision'] = revision;self.write()
            return {'patch_applied': True, 'revision': revision}
        if kind == 'request_evaluation':
            if proposal['configuration_ids'] != ['current'] or proposal['fidelity'] != 'pex_spice':
                raise ValueError('An instance policy may check only current at full physical fidelity')
            previous = value['results'].get(str(value['revision']))
            row = self.cached(previous, value['revision']) if previous else None
            if row is None:
                row = super().physical(self.point['configuration_id'], value['revision'], 'search')
            if row['checked']['execution_integrity'] == 'valid':
                value['results'][str(value['revision'])] = row
            self.write()
            return self.feedback(row)
        raise ValueError('Unknown instance action')

    def costs(self):
        result = super().costs()
        if 'post_freeze_diagnostic' in result:
            result['deployment_verification'] = result.pop('post_freeze_diagnostic')
        return result

    def seal(self, status, usage):
        value = self.state.value
        direction = self.point['contract']['objective']['direction']
        feasible = [(row['objective'] if direction == 'max' else -row['objective'], -int(revision), int(revision))
            for revision, row in value['results'].items() if row['checked']['S2'] is True
            and type(row['objective']) in (int, float) and math.isfinite(row['objective'])]
        revision = max(feasible)[-1] if feasible else 0
        value.update(sealed=True, status=status, selected_revision=revision, policy_statistics=usage,
            sealed_at_utc=now().isoformat());self.write()
        result = {'method': 'I', 'task_id': self.task['task_id'], 'arrival_ordinal': value['arrival_ordinal'],
            'trial_id': value['trial_id'], 'phase': value['phase'], 'selection_seed': None,
            'status': status, 'selected_revision': revision, 'verified_feasible_source_selected': bool(feasible),
            'objective_definition': self.point['contract']['objective'],
            'full_evaluations': value['full_evaluations'], 'decisions': value['decisions'],
            'patch_attempts': value['patch_attempts'], 'policy_statistics': usage,
            'costs_by_stage': self.costs(), 'cache_events': value['cache_events'],
            'resource_waits': value['resource_waits'], 'formal_trial': value['formal_trial'],
            'preparation_cost': {'wall_seconds': value['initial_preparation_wall_seconds'],
                'process_CPU_seconds': value['initial_preparation_process_CPU_seconds'],
                'arrival_cache_lookups_are_subset_of_preparation': True},
            'future_values_exposed': False, 'feedback_to_C_or_E4': False}
        save(self.out/'public/search.json', result)
        return result

    def deploy(self):
        value = self.state.value
        if not value['sealed'] or value['deployment_started']:
            raise ValueError('Instance deployment follows sealed source selection and runs once')
        value['deployment_started'] = True;self.write()
        result = read(self.out/'public/search.json')
        if value['status'] == 'INCOMPLETE_UNKNOWN':
            result.update(status='INCOMPLETE_UNKNOWN', complete=False, S2=False, objective=None,
                reason='Unresolved physical/transport execution; no deployment call dispatched')
        else:
            revision = value['selected_revision'];previous = value['results'].get(str(revision))
            if value['status'] == 'EXACT_CACHE_SERVED' and revision == 0 and value['opened_with_exact_cache']:
                row = previous  # this arrival's exact lookup already established deployment
            else:
                row = self.cached(previous, revision) if previous else None
            if row is None:
                row = super().physical(self.point['configuration_id'], revision, 'deployment_verification')
            value['deployment_record'] = row;self.write()
            result.update(complete=row['checked']['execution_integrity'] == 'valid',
                S2=row['checked']['S2'], objective=row['objective'],
                served_GDS_artifact=str(Path(row['run_directory'])/'accepted/candidate.gds') if row['checked']['S0'] else None,
                deployment_exact_cache_hit=row.get('exact_cache_hit', False),
                deployment_feedback=self.feedback(row, revision),
                status='COMPLETED' if row['checked']['execution_integrity'] == 'valid' else 'INCOMPLETE_UNKNOWN')
        result.update(costs_by_stage=self.costs(), cache_events=value['cache_events'],
            resource_waits=value['resource_waits'])
        save(self.out/'public/episode.json', result)
        return result


def open_arrival(study):
    study = project(study);private = study/'private';state = read(private/'state.json')
    if state['status'] != 'RUNNING' or state['current_arrival'] is not None:
        raise ValueError('A prior arrival is unresolved or the instance stream is paused')
    order = read(private/'arrival_order.json')
    if state['arrived'] == len(order):
        state['status'] = 'COMPLETE';save(private/'state.json', state)
        summary = read(study/'public/summary.json')
        summary.update(status='COMPLETE', completed_at_utc=now().isoformat())
        save(study/'public/summary.json', summary)
        return {'complete': True, 'arrivals_completed': state['arrived'], 'summary': summary}
    manifest = read(private/'manifest.json');verify(manifest);settings = instance_settings(manifest)
    task = read(private/'task.json');ordinal = state['arrived'];configuration_id = order[ordinal]
    point = next(row for row in task['configurations'] if row['configuration_id'] == configuration_id)
    began, cpu = time.monotonic(), time.process_time()
    out = private/('arrivals/%04d' % ordinal);work = out/'private';work.mkdir(parents=True);(out/'public').mkdir()
    save(work/'manifest.json', manifest);save(work/'task.json', task);save(work/'current_point.json', point)
    source = work/'revisions/000/source';source.parent.mkdir(parents=True)
    capsule(Path(state['task_path']), source)
    current_trusted = work/'current_trusted';trusted(task, point, current_trusted)
    expected_base = source_contents(source, task['source_files'], binary=True)
    hits, cache_events, seen_runs = [], [], set()
    for entry in state['verified_library']:
        if entry['parameters'] != point['parameters']:
            continue
        origin = read(entry['point_record'])
        if origin['run_directory'] in seen_runs:
            continue
        seen_runs.add(origin['run_directory'])
        started, process_cpu = time.monotonic(), time.process_time()
        event = {'library_id': entry['library_id'], 'status': 'CHECKING', 'stage': 'arrival_cache_deployment_verification'}
        try:
            expected = dict(expected_base)
            for name in task['editable_paths']:
                expected[name] = (Path(entry['source_directory'])/name).read_bytes()
            row = verify_cached(origin, expected, point, current_trusted)
            if row and row['checked']['S2']:
                hits.append((entry, row));event['status'] = 'HIT'
            else:
                event['status'] = 'MISS'
        except (OSError, ValueError, KeyError, TypeError) as error:
            event.update(status='MISS', reason=type(error).__name__+': '+str(error))
        event.update(wall_seconds=time.monotonic()-started, process_CPU_seconds=time.process_time()-process_cpu)
        cache_events.append(event)
    direction = point['contract']['objective']['direction']
    if hits:
        chosen, cached = max(hits, key=lambda item: (item[1]['objective'] if direction == 'max' else -item[1]['objective'], item[0]['library_index']))
    else:
        chosen, cached = choose_library(state['verified_library'], point['parameters']), None
    if chosen:
        for name in task['editable_paths']:
            destination = source/name;destination.chmod(0o644)
            destination.write_bytes((Path(chosen['source_directory'])/name).read_bytes())
    deadline = now()+timedelta(seconds=settings['budget']['wall_seconds'])
    sources = {name: (source/name).read_text() for name in task['editable_paths']}
    base = read(project(manifest['preparation'])/'public'/task['task_id']/'packet.json')
    packet = current_packet(base, task, point, sources, ordinal, state['arrivals'], state['verified_library'], settings['budget'], deadline.isoformat())
    save(work/'packet.json', packet)
    value = {'status': 'RUNNING', 'formal_trial': state['formal_trial'], 'arrival_ordinal': ordinal,
        'trial_id': state['trial_id'], 'phase': state['phase'],
        'created_at_utc': now().isoformat(), 'deadline_utc': deadline.isoformat(), 'revision': 0,
        'decisions': 0, 'patch_attempts': 0, 'full_evaluations': 0, 'in_flight': None,
        'sealed': False, 'deployment_started': False, 'physical_events': [], 'resource_waits': [],
        'cache_events': cache_events, 'results': {'0': cached} if cached else {},
        'opened_with_exact_cache': cached is not None,
        'warm_start_library_id': chosen['library_id'] if chosen else None,
        'initial_preparation_wall_seconds': time.monotonic()-began,
        'initial_preparation_process_CPU_seconds': time.process_time()-cpu}
    save(work/'state.json', value)
    state['current_arrival'] = str(out);save(private/'state.json', state)
    model = read(project(manifest['model_config']));model['visible_history_policy'] = 'current_source_and_feedback_v1'
    return {'complete': False, 'arrival_directory': str(out), 'packet': packet, 'model_config': model,
        'arrival_ordinal': ordinal, 'served_from_exact_cache': cached is not None,
        'implementation_sha256': manifest.get('implementation_sha256')}


def finish_arrival(study):
    study = project(study);private = study/'private';state = read(private/'state.json')
    if state['current_arrival'] is None:
        raise ValueError('No opened arrival to finish')
    out = Path(state['current_arrival']);value = read(out/'private/state.json')
    report = read(out/'public/episode.json');point = read(out/'private/current_point.json')
    task = read(private/'task.json')
    from scripts.archive_e3_evidence import archive_returned_points
    storage = archive_returned_points(out)
    save(out/'private/search_evidence_archive.json', storage)
    for revision, row in value['results'].items():
        if row['checked']['execution_integrity'] != 'valid' or row['checked']['S2'] is not True:
            continue
        index = len(state['verified_library'])
        record = out/'private'/('verified_revision_%s.json' % revision);save(record, row)
        state['verified_library'].append({'library_index': index, 'library_id': 'own_program_%04d' % index,
            'arrival_ordinal': value['arrival_ordinal'], 'parameters': point['parameters'], 'objective': row['objective'],
            'source_directory': str(out/'private'/('revisions/%03d/source' % int(revision))), 'point_record': str(record)})
    deployed = value.get('deployment_record')
    if deployed and deployed['checked']['S2'] and str(value['selected_revision']) not in value['results']:
        index = len(state['verified_library']);record = out/'private/deployment_verified.json';save(record, deployed)
        state['verified_library'].append({'library_index': index, 'library_id': 'own_program_%04d' % index,
            'arrival_ordinal': value['arrival_ordinal'], 'parameters': point['parameters'], 'objective': deployed['objective'],
            'source_directory': str(out/'private'/('revisions/%03d/source' % value['selected_revision'])), 'point_record': str(record)})
    state['arrivals'].append({'arrival_ordinal': value['arrival_ordinal'], 'parameters': point['parameters'],
        'status': report['status'], 'complete': report['complete'], 'S2': report['S2'], 'objective': report['objective'],
        'objective_definition': report['objective_definition'],
        'costs_by_stage': report['costs_by_stage'], 'policy_statistics': report['policy_statistics'],
        'preparation_cost': report['preparation_cost'], 'cache_events': report['cache_events'],
        'resource_waits': report['resource_waits']})
    state['arrivals'][-1]['evidence_storage_events'] = storage['events']
    state['arrived'] += 1;state['current_arrival'] = None
    if not report['complete']:
        state['status'] = 'PAUSED_INCOMPLETE_UNKNOWN'
    save(private/'state.json', state)
    summary = {'method': 'I', 'task_id': task['task_id'], 'status': state['status'],
        'trial_id': state['trial_id'], 'phase': state['phase'], 'selection_seed': None,
        'arrivals_completed': state['arrived'], 'verified_own_programs': len(state['verified_library']),
        'arrivals': state['arrivals'], 'formal_trial': state['formal_trial'],
        'future_values_exposed': False, 'feedback_to_C_or_E4': False,
        'quality_matching': 'Join against the separately frozen shared-patch C deployment stream after both runs; no C results enter this strategy.'}
    summary['cumulative_costs'] = cumulative_costs(state['arrivals'])
    save(study/'public/summary.json', summary)
    return summary


def cumulative_costs(arrivals):
    result = {'physical_calls_by_stage': {}, 'physical_child_CPU_seconds': 0.,
        'physical_stage_wall_seconds': 0., 'missing_physical_CPU_records': 0,
        'model_cli_invocations': 0, 'decision_step_attempts': 0,
        'preparation_wall_seconds': 0., 'preparation_process_CPU_seconds': 0.,
        'additional_cache_wall_seconds': 0., 'additional_cache_process_CPU_seconds': 0.,
        'resource_gate_wait_wall_seconds': 0., 'provider_queue_or_GPU_seconds': None,
        'evidence_storage_wall_seconds': 0., 'evidence_storage_process_CPU_seconds': 0.,
        'scope': 'Physical stage wall is not added to end-to-end wall. Arrival cache checks are a subset of preparation; only later cache checks are additional. Provider queue/GPU time is unavailable, not zero.'}
    for arrival in arrivals:
        for stage, costs in arrival['costs_by_stage'].items():
            result['physical_calls_by_stage'][stage] = result['physical_calls_by_stage'].get(stage, 0)+costs['physical_calls']
            result['physical_child_CPU_seconds'] += costs['waited_child_CPU_seconds']
            result['physical_stage_wall_seconds'] += costs['stage_wall_seconds']
            result['missing_physical_CPU_records'] += costs['missing_CPU_records']
        statistics = arrival['policy_statistics']
        result['model_cli_invocations'] += statistics['model_cli_invocations']
        result['decision_step_attempts'] += statistics['decision_step_attempts']
        result['preparation_wall_seconds'] += arrival['preparation_cost']['wall_seconds']
        result['preparation_process_CPU_seconds'] += arrival['preparation_cost']['process_CPU_seconds']
        for check in arrival['cache_events']:
            if check['stage'] != 'arrival_cache_deployment_verification':
                result['additional_cache_wall_seconds'] += check['wall_seconds']
                result['additional_cache_process_CPU_seconds'] += check['process_CPU_seconds']
        result['resource_gate_wait_wall_seconds'] += sum(row['actual_wait_wall_seconds'] for row in arrival['resource_waits'])
        result['evidence_storage_wall_seconds'] += sum(row['operation_wall_seconds'] for row in arrival.get('evidence_storage_events', []))
        result['evidence_storage_process_CPU_seconds'] += sum(row['operation_process_CPU_seconds'] for row in arrival.get('evidence_storage_events', []))
    return result


def backend(request):
    operation = request['op']
    if operation == 'start':
        return start_study(request)
    if operation in ('open_next', 'finish_arrival'):
        study = project(request['study_directory'])
        with (study/'private/coordinator.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return open_arrival(study) if operation == 'open_next' else finish_arrival(study)
    out = project(request['arrival_directory'])
    with (out/'private/backend.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        gateway = InstanceGateway(out)
        if operation == 'current':
            return gateway.current()
        if operation == 'action':
            return gateway.action(request['action'])
        if operation == 'seal':
            return gateway.seal(request['status'], request.get('policy_statistics'))
        if operation == 'deploy':
            return gateway.deploy()
        raise ValueError('Unknown instance operation')


def transport(request):
    command = SSH+['cd '+shlex.quote(REMOTE)+' && '+shlex.quote(REMOTE+'/runtime/GLdev/bin/python')+' scripts/e3_instance_episode.py --backend']
    run = subprocess.run(command, input=json.dumps(request), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if run.returncode:
        raise RuntimeError('Instance transport failed: '+run.stderr[-1500:])
    envelope = json.loads(run.stdout)
    if envelope.get('error'):
        raise {'ValueError': ValueError, 'TimeoutError': TimeoutError}.get(envelope['error_type'], RuntimeError)(envelope['error'])
    return envelope['result']


def run_policy(args):
    from transformers import AutoTokenizer
    from src.model_adapter import GptDecisionAdapter
    output = None;rpc_events = []
    def rpc(request):
        started, utc = time.monotonic(), now()
        event = {'operation': request['op'], 'started_at_utc': utc.isoformat(), 'status': 'RUNNING'}
        rpc_events.append(event)
        try:
            result = transport(request);event['status'] = 'RETURNED';return result
        except Exception as error:
            event.update(status='ERROR', error=type(error).__name__+': '+str(error));raise
        finally:
            end = now();event.update(ended_at_utc=end.isoformat(), wall_seconds=time.monotonic()-started,
                utc_elapsed_seconds=(end-utc).total_seconds(),
                scope='Observed RPC wall includes backend computation/resource waits/network transport; it is not an additive CPU or provider queue measure.')
            if output is not None:
                save(output/'rpc_wall.json', rpc_events)
    study = rpc({'op': 'start', 'manifest': args.manifest, 'task_id': args.task,
        'trial_id': args.trial, 'formal': args.formal})['study_directory']
    output = ROOT/('runs/formal/E3_instance_policy' if args.formal else 'runs/development/E3_instance_policy')/Path(study).name
    output.mkdir(parents=True);save(output/'backend.json', {'study_directory': study});save(output/'rpc_wall.json', rpc_events)
    if args.dispatch_record:
        save(Path(args.dispatch_record), {'study_directory': study, 'local_output_directory': str(output),
            'task_id': args.task, 'method': 'I', 'trial_id': str(args.trial), 'formal': args.formal,
            'policy_variant': 'GPT', 'training_seed': None, 'evaluation_seed_slot': None, 'selector_variant': 'main'})
    tokenizer = None
    while True:
        initialized = rpc({'op': 'open_next', 'study_directory': study})
        if initialized['complete']:
            save(output/'complete.json', initialized);save(output/'summary.json', initialized['summary']);break
        directory = initialized['arrival_directory'];out = output/('%04d' % initialized['arrival_ordinal']);out.mkdir()
        save(out/'backend.json', {'arrival_directory': directory})
        frozen = {'status': 'FROZEN_E3' if args.formal else 'DRAFT', 'implementation_sha256': initialized['implementation_sha256']}
        verify(frozen)
        if initialized['served_from_exact_cache']:
            usage = {'model_cli_invocations': 0, 'decision_step_attempts': 0,
                'scope': 'Independent arrival served by exact own-library evidence cache; no model request'}
            status = 'EXACT_CACHE_SERVED'
            save(out/'session.json', {'status': 'EXACT_CACHE_NO_MODEL_REQUEST',
                'independent_arrival_scope': True, 'history': [], 'usage': [], 'closed': True})
        else:
            if tokenizer is None:
                tokenizer = AutoTokenizer.from_pretrained(ROOT/'runtime/policy_tokenizer', local_files_only=True, trust_remote_code=False)
            adapter = GptDecisionAdapter(out/'decisions', tokenizer=tokenizer)
            session = adapter.start(initialized['packet'], initialized['model_config'])
            status = 'DECISION_BUDGET_EXHAUSTED';observation = {'status': 'current_instance_arrived'}
            try:
                for _ in range(initialized['packet']['budget']['decisions']):
                    verify(frozen)
                    current = rpc({'op': 'current', 'arrival_directory': directory})
                    try:
                        proposal = adapter.step(session, observation, current_sources=current['current_sources'])
                    except TimeoutError:
                        raise
                    except Exception as error:
                        status = 'MODEL_FAILED';save(out/'policy_error.json', {'error': type(error).__name__+': '+str(error)});break
                    try:
                        observation = rpc({'op': 'action', 'arrival_directory': directory, 'action': proposal})
                    except ValueError as error:
                        observation = {'error': str(error)}
                    if proposal['action'] == 'finish':
                        status = 'SEARCH_FINISHED';break
                    if observation.get('episode_status') in ('BUDGET_EXHAUSTED', 'INCOMPLETE_UNKNOWN'):
                        status = observation['episode_status'];break
            except TimeoutError:
                status = 'BUDGET_EXHAUSTED'
            except Exception as error:
                status = 'INCOMPLETE_UNKNOWN';save(out/'transport_error.json', {'error': type(error).__name__+': '+str(error)})
            finally:
                session['closed'] = True;save(out/'session.json', session);usage = policy_statistics(session, out)
        report = rpc({'op': 'seal', 'arrival_directory': directory, 'status': status, 'policy_statistics': usage})
        save(out/'search.json', report)
        deployed = rpc({'op': 'deploy', 'arrival_directory': directory});save(out/'episode.json', deployed)
        summary = rpc({'op': 'finish_arrival', 'study_directory': study});save(output/'summary.json', summary)
        if summary['status'] != 'RUNNING':
            break
    print(json.dumps({'study_directory': study, 'local_output_directory': str(output)}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', action='store_true');parser.add_argument('--manifest');parser.add_argument('--task')
    parser.add_argument('--trial', default='development')
    parser.add_argument('--dispatch-record', type=Path)
    parser.add_argument('--formal', action='store_true');args = parser.parse_args()
    if args.backend:
        try:
            print(json.dumps({'result': backend(json.load(sys.stdin))}), flush=True)
        except Exception as error:
            print(json.dumps({'error': str(error), 'error_type': type(error).__name__}), flush=True)
    else:
        if not (args.manifest and args.task):
            parser.error('Instance execution requires manifest and task')
        run_policy(args)
