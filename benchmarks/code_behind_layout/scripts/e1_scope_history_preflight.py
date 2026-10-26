#!/usr/bin/env python3
"""Exact72 initial16k packets and explicitly repeated real feedback stress."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1];sys.path.insert(0, str(ROOT))
from scripts.e1_matched_runner import visible_feedback
from scripts.prepare_e1_scope_cohort import BUDGET, COHORT, read, save
from src.local_model_adapter import decision_prompt
from src.model_adapter import PACKET_FIELDS, prompt_token_budget
from src.policy_state import current_state_request


def preflight(manifest_path, tokenizer_path, output):
    from transformers import AutoTokenizer
    manifest = read(manifest_path)
    if manifest['cohort_id'] != COHORT or manifest['budget'] != BUDGET:raise ValueError('Wrong prospective cohort/budget')
    prior = read(manifest['prior_interface_manifest']);controls = read(Path(manifest['prior_interface_manifest']).parent/'mechanical_controls.json')
    actual = {}
    for row in controls:
        run = Path(row['run_directory']);raw = read(run/'evidence/validation.json')
        state = read(Path(row['episode_directory'])/'private/state.json')
        point = next(value for value in state['points'].values() if value['run_directory'] == str(run))
        actual[row['target']] = {'run_directory': str(run), 'feedback': visible_feedback({
            'status': read(run/'manifest.json')['status'], 'run_directory': str(run), 'physical_result': raw}),
            'checked': {key: point[key] for key in ('configuration_id', 'fidelity', 'complete', 'S0', 'S1', 'S2',
                'execution_integrity', 'failure_class', 'reason') if key in point}}
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, local_files_only=True, trust_remote_code=False)
    began = time.monotonic();results = [];packets = Path(manifest['packet_root'])
    for task_id in manifest['task_ids']:
        task = read(packets/'private'/task_id/'task.json');measured = actual[task['target']]
        for method in manifest['methods']:
            packet = read(packets/'public'/task_id/(method+'.json'))
            if (set(packet) != PACKET_FIELDS or packet['documents']['action_gateway']['read_source_paths'] != list(packet['visible_sources'])
                    or packet['documents']['cohort_id'] != COHORT):raise ValueError('Incomplete packet/source scope')
            packet['budget'] = {**BUDGET, 'deadline_utc': '2099-01-01T00:00:00.000000+00:00'}
            history = [{'observation': {'status': 'initial'}}];stress = []
            for count in range(BUDGET['physical_evaluations']+1):
                request = current_state_request(packet, history, packet['visible_sources'])
                budget = prompt_token_budget(tokenizer, decision_prompt(request), {'max_context_tokens': 16384, 'max_new_tokens': 1024})
                stress.append({'replayed_actual_payloads': count, **budget})
                history[-1]['action'] = {'action': 'request_evaluation', 'path': '', 'patch': '',
                    'configuration_ids': ['anchor'], 'fidelity': 'pex_spice',
                    'summary': 'Capacity replay only; no new model or physical event.'}
                history.append({'observation': {'anchor': {**measured['checked'], 'physical_feedback': measured['feedback']}}})
            results.append({'task_id': task_id, 'method': method, 'source_packet': str(packets/'public'/task_id/(method+'.json')),
                'measured_payload_origin': measured['run_directory'], 'initial': stress[0], 'stress': stress})
    report = {'status': 'COMPLETE_E1_SCOPE_CAPACITY_REPLAY', 'cohort_id': COHORT, 'manifest': str(manifest_path),
        'packet_root': str(packets), 'packets': len(results), 'context_limit': 16384, 'output_reserve': 1024,
        'all_initial_fit': len(results) == 72 and all(r['initial']['fits_with_full_output_reserve'] for r in results),
        'all_three_real_payloads_fit': len(results) == 72 and all(r['stress'][-1]['fits_with_full_output_reserve'] for r in results),
        'wall_seconds': time.monotonic()-began, 'source_or_history_truncated': False, 'results': results,
        'prior_circuit_qualification': prior['qualification'], 'new_model_calls': 0, 'new_physical_calls': 0,
        'scope': 'Initial packets plus repeated real same-target control feedback. Replays are capacity probes, not new observations or policy histories. Arbitrary future source growth remains subject to the live common limit.'}
    if Path(output).exists():raise ValueError('Keep previous actual capacity reports; write a new version')
    save(output, report);return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--tokenizer', type=Path, required=True);p.add_argument('--output', type=Path, required=True);a = p.parse_args()
    r = preflight(a.manifest, a.tokenizer, a.output)
    print(json.dumps({k: v for k, v in r.items() if k != 'results'}))
