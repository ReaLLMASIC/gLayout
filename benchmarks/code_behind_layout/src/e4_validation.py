"""Prospective validation plan and raw-bound checkpoint selection control.

Preparation and validation import no torch and launch no physical/model work.
Unknown evidence cannot be converted into a negative validation label.
"""
from datetime import datetime, timezone
from fractions import Fraction
import json
from pathlib import Path
import copy
import subprocess
import tempfile
import shutil
import sys
import time
from datetime import timedelta

from src.e4_methods import (METHODS, SEEDS, SELECTION_RULE, REVISION, checkpoint_files,
    file_digest, validate_selection, inspect_formal_run)
from src.model_adapter import PACKET_FIELDS, validate_action
from src.training import TrustedPhysicalStore, frozen_train_registry
from src.policy_state import current_state_request
from src.candidate_executor import apply_source_patch
from src.model_adapter import check_utc_budget


def read(path): return json.loads(Path(path).read_text())
def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream: stream.write(json.dumps(value, indent=2, allow_nan=False)+'\n')
def now(): return datetime.now(timezone.utc).isoformat()
def absolute(root, value):
    path = Path(value); return (path if path.is_absolute() else Path(root)/path).resolve()


def validation_assignments(registry, *, allow_joint_draft=False):
    if allow_joint_draft and registry.get('status') == 'DRAFT_E4_JOINT_REGISTRY':
        from src.measurement import split_errors
        errors = split_errors(registry)
        if errors: raise ValueError('Invalid prospective joint assignments: '+', '.join(errors))
        return {row['lineage_id']: row for row in registry['lineages']}
    return frozen_train_registry(registry)


def prepare_joint_registry(registry_path, qualified_task_path, output):
    """Propose a separate append; never mutate or relabel the global registry."""
    registry_path = Path(registry_path).resolve(); original = read(registry_path)
    original_assignments = frozen_train_registry(original)
    task_path = Path(qualified_task_path).resolve(); task = read(task_path)
    if (task.get('status') != 'FROZEN_E4_VALIDATION_TASK' or task.get('formal_admission') is not True
            or task_path.stat().st_mode & 0o222):
        raise ValueError('An actually qualified readonly validation task is required')
    lineage = task['parent_lineage']
    if original_assignments.get(lineage, {}).get('split') != 'validation':
        raise ValueError('Validation cannot replace a train/test source assignment')
    points = task['points']; seen = {point['configuration_id'] for point in original.get('configurations', [])}
    if (len(points) != 9 or len({p['configuration_id'] for p in points}) != 9
            or any(p['configuration_id'] in seen or p.get('split') != 'validation' or p['parent_lineage'] != lineage for p in points)):
        raise ValueError('Prospective validation must append nine distinct validation-only configuration IDs')
    result = copy.deepcopy(original)
    assignment = next(row for row in result['lineages'] if row['lineage_id'] == lineage)
    assignment.update(formal_admission=True, editable_paths=task['editable_paths'],
        source_mapping={name: original_assignments[lineage]['source'] for name in task['editable_paths']},
        qualified_validation_task=str(task_path),
        qualification_status='actual_complete_fixed9full_gold_and_clean_DRC_failed_LVS_initial_with_feasible_witness',
        sizing_domain_status='qualified_fixed_3x3_W_L_nf2_channel24')
    result['configurations'] = result.get('configurations', [])+copy.deepcopy(points)
    result.update(status='DRAFT_E4_JOINT_REGISTRY', prepared_at_utc=now(),
        prior_global_registry=str(registry_path), prior_global_registry_sha256=file_digest(registry_path),
        canonical_append_requires_review=True, formal_training_or_checkpoint_selection_allowed=False,
        final_training_data_registry_still_pending=True,
        same_final_registry_SHA_required_for_every_formal_training_run_and_validation_plan=True)
    proposed = validation_assignments(result, allow_joint_draft=True)
    if {key: row['split'] for key, row in proposed.items()} != {key: row['split'] for key, row in original_assignments.items()}:
        raise ValueError('The proposed append changed source split assignments')
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(registry_path, output/'prior_global_registry.json')
    save(output/'registry.json', result)
    save(output/'summary.json', {'status': result['status'], 'prior_global_registry_sha256': file_digest(registry_path),
        'preserved_source_assignments': len(original_assignments), 'original_configuration_count': len(seen),
        'new_validation_configurations': 9, 'qualified_task': str(task_path), 'global_registry_modified': False,
        'formal_training_allowed': False, 'new_model_or_EDA_calls': 0})
    return read(output/'summary.json')


def validate_budget(budget):
    required = {'decisions', 'patches', 'physical_evaluations', 'wall_seconds',
        'maximum_context_tokens', 'maximum_output_tokens', 'generation_timeout_seconds', 'evaluator_timeout_seconds'}
    if set(budget) != required or any(type(v) is not int or v <= 0 for v in budget.values()):
        raise ValueError('Declare the complete positive common validation budget')
    if budget['maximum_context_tokens'] != 16384 or budget['maximum_output_tokens'] != 1024:
        raise ValueError('Ordinary checkpoint validation uses the calibrated16384/1024 interface')
    return budget


