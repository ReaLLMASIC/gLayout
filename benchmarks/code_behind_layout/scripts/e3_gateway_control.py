"""A fixed two-point engineering control of the actual C gateway, with no hidden calls."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.e3_episode import Gateway, initialize, project, read, save
from src.e3_risk_model import normalized_margin


def run(manifest_path, output):
    if output.exists():
        raise ValueError('Do not repeat a retained engineering control; reconcile its raw state')
    output.mkdir(parents=True)
    manifest = read(manifest_path)
    if manifest['status'] != 'DRAFT_E3_RUNNER' or manifest['formal_dispatch'] is not False:
        raise ValueError('This is an independent pre-freeze engineering control')
    task_id = 'draft_E3_stacked_switch_edit01'
    started = initialize({'manifest': str(manifest_path), 'task_id': task_id,
        'method': 'C', 'selection_seed': 41, 'trial_id': 'engineering_control', 'formal': False})
    save(output/'backend.json', {'episode_directory': started['episode_directory']})
    gateway = Gateway(started['episode_directory'])
    results = []
    for _ in range(2):
        current = gateway.current()
        ident = current['next_configuration']
        if ident is None:
            raise ValueError('C gateway did not select its next declared visible configuration')
        results.append(gateway.action({'action': 'request_evaluation', 'path': '', 'patch': '',
            'configuration_ids': [ident], 'fidelity': 'pex_spice',
            'summary': 'Fixed engineering integration control; no experimental model decision.'}))
        if results[-1]['checked']['execution_integrity'] != 'valid':
            gateway.seal('INCOMPLETE_UNKNOWN', {'model_cli_invocations': 0})
            save(output/'summary.json', {'status': 'INCOMPLETE_UNKNOWN', 'episode_directory': str(gateway.out),
                'new_model_calls': 0, 'hidden_calls': 0, 'observed_points': results})
            return read(output/'summary.json')
    value = gateway.state.value
    margins = {ident: normalized_margin(value['contracts_by_configuration'][ident], row['physical_feedback'])
        for ident, row in gateway.state.current()['results'].items()}
    predictions = gateway.predictions()
    next_point = gateway.next()
    search = gateway.seal('ENGINEERING_CONTROL_COMPLETE', {'model_cli_invocations': 0})
    report = {'status': 'COMPLETE', 'scope': 'Fixed actual C gateway engineering integration, not a tested-policy trial',
        'task_id': task_id, 'episode_directory': str(gateway.out), 'new_model_calls': 0,
        'new_physical_calls': len(value['physical_events']), 'hidden_calls': 0,
        'actual_visible_observations': results, 'actual_observed_continuous_margins': margins,
        'continuous_margin_available': any(v is not None for v in margins.values()),
        'predictor_output': predictions, 'next_configuration': next_point,
        'risk_model': manifest['risk_model'],
        'risk_model_sha256': hashlib.sha256(project(manifest['risk_model']).read_bytes()).hexdigest(),
        'risk_weights': manifest['risk_weights'], 'costs_by_stage': search['costs_by_stage'],
        'source_edits': 0, 'ordinary_policy_decisions': 0, 'formal_trials': 0,
        'private_raw_retained': True}
    save(output/'summary.json', report)
    print(json.dumps({key: report[key] for key in ('status', 'episode_directory', 'new_model_calls',
        'new_physical_calls', 'hidden_calls', 'continuous_margin_available', 'next_configuration')}), flush=True)
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    raise SystemExit(0 if run(a.manifest, a.output)['status'] == 'COMPLETE' else 2)
