#!/usr/bin/env python3
"""Offline token replay of a prospective E1 documentation-only proposal.

The source packets and frozen implementation are never written. This measures
initial context only and cannot replace a real policy-interface qualification.
"""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1];sys.path.insert(0, str(ROOT))
from src.local_model_adapter import decision_prompt


def read(filename):return json.loads(Path(filename).read_text())


def proposed_request(original, method, proposal):
    request = copy.deepcopy(original);docs = request['task_packet']['documents']
    docs['action_gateway'] = proposal['action_gateway']
    docs['candidate_runtime_configuration'] = proposal['candidate_runtime_configuration']
    if method != 'G0':docs['candidate_runtime_primitive_library'] = proposal['candidate_runtime_primitive_library_G1_G2']
    docs['intended_anchor_graph']['runtime'] = proposal['graph_runtime_replacements']['G0' if method == 'G0' else 'G1_G2']
    if {k: v for k, v in original['task_packet'].items() if k != 'documents'} != {
            k: v for k, v in request['task_packet'].items() if k != 'documents'}:
        raise ValueError('A documentation proposal changed actual source/contract/budget')
    return request


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proposal', type=Path, required=True);parser.add_argument('--output', type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--suite-state', type=Path);source.add_argument('--packet-root', type=Path)
    args = parser.parse_args()
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(ROOT/'runtime/policy_tokenizer', local_files_only=True, trust_remote_code=False)
    proposal = read(args.proposal);inputs = []
    if args.suite_state:
        for job in read(args.suite_state)['jobs']:
            if job['status'] != 'RECORDED':continue
            filename = next(Path(job['local_output_directory']).glob('decisions/*/decision_000/request.json'))
            inputs.append((filename, job['method'], read(filename)))
    else:
        for filename in sorted((args.packet_root/'public').glob('*/G*.json')):
            if filename.stem not in ('G0', 'G1', 'G2'):continue
            packet = read(filename)
            # Use the actual UTC-field shape, not a null placeholder, for fit.
            packet['budget']['deadline_utc'] = '2099-01-01T00:00:00.000000+00:00'
            inputs.append((filename, filename.stem, {'task_packet': packet, 'visible_history': [{'observation': {'status': 'initial'}}]}))
        if len(inputs) != 72:raise ValueError('Full prospective initial qualification requires all72 public packets')
    rows = []
    for filename, method, original in inputs:
        request = proposed_request(original, method, proposal)
        before = len(tokenizer(decision_prompt(original), add_special_tokens=False)['input_ids'])
        after = len(tokenizer(decision_prompt(request), add_special_tokens=False)['input_ids'])
        budget = request['task_packet']['budget'];reserve = budget['maximum_output_tokens'];limit = budget['maximum_context_tokens']
        rows.append({'task_id': request['task_packet']['task_id'], 'method': method, 'source': str(filename),
            'original_prompt_tokens': before, 'prospective_prompt_tokens': after, 'output_reserve': reserve,
            'context_limit': limit, 'fits': after+reserve <= limit})
    report = {'status': 'COMPLETE_OFFLINE_TOKEN_REPLAY_NOT_POLICY_CONTROL', 'proposal': str(args.proposal),
        'source': str(args.suite_state or args.packet_root), 'packets': len(rows), 'all_fit': all(r['fits'] for r in rows),
        'maximum_prompt_tokens': max(r['prospective_prompt_tokens'] for r in rows), 'rows': rows,
        'frozen_files_modified': False, 'new_model_calls': 0, 'new_physical_calls': 0,
        'scope': 'Complete source/PDK unchanged; documentation only in memory. Initial context replay is not whole-episode or real policy/physical qualification.'}
    args.output.parent.mkdir(parents=True, exist_ok=True);args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({key: report[key] for key in ('packets', 'all_fit', 'maximum_prompt_tokens', 'frozen_files_modified')}))
