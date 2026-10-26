"""Independent ratio span8 acceptance: one worker,72 candidate points,zero models."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path.cwd().resolve(); sys.path.insert(0, str(ROOT))
from scripts import evaluate_train_span_proposals as span
from scripts import evaluate_matched_t0_proposals as physical
from scripts.prepare_ratio_source_train_baselines import packet as baseline_packet
from scripts.prepare_ratio_train_context import add_caller
from scripts.prepare_ratio_training_draft import with_exact_configuration_constraints
from scripts.ratio_source_physical_probe import contracted_rc_devices
from src.device_intent import compare_device_intent
from src.train_ratio_span_bundle import load_bundle, validate_tokenizer, SID, LINEAGE, ORDER
from src.training import TrustedPhysicalStore
from src.training_selection_v2 import make_rule

read, save, now = physical.read, physical.save, physical.now
ROLE = 'ratio_source_literal_span8_physical_followup_train_only'
CODE = tuple(dict.fromkeys((*span.CODE, 'scripts/evaluate_ratio_span_proposals.py',
    'scripts/prepare_ratio_source_train_baselines.py', 'scripts/prepare_ratio_train_context.py',
    'scripts/prepare_ratio_training_draft.py', 'scripts/run_ratio_source_train_baselines.py',
    'scripts/ratio_source_physical_probe.py', 'scripts/ratio_source_physical_qualification.py',
    'src/train_generators/ratio_source_intent.py', 'src/train_ratio_span_bundle.py')))
RESOURCES = {'workers': 1, 'cpus_per_job': 2, 'memory_GiB_per_job': 8,
    'generation_timeout_seconds': 240, 'evaluator_timeout_seconds': 900, 'maximum_dispatch_hours': 8,
    'maximum_new_candidate_points': 72, 'maximum_new_baseline_points': 0,
    'actual_busy_cores_plus_new_limit': 24, 'RAM_used_GiB_limit': 190, 'minimum_free_disk_GiB': 4}
TRIAL_ORDER = {'mode': 'train_collection_action_gpt', 'trials': list(range(1, 9))}


def packet(manifest, initial, points, baselines):
    summaries = [{'configuration_id': p['configuration_id'], **{key: baselines[p['configuration_id']]['checked'][key]
        for key in ('S0', 'S1', 'S2', 'objective', 'failure_class')}} for p in points]
    request = baseline_packet(initial, points, summaries)
    request = add_caller(request, (Path(manifest['source_pack']) / 'generator.py').read_text())
    request = with_exact_configuration_constraints(request, points)
    return request['task_packet'], request['visible_history']


def proposal_definition(path, folder):
    path = Path(path).resolve(); bundle = path.parent; plan = load_bundle(path)
    for name in ['train_span_proposer.py', 'student_interface.py']:
        if (ROOT / 'src' / name).read_bytes() != (bundle / 'interface/src' / name).read_bytes():
            raise ValueError('Ratio compiler/ordinary mapper changed: ' + name)
    if (ROOT / 'src/train_ratio_span_bundle.py').read_bytes() != (bundle / 'interface/src/train_span_bundle.py').read_bytes():
        raise ValueError('Use the exact ratio-only loader')
    entry, = plan['contexts']; initial = read(bundle / entry['initial_state'])
    runtime = read(bundle / entry['parent_collection']); registry = read(bundle / entry['effective_registry'])
    runtime.update(output_root=str(folder / 'parents' / entry['parent_collection_id']),
        label_rule_path=str(bundle / entry['label_rule']), physical={key: RESOURCES[key]
            for key in ['generation_timeout_seconds', 'evaluator_timeout_seconds']})
    parent = {'manifest': runtime, 'registry': registry, 'states': [initial],
        'files': runtime['source_files'], 'collector': sys.modules[__name__]}
    context = {**entry, 'state': initial, 'base_source': initial['base_source'],
        'parent_collection': entry['parent_collection_id'],
        'original_request_value': read(bundle / entry['original_request']),
        'teacher_request_value': read(bundle / entry['teacher_request']),
        'materialized_task_packet': str(folder / 'task_packet.json'),
        'materialized_visible_history': str(folder / 'visible_history.json')}
    return plan, {entry['parent_collection_id']: parent}, [context], registry


def prepare(proposal, folder, output):
    folder = Path(folder).resolve(); plan, parents, contexts, registry = proposal_definition(proposal, folder)
    folder.mkdir(parents=True, exist_ok=False); output = Path(output).resolve()
    output.relative_to(ROOT / 'runs/train_collection')
    for name in CODE:
        target = folder / 'interface' / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    (folder / 'interface/base_selection.py').write_text(span.frozen_base_selection((ROOT / 'src/training.py').read_text()))
    context, = contexts; name = context['parent_collection']; parent = parents[name]
    bundle = Path(proposal).resolve().parent
    save(folder / 'parents' / name / 'runtime_binding.json', parent['manifest'])
    save(folder / 'parents' / name / SID / 'baseline_results.json', read(bundle / context['baseline_results']))
    save(folder / 'task_packet.json', context['original_request_value']['task_packet'])
    save(folder / 'visible_history.json', context['original_request_value']['visible_history'])
    save(folder / 'rules' / (name + '.json'), make_rule(read(parent['manifest']['label_rule_path']), TRIAL_ORDER))
    definition = {'status': 'DRAFT', 'role': ROLE, 'proposal_collection': str(Path(proposal).resolve()),
        'proposal_collection_sha256': hashlib.sha256(Path(proposal).read_bytes()).hexdigest(),
        'created_at_utc': now(), 'evidence_root': str(ROOT), 'output_root': str(output),
        'physical': RESOURCES, 'trials': list(range(1, 9)), 'declared_proposals': 8,
        'contexts': [{'initial_state_id': SID, 'parent_collection': name}], 'implementation_files': list(CODE),
        'maximum_full_points': 72, 'new_baseline_points': 0, 'new_model_calls': 0,
        'source_lineages': 1, 'physical_domain_contexts': 1, 'new_contexts_from_proposals': 0,
        'selection': 'Original Point/Family feasibility and1% meaningful-area rule; exact eight-trial v2 equivalent-best earliest representative. No opposite pair or useful target presumed.',
        'raw_input_policy': 'Only the independent ratio8 GPT proposal pool. Old span16,NF32,T0 and development repairs are excluded.',
        'loop': 'Rescan producer raw matrix after each physical pass and before closing; drain every newly returned eligible candidate.',
        'failure_policy': 'Durable no-retry point reservations,1worker2CPU8GB,actual resource/disk gate,8h dispatch,unknown stops future points and no unknown negative labels.'}
    save(folder / 'acceptance.json', definition); return definition


def load_acceptance(path, require_frozen=True):
    path = Path(path).resolve(); definition = read(path)
    if (definition.get('status') != ('frozen' if require_frozen else 'DRAFT') or definition.get('role') != ROLE
            or definition.get('physical') != RESOURCES or definition.get('implementation_files') != list(CODE)
            or definition.get('contexts') != [{'initial_state_id': SID, 'parent_collection': 'ratio_source_fresh9_v1'}]
            or definition.get('trials') != list(range(1, 9)) or definition.get('declared_proposals') != 8
            or definition.get('evidence_root') != str(ROOT)):
        raise ValueError('Keep the separate ratio source,all eight proposals,and finite single-worker physical plan')
    span.verify_code(path, definition)
    if hashlib.sha256(Path(definition['proposal_collection']).read_bytes()).hexdigest() != definition['proposal_collection_sha256']:
        raise ValueError('Frozen ratio proposal identity changed')
    plan, parents, contexts, registry = proposal_definition(definition['proposal_collection'], path.parent)
    context, = contexts; name = context['parent_collection']; parent = parents[name]
    if (read(path.parent / 'parents' / name / 'runtime_binding.json') != parent['manifest']
            or read(path.parent / 'rules' / (name + '.json')) != make_rule(read(parent['manifest']['label_rule_path']), TRIAL_ORDER)
            or read(path.parent / 'task_packet.json') != context['original_request_value']['task_packet']
            or read(path.parent / 'visible_history.json') != context['original_request_value']['visible_history']):
        raise ValueError('Ratio source/contract/history/label rule changed')
    if require_frozen and any(p.stat().st_mode & 0o222 for p in [path.parent, *path.parent.rglob('*')]):
        raise ValueError('Ratio acceptance must be readonly')
    return definition, plan, parents, contexts, registry


def baseline_control(path, report):
    definition, _, parents, contexts, registry = load_acceptance(path, False)
    context, = contexts; parent = parents[context['parent_collection']]
    proposal = {'request': context['teacher_request_value'], 'source': context['base_source'], 'patch': '', 'attempt': {}}
    row = span.candidate_row(context, parent, proposal, 1)
    proof = span.student_identity_proof(context, row)
    bindings = physical.baseline_bindings(context, parent, registry, row)
    records = []
    for point in registry['configurations']:
        raw = Path(bindings[point['configuration_id']]['origin_run_directory'])
        graph = audit_full_rc(raw, point)
        if not graph.get('is_clean'): raise ValueError('Fresh baseline full-RC graph does not establish ratio intent')
        records.append({'configuration_id': point['configuration_id'], 'S2': bindings[point['configuration_id']]['checked']['S2'],
            'full_RC_device_graph_clean': graph['is_clean'], 'run_directory': str(raw)})
    result = {'status': 'ACTUAL_RATIO_FRESH9_ORDINARY_CONTEXT_AND_RC_CONTROL', 'actual_baselines_reread': 9,
        'records': records, 'mapping': proof, 'new_model_calls': 0, 'new_physical_calls': 0}
    save(report, result); return {key: value for key, value in result.items() if key not in ('records', 'mapping')}


def freeze(path):
    path = Path(path).resolve(); definition, _, _, _, _ = load_acceptance(path, False)
    proof = read(path.parent / 'baseline_control.json')
    if proof.get('status') != 'ACTUAL_RATIO_FRESH9_ORDINARY_CONTEXT_AND_RC_CONTROL' or proof.get('actual_baselines_reread') != 9:
        raise ValueError('Actual nine-baseline/ordinary-context/full-RC control required before acceptance freeze')
    definition.update(status='frozen', frozen_at_utc=now()); save(path, definition)
    for p in sorted(path.parent.rglob('*'), key=lambda p: len(p.parts), reverse=True): p.chmod(0o555 if p.is_dir() else 0o444)
    path.parent.chmod(0o555); load_acceptance(path)
    return {'status': 'FROZEN_RATIO8_ACCEPTANCE_NO_CALLS', 'new_model_or_physical_calls': 0}


def audit_full_rc(run, point):
    path = Path(run) / 'evidence/validation.json'
    if not path.exists() or not read(path).get('assessment', {}).get('S1'):
        return {'status': 'NOT_APPLICABLE_BEFORE_S1', 'not_a_negative_RC_label': True}
    value = read(path); pex = value['artifacts']['pex']
    if sorted(p.upper() for p in pex['ports']) != sorted(p.upper() for p in point['contract']['ports']):
        raise ValueError('Full RC omits a required ratio port')
    view = contracted_rc_devices((Path(run) / 'evidence' / pex['netlist']).read_text(), pex['top_cell'], pex['ports'])
    graph = compare_device_intent(view, (Path(run) / 'trusted' / point['reference_file']).read_text())
    if not graph['is_clean']: raise ValueError('Full RC device/body graph differs from independent per-finger reference')
    return graph


def serial_physical_pass(definition, parents, registry, state, output, check_implementation, *,
                         sample=physical.resource_sample, execute_point=physical.point_call):
    store = TrustedPhysicalStore(ROOT, registry)
    while physical.pending_points(state) and not state['status'].startswith('PAUSED'):
        if datetime.now(timezone.utc) >= datetime.fromisoformat(state['deadline_utc']):
            state['dispatch_window_ended'] = True; return
        resource = sample(); state['resource_samples'].append(resource)
        if resource['available_disk_GiB'] < 4: state['status'] = 'PAUSED_STORAGE'; return
        if resource['actual_busy_cores'] + 2 > 24 or resource['RAM_used_GiB'] > 190:
            save(output / 'state.json', state); time.sleep(5); continue
        if sum(c.get('physical_point_reservations', 0) for c in state['cells']) >= 72:
            raise ValueError('The original maximum72 point reservations is exhausted')
        check_implementation(); cell, job = physical.pending_points(state)[0]
        row = read(output / cell['candidate_file']); point = store._configuration(row, job['configuration_id'])
        folder = output / 'candidates' / row['candidate_id'] / 'points' / job['configuration_id']
        if folder.exists():
            job['status'] = 'UNRESOLVED_EXISTING_POINT_NO_RETRY'; state['status'] = 'PAUSED_UNKNOWN'; return
        job.update(status='DISPATCH_RESERVED', reserved_at_utc=now(), resources_before_dispatch=resource)
        cell['physical_point_reservations'] = cell.get('physical_point_reservations', 0) + 1; save(output / 'state.json', state)
        try:
            result = execute_point(parents[cell['parent_collection']], point, row,
                (output / cell['candidate_file']).parent / 'source', folder, state['deadline_utc'])
            run = Path(result['run_directory']).resolve(); began = time.monotonic(); cpu = time.process_time()
            graph = {'status': 'RC_GRAPH_NOT_YET_READ'}
            try:
                graph = audit_full_rc(run, point)
            except Exception as exc:
                graph = {'status': 'UNKNOWN_RC_GRAPH_QUARANTINE', 'actual_audit': graph,
                    'error': type(exc).__name__ + ': ' + str(exc)}
                raise
            finally:
                save(folder / 'full_RC_device_graph_audit.json', {'audit': graph, 'wall_seconds': time.monotonic() - began,
                    'CPU_seconds': time.process_time() - cpu, 'simulation_netlist_simplified': False})
            job['evidence_path'] = str((run / 'manifest.json').relative_to(ROOT))
            baseline = read(output / cell['baseline_adoption'])[job['configuration_id']]
            row['outcomes'].append({'configuration_id': job['configuration_id'], 'role': point['domain_role'],
                'evidence_path': job['evidence_path'], 'baseline_evidence_path': baseline['evidence_path'],
                'baseline_candidate_id': baseline['baseline_candidate_id']})
            save(output / cell['candidate_file'], row)
            checked = store._read_run(job['evidence_path'], row, job['configuration_id'], row['candidate_source'], row['candidate_id'])
            if checked.get('point_evaluation_complete') is not True:
                raise ValueError('Partial corner evidence is unknown,not a candidate negative')
            job.update(checked=checked, status='COMPLETE', returned_at_utc=now())
        except Exception as exc:
            job.update(status='UNKNOWN_NO_RETRY', error=type(exc).__name__ + ': ' + str(exc), returned_at_utc=now())
            cell['status'] = 'QUARANTINED_UNKNOWN'; state['status'] = 'PAUSED_UNKNOWN'
        save(output / 'state.json', state)


def derive(definition, parents, registry, state, output, tokenizer, folder):
    span.derive(definition, parents, registry, state, output, tokenizer, folder)
    if (output / 'student_selection.json').exists():
        result = read(output / 'student_selection.json')
        result.update(planned_proposals=8, initial_contexts_reused=1, source_lineages=1,
            proposer_cohort='independent_ratio_source_literal_span8_only', raw_other_candidate_pool_used=False)
        save(output / 'student_selection.json', result)


def cycle(definition, plan, parents, contexts, registry, state, output, tokenizer, folder, verify):
    span.scan_returned(definition, plan, parents, contexts, registry, state, output, tokenizer)
    save(output / 'state.json', state)
    serial_physical_pass(definition, parents, registry, state, output, verify)
    if state['status'].startswith('PAUSED'): return
    derive(definition, parents, registry, state, output, tokenizer, folder)
    if (Path(plan['output_root']) / 'completion.json').exists():
        # A model return during a long physical pass must be consumed before COMPLETE.
        span.scan_returned(definition, plan, parents, contexts, registry, state, output, tokenizer)
        save(output / 'state.json', state)
        if any(c['status'] == 'PHYSICAL_PENDING' for c in state['cells']): return
        matrix = span.raw_matrix(plan)
        for cell in state['cells']:
            if cell['status'] == 'NOT_RUN':
                if matrix[(cell['initial_state_id'], cell['trial_id'])]['status'] != 'NOT_RUN':
                    raise ValueError('Completed producer still has an unresolved returned/dispatched ratio slot')
                cell['status'] = 'ORIGINAL_NOT_RUN_PROPOSAL_WINDOW_ENDED'
        derive(definition, parents, registry, state, output, tokenizer, folder)
        if not state['status'].startswith('PAUSED'): state['status'] = 'COMPLETE'


def run(path):
    path = Path(path).resolve(); definition, plan, parents, contexts, registry = load_acceptance(path)
    output = Path(definition['output_root']); output.mkdir(parents=True, exist_ok=True)
    with (output / 'coordinator.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (output / 'acceptance.json').exists() and read(output / 'acceptance.json') != definition:
            raise ValueError('Another acceptance owns this output')
        save(output / 'acceptance.json', definition)
        state = read(output / 'state.json') if (output / 'state.json').exists() else span.initial_state(definition)
        expected = [(SID, trial) for trial in range(1, 9)]
        if [(c['initial_state_id'], c['trial_id']) for c in state['cells']] != expected:
            raise ValueError('Keep all original eight proposal identities on resume')
        state['role'] = ROLE; physical.mark_orphaned_reservations(state)
        if state['status'].startswith('PAUSED') or state['status'] in ('COMPLETE', 'WINDOW_ENDED'): return state
        from transformers import AutoTokenizer
        cache = read(ROOT / 'configs/training/backbone_cache.json')
        validate_tokenizer(cache['snapshot'], Path(definition['proposal_collection']).parent)
        tokenizer = AutoTokenizer.from_pretrained(cache['snapshot'], local_files_only=True, trust_remote_code=False)
        while datetime.now(timezone.utc) < datetime.fromisoformat(state['deadline_utc']):
            state.update(status='RUNNING', coordinator_pid=os.getpid())
            if not (Path(plan['output_root']) / 'matrix.json').exists():
                save(output / 'state.json', state); time.sleep(5); continue
            try:
                cycle(definition, plan, parents, contexts, registry, state, output, tokenizer, path.parent,
                    lambda: span.verify_code(path, definition))
            except json.JSONDecodeError as exc:
                state.setdefault('metadata_waits', []).append({'at_utc': now(), 'error': str(exc)})
                save(output / 'state.json', state); time.sleep(5); continue
            except Exception as exc:
                state.update(status='PAUSED_UNKNOWN', error=type(exc).__name__ + ': ' + str(exc)); break
            if state['status'].startswith('PAUSED') or state['status'] == 'COMPLETE' or state.get('dispatch_window_ended'): break
            save(output / 'state.json', state)
            if not physical.pending_points(state): time.sleep(5)
        else: state['status'] = 'WINDOW_ENDED'
        if state.get('dispatch_window_ended') and not state['status'].startswith('PAUSED'): state['status'] = 'WINDOW_ENDED'
        if state['status'].startswith('PAUSED'): physical.invalidate_derivation(output)
        state.update(coordinator_pid=None, ended_at_utc=now()); save(output / 'state.json', state)
        result = span.completion(state)
        result.update(planned_proposals=8, physical_domain_contexts=1, original_contexts_reused=1, maximum_candidate_points=72)
        result['stage_funnel']['declared_raw_slots'] = 8
        save(output / 'completion.json', result); return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); modes = p.add_mutually_exclusive_group(required=True)
    for name in ['prepare', 'baseline-control', 'freeze', 'validate-only', 'execute']: modes.add_argument('--' + name, action='store_true')
    for name in ['proposal', 'folder', 'output-root', 'plan', 'report']: p.add_argument('--' + name, type=Path)
    a = p.parse_args()
    if a.prepare: result = prepare(a.proposal, a.folder, a.output_root)
    elif a.baseline_control: result = baseline_control(a.plan, a.report)
    elif a.freeze: result = freeze(a.plan)
    elif a.validate_only: result = {'status': 'VALIDATED_RATIO8_ACCEPTANCE_NO_CALLS', 'declared_proposals': load_acceptance(a.plan)[0]['declared_proposals']}
    else: result = run(a.plan)
    print(json.dumps(result, indent=2, allow_nan=False))
