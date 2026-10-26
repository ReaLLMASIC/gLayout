"""Freeze a Claude literal-span teacher proposal collection over multi-state textbook parents (E4 stage 2); no model or EDA calls.

v2 of scripts/prepare_textbook_opus_span_collection.py. Differences: a parent collection may hold several initial
states (plan/order lattice variants or injected fault states), the states are selected by origin, the number of fresh
trials per context is declared (default 8), and every context's ordinary packet/history is the one its parent collection
actually produced from that state's own fresh nine-point baseline. The teacher request is the span-teacher mapping of
that ordinary request (src/train_span_proposer.teacher_request); token budgets are preflighted with the pinned tokenizer.

    runtime/training-venv/bin/python scripts/prepare_textbook_opus_span_collection_v2.py --parents c03_faults_v1 ... \
        --origins injected --trials 4 --collection-id textbook_claude_repair_v1
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from src.model_adapter import prompt_token_budget
from src.train_span_proposer import MODE, VERSION, teacher_request, mapping_proof, proposal_prompt
from src.train_span_opus_cli import BACKEND, MODEL, ROLE

TOKENIZER_FILES = ['tokenizer.json', 'tokenizer_config.json', 'vocab.json', 'merges.txt']


def read(p): return json.loads(Path(p).read_text())
def save(p, value): Path(p).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parents', nargs='+', required=True, help='frozen parent collection ids under runtime/train_collections')
    parser.add_argument('--origins', nargs='+', default=['natural', 'injected'], choices=['natural', 'injected'])
    parser.add_argument('--skip-first-state', action='store_true', help='leave out each parent\'s first (unmodified original) control state')
    parser.add_argument('--trials', type=int, default=8)
    parser.add_argument('--proposal-workers', type=int, default=2)
    parser.add_argument('--collection-id', required=True)
    parser.add_argument('--hours', type=float, default=12)
    args = parser.parse_args()
    if not 1 <= args.trials <= 8: raise ValueError('Declare between one and eight fresh trials per context')
    from transformers import AutoTokenizer
    snapshot = read(ROOT / 'configs/training/backbone_cache.json')['snapshot']
    tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True, trust_remote_code=False)
    if tokenizer.eos_token_id != 151645: raise ValueError('Unexpected pinned tokenizer EOS')
    output = ROOT / 'runtime/train_collection_proposals' / args.collection_id
    output.mkdir(parents=True, exist_ok=False)
    contexts = []; flights = []; skipped = []
    for parent_id in args.parents:
        parent_path = ROOT / 'runtime/train_collections' / parent_id / 'collection.json'
        manifest = read(parent_path)
        if manifest.get('status') != 'frozen': raise ValueError('Parent collection is not frozen: ' + parent_id)
        states = [json.loads(line) for line in Path(manifest['initial_states_path']).read_text().splitlines() if line.strip()]
        for index, state in enumerate(states):
            sid = state['initial_state_id']
            if state['origin'] not in args.origins or (args.skip_first_state and index == 0): skipped.append({'initial_state_id': sid, 'reason': 'origin or first-state filter'}); continue
            run_root = Path(manifest['output_root']) / sid
            if not (run_root / 'task_packet.json').is_file() or not (run_root / 'visible_history.json').is_file():
                skipped.append({'initial_state_id': sid, 'reason': 'parent has not produced its packet yet'}); continue
            ordinary = {'task_packet': read(run_root / 'task_packet.json'), 'visible_history': read(run_root / 'visible_history.json')}
            if ordinary['task_packet'].get('visible_sources', {}) != state['base_source']: raise ValueError('Packet visible sources differ from the frozen initial state: ' + sid)
            teacher = teacher_request(ordinary); mapping = mapping_proof(ordinary, teacher); mapping.pop('ordinary_request', None)
            flight = prompt_token_budget(tokenizer, proposal_prompt(teacher), {'max_context_tokens': 16384, 'max_new_tokens': 3072})
            if not flight['fits_with_full_output_reserve']: raise ValueError('Teacher context does not fit 16k with the 3072 reserve: ' + sid)
            folder = output / 'contexts' / sid; folder.mkdir(parents=True)
            values = {'original_request': ordinary, 'teacher_request': teacher, 'mapping_proof': mapping, 'initial_state': state,
                      'effective_registry': read(Path(manifest['output_root']) / 'effective_registry.json'), 'parent_collection': manifest,
                      'label_rule': read(manifest['label_rule_path'])}
            record = {'initial_state_id': sid, 'parent_collection_id': parent_id, 'parent_lineage': state['parent_lineage'], 'origin': state['origin'],
                      'circuit_id': manifest.get('preparation', {}).get('domain') or parent_id.split('_')[0].upper(), 'state_kind': manifest.get('state_kind', 'original'),
                      'parent_output_root': manifest['output_root'], 'parent_collection_path': str(parent_path)}
            for name, value in values.items():
                file = folder / (name + '.json'); save(file, value); record[name] = str(file.relative_to(output))
            contexts.append(record); flights.append({'initial_state_id': sid, **flight})
    if not contexts: raise ValueError('No context selected')
    trials = list(range(1, args.trials + 1))
    save(output / 'tokenizer_inventory.json', {'snapshot': snapshot, 'files_sha256': {name: sha(Path(snapshot) / name) for name in TOKENIZER_FILES}})
    save(output / 'teacher_context_preflight.json', flights); save(output / 'skipped_states.json', skipped)
    manifest = {'status': 'frozen', 'role': 'train_proposal_collection', 'collection_id': args.collection_id, 'teacher_interface_version': VERSION,
                'source_role': ROLE, 'contexts': contexts, 'planned_proposals': len(trials) * len(contexts), 'independent_contexts_added': len(contexts),
                'origins': sorted({c['origin'] for c in contexts}), 'parents': list(dict.fromkeys(args.parents)),
                'sampling': {'backend': BACKEND, 'model': MODEL, 'reasoning_effort': 'high', 'mode': MODE, 'trials': trials, 'seed': None,
                             'proposal_workers': args.proposal_workers, 'max_new_tokens': 3072, 'max_context_tokens': 16384, 'timeout_seconds': 240},
                'student_preselection': {'interface_version': 'ordinary_policy_action_context_v2', 'max_new_tokens': 1024, 'max_context_tokens': 16384, 'stage': 'before_physics'},
                'producer': 'src/train_span_opus_cli.py on the operator workstation (Claude CLI, tools disabled); proposals are copied back to runs/train_proposals/<collection_id>',
                'output_root': str(ROOT / 'runs/train_proposals' / args.collection_id), 'maximum_dispatch_hours': args.hours,
                'physical_runs_in_this_collection': 0, 'training_rows_in_this_collection': 0,
                'prepared_at_utc': datetime.now(timezone.utc).isoformat(), 'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
                'counting': 'One declared initial state per context (natural variant or injected fault, reported separately); all proposals may yield zero useful contexts.'}
    save(output / 'collection.json', manifest)
    save(output / 'freeze_identity.json', {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob('*')) if p.is_file()})
    for p in sorted(output.rglob('*'), key=lambda p: len(p.parts), reverse=True): p.chmod(0o555 if p.is_dir() else 0o444)
    output.chmod(0o555)
    print(json.dumps({'collection': str(output / 'collection.json'), 'contexts': len(contexts), 'skipped': len(skipped), 'trials': len(trials),
                      'planned_proposals': manifest['planned_proposals'], 'max_prompt_tokens': max(f['prompt_tokens'] for f in flights)}))


if __name__ == '__main__':
    main()
