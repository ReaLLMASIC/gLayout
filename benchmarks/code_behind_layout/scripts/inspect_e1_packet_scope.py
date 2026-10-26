#!/usr/bin/env python3
"""Read recorded E1 requests/actions to diagnose the observed manifest read trap."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):return json.loads(Path(path).read_text())


def inspect(state_path, output):
    suite = read(state_path);manifest = read(suite['manifest']);rows = []
    for job in suite['jobs']:
        if job['status'] != 'RECORDED':continue
        directory = Path(job['local_output_directory']);error = read(directory/'policy_error.json') if (directory/'policy_error.json').is_file() else None
        for request_path in sorted(directory.glob('decisions/*/decision_*/request.json')):
            packet = read(request_path)['task_packet'];docs = packet['documents']
            action_path = request_path.with_name('action.json')
            action = read(action_path) if action_path.is_file() else None
            graph = docs.get('intended_anchor_graph', {})
            interface = docs.get('primitive_interface', {})
            rows.append({'task_id': job['task_id'], 'method': job['method'], 'trial_id': str(job['trial_id']),
                'request': str(request_path), 'action_record': str(action_path), 'policy_error': error,
                'action': action, 'allowed_edit_paths': packet['allowed_paths'], 'visible_source_keys': list(packet['visible_sources']),
                'explicit_gateway_read_paths': docs.get('action_gateway', {}).get('read_source_paths'),
                'runtime_graph_description': graph.get('runtime'), 'API_description': docs.get('API'),
                'primitive_runtime_manifest': interface.get('manifest'), 'primitive_runtime_generation': interface.get('generation'),
                'CLI_description': docs.get('CLI'),
                'G0_manifest_availability_conflict': job['method'] == 'G0' and '/library/manifest.json' in graph.get('runtime', '')
                    and 'no PCell/GDS library' in docs.get('API', ''),
                'manifest_gateway_read_rejected': bool(action and action.get('action') == 'read_source'
                    and action.get('path') == '/library/manifest.json' and error
                    and 'Source read is outside the task packet' in error['error'])})
    pilots = []
    for path in sorted((ROOT/'runs/development/validation_policy').glob('*/*/decisions/*/session.json')):
        session = read(path);documents = session['packet']['documents'];history = session['history']
        pilots.append({'session': str(path), 'steps': len(history),
            'first_action': history[0].get('action') if history else None,
            'runtime_manifest_documented': 'manifest.json' in json.dumps(documents),
            'primitive_metadata_paths': {k: v for k, v in documents.get('primitive', {}).items() if k.startswith('read_only_')},
            'accepted_evaluation_actions': sum(h.get('action', {}).get('action') == 'request_evaluation' for h in history)})
    pinned = {}
    for name in ('src/e1_packets.py', 'src/model_adapter.py', 'src/local_model_adapter.py'):
        expected = manifest['implementation_sha256'].get(name)
        pinned[name] = {'expected_frozen_digest_present': expected is not None,
            'current_bytes_match_frozen_source': hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == expected}
    result = {'scope': 'Read-only diagnosis of actual frozen E1 interface failures; no reclassification or rerun',
        'generated_at_utc': datetime.now(timezone.utc).isoformat(), 'suite_snapshot': str(state_path),
        'suite_update_utc': suite['updated_at_utc'], 'frozen_manifest': suite['manifest'],
        'recorded_episodes': sum(j['status'] == 'RECORDED' for j in suite['jobs']), 'actual_requests_inspected': len(rows),
        'counts_by_method': dict(Counter(row['method'] for row in rows)),
        'rejected_manifest_reads': sum(row['manifest_gateway_read_rejected'] for row in rows),
        'requests_without_explicit_gateway_read_paths': sum(row['explicit_gateway_read_paths'] is None for row in rows),
        'G0_runtime_documentation_conflicts': sum(row['G0_manifest_availability_conflict'] for row in rows),
        'frozen_instruction_source_check': pinned, 'requests': rows, 'prior_development_pilots': pilots,
        'interpretation': 'The validator enforces visible_sources. The packets omit an explicit read_source scope; G1/G2 document a candidate-runtime manifest without a full named-record JSON schema, and G0 advertises that manifest while saying no library is mounted. These actual interface defects confound a representation-capability interpretation of the common first-action failures.',
        'prospective_change': ['Declare exact read_source_paths and distinguish candidate runtime file reads from policy gateway reads.',
            'Remove manifest availability from G0; supply complete common configuration.graph schema.',
            'For G1/G2 supply complete primitive-manifest/cell/terminal-access schema without adding hidden values or target assembly.',
            'Keep model/budgets/retry rule matched. Freeze a distinct packet version after bounded actual policy interface qualification; do not overwrite or silently repeat old trials.'],
        'original_analysis': 'Retain all old360 identities, raw outcomes/costs and NOT_RUN rows. This stopped/partial interface version cannot establish geometry-versus-PCell-versus-generator construction ability. A new qualified matched version must be reported separately.',
        'new_model_calls': 0, 'new_physical_calls': 0, 'E1_frozen_files_changed': False}
    output.parent.mkdir(parents=True, exist_ok=True);output.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps({k: result[k] for k in ('actual_requests_inspected', 'rejected_manifest_reads',
        'requests_without_explicit_gateway_read_paths', 'G0_runtime_documentation_conflicts', 'E1_frozen_files_changed')}))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__);parser.add_argument('--suite-state', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True);args = parser.parse_args();inspect(args.suite_state, args.output)
