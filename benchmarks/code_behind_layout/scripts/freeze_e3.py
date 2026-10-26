#!/usr/bin/env python3
"""Freeze E3 only after rereading its actual physical and implementation evidence."""
import argparse
from collections import Counter
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.e3_anchor_qualify import cache_control
from scripts.e3_generation_qualify import same_geometry
from scripts.e3_instance_episode import instance_settings, verify_cached
from scripts.e3_original_baseline import prepare, validate_task
from scripts.e3_parameter_binding_check import inspect as parameter_binding
from scripts.e3_parameter_episode import validate_baseline
from scripts.e3_physical_point import trusted
from scripts.e3_summarize_qualification import classify
from scripts.e3_task_prepare import capsule
from src.candidate_executor import IMAGE, PREFIX
from src.domain_runner import source_contents
from src.e3_risk_model import VisibleMarginDistanceRule, normalized_margin
from src.e3_dispatch import PARTS, identity as dispatch_identity, plan as dispatch_plan
from src.measurement import split_errors, validate_contract
from src.model_adapter import PACKET_FIELDS, validate_action

LIVE_IMPLEMENTATION = (
    'scripts/freeze_e3.py', 'scripts/e3_episode.py', 'scripts/e3_physical_point.py',
    'scripts/e3_trusted_objective.py', 'scripts/e3_task_prepare.py',
    'scripts/e3_parameter_episode.py', 'scripts/e3_instance_episode.py',
    'scripts/e3_original_baseline.py', 'scripts/archive_e3_evidence.py',
    'scripts/e3_anchor_qualify.py', 'scripts/e3_generation_qualify.py',
    'scripts/e3_parameter_binding_check.py', 'scripts/e3_summarize_qualification.py',
    'scripts/e3_gateway_control.py', 'scripts/e3_history_preflight.py',
    'scripts/run_e3_suite.py', 'scripts/release_e3_hidden.py', 'scripts/run_e3_evaluation.py',
    'src/e3_episode_state.py', 'src/e3_risk_model.py', 'src/e3_feedback.py',
    'src/e3_regression.py', 'src/e3_analysis.py', 'src/e3_parameters.py',
    'src/e3_task_prepare.py', 'src/regression_selector.py', 'src/e3_dispatch.py',
    'src/e3_policy_models.py', 'scripts/request_frozen_policy.py',
    'docs/e3_protocol.md')


def read(filename):
    return json.loads(Path(filename).read_text())


def save(filename, value):
    filename = Path(filename);filename.parent.mkdir(parents=True, exist_ok=True)
    filename.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def path(value):
    value = Path(value)
    return value if value.is_absolute() else ROOT/value


def digest(filename):
    return hashlib.sha256(Path(filename).read_bytes()).hexdigest()


def committed_implementation(index, e1):
    if not re.fullmatch('[0-9a-f]{40}', index['revision']):
        raise ValueError('The source index must identify the actual full committed local Git revision')
    required = sorted(set(LIVE_IMPLEMENTATION)|set(e1['implementation_sha256']))
    result = {}
    for name in required:
        if name not in index['files_sha256'] or digest(ROOT/name) != index['files_sha256'][name]:
            raise ValueError('Live source differs from the committed-source index: '+name)
        if name in e1['implementation_sha256'] and index['files_sha256'][name] != e1['implementation_sha256'][name]:
            raise ValueError('E3 cannot alter the actual frozen E1 dependency: '+name)
        result[name] = index['files_sha256'][name]
    return result


def same_electrical_domain(task, e1_task):
    """E3 may change its task identity/objective; N(z) and electrical limits stay."""
    validate_task(task)
    if task['target'] != e1_task['target'] or task['parent_lineage'] != e1_task['target_logic_id']:
        raise ValueError('Editing ancestry differs from the frozen E1 source logic')
    fields = ('configuration_id', 'role', 'parameters')
    ignored = {'task_id', 'configuration_id', 'reference_id', 'objective'}
    if len(e1_task['configurations']) != 25:
        raise ValueError('Frozen E1 source domain is incomplete')
    for before, after in zip(task['configurations'], e1_task['configurations']):
        if any(before[key] != after[key] for key in fields):
            raise ValueError('Editing task changed sizing, point order or visible/hidden role')
        if {k: v for k, v in before['contract'].items() if k not in ignored} != {
                k: v for k, v in after['contract'].items() if k not in ignored}:
            raise ValueError('Editing task changed an electrical specification, analysis, port or numeric option')
        if path(before['reference_file']).read_bytes() != path(after['reference_file']).read_bytes():
            raise ValueError('Editing task changed its independent per-configuration N(z)')
        validate_contract(before['contract'])