def prepare(registry_path, task_index, budget, checkpoint_backend=None):
    """Return a DRAFT with concrete blockers; never invent ready validation data."""
    registry_path = Path(registry_path).resolve(); registry = read(registry_path)
    assignments = validation_assignments(registry, allow_joint_draft=True); validate_budget(budget)
    points = [p for p in registry.get('configurations', []) if p.get('split') == 'validation']
    blockers = []; tasks = []
    if registry.get('status') != 'frozen':
        blockers.append('Combined registry is a prospective DRAFT; final training-data/canonical append review and one shared registry SHA remain required before every formal training run')
    if not points: blockers.append('Frozen registry has zero validation configurations')
    backend = None; implementations = {}
    if checkpoint_backend is None:
        blockers.append('No independent16k checkpoint ordinary-action backend code is bound; frozen-method serving cannot be used before selection')
    else:
        backend_path = Path(checkpoint_backend).resolve()
        if not backend_path.is_file(): raise ValueError('Checkpoint backend implementation is absent')
        backend = {'path': str(backend_path), 'sha256': file_digest(backend_path),
            'status': 'CODE_BOUND_NOT_RUNTIME_QUALIFIED', 'actual_GPU_load_or_READY_claimed': False}
        project = Path(__file__).resolve().parents[1]
        for name in ('src/e4_validation.py', 'scripts/e4_checkpoint_validation.py', 'src/e4_methods.py',
                'scripts/serve_checkpoint_policy.py', 'scripts/serve_frozen_policy.py',
                'src/local_model_adapter.py', 'src/model_adapter.py', 'src/student_interface.py', 'src/policy_state.py',
                'src/e3_feedback.py', 'scripts/e1_matched_runner.py',
                'src/candidate_executor.py', 'src/training.py', 'src/domain_runner.py', 'src/device_intent.py',
                'src/spice_validation.py', 'src/measurement.py', 'src/report_parsers.py', 'src/physical_drc.py'):
            implementations[str(project/name)] = file_digest(project/name)
    indexes = read(task_index) if task_index else []
    if not indexes: blockers.append('No qualified complete-source validation editing task index')
    expected = {(p['contract']['task_id'], p['configuration_id']): p for p in points}
    if len(expected) != len(points): raise ValueError('Validation registry has duplicate task/configuration IDs')
    for record in indexes:
        path = absolute(Path(task_index).parent, record['task_file']); task = read(path)
        ident, lineage = task['task_id'], task['parent_lineage']; assignment = assignments.get(lineage, {})
        if assignment.get('split') != 'validation' or task.get('split') != 'validation':
            raise ValueError('Training/test source cannot be repurposed for checkpoint selection')
        if 'F3' in assignment.get('purpose', '') and 'only' in assignment.get('purpose', '').lower():
            raise ValueError('F3-only validation source is not an E4 editing task')
        if assignment.get('formal_admission') is not True or task.get('formal_admission') is not True:
            blockers.append(ident+': source/domain is not admitted')
        editable = task['editable_paths']; pack = absolute(path.parent, task['source_pack'])
        if not editable or not set(editable).issubset(task['source_files']): raise ValueError('Full editable modules and source closure required')
        for name in task['source_files']:
            target = pack/name
            if target.is_symlink() or not target.is_file(): raise ValueError('Missing declared source file: '+name)
        packet = read(absolute(path.parent, task['packet']))
        if set(packet) != PACKET_FIELDS or packet['task_id'] != ident or set(packet['allowed_paths']) != set(editable):
            raise ValueError('Validation packet violates the ordinary policy boundary')
        if packet['visible_sources'] != {name: (pack/name).read_text() for name in editable}:
            raise ValueError('Packet must contain complete original editable source text')
        if packet['documents']['action_gateway']['read_source_paths'] != editable:
            raise ValueError('Packet must explicitly delimit read_source from runtime-only files')
        declared = {(ident, name) for name in task['configuration_ids']}
        if not declared or not declared.issubset(expected): raise ValueError('Task points are not frozen validation configurations')
        if set(packet['visible_configurations']) != set(task['configuration_ids']): raise ValueError('Validation policy receives exactly its visible plan')
        if any(expected[key]['parent_lineage'] != lineage or expected[key].get('role') == 'hidden' for key in declared):
            raise ValueError('Hidden/foreign-lineage points cannot select checkpoints')
        if not task.get('useful_editing_signal_evidence'):
            blockers.append(ident+': actual repair/shortfall signal and feasible witness absent')
        if not task.get('actual_context_preflight'):
            blockers.append(ident+': exact pinned-tokenizer complete-source preflight absent')
        if set(task.get('qualification_runs', {})) != set(task['configuration_ids']) or not task.get('qualification_sources'):
            blockers.append(ident+': complete raw-bound whole-domain gold qualification absent')
        tasks.append({'task_id': ident, 'parent_lineage': lineage, 'task_file': str(path),
            'configuration_ids': task['configuration_ids'], 'editable_paths': editable})
    if len({t['task_id'] for t in tasks}) != len(tasks): raise ValueError('Duplicate validation task')
    used = {(t['task_id'], name) for t in tasks for name in t['configuration_ids']}
    return {'status': 'DRAFT_E4_VALIDATION_PLAN', 'prepared_at_utc': now(),
        'split_registry': str(registry_path), 'split_registry_sha256': file_digest(registry_path),
        'selection_rule': SELECTION_RULE, 'tasks': tasks,
        'points': [{'task_id': t, 'configuration_id': c} for t, c in sorted(used)],
        'budget': budget, 'history_policy': 'current_source_and_feedback_v1', 'checkpoint_backend': backend,
        'implementation_sha256': implementations,
        'checkpoint_decoding': {'do_sample': False, 'max_new_tokens': 1024, 'implementation_seed': 41},
        'source_rule': 'One sealed final complete source per task/checkpoint; fresh entire visible point plan after search',
        'failure_rule': 'Retain model/action failures and all failed point denominators; unknown physical evidence pauses selection without automatic retry',
        'selection_metric': 'Actual complete task-mean S2 fraction; token loss and hidden/test labels never select',
        'training_order_constraint': 'Freeze this same combined train+validation registry before formal training so its identity matches all12runs',
        'freeze_blockers': blockers, 'new_model_or_EDA_calls': 0}


