#!/usr/bin/env python3
"""Freeze a fresh matched360 scope cohort after real bounded qualification."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1];sys.path.insert(0, str(ROOT))
from scripts import e1_matched_runner as original
from scripts.freeze_e1 import mechanical_controls, rebase
from scripts.prepare_e1_scope_cohort import BUDGET, COHORT, packet, read, save
from scripts.e1_scope_runner import bad_patch_error
from src.candidate_executor import apply_source_patch
from src.domain_runner import source_contents

OWN = ['scripts/prepare_e1_scope_cohort.py', 'scripts/e1_scope_runner.py',
    'scripts/e1_scope_history_preflight.py', 'scripts/e1_scope_pilot.py', 'scripts/e1_scope_proposal_preflight.py',
    'scripts/freeze_e1_scope_cohort.py', 'scripts/run_e1_scope_suite.py', 'scripts/analyze_e1_scope.py', 'scripts/freeze_e1.py',
    'configs/development/e1_scope_candidate_error_classification.patch']


def digest(filename):return hashlib.sha256(Path(filename).read_bytes()).hexdigest()


def runtime_bindings(out, state, required_code):
    if set(state.get('execution_implementation_sha256', {})) != required_code:
        raise ValueError('The actual pre-inference backend source snapshot is incomplete')
    changes = []
    for name, expected in state['execution_implementation_sha256'].items():
        snapshot = out/'private/execution_implementation'/name
        if digest(snapshot) != expected:raise ValueError('The actual pre-inference source snapshot changed')
        current = ROOT/name
        if digest(current) == expected:continue
        if name != 'scripts/e1_scope_runner.py':raise ValueError('Unapproved runtime change since pilot: '+name)
        amendment = ROOT/'configs/development/e1_scope_candidate_error_classification.patch'
        with tempfile.TemporaryDirectory(prefix='scope_classifier_amendment_') as temporary:
            source = Path(temporary);destination = source/name;destination.parent.mkdir(parents=True)
            shutil.copyfile(snapshot, destination)
            apply_source_patch(source, amendment.read_text(), [name])
            if destination.read_bytes() != current.read_bytes():
                raise ValueError('The current runner differs outside the exact committed candidate-error amendment')
        changes.append({'file': name, 'actual_pilot_sha256': expected, 'prospective_sha256': digest(current),
            'exact_committed_patch': str(amendment), 'raw_pilot_status_rewritten': False})
    return changes


def unchanged_physical_inputs(packets, old_packets, manifest, proposal):
    """Only the documented packet edits and private path relocation may differ."""
    packets, old_packets = Path(packets), Path(old_packets)
    before = {p.relative_to(old_packets) for p in old_packets.rglob('*') if p.is_file()}
    after = {p.relative_to(packets) for p in packets.rglob('*') if p.is_file()}
    if before != after:raise ValueError('The source/reference/library file set changed')
    tasks = set(manifest['task_ids'])
    for relative in sorted(before):
        old_file, new_file = old_packets/relative, packets/relative
        if relative.parts[0] == 'private' and relative.suffix == '.json':
            expected = rebase(read(old_file), old_packets, packets)
            if len(relative.parts) == 3 and relative.parts[1] in tasks and relative.name == 'task.json':
                expected.update(status='DRAFT_E1_SCOPE_TASK', formal_admission=False, cohort_id=COHORT)
            if read(new_file) != expected:raise ValueError('Private source/domain/reference binding changed: '+str(relative))
        elif len(relative.parts) == 3 and relative.parts[0] == 'public' and relative.parts[1] in tasks and relative.stem in manifest['methods']:
            if read(new_file) != packet(read(old_file), relative.stem, proposal):raise ValueError('Matched packet changed outside the declared proposal')
        elif relative == Path('public/catalog.json'):
            expected = read(old_file);expected.update(status='DRAFT_E1_SCOPE_TASK_CATALOG', formal_admission=False, cohort_id=COHORT)
            if read(new_file) != expected:raise ValueError('The task/stratum catalog changed')
        elif new_file.read_bytes() != old_file.read_bytes():
            raise ValueError('Immutable physical/source bytes changed: '+str(relative))


def inspect_pilot(directory, manifest):
    directory = Path(directory);summary = read(directory/'summary.json')
    if summary['cohort_id'] != COHORT or summary['status'] != 'FINITE_PILOT_RETURNED' or len(summary['jobs']) != 3:
        raise ValueError('The fixed fresh three-method interface pilot is not complete')
    if {row['method'] for row in summary['jobs']} != {'G0', 'G1', 'G2'}:raise ValueError('All three interfaces must be qualified')
    with tarfile.open(directory/'pre_dispatch_deploy_v2.tar.gz', 'r:gz') as archive:
        if archive.extractfile('scripts/e1_scope_pilot.py').read() != (ROOT/'scripts/e1_scope_pilot.py').read_bytes():
            raise ValueError('The finite actual pilot controller changed')
        if json.loads(archive.extractfile('runtime/e1_packet_scope_cohort_scope_v2_16k.json').read()) != read(manifest['scope_proposal']):
            raise ValueError('The actual pre-dispatch proposal/schema differs')
    proofs = [];sessions = set();episodes = set()
    for row in summary['jobs']:
        out = Path(row['episode_directory']);state = read(out/'private/state.json');task = read(out/'private/task.json')
        raw = directory/'policy'/row['method'];session = read(raw/'session.json');packet = read(out/'private/packet.json')
        required_code = set(read(manifest['prior_interface_manifest'])['implementation_sha256'])|{
            'scripts/e1_scope_runner.py', 'scripts/prepare_e1_scope_cohort.py', 'scripts/e1_scope_proposal_preflight.py'}
        changes = runtime_bindings(out, state, required_code)
        if (row['returncode'] != 0 or state.get('cohort_id') != COHORT or state.get('formal_trial') is not False
                or state.get('interface_pilot') is not True or state['hidden_started'] is not False
                or state['selection_calls'] not in (0, 1) or state['costs_by_stage']['hidden']['physical_calls'] != 0
                or state['costs_by_stage']['post_freeze_diagnostic']['physical_calls'] != 0
                or not state['sealed'] or state.get('in_flight_point')):
            raise ValueError('A bounded pilot must retain its actual zero/one visible call and no hidden/post-freeze work')
        if read(out/'private/freeze_manifest.json') != manifest or session['packet'] != packet:
            raise ValueError('The actual pilot used another task packet or prospective freeze')
        expected_packet = read(Path(manifest['packet_root'])/'public'/task['task_id']/(row['method']+'.json'))
        expected_packet['budget'] = {**BUDGET, 'deadline_utc': packet['budget']['deadline_utc'], 'decisions': 2, 'physical_evaluations': 1}
        if (packet != expected_packet or task != read(Path(manifest['packet_root'])/'private'/task['task_id']/'task.json')
                or state['method'] != row['method'] or state['task_id'] != task['task_id']):
            raise ValueError('The actual policy did not receive this complete matched packet/task')
        expected_model = read(manifest['model_config']);expected_model['visible_history_policy'] = manifest['visible_history_policy']
        if session['config'] != expected_model or read(out/'private/model_config.json') != expected_model:
            raise ValueError('The actual model controller configuration differs')
        if (session['config']['model'] != 'gpt-6.1-sol' or session['config']['reasoning_effort'] != 'high'
                or session['config']['max_context_tokens'] != 16384 or session['config']['max_new_tokens'] != 1024
                or len(session['history']) > 2 or packet['budget']['decisions'] != 2 or packet['budget']['physical_evaluations'] != 1):
            raise ValueError('Actual model, context or finite pilot budget differs')
        decision_folder = raw/'decisions'/Path(session['output']).name
        files = sorted(decision_folder.glob('decision_*/invocation.json'));positive = [];invalid = None
        if len(files) != len(session['history']):raise ValueError('The full request/action history is incomplete')
        with tempfile.TemporaryDirectory(prefix='scope_pilot_source_replay_') as temporary:
            source = Path(temporary);(source/'generator.py').write_text(packet['visible_sources']['generator.py'])
            for index, invocation_path in enumerate(files):
                invocation = read(invocation_path);work = invocation_path.parent
                if type(invocation.get('pid')) is not int or invocation['pid'] <= 0:raise ValueError('No actual policy invocation')
                positive.append(str(invocation_path));request = read(work/'request.json');budget = read(work/'token_budget.json')
                if (invocation['status'] != 'COMPLETED' or invocation.get('returncode') != 0 or invocation.get('native_item_types') != []
                        or budget['fits_with_full_output_reserve'] is not True or budget.get('output_within_budget') is not True
                        or request['task_packet']['visible_sources'] != {'generator.py': (source/'generator.py').read_text()}
                        or request['task_packet']['budget'] != packet['budget']
                        or request['task_packet']['documents']['action_gateway']['read_source_paths'] != ['generator.py']):
                    raise ValueError('A pilot decision lacks a real valid bounded tool-disabled request and complete source')
                action = session['history'][index].get('action')
                if action is None or action != read(work/'action.json'):raise ValueError('No accepted raw policy action')
                if action != read(out/'private/actions'/('%03d.json' % (index+1))):raise ValueError('The backend did not receive this exact action')
                if action['action'] == 'propose_patch':
                    try:apply_source_patch(source, action['patch'], ['generator.py'])
                    except subprocess.CalledProcessError as error:
                        if not bad_patch_error(error) or index != len(files)-1:raise
                        invalid = {'failure_class': 'candidate_invalid_action', 'reason': 'candidate_bad_patch',
                            'actual_returncode': error.returncode, 'same_raw_patch_check_stderr': error.stderr,
                            'patch_modified': False, 'candidate_code_executed': False, 'physical_calls': 0}
                        if (state['status'] != 'INCOMPLETE_UNKNOWN' or not changes or
                                'exit status 128' not in read(raw/'backend_error.json')['error']):
                            raise ValueError('The historical bad-patch classification chain is not preserved')
                elif action['action'] == 'request_evaluation' and len(action['configuration_ids']) > packet['budget']['physical_evaluations']:
                    if (index != len(files)-1 or read(raw/'latest_observation.json').get('error') !=
                            'ValueError: Request exceeds remaining point budget'):
                        raise ValueError('The over-budget action lacks its real gateway rejection')
                    invalid = {'failure_class': 'candidate_invalid_action', 'reason': 'exceeds_visible_point_budget',
                        'requested_configurations': action['configuration_ids'], 'visible_physical_limit': packet['budget']['physical_evaluations'],
                        'physical_calls': 0}
            if (out/'private/sealed_generator.py').read_text() != (source/'generator.py').read_text():
                raise ValueError('Sealed source differs from the actual successful patches')
        if not 1 <= len(positive) <= 2:raise ValueError('The pilot requires one or two actual CLI invocations')
        if session['session_id'] in sessions or str(out) in episodes:raise ValueError('The three pilots must be fresh independent sessions')
        sessions.add(session['session_id']);episodes.add(str(out))
        events = state['events'];checked = None;run = None
        if events:
            if len(events) != 1 or events[0]['stage'] != 'search' or events[0]['fidelity'] != 'pex_spice':
                raise ValueError('A real pilot point must request full visible fidelity')
            event = events[0];point = next(p for p in task['configurations'] if p['configuration_id'] == event['configuration_id'])
            if point['role'] == 'hidden' or event.get('complete') is not True:raise ValueError('Unknown/hidden pilot work is not an interface pass')
            run = Path(event['run_directory']);execution = read(run/'manifest.json')
            expected = source_contents(run/'source', execution['source_files'], binary=True)
            if expected['generator.py'] != event['source_text'].encode() or read(run/'configuration.json')['parameters'] != point['parameters']:
                raise ValueError('Pilot execution does not bind the actual full source/configuration')
            result = {'run_directory': str(run), 'status': execution['status'],
                'physical_result': read(run/'evidence/validation.json') if (run/'evidence/validation.json').is_file() else None}
            checked = original.Backend(out).inspect(result, point, expected, read(run/'configuration.json'), 'pex_spice')
            if checked['execution_integrity'] != 'valid' or checked['failure_class'] not in (None, 'candidate'):
                raise ValueError('The real trusted physical boundary did not return a classifiable visible result')
        elif invalid is None or state['selection_calls'] != 0:
            raise ValueError('A zero-point pilot requires a verified candidate-invalid terminal action')
        proofs.append({'method': row['method'], 'episode_directory': str(out), 'run_directory': str(run) if run else None,
            'raw_directory': str(raw), 'actual_model_invocations': positive, 'checked': checked,
            'actual_raw_status': state['status'], 'derived_terminal_action': invalid, 'runtime_amendment': changes,
            'hidden_calls': 0, 'interpretation': 'Finite actual interface control; policy failure is retained. Existing independent physical controls establish the unchanged physical flow, not this policy sample.'})
    return proofs


def freeze(manifest_path, preflight_path, pilot_directory, prior_state_path, source_index_path, output, check_only=False):
    manifest = read(manifest_path);prior_path = Path(manifest['prior_interface_manifest']);prior = read(prior_path)
    if (manifest['status'] != 'DRAFT_E1_RUNNER' or manifest['formal_dispatch'] is not False or
            manifest['cohort_id'] != COHORT or manifest['budget'] != BUDGET):raise ValueError('Freeze the new unrun16k cohort only')
    old_state = read(prior_state_path)
    if (len(old_state['jobs']) != 360 or any(row['status'] in ('RUNNING', 'DISPATCH_RESERVED') for row in old_state['jobs'])
            or old_state.get('coordinator_pid') is not None):raise ValueError('Retain and drain the old partial360 matrix before the new cohort')
    for key in ('methods', 'trials', 'task_ids', 'runtime', 'visible_history_policy'):
        if manifest[key] != prior[key]:raise ValueError('Unapproved comparison change: '+key)
    expected_model = read(prior['model_config'])
    expected_model.update(status='DRAFT_E1_SCOPE_POLICY', max_context_tokens=16384, max_new_tokens=1024)
    if read(manifest['model_config']) != expected_model:raise ValueError('The actual model/decoding/tool configuration changed')
    packets = Path(manifest['packet_root']);old_packets = Path(prior['packet_root']);proposal = read(manifest['scope_proposal'])
    unchanged_physical_inputs(packets, old_packets, manifest, proposal)
    preflight = read(preflight_path)
    if (preflight['cohort_id'] != COHORT or Path(preflight['packet_root']).resolve() != packets.resolve() or
            preflight['packets'] != 72 or not preflight['all_initial_fit'] or not preflight['all_three_real_payloads_fit']
            or preflight['context_limit'] != 16384 or preflight['output_reserve'] != 1024 or preflight['source_or_history_truncated'] is not False):
        raise ValueError('Actual complete initial and real-payload history capacity preflight is required')
    pilot = inspect_pilot(pilot_directory, manifest)
    # Reuse actual full-flow controls only after inspecting their raw reports
    # against the unchanged new task references/evaluator bytes. No new EDA.
    controls = read(prior_path.parent/'mechanical_controls.json');catalog = read(packets/'public/catalog.json')
    with tempfile.TemporaryDirectory(prefix='scope_mechanical_reinspection_') as temporary:
        filename = Path(temporary)/'controls.json'
        save(filename, {'episodes': [original.Backend(row['episode_directory']).summary() for row in controls]})
        mechanical = mechanical_controls([filename], catalog, packets)
    feasibility = read(prior_path.parent/'circuit_feasibility.json')
    if feasibility['status'] != 'COMPLETE' or feasibility['scope'] != 'schematic_only_not_S1_S2' or any(
            any(row[key] != 25 for key in ('declared_configurations', 'complete_configurations', 'meet_specifications')) for row in feasibility['targets']):
        raise ValueError('The unchanged circuit domains lack their original complete independent feasibility control')
    index = read(source_index_path);required = sorted(set(prior['implementation_sha256'])|set(OWN))
    if not re.fullmatch('[0-9a-f]{40}', index['revision']):raise ValueError('Bind actual full committed source revision')
    for name in required:
        if digest(ROOT/name) != index['files_sha256'].get(name):raise ValueError('Committed live source differs: '+name)
        if name in prior['implementation_sha256'] and digest(ROOT/name) != prior['implementation_sha256'][name]:
            raise ValueError('The old E1 implementation must remain unchanged: '+name)
    registry = read(ROOT/'data/splits/registry.json');assignments = {row['lineage_id']: row['split'] for row in registry['lineages']}
    if any(assignments.get(read(packets/'private'/ident/'task.json')['target_logic_id']) != 'test' for ident in manifest['task_ids']):
        raise ValueError('The prospective tasks lost their existing evaluation-only source assignment')
    if check_only:return {'status': 'READY_FOR_E1_SCOPE_FREEZE', 'cohort_id': COHORT, 'fresh_episodes': 360, 'new_model_calls': 0, 'new_physical_calls': 0}
    output = Path(output).resolve()
    if output.exists():raise ValueError('Never overwrite an independent protocol freeze')
    output.mkdir(parents=True, mode=0o700);new_packets = output/'packets';shutil.copytree(packets, new_packets)
    for filename in (new_packets/'private').rglob('*.json'):
        filename.chmod(0o644);save(filename, rebase(read(filename), packets, new_packets))
    for ident in manifest['task_ids']:
        filename = new_packets/'private'/ident/'task.json';task = read(filename)
        task.update(status='FROZEN_E1_TASK', formal_admission=True);save(filename, task)
    catalog.update(status='FROZEN_E1_TASK_CATALOG', formal_admission=True)
    save(new_packets/'public/catalog.json', catalog)
    shutil.copytree(pilot_directory, output/'policy_interface_control')
    for proof in pilot:
        private = Path(proof['episode_directory'])/'private';snapshot = output/'pilot_backend_snapshots'/proof['method']
        shutil.copytree(private/'execution_implementation', snapshot/'execution_implementation')
        shutil.copytree(private/'actions', snapshot/'actions')
        for name in ('state.json', 'task.json', 'packet.json', 'model_config.json', 'sealed_generator.py'):
            shutil.copyfile(private/name, snapshot/name)
    for name, value in [('token_history_preflight', preflight), ('mechanical_controls', mechanical),
            ('circuit_feasibility', feasibility), ('pilot_reinspection', pilot), ('prior_partial_suite', old_state),
            ('committed_source_index', index)]:save(output/(name+'.json'), value)
    save(output/'scope_proposal.json', proposal);model = read(manifest['model_config'])
    model['status'] = 'FROZEN_E1_SCOPE_POLICY';save(output/'model_config.json', model)
    save(output/'registry.json', registry)  # no reassignment or replacement of concurrent E3/train freezes
    for name in required:
        destination = output/'implementation'/name;destination.parent.mkdir(parents=True, exist_ok=True);shutil.copyfile(ROOT/name, destination)
    frozen = {**copy.deepcopy(manifest), 'status': 'FROZEN_E1', 'formal_dispatch': True, 'phase': 'formal_E1',
        'freeze_id': output.name, 'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
        'packet_root': str(new_packets), 'task_catalog': str(new_packets/'public/catalog.json'),
        'backend_manifest_path': str(output/'manifest.json'), 'source_revision': index['revision'],
        'model_config': str(output/'model_config.json'), 'scope_proposal': str(output/'scope_proposal.json'),
        'frozen_registry': str(output/'registry.json'),
        'implementation_sha256': {name: index['files_sha256'][name] for name in required}, 'freeze_blockers': [],
        'prior_partial_matrix': str(output/'prior_partial_suite.json'),
        'qualification': {'mechanical': str(output/'mechanical_controls.json'), 'schematic': str(output/'circuit_feasibility.json'),
            'policy_interface': str(output/'pilot_reinspection.json'), 'capacity': str(output/'token_history_preflight.json')},
        'cohort_analysis_rule': 'Only this cohort-specific complete index enters its360 task-paired analysis. Old partial interface trials remain a separate matrix and research cost.'}
    save(output/'manifest.json', frozen)
    save(output/'freeze_identity.json', {'files_sha256': {str(p.relative_to(output)): digest(p) for p in sorted(output.rglob('*')) if p.is_file()}})
    for filename in sorted(output.rglob('*'), reverse=True):filename.chmod(0o555 if filename.is_dir() else 0o444)
    output.chmod(0o555)
    return {'status': 'FROZEN_E1', 'cohort_id': COHORT, 'manifest': str(output/'manifest.json'), 'fresh_episodes': 360,
        'new_model_calls': 0, 'new_physical_calls': 0}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest', 'preflight', 'pilot-directory', 'prior-suite-state', 'source-index', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--check-only', action='store_true');a = p.parse_args()
    print(json.dumps(freeze(a.manifest, a.preflight, a.pilot_directory, a.prior_suite_state, a.source_index, a.output, a.check_only)))