def actual_gpu_calibration(report, context):
    if (report.get('scope') != 'development_gpu_algorithm_calibration_not_E4' or report.get('status') != 'COMPLETED'
            or report.get('allocated_sequence_tokens') != context or context < 12288):
        raise ValueError('A completed actual same-context GPU algorithm calibration is required')
    backbone = read(ROOT/'configs/training/backbone_cache.json')
    recipe = report['recipe']
    if (Path(report['snapshot']).resolve() != path(backbone['snapshot']).resolve() or
            recipe['backbone'] != 'Qwen/Qwen2.5-Coder-32B-Instruct' or recipe['revision'] != backbone['revision'] or
            recipe['quantization'] != {'load_in_4bit': True, 'bnb_4bit_quant_type': 'nf4',
                'bnb_4bit_use_double_quant': True, 'compute_dtype': 'bfloat16'}):
        raise ValueError('GPU control used another base checkpoint, precision or quantization')
    sft = [s for s in report['stages'] if s['name'] == 'SFT_optimizer_update' and s.get('allocated_sequence_tokens') == context]
    dpo = [s for s in report['stages'] if s['name'] == 'DPO_'+str(context)+'_pair_optimizer_update']
    restore = [s for s in report['stages'] if s['name'] == 'actual_saved_adapter_optimizer_RNG_disk_restore']
    if not sft or len(dpo) != 1 or len(restore) != 1:
        raise ValueError('Actual near-full SFT, DPO and adapter/optimizer/RNG disk restore must all finish')
    for stage in [sft[-1], dpo[0]]:
        if (stage.get('prompt_tokens', 0) < context-256 or not math.isfinite(stage['loss']) or
                stage['wall_seconds'] <= 0 or stage['peak_allocated_bytes'] <= 0):
            raise ValueError('GPU control used padding/short context or lacks actual finite update/memory evidence')
    if dpo[0].get('frozen_reference_bitwise_unchanged') is not True or any(restore[0].get(key) is not True
            for key in ('adapter_bitwise_equal', 'optimizer_state_bitwise_equal', 'next_CPU_and_CUDA_RNG_equal')):
        raise ValueError('The fixed DPO reference or real checkpoint restore did not pass')
    gpu = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'],
        text=True, capture_output=True, check=True, timeout=12).stdout.strip().splitlines()
    if len(gpu) != 1 or 'H100' not in gpu[0]:
        raise ValueError('This actual calibration/freezing backend is not the declared single H100')
    return {'GPU_names': gpu, 'allocated_sequence_tokens': context, 'actual_updates': ['SFT', 'DPO'],
        'disk_restore_verified': True, 'formal_training_runs': 0}


def verify_generation(task_path, generated, temporary):
    import gdstk
    task = read(task_path);run = Path(generated['result']['run_directory']);manifest = read(run/'manifest.json')
    source = temporary/'source';capsule(task_path, source)
    expected = source_contents(source, task['source_files'], binary=True)
    if (source_contents(run/'source', manifest['source_files'], binary=True) != expected or
            read(run/'configuration.json') != {'parameters': task['configurations'][0]['parameters'], 'top_cell': task['top_cell']}):
        raise ValueError('Actual generation belongs to another complete source or sizing')
    if (manifest['fidelity'] != 'geometry' or manifest['status'] != 'EVALUATED' or
            any(manifest[stage]['container_state'].get('Running') is not False for stage in ('candidate', 'trusted')) or
            IMAGE not in manifest['candidate']['argv'] or IMAGE not in manifest['trusted']['argv'] or
            str((ROOT/'runtime/GLdev').resolve())+':'+PREFIX+':ro' not in manifest['candidate']['argv']):
        raise ValueError('Initial single-GDS generation lacks its actual stopped isolated execution')
    actual = run/'accepted/candidate.gds';library = gdstk.read_gds(actual)
    tops = [cell for cell in library.cells if cell.name == task['top_cell']]
    if len(tops) != 1 or tops[0].bounding_box() is None:
        raise ValueError('Actual generation has no unique complete contract top')
    bbox = tops[0].bounding_box();scale = library.unit/1e-6
    area = float((bbox[1][0]-bbox[0][0])*(bbox[1][1]-bbox[0][1]))*scale**2
    enriched = copy.deepcopy(generated);enriched['result']['physical_result']['area_um2'] = area
    return task, expected, enriched, actual