def validate_plan(plan, plan_path, *, frozen=True):
    path = Path(plan_path).resolve()
    if frozen and (plan.get('status') != 'FROZEN_E4_VALIDATION_PLAN' or path.stat().st_mode & 0o222):
        raise ValueError('Checkpoint validation requires the prospective readonly plan')
    if plan['selection_rule'] != SELECTION_RULE: raise ValueError('Validation selection rule changed')
    validate_budget(plan['budget'])
    registry_path = absolute(path.parent, plan['split_registry']); registry = read(registry_path)
    if file_digest(registry_path) != plan['split_registry_sha256']: raise ValueError('Combined training/validation registry changed')
    assignments = validation_assignments(registry, allow_joint_draft=not frozen)
    backend = plan.get('checkpoint_backend')
    if frozen and (not backend or file_digest(backend['path']) != backend['sha256']):
        raise ValueError('Checkpoint backend code is absent or changed since the prospective plan')
    if frozen and (not plan.get('implementation_sha256') or any(file_digest(name) != digest
            for name, digest in plan['implementation_sha256'].items())):
        raise ValueError('Validation ordinary interface/physical consumer code changed after plan freeze')
    expected = {(p['contract']['task_id'], p['configuration_id']): p for p in registry.get('configurations', []) if p.get('split') == 'validation'}
    declared = {(p['task_id'], p['configuration_id']) for p in plan['points']}
    if not declared or len(declared) != len(plan['points']) or not declared.issubset(expected):
        raise ValueError('No distinct frozen validation configurations are ready')
    task_ids = [task['task_id'] for task in plan['tasks']]
    if len(set(task_ids)) != len(task_ids) or set(task_ids) != {task for task, _ in declared}:
        raise ValueError('Validation task list differs from the actual point plan')
    for key in declared:
        point = expected[key]
        if assignments[point['parent_lineage']]['split'] != 'validation' or point.get('role') == 'hidden':
            raise ValueError('Hidden/train/test point reached checkpoint validation')
    return registry, expected


def validate_model_response(response, digest, method, seed, checkpoint=None):
    """Distinguish a measured policy-output failure from an unknown transport.

    The error label alone is insufficient: the same actual weights, ordinary
    boundary and real bounded generation usage remain mandatory.
    """
    identity = response.get('model', {})
    if (response.get('native_tools') != [] or identity.get('adapter_sha256') != digest
            or identity.get('variant') != method or identity.get('training_seed') != seed
            or identity.get('base_revision') != REVISION
            or identity.get('source_role') != 'E4_checkpoint_validation_not_selected'):
        raise ValueError('Validation response exposed native tools or used different weights')
    if checkpoint is not None and (not identity.get('checkpoint') or Path(identity['checkpoint']).resolve() != Path(checkpoint).resolve()):
        raise ValueError('Served model belongs to another saved checkpoint')
    usage = response.get('usage', {})
    if (usage.get('maximum_context_tokens') != 16384 or usage.get('max_new_tokens') != 1024
            or type(usage.get('output_tokens')) is not int or not 0 <= usage['output_tokens'] <= 1024
            or type(usage.get('input_tokens')) is not int or not 0 < usage['input_tokens'] <= 16384-1024):
        raise ValueError('Actual checkpoint action violated the common16384/1024 interface')
    failed = bool(response.get('error'))
    if failed:
        if (response.get('failure_class') != 'policy_output_or_budget'
                or response.get('generation_started') is not True or 'action' in response):
            raise ValueError('Model/transport failure has no measured policy-output classification')
    elif usage.get('eos_terminated') is not True:
        raise ValueError('Successful action did not terminate within the common output budget')
    elif 'action' not in response:
        raise ValueError('Successful ordinary response has no structured action')
    return failed


