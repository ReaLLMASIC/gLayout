"""Count complete E3 packets and explicit history-capacity stress replays.

Stress rows reuse real same-target development measurements. They are a token
capacity probe, not new physical observations, model decisions or an episode.
Actual engineering gateway controls are reported independently.
"""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.e3_episode import policy_packet, read
from scripts.e1_matched_runner import visible_feedback
from src.e3_feedback import compact, public_checked
from src.local_model_adapter import decision_prompt
from src.model_adapter import prompt_token_budget
from src.policy_state import current_state_request


def measured_feedback(row):
    if 'physical_feedback' in row:
        return row['physical_feedback']
    # Older exact engineering controls carry an independently inspected GDS
    # objective in the qualification record, while their raw electrical feedback
    # remains the original full measured report. Do not add fictitious metrics.
    run = Path(row['original_run'])
    return visible_feedback({'status': 'EVALUATED', 'run_directory': str(run),
        'physical_result': read(run/'evidence/validation.json')})


def preflight(manifest_path, evidence_path, tokenizer_path, output):
    from transformers import AutoTokenizer
    began = time.monotonic()
    manifest, evidence = read(manifest_path), read(evidence_path)
    preparation = ROOT/manifest['preparation']
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, local_files_only=True, trust_remote_code=False)
    actual = {row['task_id']: row for row in evidence['records']
        if row.get('adopted') is True or 'run_directory' in row}
    results = []
    for ident in manifest['task_ids']:
        original = read(preparation/'public'/ident/'packet.json')
        row = actual.get(ident)
        if row is None:
            raise ValueError('Actual initial feedback missing for '+ident)
        feedback = compact(measured_feedback(row))
        for method in manifest['methods']:
            packet = policy_packet(original, manifest, method, '2099-01-01T00:00:00.000000+00:00')
            history = [{'observation': {'status': 'initial'}}]
            counts = []
            for count in range(manifest['budget']['full_evaluations']+1):
                request = current_state_request(packet, history, packet['visible_sources'])
                budget = prompt_token_budget(tokenizer, decision_prompt(request),
                    {'max_context_tokens': manifest['budget']['maximum_context_tokens'], 'max_new_tokens': 1024})
                counts.append({'replayed_measured_feedback_rows': count, **budget})
                history[-1]['action'] = {'action': 'request_evaluation', 'path': '', 'patch': '',
                    'configuration_ids': ['anchor'], 'fidelity': 'pex_spice',
                    'summary': 'Capacity stress placeholder; no inference or physical call was made.'}
                history.append({'observation': {'configuration_id': 'anchor', 'revision': count,
                    'checked': public_checked(row['checked']), 'objective': row.get('objective'),
                    'episode_status': 'RUNNING', 'physical_feedback': feedback, 'next_configuration': 'dev_01'}})
            results.append({'task_id': ident, 'method': method,
                'actual_feedback_provenance': row.get('run_directory', row.get('original_run')),
                'initial': counts[0], 'maximum_stress_rows_fitting': max(
                    (r['replayed_measured_feedback_rows'] for r in counts if r['fits_with_full_output_reserve']), default=None),
                'stress': counts})
    report = {'scope': 'Exact initial E3 packets plus explicitly repeated actual-feedback capacity stress, NOT an actual episode history',
        'manifest': str(manifest_path), 'preparation': str(preparation), 'evidence': str(evidence_path),
        'tokenizer': str(tokenizer_path), 'states': len(manifest['task_ids']), 'method_packets': len(results),
        'all_initial_fit': all(r['initial']['fits_with_full_output_reserve'] for r in results),
        'all_declared_feedback_stress_rows_fit': all(r['stress'][-1]['fits_with_full_output_reserve'] for r in results),
        'minimum_stress_rows_fitting': min(r['maximum_stress_rows_fitting'] for r in results),
        'context_limit': manifest['budget']['maximum_context_tokens'], 'output_reserve': 1024,
        'wall_seconds': time.monotonic()-began, 'new_model_calls': 0, 'new_physical_calls': 0,
        'source_or_history_truncated': False,
        'limitations': 'This probes unchanged complete source plus real measured feedback payloads and action metadata. It does not assert that arbitrary edited source growth or all future action summaries fit. Live exhaustion is a common resource endpoint and preserves raw history.',
        'results': results}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'results'}), flush=True)
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--evidence', type=Path, required=True)
    p.add_argument('--tokenizer', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    raise SystemExit(0 if preflight(a.manifest, a.evidence, a.tokenizer, a.output)['all_initial_fit'] else 2)