def validate_physical(preparation, generation, evidence, mechanical_summaries, temporary):
    generated = {row['task_id']: row for row in generation['records']}
    outcomes = {row['task_id']: row for row in evidence['records'] if row.get('adopted') is True or row.get('run_directory')}
    task_paths = sorted((preparation/'private').glob('*/task.json'))
    if len(task_paths) != 24 or set(generated) != {p.parent.name for p in task_paths} or set(outcomes) != set(generated):
        raise ValueError('Actual generation and anchor evidence must cover exactly the24 complete initial programs')
    controls = {}
    for summary in mechanical_summaries:
        for row in read(summary)['episodes']:
            control_task = read(Path(row['episode_directory'])/'private/task.json')
            if row['final_anchor']['complete'] and row['final_anchor']['S2']:
                controls[control_task['target']] = row
    rows, masks, tasks = {}, {}, {}
    for task_path in task_paths:
        ident = task_path.parent.name;folder = temporary/ident;folder.mkdir()
        task, source, generated_row, gds = verify_generation(task_path, generated[ident], folder)
        tasks[ident] = task;masks.setdefault(task['target'], []).append(gds)
        original = outcomes[ident]
        if original.get('adopted') is True:
            if task['target'] not in controls:
                raise ValueError('A cached E1 anchor has no actual matching engineering control')
            checked = cache_control(task_path, generated_row, controls[task['target']], folder/'adopted_audit')
            if checked['adopted'] is not True or checked['original_run'] != original['original_run']:
                raise ValueError('The two old E1 anchors must pass a fresh exact geometry/N/bench/intent audit')
            rows[ident] = checked
        else:
            evaluator = folder/'trusted';trusted(task, task['configurations'][0], evaluator)
            checked = verify_cached(original, source, task['configurations'][0], evaluator)
            if checked is None:
                raise ValueError('Actual initial point is unknown or its source/contract/trusted bytes differ: '+ident)
            rows[ident] = checked
    for target, artifacts in masks.items():
        if len(artifacts) != 3:
            raise ValueError('Every target has exactly three genuinely distinct initial programs')
        top = next(task['top_cell'] for task in tasks.values() if task['target'] == target)
        if any(same_geometry(a, b, top) for i, a in enumerate(artifacts) for b in artifacts[i+1:]):
            raise ValueError('Two editing states have the same actual all-layer filled geometry: '+target)
    witnesses = []
    for ident, task in tasks.items():
        baseline_id = 'draft_E3_'+task['target']+'_edit01'
        result = classify(rows[ident], rows[baseline_id], task['configurations'][0]['contract']['objective'])
        if task['ancestry']['injected_defect']:
            result['qualifies_shortfall'] = False
        witnesses.append({'task_id': ident, 'witness_task_id': baseline_id, **result})
    if sum(row['qualifies_shortfall'] for row in witnesses) < 12:
        raise ValueError('Fewer than12 actual non-injected failures/clean-poor states have a feasible same-circuit witness')
    return tasks, rows, witnesses


def verify_C_control(report, manifest, preparation, temporary):
    artifact = read(path(manifest['risk_model']));VisibleMarginDistanceRule(artifact)
    if (report['status'] != 'COMPLETE' or report['new_physical_calls'] != 2 or report['hidden_calls'] != 0 or
            report['source_edits'] != 0 or report['new_model_calls'] != 0 or
            report['risk_model_sha256'] != digest(path(manifest['risk_model'])) or report['risk_weights'] != manifest['risk_weights']):
        raise ValueError('An actual fixed two-point C integration control with the same rule/weights is required')
    private = Path(report['episode_directory'])/'private';state = read(private/'state.json');task = read(private/'task.json')
    current = read(preparation/'private'/task['task_id']/'task.json')
    if task != current or state['formal_trial'] is not False or state['method'] != 'C' or state['revision'] != 0:
        raise ValueError('C control must use the same unedited actual development task')
    results = []
    for index, event in enumerate(state['physical_events']):
        if event['status'] != 'RETURNED' or event['stage'] != 'search':
            raise ValueError('C control has an unresolved/non-visible physical call')
        point = next(p for p in task['configurations'] if p['configuration_id'] == event['configuration_id'])
        if point['role'] == 'hidden':
            raise ValueError('C calibration cannot use a hidden point')
        evaluator = temporary/('C_trusted_%02d' % index);trusted(task, point, evaluator)
        source = source_contents(private/'revisions/000/source', task['source_files'], binary=True)
        row = verify_cached(read(event['point_record']), source, point, evaluator)
        if row is None:
            raise ValueError('C actual raw source/physical/contract inspection failed')
        measured = read(Path(row['run_directory'])/'evidence/validation.json')['observation']
        margin = normalized_margin(point['contract'], measured)
        if report['actual_observed_continuous_margins'][point['configuration_id']] != margin:
            raise ValueError('Reported C margin contradicts actual raw corner measurements')
        results.append({'configuration_id': point['configuration_id'], 'actual_normalized_margin': margin,
            'run_directory': row['run_directory'], 'checked': row['checked']})
    if len(results) != 2 or not any(row['actual_normalized_margin'] is not None for row in results):
        raise ValueError('No actual continuous margin exists in the two-point C control')
    return results


