"""Freeze a Claude literal-span teacher proposal collection for the textbook train domains (E4 stage 1); no model or EDA calls.

Each context is one frozen rule collection's single natural initial state (the original cropped compiler) together with
the ordinary task packet and visible history that collection actually produced from its fresh nine-point baseline
(runs/train_collection/<cid>_rules_v1/<state>/task_packet.json, visible_history.json). The teacher request is the span
teacher mapping of that ordinary request (src/train_span_proposer.teacher_request) and its student mapping proof is
recorded. Token budgets are preflighted with the pinned Qwen tokenizer. The bundle is written read-only with a
freeze identity so that the workstation-side collector (scripts/collect_textbook_opus_spans.py) and the server-side admission
(scripts/evaluate_textbook_opus_spans.py) can verify every byte.

    runtime/training-venv/bin/python scripts/prepare_textbook_opus_span_collection.py --domains C03 C13 ... --collection-id textbook_claude_span_v1
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
    parser.add_argument('--domains', nargs='+', required=True)
    parser.add_argument('--collection-id', required=True)
    parser.add_argument('--hours', type=float, default=4)
    args = parser.parse_args()
    from transformers import AutoTokenizer
    snapshot = read(ROOT / 'configs/training/backbone_cache.json')['snapshot']
    tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True, trust_remote_code=False)
    if tokenizer.eos_token_id != 151645: raise ValueError('Unexpected pinned tokenizer EOS')
    output = ROOT / 'runtime/train_collection_proposals' / args.collection_id
    output.mkdir(parents=True, exist_ok=False)
    contexts = []; flights = []
    for cid in args.domains:
        parent_id = cid.lower() + '_rules_v1'
        parent_path = ROOT / 'runtime/train_collections' / parent_id / 'collection.json'
        manifest = read(parent_path)
        if manifest.get('status') != 'frozen': raise ValueError('Parent rule collection is not frozen: ' + parent_id)
        states = [json.loads(line) for line in Path(manifest['initial_states_path']).read_text().splitlines() if line.strip()]
        if len(states) != 1: raise ValueError('Expected the single natural initial state of ' + parent_id)
        state = states[0]; sid = state['initial_state_id']
        run_root = Path(manifest['output_root']) / sid
        if not (run_root / 'task_packet.json').is_file() or not (run_root / 'visible_history.json').is_file():
            raise ValueError('Rule collection has not produced its ordinary packet yet: ' + str(run_root))
        ordinary = {'task_packet': read(run_root / 'task_packet.json'), 'visible_history': read(run_root / 'visible_history.json')}
        if ordinary['task_packet'].get('visible_sources', {}) != state['base_source']:
            raise ValueError('Packet visible sources differ from the frozen initial state: ' + sid)
        teacher = teacher_request(ordinary); mapping = mapping_proof(ordinary, teacher); mapping.pop('ordinary_request', None)
        flight = prompt_token_budget(tokenizer, proposal_prompt(teacher), {'max_context_tokens': 16384, 'max_new_tokens': 3072})
        folder = output / 'contexts' / sid; folder.mkdir(parents=True)
        values = {'original_request': ordinary, 'teacher_request': teacher, 'mapping_proof': mapping, 'initial_state': state,
                  'effective_registry': read(Path(manifest['output_root']) / 'effective_registry.json'), 'parent_collection': manifest,
                  'label_rule': read(manifest['label_rule_path'])}
        record = {'initial_state_id': sid, 'parent_collection_id': parent_id, 'parent_lineage': state['parent_lineage'], 'circuit_id': cid,
                  'parent_output_root': manifest['output_root'], 'parent_collection_path': str(parent_path)}
        for name, value in values.items():
            file = folder / (name + '.json'); save(file, value); record[name] = str(file.relative_to(output))
        contexts.append(record); flights.append({'initial_state_id': sid, **flight})
        if not flight['fits_with_full_output_reserve']: raise ValueError('Teacher context does not fit 16k with the 3072 reserve: ' + sid)
    save(output / 'tokenizer_inventory.json', {'snapshot': snapshot, 'files_sha256': {name: sha(Path(snapshot) / name) for name in TOKENIZER_FILES}})
    save(output / 'teacher_context_preflight.json', flights)
    manifest = {'status': 'frozen', 'role': 'train_proposal_collection', 'collection_id': args.collection_id, 'teacher_interface_version': VERSION,
                'source_role': ROLE, 'contexts': contexts, 'planned_proposals': 8 * len(contexts), 'independent_contexts_added': len(contexts),
                'sampling': {'backend': BACKEND, 'model': MODEL, 'reasoning_effort': 'high', 'mode': MODE, 'trials': list(range(1, 9)), 'seed': None,
                             'proposal_workers': 2, 'max_new_tokens': 3072, 'max_context_tokens': 16384, 'timeout_seconds': 240},
                'student_preselection': {'interface_version': 'ordinary_policy_action_context_v2', 'max_new_tokens': 1024, 'max_context_tokens': 16384, 'stage': 'before_physics'},
                'producer': 'src/train_span_opus_cli.py on the operator workstation (Claude CLI, tools disabled); proposals are copied back to runs/train_proposals/<collection_id>',
                'output_root': str(ROOT / 'runs/train_proposals' / args.collection_id), 'maximum_dispatch_hours': args.hours,
                'physical_runs_in_this_collection': 0, 'training_rows_in_this_collection': 0,
                'prepared_at_utc': datetime.now(timezone.utc).isoformat(), 'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
                'counting': 'One natural initial state per textbook domain (the original compiler); all proposals may yield zero useful contexts.'}
    save(output / 'collection.json', manifest)
    save(output / 'freeze_identity.json', {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob('*')) if p.is_file()})
    for p in sorted(output.rglob('*'), key=lambda p: len(p.parts), reverse=True): p.chmod(0o555 if p.is_dir() else 0o444)
    output.chmod(0o555)
    print(json.dumps({'collection': str(output / 'collection.json'), 'contexts': len(contexts), 'planned_proposals': 8 * len(contexts),
                      'preflight': [{k: f[k] for k in ('initial_state_id', 'prompt_tokens', 'fits_with_full_output_reserve')} for f in flights]}))


if __name__ == '__main__':
    main()