def freeze(draft_path, output):
    """Read actual qualification; this operation itself launches no work."""
    draft_path = Path(draft_path).resolve(); plan = read(draft_path)
    if plan['status'] != 'DRAFT_E4_VALIDATION_PLAN' or plan['freeze_blockers']:
        raise ValueError('Validation plan is DRAFT/blocked; no readiness is inferred')
    registry, points = validate_plan(plan, draft_path, frozen=False)
    if registry.get('status') != 'frozen':
        raise ValueError('Final validation plan cannot freeze before the canonical joint registry is actually frozen')
    audits = []
    for task_row in plan['tasks']:
        task_path = Path(task_row['task_file']); task = read(task_path)
        if task.get('formal_admission') is not True or task_path.stat().st_mode & 0o222:
            raise ValueError('Validation task must already have its own readonly qualification freeze')
        pack = absolute(task_path.parent, task['source_pack'])
        source = task['qualification_sources']
        for ident in task['configuration_ids']:
            run = absolute(task_path.parent, task['qualification_runs'][ident])
            checked = TrustedPhysicalStore._inspect_execution_run(run, points[task['task_id'], ident], source)
            if not checked['S2']: raise ValueError('Declared independent gold domain has a real electrical shortfall')
            audits.append({'task_id': task['task_id'], 'configuration_id': ident, 'run_directory': str(run), 'S2': checked['S2']})
        # Evidence is an actual failed initial state plus a raw-bound feasible
        # witness; qualification provider supplies their exact immutable point.
        signal = read(absolute(task_path.parent, task['useful_editing_signal_evidence']))
        if (signal.get('actual_initial_failure_verified') is not True or signal.get('feasible_repair_verified') is not True
                or not signal.get('initial_run_directory') or not signal.get('witness_run_directory')):
            raise ValueError('Checkpoint validation lacks a useful actual editing signal')
        point = points[task['task_id'], signal['configuration_id']]
        before = TrustedPhysicalStore._inspect_execution_run(absolute(task_path.parent, signal['initial_run_directory']), point, signal['initial_source'])
        after = TrustedPhysicalStore._inspect_execution_run(absolute(task_path.parent, signal['witness_run_directory']), point, signal['witness_source'])
        if before['S2'] or not after['S2']: raise ValueError('Actual initial/witness evidence contradicts selection signal')
        preflight = read(absolute(task_path.parent, task['actual_context_preflight']))
        snapshot = Path(preflight['tokenizer_snapshot'])
        if snapshot.name != REVISION: raise ValueError('Validation tokenizer is not the pinned revision')
        from transformers import AutoTokenizer
        from src.local_model_adapter import decision_prompt
        tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True, trust_remote_code=False)
        packet = read(absolute(task_path.parent, task['packet']))
        initial = {name: (pack/name).read_text() for name in task['editable_paths']}
        request = current_state_request(packet, [], initial)
        encoded = tokenizer.apply_chat_template([{'role': 'user', 'content': decision_prompt(request)}], tokenize=True, add_generation_prompt=True)
        tokens = len(encoded['input_ids'] if hasattr(encoded, 'keys') else encoded)
        if tokens != preflight['input_tokens'] or tokens+1024 > 16384:
            raise ValueError('Actual complete-source validation packet exceeds its frozen context or preflight differs')
    frozen = {**plan, 'status': 'FROZEN_E4_VALIDATION_PLAN', 'frozen_at_utc': now(), 'qualification_audit': audits}
    save(output, frozen); Path(output).chmod(0o444)
    return frozen