def verify_policy_control(report, manifest, preparation, temporary):
    if (report['status'] != 'COMPLETE_POLICY_INTERFACE_CONTROL' or report['scope'] != 'development_only' or
            report['method'] != 'C' or report['maximum_decisions'] != 2 or report['actual_model_cli_invocations'] != 2 or
            report['hidden_calls'] != 0):
        raise ValueError('A fresh actual two-decision GPT interface control with no hidden calls is required')
    raw = path(report['raw_directory']);session = read(raw/'session.json')
    packet, config = session['packet'], session['config']
    if (packet['task_id'] != report['task_id'] or set(packet) != PACKET_FIELDS or len(session['history']) != 2 or
            config['model'] != 'gpt-6.1-sol' or config['reasoning_effort'] != 'high' or
            config['max_context_tokens'] != manifest['budget']['maximum_context_tokens'] or config['max_new_tokens'] != 1024 or
            packet['documents']['action_gateway']['read_source_paths'] != list(packet['visible_sources'])):
        raise ValueError('The real GPT control used another task/context/read-source interface')
    task = read(preparation/'private'/report['task_id']/'task.json')
    expected = {name: path(task['source_overrides'][name]).read_text() for name in task['editable_paths']}
    if packet['visible_sources'] != expected:
        raise ValueError('The GPT pilot did not receive the complete actual initial source')
    decisions = raw/'decisions'/Path(session['output']).name
    actions = []
    for number in range(2):
        folder = decisions/('decision_%03d' % number)
        invocation, budget = read(folder/'invocation.json'), read(folder/'token_budget.json')
        if (type(invocation.get('pid')) is not int or invocation['pid'] <= 0 or invocation['status'] != 'COMPLETED' or
                invocation.get('native_item_types') != [] or invocation.get('returncode') != 0 or
                invocation.get('requested_model') != 'gpt-6.1-sol' or budget['fits_with_full_output_reserve'] is not True or
                budget['output_within_budget'] is not True or budget['max_context_tokens'] != manifest['budget']['maximum_context_tokens'] or
                budget['output_reserve'] != 1024 or budget['source_or_history_truncated'] is not False or
                budget['completion_tokens_including_EOS'] > 1024 or budget['actual_total_tokens'] > budget['max_context_tokens']):
            raise ValueError('A real bounded tool-disabled GPT invocation did not complete')
        proposal = read(folder/'action.json');validate_action(proposal, packet)
        if session['history'][number].get('action') != proposal:
            raise ValueError('Pilot raw action differs from its actual visible-history record')
        request = read(folder/'request.json')
        if request['task_packet']['visible_sources'] != expected:
            raise ValueError('A pilot decision omitted the full current source')
        actions.append(proposal)
    evaluations = {a['configuration_ids'][0] for a in actions if a['action'] == 'request_evaluation'
        and len(a['configuration_ids']) == 1 and a['fidelity'] == 'pex_spice'}
    private = Path(report['episode_directory'])/'private';state = read(private/'state.json')
    if state['formal_trial'] is not False or read(private/'task.json') != task or state.get('post_freeze_started') is not False:
        raise ValueError('The pilot must be a fresh development search with no test-oracle use')
    accepted = []
    for i, event in enumerate(state['physical_events']):
        if event['configuration_id'] not in evaluations or event['status'] != 'RETURNED' or event['stage'] != 'search':
            continue
        point = next(p for p in task['configurations'] if p['configuration_id'] == event['configuration_id'])
        evaluator = temporary/('policy_trusted_%02d' % i);trusted(task, point, evaluator)
        source = source_contents(private/('revisions/%03d/source' % event['revision']), task['source_files'], binary=True)
        checked = verify_cached(read(event['point_record']), source, point, evaluator)
        if checked is not None and point['role'] != 'hidden':
            accepted.append({'configuration_id': point['configuration_id'], 'run_directory': checked['run_directory'],
                'checked': checked['checked']})
    if not accepted:
        raise ValueError('No real GPT request_evaluation reached an actual independently checked visible physical result')
    return {'actual_model_cli_invocations': 2, 'accepted_physical_feedback': accepted,
        'raw_directory': str(raw), 'episode_directory': report['episode_directory'], 'hidden_calls': 0}


def validate_dispatch(manifest, tasks):
    """Freeze actual consumers' matrices before any separate method is ready."""
    required = ['gpt', 'parameter', 'local', 'signals', 'fidelity']
    if (manifest['global_release_parts'] != required or manifest['global_release_requires_fidelity_freeze'] is not True):
        raise ValueError('Global release must cover all five declared search parts; I is an independent stream')
    if (manifest['signal_task_ids'] != manifest['parameter_task_ids'] or
            manifest['parameter_baseline']['strategies'] != ['random', 'gpt_feedback'] or
            manifest['instance_trials'] != 1):
        raise ValueError('Freeze the fixed P/random, P/GPT, signal and independent-instance comparison')
    expected_ablation = {
        'without_distance': {**manifest['risk_weights'], 'uncertainty': 0},
        'without_margin': {**manifest['risk_weights'], 'low_margin': 0}}
    if manifest['selector_ablation_weights'] != expected_ablation:
        raise ValueError('A signal ablation may disable only its named channel')
    selected = manifest['fidelity_task_ids']
    if (len(selected) != 2 or any(name not in tasks for name in selected) or
            {tasks[name]['target'] for name in selected} != {'five_t', 'compact_miller'} or
            any(not name.endswith('_edit02') for name in selected)):
        raise ValueError('F3 must retain the two prospectively chosen OTA edit02 states')
    expected_e4 = {'variants': ['T0', 'T1', 'T2', 'T3', 'T4'],
        'matched_evaluation_seed_slots': [41, 73, 109], 'inference_trials': 3,
        'T0_actual_model_count': 1, 'T0_independent_training_seeds': 0}
    if manifest['e4_evaluation'] != expected_e4:
        raise ValueError('Local policy slots must not be represented as independent T0 training seeds')
    for field in ('e4_methods_manifest', 'fidelity_manifest'):
        if not isinstance(manifest[field], str) or not manifest[field]:
            raise ValueError('Later model/fidelity freezes need explicit immutable destination paths')
    prospective = {**manifest, 'status': 'FROZEN_E3', 'formal_dispatch': True}
    expected_counts = dict(gpt=480, parameter=80, local=1080, signals=80, fidelity=10, instance=8)
    for part in PARTS:
        rows = dispatch_plan(prospective, part)
        if len(rows) != expected_counts[part] or len({dispatch_identity(row) for row in rows}) != len(rows):
            raise ValueError('Actual dispatch consumer changed the declared fixed '+part+' matrix')
    return expected_counts


def validate_metadata(manifest, preparation, tasks, p_binding, history, gpu, e1, index, registry):
    if (manifest['status'] != 'DRAFT_E3_RUNNER' or manifest['formal_dispatch'] is not False or
            manifest['methods'] != ['A', 'R', 'B', 'C'] or manifest['trials'] != 5 or e1['status'] != 'FROZEN_E1'):
        raise ValueError('Freeze the unrun24×4×5 E3 comparison against an actual frozen E1')
    if set(manifest['task_ids']) != set(tasks) or len(manifest['selection_seeds']) != 5 or len(set(manifest['selection_seeds'])) != 5:
        raise ValueError('The declared E3 task/trial/selection-seed matrix differs')
    if manifest['fidelity_policy'] != 'F0_actual_full_each_selected_configuration':
        raise ValueError('Main E3 selection comparison must use F0 actual full checks')
    budget = manifest['budget']
    if (set(budget) != {'wall_seconds', 'decisions', 'patches', 'full_evaluations', 'maximum_context_tokens', 'maximum_output_tokens'}
            or any(type(v) is not int or v <= 0 for v in budget.values()) or budget['maximum_output_tokens'] != 1024):
        raise ValueError('Explicit positive common E3 budgets and1024-token actions are required')
    model = read(path(manifest['model_config']))
    if (model['max_context_tokens'] != budget['maximum_context_tokens'] or model['max_new_tokens'] != 1024 or
            model['model'] != 'gpt-6.1-sol' or model['reasoning_effort'] != 'high'):
        raise ValueError('The actual model and common context/action budget differ')
    if (p_binding['status'] != 'COMPLETE' or p_binding['bound_states'] != 24 or
            path(p_binding['preparation']).resolve() != preparation):
        raise ValueError('Actual24 parameter initial-source bindings are required')
    for ident in tasks:
        if not parameter_binding(preparation/'private'/ident/'task.json')['source_bytes_identical']:
            raise ValueError('Actual P renderer no longer exactly represents the full initial source')
        packet = read(preparation/'public'/ident/'packet.json')
        if set(packet) != PACKET_FIELDS or packet['visible_sources'] != {
                name: path(tasks[ident]['source_overrides'][name]).read_text() for name in tasks[ident]['editable_paths']}:
            raise ValueError('The policy packet must contain its complete actual editable source')
    expected = {(ident, method) for ident in tasks for method in manifest['methods']}
    if (history['all_initial_fit'] is not True or path(history['preparation']).resolve() != preparation or
            history['context_limit'] != budget['maximum_context_tokens'] or history['output_reserve'] != 1024 or
            {(r['task_id'], r['method']) for r in history['results']} != expected or
            any(r['initial']['fits_with_full_output_reserve'] is not True for r in history['results']) or
            history['source_or_history_truncated'] is not False):
        raise ValueError('Complete actual96 initial E3 packets must fit with the common full output reserve')
    if any(manifest['risk_weights'].get(name, 0) != 0 for name in ('failure_probability', 'changed_call_coverage')):
        raise ValueError('Uncalibrated probability/coverage channels must remain disabled')
    validate_baseline(manifest, 'random');validate_baseline(manifest, 'gpt_feedback');instance_settings(manifest)
    if manifest['parameter_baseline']['configuration_selector'] != 'C':
        raise ValueError('Primary P and code C must share the same configuration selector')
    p_tasks, i_tasks = manifest['parameter_task_ids'], manifest['instance_task_ids']
    if (len(p_tasks) < 8 or len(p_tasks) != len(set(p_tasks)) or set(p_tasks) != set(i_tasks) or
            not set(p_tasks) <= set(tasks) or len({tasks[name]['target'] for name in p_tasks}) < 8):
        raise ValueError('Freeze at least8 common P/I/code tasks covering all8 target logics')
    order = read(path(manifest['instance_baseline']['arrival_order']))
    if not order or any(name not in {p['configuration_id'] for p in tasks[ident]['configurations']} for ident in i_tasks for name in order):
        raise ValueError('The frozen instance stream contains an undeclared configuration')
    if split_errors(registry):
        raise ValueError('Existing lineage/topology assignments are invalid')
    assignments = {row['lineage_id']: row['split'] for row in registry['lineages']}
    if any(assignments.get(task['parent_lineage']) != 'test' for task in tasks.values()):
        raise ValueError('E3 source logics must retain their test-only assignment')
    groups = Counter(task['logical_group'] for task in tasks.values())
    if len(groups) != 8 or set(groups.values()) != {3} or len({task['merge_sensitivity_group'] for task in tasks.values()}) != 7:
        raise ValueError('Report24 dependent programs from8 logics and the7-group sensitivity')
    validate_dispatch(manifest, tasks)
    identity = committed_implementation(index, e1)
    hardware = actual_gpu_calibration(gpu, budget['maximum_context_tokens'])
    return identity, hardware