def validate_editing_ledger(ledger_path, plan, checkpoint, method, seed):
    """Bind actual ordinary model actions and final source to one adapter."""
    path = Path(ledger_path).resolve(); ledger = read(path); checkpoint = Path(checkpoint).resolve()
    digest = file_digest(checkpoint/'adapter/policy/adapter_model.safetensors')
    if (ledger.get('status') != 'SEALED_E4_VALIDATION_EDITING' or ledger['method'] != method or ledger['seed'] != seed
            or absolute(path.parent, ledger['checkpoint']) != checkpoint or ledger['adapter_sha256'] != digest
            or ledger.get('hidden_calls') != 0): raise ValueError('Editing ledger is not bound to the actual checkpoint')
    if set(ledger['tasks']) != {t['task_id'] for t in plan['tasks']}: raise ValueError('Editing ledger dropped a task')
    for ident, task in ledger['tasks'].items():
        session = read(absolute(path.parent, task['session_json']))
        if session.get('closed') is not True or session['packet']['task_id'] != ident:
            raise ValueError('Actual ordinary editing session is absent or unsealed')
        if not session['history']: raise ValueError('No actual checkpoint decision was made for the validation task')
        if len(session['history']) > plan['budget']['decisions']: raise ValueError('Checkpoint received extra decisions')
        declaration = next(t for t in plan['tasks'] if t['task_id'] == ident)
        task_path = Path(declaration['task_file']); frozen_task = read(task_path)
        packet = read(absolute(task_path.parent, frozen_task['packet']))
        original = absolute(task_path.parent, frozen_task['source_pack'])
        current = {name: (original/name).read_text() for name in frozen_task['editable_paths']}
        for key in ('task_id', 'goal', 'contract', 'allowed_paths', 'documents', 'visible_configurations'):
            if session['packet'][key] != packet[key]: raise ValueError('A checkpoint received a different frozen validation packet')
        for key in ('decisions', 'patches', 'physical_evaluations', 'wall_seconds', 'maximum_context_tokens', 'maximum_output_tokens'):
            if session['packet']['budget'].get(key) != plan['budget'][key]: raise ValueError('Checkpoint action/search budget differs')
        folders = sorted(Path(session['output']).glob('decision_*'))
        if len(folders) != len(session['history']): raise ValueError('Every actual model decision must retain its raw records')
        if len(task['gateway_events']) != len(folders): raise ValueError('Each actual model attempt needs its matching gateway outcome')
        patches = 0
        for number, folder in enumerate(folders):
            request = read(folder/'request.json'); response = read(folder/'response.json'); invocation = read(folder/'invocation.json')
            if type(invocation.get('pid')) is not int or invocation['pid'] <= 0: raise ValueError('A fabricated/noninvoked model response cannot select a checkpoint')
            if datetime.fromisoformat(invocation['started_at_utc'].replace('Z', '+00:00')) < datetime.fromisoformat(plan['frozen_at_utc'].replace('Z', '+00:00')):
                raise ValueError('Model decision predates its prospectively frozen validation plan')
            failed = validate_model_response(response, digest, method, seed, checkpoint)
            if request['request']['task_packet']['task_id'] != ident: raise ValueError('Model request belongs to another validation task')
            history = copy.deepcopy(session['history'][:number+1]); history[-1].pop('action', None)
            if request['request'] != current_state_request(session['packet'], history, current):
                raise ValueError('Raw model request changed complete source/history/contract')
            event = task['gateway_events'][number]
            if event['status'] == 'BUDGET_REJECTED':
                deadline = request['request']['task_packet']['budget'].get('deadline_utc')
                if (number != len(folders)-1 or not deadline or invocation.get('utc_deadline_exceeded') is not True
                        or datetime.fromisoformat(invocation['ended_at_utc']) < datetime.fromisoformat(deadline)):
                    raise ValueError('A rejected late action needs the actual elapsed UTC budget record')
                continue
            if failed:
                if number != len(folders)-1 or event['status'] != 'MODEL_RESPONSE_FAILURE':
                    raise ValueError('A failed generation must terminate editing without applying an action')
                continue
            if 'action' in response:
                try: action = validate_action(response['action'], request['request']['task_packet'])
                except ValueError:
                    if event['status'] != 'ACTION_REJECTED': raise
                    continue
                if action['action'] == 'propose_patch':
                    patches += 1
                    if patches > plan['budget']['patches']:
                        if number != len(folders)-1 or event['status'] != 'ACTION_REJECTED':
                            raise ValueError('Checkpoint received extra patch applications beyond its budget')
                        continue
                    with tempfile.TemporaryDirectory() as tmp:
                        work = Path(tmp)
                        for name, content in current.items():
                            target = work/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(content)
                        try: apply_source_patch(work, action['patch'], list(current))
                        except (ValueError, subprocess.CalledProcessError):
                            if event['status'] != 'ACTION_REJECTED': raise ValueError('Claimed applied patch was not executable')
                        else:
                            if event['status'] != 'APPLIED': raise ValueError('Executable patch outcome differs from actual gateway ledger')
                            current = {name: (work/name).read_text() for name in current}
        if task['final_sources'] != current: raise ValueError('Final physical source is not the actual model/gateway result')
    return ledger


def record_checkpoint(plan_path, checkpoint, method, seed, task_records, output):
    """Generate the compatible ledger from actual external ordinary sessions.

    This is a recorder, not a mock inference or physical producer. Missing actual
    session/point evidence remains missing; it cannot create a selection score.
    """
    plan = read(plan_path); validate_plan(plan, plan_path)
    checkpoint = Path(checkpoint).resolve(); checkpoint_files(checkpoint)
    if method not in METHODS or seed not in SEEDS: raise ValueError('One actual T1--T4/seed checkpoint required')
    saved = read(checkpoint/'metadata/run.json')
    if saved.get('method') != method or saved.get('seed') != seed:
        raise ValueError('Engineering or another-method checkpoint is not the declared validation model')
    tasks = {}; points = []
    for item in task_records:
        if item['task_id'] in tasks: raise ValueError('Duplicate actual editing task')
        tasks[item['task_id']] = {key: item[key] for key in ('session_json', 'gateway_events', 'final_sources')}
        points.extend(item['points'])
    ledger = {'status': 'SEALED_E4_VALIDATION_EDITING', 'method': method, 'seed': seed,
        'checkpoint': str(checkpoint), 'adapter_sha256': file_digest(checkpoint/'adapter/policy/adapter_model.safetensors'),
        'validation_plan_sha256': file_digest(plan_path), 'tasks': tasks, 'points': points,
        'hidden_calls': 0, 'recorded_at_utc': now(), 'new_model_or_EDA_calls_during_recording': 0}
    save(output, ledger)
    try: validate_editing_ledger(output, plan, checkpoint, method, seed)
    except Exception:
        Path(output).write_text(json.dumps({**ledger, 'status': 'REJECTED_ACTUAL_EDITING_LEDGER_NOT_ADMITTED'}, indent=2)+'\n')
        raise
    return ledger