def copy_task(preparation, output, task, e1_manifest):
    """Copy complete bytes while replacing external mutable path bindings."""
    ident = task['task_id'];folder = output/'packets/private'/ident;folder.mkdir(parents=True, exist_ok=True)
    result = copy.deepcopy(task)
    e1_path = path(e1_manifest['packet_root'])/'private'/Path(task['E1_binding']).parent.name/'task.json'
    e1_task = read(e1_path);same_electrical_domain(task, e1_task)
    base = output/'base'/task['target']
    if not base.exists():
        shutil.copytree(path(task['source_pack_base']), base, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    elif source_contents(base, task['source_files'], binary=True) != source_contents(path(task['source_pack_base']), task['source_files'], binary=True):
        raise ValueError('Same-target states unexpectedly bind different frozen dependency capsules')
    result['source_pack_base'] = str(base);result['E1_binding'] = str(e1_path)
    result['trusted_template'] = e1_task['trusted_template']
    for field, subfolder in (('source_overrides', 'source'), ('frozen_source_overrides', 'frozen_export')):
        result[field] = {}
        for relative, original in task[field].items():
            target = folder/subfolder/relative;target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path(original), target);result[field][relative] = str(target)
    original = folder/'original'/task['editable_paths'][0];original.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path(task['expanded_parameter_baseline']['immutable_original_module']), original)
    for field in ('parameter_baseline', 'expanded_parameter_baseline'):
        result[field]['immutable_original_module'] = str(original)
    pdk = output/'PDK'/('rules_'+task['target']+'.json');pdk.parent.mkdir(exist_ok=True)
    original_pdk = path(task['expanded_parameter_baseline']['frozen_PDK_rules'])
    if pdk.exists() and pdk.read_bytes() != original_pdk.read_bytes():
        raise ValueError('Same-target PDK rule documents differ')
    shutil.copyfile(original_pdk, pdk);result['expanded_parameter_baseline']['frozen_PDK_rules'] = str(pdk)
    for key in ('original_generator', 'patch'):
        original_path = path(task['export_transport'][key]);target = folder/'export_transport'/original_path.name
        target.parent.mkdir(exist_ok=True);shutil.copyfile(original_path, target);result['export_transport'][key] = str(target)
    ancestry = result['ancestry'];ancestry['base_module'] = str(base/task['editable_paths'][0])
    old_patch = path(task['ancestry']['initial_patch']);new_patch = folder/'initial_layout_variant.patch'
    shutil.copyfile(old_patch, new_patch);ancestry['initial_patch'] = str(new_patch)
    for point in result['configurations']:
        reference = folder/'references'/(point['configuration_id']+'.spice');reference.parent.mkdir(exist_ok=True)
        shutil.copyfile(path(point['reference_file']), reference);point['reference_file'] = str(reference)
    result.update(status='FROZEN_E3_TASK', formal_admission=True)
    save(folder/'task.json', result)
    public = output/'packets/public'/ident/'packet.json';public.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(preparation/'public'/ident/'packet.json', public)
    if public.read_bytes() != (preparation/'public'/ident/'packet.json').read_bytes():
        raise ValueError('Freezing must not rewrite a visible complete-source packet')
    return result


def freeze(manifest_path, generation_summary, anchor_evidence, witness_report, parameter_report, history_preflight,
           gpu_calibration, gateway_control, policy_control, e1_manifest, mechanical_summaries, registry_path,
           committed_source_index, output, check_only=False):
    manifest, e1, index = read(manifest_path), read(e1_manifest), read(committed_source_index)
    preparation = path(manifest['preparation']).resolve();registry = read(registry_path)
    generation, evidence, witness = read(generation_summary), read(anchor_evidence), read(witness_report)
    with tempfile.TemporaryDirectory(prefix='e3_freeze_raw_control_') as temporary:
        tasks, checked, witnessed = validate_physical(preparation, generation, evidence, mechanical_summaries, Path(temporary))
        computed = {row['task_id']: row['qualifies_shortfall'] for row in witnessed}
        if (witness['declared_states'] != 24 or {row['task_id']: row['qualifies_shortfall'] for row in witness['states']} != computed):
            raise ValueError('Supplied witness classification contradicts actual re-inspected initial/witness outcomes')
        identity, hardware = validate_metadata(manifest, preparation, tasks, read(parameter_report), read(history_preflight),
            read(gpu_calibration), e1, index, registry)
        C_rows = verify_C_control(read(gateway_control), manifest, preparation, Path(temporary))
        policy_rows = verify_policy_control(read(policy_control), manifest, preparation, Path(temporary))
    # Check the original electrical domain for every state, including all16
    # private points, before creating any freeze output.
    for task in tasks.values():
        bound = path(e1['packet_root'])/'private'/Path(task['E1_binding']).parent.name/'task.json'
        same_electrical_domain(task, read(bound))
    for filename in ('calibration_source.py', 'training_source.py'):
        if not (Path(gpu_calibration).parent/filename).is_file():
            raise ValueError('Actual GPU calibration must retain its executed source snapshot: '+filename)
    before = read(ROOT/'data/splits/registry.json')
    if registry['lineages'] != before['lineages'] or registry.get('formal_tasks', []) != before.get('formal_tasks', []):
        raise ValueError('E3 cannot replace any existing source assignment or frozen E1 task')
    additions = [{'task_id': task['task_id'], 'experiment': 'E3', 'split': 'test',
        'parent_lineage': task['parent_lineage']} for task in tasks.values()]
    if {r['task_id'] for r in additions} & {r['task_id'] for r in before.get('formal_tasks', [])}:
        raise ValueError('This editing matrix already has a formal registry assignment')
    if check_only:
        return {'status': 'READY_FOR_E3_FREEZE', 'tasks': 24, 'main_episodes': 480,
            'actual_non_injected_shortfalls': sum(computed.values()), 'new_physical_calls': 0, 'new_model_calls': 0}
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Never overwrite or resume a partial immutable protocol freeze')
    output.mkdir(parents=True, mode=0o700)
    save(output/'manifest.json', {'status': 'FREEZE_IN_PROGRESS', 'formal_dispatch': False})
    new_tasks = [copy_task(preparation, output, tasks[name], e1) for name in manifest['task_ids']]
    baseline = prepare(output/'packets', output/'original_baseline')
    implementation = output/'implementation'
    for name in identity:
        target = implementation/name;target.parent.mkdir(parents=True, exist_ok=True);shutil.copyfile(ROOT/name, target)
    save(output/'committed_source_index.json', index)
    qualification = output/'qualification';qualification.mkdir()
    reports = {'generation': generation_summary, 'anchor_evidence': anchor_evidence, 'witness': witness_report,
        'P24': parameter_report, 'history': history_preflight, 'GPU': gpu_calibration, 'C_gateway': gateway_control,
        'policy_interface': policy_control}
    for name, original in reports.items():
        shutil.copyfile(original, qualification/(name+'.json'))
    save(qualification/'raw_reinspection.json', {'anchors': checked, 'witnesses': witnessed, 'C_points': C_rows,
        'policy_interface': policy_rows,
        'hardware': hardware, 'new_physical_calls': 0, 'new_model_calls': 0})
    for filename in ('calibration_source.py', 'training_source.py'):
        original = Path(gpu_calibration).parent/filename
        shutil.copyfile(original, qualification/filename)
    shutil.copytree(path(read(policy_control)['raw_directory']), qualification/'policy_interface_raw')
    risk = read(path(manifest['risk_model']));risk.update(formal_C_ready=True,
        readiness_scope='Actual two-point visible-margin gateway control; transparent heuristic, not a calibrated failure-probability ensemble',
        actual_control=str(qualification/'C_gateway.json'))
    save(output/'risk_model.json', risk)
    model = read(path(manifest['model_config']));model.update(status='FROZEN_E3_POLICY', visible_history_policy='current_source_and_feedback_v1')
    save(output/'model_config.json', model)
    order = read(path(manifest['instance_baseline']['arrival_order']));save(output/'instance_arrival_order.json', order)
    if read(ROOT/'data/splits/registry.json') != before:
        raise ValueError('Registry changed during snapshot preparation; preserve this incomplete output and reconcile')
    save(output/'prior_global_registry.json', before)
    frozen_at = datetime.now(timezone.utc).isoformat()
    updated = copy.deepcopy(registry);updated['formal_tasks'] = before.get('formal_tasks', [])+additions
    updated.update(status='frozen', freeze_scope='E3_append_only_'+output.name, frozen_at_utc=frozen_at,
        main_benchmark_protocol_status='E1_E3_frozen_other_experiments_separate')
    save(output/'registry.json', updated)
    instance = copy.deepcopy(manifest['instance_baseline']);instance['arrival_order'] = str(output/'instance_arrival_order.json')
    frozen = {**manifest, 'status': 'FROZEN_E3', 'formal_dispatch': True, 'phase': 'formal_E3',
        'freeze_id': output.name, 'frozen_at_utc': frozen_at, 'backend_manifest_path': str(output/'manifest.json'),
        'preparation': str(output/'packets'), 'source_revision': index['revision'], 'implementation_sha256': identity,
        'model_config': str(output/'model_config.json'), 'risk_model': str(output/'risk_model.json'),
        'instance_baseline': instance, 'original_baseline_plan': str(output/'original_baseline/plan.json'),
        'hidden_release_file': str(ROOT/'runtime/evaluation_releases'/('E3_'+output.name+'.json')),
        'hidden_evaluation': 'Deferred until all declared searches and all method/model artifacts are sealed; private oracle released once',
        'frozen_registry': str(output/'registry.json'), 'E1_manifest': str(Path(e1_manifest).resolve()),
        'tasks': [{'task_id': task['task_id'], 'target': task['target'], 'source_group': task['logical_group'],
            'merged_source_group': task['merge_sensitivity_group'], 'parent_lineage': task['parent_lineage']} for task in new_tasks],
        'primary_source_groups': 8, 'merged_sensitivity_groups': 7, 'freeze_blockers': [],
        'qualification': str(qualification), 'original_baseline_declared_points': baseline['declared_points'],
        'analysis': {'primary_contrasts': ['C-R', 'C-B'], 'cluster_bootstrap_replicates': 2000,
            'bootstrap_seed': 20261019, 'group_units': [8, 7], 'baseline_regression': 'Private original-pass denominator join'},
        'GPT_sampling_seed': 'Unavailable; five fresh trial identities, not claimed provider random seeds'}
    save(output/'manifest.json', frozen)
    save(ROOT/'data/splits/registry.json', updated)
    for filename in sorted(output.rglob('*'), reverse=True):
        filename.chmod(0o555 if filename.is_dir() else 0o444)
    output.chmod(0o555)
    return {'status': 'FROZEN_E3', 'manifest': str(output/'manifest.json'), 'tasks': 24,
        'planned_main_episodes': 480, 'original_baseline_points': 600, 'new_physical_calls': 0, 'new_model_calls': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest', 'generation-summary', 'anchor-evidence', 'witness-report', 'parameter-binding',
                 'history-preflight', 'gpu-calibration', 'gateway-control', 'policy-control', 'e1-manifest', 'registry',
                 'committed-source-index', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--mechanical-summary', type=Path, action='append', required=True)
    parser.add_argument('--check-only', action='store_true');args = parser.parse_args()
    result = freeze(args.manifest, args.generation_summary, args.anchor_evidence, args.witness_report,
        args.parameter_binding, args.history_preflight, args.gpu_calibration, args.gateway_control, args.policy_control,
        args.e1_manifest, args.mechanical_summary, args.registry, args.committed_source_index,
        args.output, args.check_only)
    print(json.dumps(result), flush=True)