def run_checkpoint(plan_path, entry, checkpoint, output, project, entry_root=None):
    """Future real ordinary editing + isolated physical producer, one checkpoint.

    The operator must already have loaded this exact checkpoint in the separate
    checkpoint service. This function neither starts/replaces a GPU service nor
    accesses a test oracle. Do not call it during preparation/software controls.
    """
    from src.local_model_adapter import LocalDecisionAdapter
    from src.candidate_executor import CandidateExecutor
    from src.e3_feedback import public_checked, compact as compact_feedback
    from scripts.e1_matched_runner import visible_feedback
    from scripts.e1_schematic_parallel import resources
    project = Path(project).resolve(); plan_path = Path(plan_path).resolve(); plan = read(plan_path)
    registry, points = validate_plan(plan, plan_path); method, seed = entry['method'], entry['seed']
    from src.student_interface import interface_definition, CONTEXT_VERSION
    training = inspect_formal_run(entry, entry_root or project,
        interface_definition(CONTEXT_VERSION, 16384, 1024), plan['split_registry_sha256'])
    checkpoint = Path(checkpoint).resolve(); checkpoint_files(checkpoint)
    if checkpoint not in [Path(path).resolve() for path in training['checkpoints']]:
        raise ValueError('Validation may only evaluate this actual completed run saved checkpoint')
    digest = file_digest(checkpoint/'adapter/policy/adapter_model.safetensors')
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    save(output/'reservation.json', {'checkpoint': str(checkpoint), 'method': method, 'seed': seed,
        'plan_sha256': file_digest(plan_path), 'status': 'RESERVED_ONCE_NO_AUTOMATIC_RETRY', 'created_at_utc': now()})
    task_records = []; executor = CandidateExecutor(project/'runtime/GLdev', output/'physical', project/'runtime/magic-8.3.685')
    for declaration in plan['tasks']:
        task_path = Path(declaration['task_file']); task = read(task_path); ident = task['task_id']
        work = output/ident; work.mkdir(); source = work/'source'
        shutil.copytree(absolute(task_path.parent, task['source_pack']), source)
        for path in source.rglob('*'):
            if path.is_dir(): path.chmod(path.stat().st_mode | 0o700)
        source.chmod(0o700)
        for name in task['editable_paths']: (source/name).chmod(0o644)
        def sources(): return {name: (source/name).read_text() for name in task['editable_paths']}
        packet = read(absolute(task_path.parent, task['packet']))
        packet['budget'] = {**plan['budget'], 'deadline_utc': (datetime.now(timezone.utc)+timedelta(seconds=plan['budget']['wall_seconds'])).isoformat()}
        adapter = LocalDecisionAdapter(work/'decisions', [sys.executable, str(project/'scripts/serve_checkpoint_policy.py'), '--request'])
        session = adapter.start(packet, {'variant': method, 'base_revision': REVISION,
            'visible_history_policy': 'current_source_and_feedback_v1', 'timeout_seconds_per_decision': 600})
        gateway = []; search_runs = []; patch_attempts = checks = 0; terminal = 'DECISION_BUDGET_EXHAUSTED'

        def physical(configuration_id, stage):
            nonlocal checks
            key = ident, configuration_id
            if key not in points or configuration_id not in task['configuration_ids']:
                raise ValueError('Hidden or undeclared validation point')
            if stage == 'search':
                check_utc_budget(packet)
                if checks >= plan['budget']['physical_evaluations']: raise ValueError('Common physical budget exhausted')
                checks += 1
            began = time.monotonic()
            while True:
                if stage == 'search': check_utc_budget(packet)
                sample = resources()
                if (sample['busy_cores']+2 <= 24 and sample['RAM_used_GiB'] <= 190
                        and shutil.disk_usage(project).free >= 4*2**30): break
                if time.monotonic()-began > 600: raise RuntimeError('Resource gate unresolved; no validation point dispatched')
                time.sleep(10)
            point = points[key]; slot = work/('search_%03d'%checks if stage == 'search' else 'final_'+configuration_id)
            slot.mkdir(); trusted = slot/'trusted'; trusted.mkdir()
            for name, content in point['trusted_evaluator_files'].items():
                target = trusted/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(content)
            save(slot/'reserved.json', {'task_id': ident, 'configuration_id': configuration_id, 'stage': stage, 'created_at_utc': now()})
            actual = executor.execute(source_dir=source, source_paths=task['source_files'], entrypoint=task['entrypoint'],
                representation='G2', configuration=point['parameters'], trusted_dir=trusted,
                trusted_paths=sorted(point['trusted_evaluator_files']), fidelity='pex_spice',
                phase='development_E4_checkpoint_validation', context={'source_role': 'E4_validation_checkpoint_selection',
                    'method': method, 'training_seed': seed, 'model_adapter_sha256': digest,
                    'configuration_id': configuration_id, 'reference_id': point['contract']['reference_id'],
                    'pdk_revision': point['pdk_revision'], 'stage': stage},
                generation_timeout_seconds=plan['budget']['generation_timeout_seconds'],
                evaluator_timeout_seconds=plan['budget']['evaluator_timeout_seconds'],
                **({'execution_deadline_utc': packet['budget']['deadline_utc']} if stage == 'search' else {}))
            save(slot/'execution.json', actual)
            if actual.get('status') == 'BUDGET_EXHAUSTED' and stage == 'search':
                raise TimeoutError('Actual physical search exhausted its declared UTC budget')
            try: checked = TrustedPhysicalStore._inspect_execution_run(actual['run_directory'], point, sources())
            except Exception as error:
                save(slot/'unknown.json', {'status': 'UNKNOWN_NO_AUTOMATIC_RETRY', 'error': type(error).__name__+': '+str(error),
                    'run_directory': actual['run_directory']})
                raise RuntimeError('Actual physical evidence is unknown; stop this checkpoint without further points') from error
            record = {'task_id': ident, 'configuration_id': configuration_id, 'run_directory': actual['run_directory'],
                'checked': checked, 'source': sources(), 'stage': stage, 'resource_sample': sample,
                'physical_feedback': compact_feedback(visible_feedback(actual))}
            save(slot/'point.json', record)
            return record

        observation = {'status': 'initial', 'read_source_paths': task['editable_paths']}
        try:
            for _ in range(plan['budget']['decisions']):
                try: check_utc_budget(packet)
                except TimeoutError: terminal = 'SEARCH_UTC_BUDGET_EXHAUSTED'; break
                try: action = adapter.step(session, observation, current_sources=sources())
                except Exception as error:
                    # Only the independently recorded same-checkpoint generation
                    # failure can retain a known model-failure denominator. An
                    # absent response, OOM or transport failure pauses selection.
                    number = len(session['history'])-1
                    response_file = Path(session['output'])/('decision_%03d'%number)/'response.json'
                    if number >= 0 and response_file.is_file() and response_file.stat().st_size:
                        response = read(response_file)
                        if validate_model_response(response, digest, method, seed, checkpoint):
                            gateway.append({'status': 'MODEL_RESPONSE_FAILURE', 'error': response['error']})
                            terminal = 'MODEL_RESPONSE_FAILURE'; break
                        invocation = read(response_file.parent/'invocation.json')
                        if invocation.get('utc_deadline_exceeded') is True:
                            gateway.append({'status': 'BUDGET_REJECTED', 'error': 'Actual UTC deadline exceeded before action execution'})
                            terminal = 'SEARCH_UTC_BUDGET_EXHAUSTED'; break
                    raise RuntimeError('Unknown checkpoint model/transport failure; no final point dispatch') from error
                number = len(session['history'])-1
                validate_model_response(read(Path(session['output'])/('decision_%03d'%number)/'response.json'),
                    digest, method, seed, checkpoint)
                event = {'action': action, 'status': 'APPLIED'}; gateway.append(event)
                try:
                    kind = action['action']
                    if kind == 'finish': terminal = 'FINISHED'; break
                    if kind == 'read_source': observation = {'path': action['path'], 'content': sources()[action['path']]}
                    elif kind == 'propose_patch':
                        patch_attempts += 1
                        if patch_attempts > plan['budget']['patches']: raise ValueError('Common patch budget exhausted')
                        apply_source_patch(source, action['patch'], task['editable_paths']); observation = {'patch_applied': True}
                    else:
                        if action['fidelity'] != 'pex_spice': raise ValueError('Validation uses the common full physical fidelity')
                        if len(action['configuration_ids'])+checks > plan['budget']['physical_evaluations']:
                            raise ValueError('Request exceeds the remaining common physical budget')
                        obtained = []
                        for name in action['configuration_ids']:
                            record = physical(name, 'search'); obtained.append(record); search_runs.append(record)
                        observation = {'actual_validation_feedback': [{'configuration_id': r['configuration_id'],
                            'checked': public_checked(r['checked']), 'physical_feedback': r['physical_feedback']} for r in obtained]}
                    event['observation'] = observation
                except TimeoutError as error:
                    event.update(status='ACTION_REJECTED', error=str(error)); terminal = 'SEARCH_UTC_BUDGET_EXHAUSTED'; break
                except (ValueError, subprocess.CalledProcessError) as error:
                    event.update(status='ACTION_REJECTED', error=type(error).__name__+': '+str(error)); terminal = 'MODEL_ACTION_FAILURE'; break
        except Exception as error:
            terminal = 'PAUSED_UNKNOWN_NO_AUTOMATIC_RETRY'
            save(work/'unknown.json', {'status': terminal, 'error': type(error).__name__+': '+str(error), 'hidden_calls': 0})
            raise
        finally:
            adapter.finish(session)
            save(work/'gateway.json', {'events': gateway, 'search_runs': search_runs, 'termination': terminal,
                'search_physical_attempts': checks, 'patch_attempts': patch_attempts, 'hidden_calls': 0})
        # Select source before its complete final validation measurements; final
        # scores never flow back to this or another checkpoint's editing session.
        final_sources = sources(); final = []
        save(work/'selected_sources.json', final_sources)
        for name in task['configuration_ids']:
            try: record = physical(name, 'final')
            except Exception as error:
                save(work/'final_unknown.json', {'status': 'PAUSED_UNKNOWN_NO_AUTOMATIC_RETRY',
                    'configuration_id': name, 'completed_points': len(final), 'error': type(error).__name__+': '+str(error)})
                raise
            final.append(record)
        task_records.append({'task_id': ident, 'session_json': str(Path(session['output'])/'session.json'),
            'gateway_events': gateway, 'final_sources': final_sources,
            'points': [{k: r[k] for k in ('task_id', 'configuration_id', 'run_directory')} for r in final]})
    return record_checkpoint(plan_path, checkpoint, method, seed, task_records, output/'editing_ledger.json')


def selection(entry, training, root, registry, plan_path, ledgers, output):
    """Only real saved editing+physical ledgers can create selection.json."""
    plan_path = Path(plan_path).resolve(); plan = read(plan_path); validate_plan(plan, plan_path)
    checkpoints = {str(Path(p).resolve()): p for p in training['checkpoints']}
    evaluations = []; seen = set(); scored = []
    for ledger_path in ledgers:
        raw = read(ledger_path); checkpoint = absolute(Path(ledger_path).parent, raw['checkpoint'])
        if str(checkpoint) not in checkpoints or str(checkpoint) in seen: raise ValueError('Repeated/foreign checkpoint ledger')
        seen.add(str(checkpoint)); marker = checkpoint_files(checkpoint)
        ledger = validate_editing_ledger(ledger_path, plan, checkpoint, entry['method'], entry['seed'])
        if ledger.get('validation_plan_sha256') != file_digest(plan_path): raise ValueError('Editing ledger belongs to another validation plan')
        points = ledger['points']; expected = {(p['task_id'], p['configuration_id']) for p in plan['points']}
        if {(p['task_id'], p['configuration_id']) for p in points} != expected or len(points) != len(expected):
            raise ValueError('Every checkpoint needs the same entire final-source point plan')
        task_sources = {ident: task['final_sources'] for ident, task in ledger['tasks'].items()}
        per_task = {ident: [] for ident in task_sources}
        lookup = {(p['contract']['task_id'], p['configuration_id']): p for p in registry['configurations'] if p.get('split') == 'validation'}
        for row in points:
            run = absolute(Path(ledger_path).parent, row['run_directory'])
            checked = TrustedPhysicalStore._inspect_execution_run(run, lookup[row['task_id'], row['configuration_id']], task_sources[row['task_id']])
            per_task[row['task_id']].append(int(checked['S2']))
        score = sum((Fraction(sum(values), len(values)) for values in per_task.values()), Fraction())/len(per_task)
        scored.append((score, -marker['updates'], str(checkpoint)))
        evaluations.append({'checkpoint': str(checkpoint), 'adapter_sha256': ledger['adapter_sha256'],
            'editing_ledger': str(Path(ledger_path).resolve()), 'task_sources': task_sources, 'points': points,
            'mean_task_S2_fraction': float(score)})
    if seen != set(checkpoints): raise ValueError('Missing/unknown checkpoint validation is not a negative score or an exclusion')
    best = max(scored); result = {'status': 'COMPLETED_E4_VALIDATION_CHECKPOINT_SELECTION',
        'method': entry['method'], 'seed': entry['seed'], 'validation_plan_sha256': file_digest(plan_path),
        'selected_checkpoint': best[2], 'checkpoint_evaluations': evaluations,
        'selection_rule': SELECTION_RULE, 'uninformative_equal_scores': len({s[0] for s in scored}) == 1,
        'model_or_EDA_calls_during_finalization': 0}
    # Invoke the existing gate unchanged on a temporary complete selection first.
    output = Path(output).resolve(); save(output, result)
    try:
        validate_selection({**entry, 'validation_selection': str(output), 'selected_checkpoint': best[2]},
            training, root, registry, plan, plan_path)
    except Exception:
        # Keep the rejected artifact, explicitly without a completed status.
        failed = {**result, 'status': 'REJECTED_E4_VALIDATION_SELECTION_NOT_ADMITTED'}
        output.write_text(json.dumps(failed, indent=2, allow_nan=False)+'\n')
        raise
    output.chmod(0o444)
    return result
