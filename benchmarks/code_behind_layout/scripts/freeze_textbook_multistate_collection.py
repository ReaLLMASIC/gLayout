"""Freeze a declared multi-state textbook collection (E4 stage 2) from its frozen parent rule collection's capsule.

The parent's registry, label rule, trusted evaluator bundle, calibration and capsule preparation are copied byte for
byte (new freeze scope and label-rule version only); the declared states and rule proposer are bound; the collector is
scripts/collect_training_v2.py. Nothing in an earlier freeze is modified and nothing is launched.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts import collect_training as parent_collector
from scripts import collect_training_v2 as collector
from src.training import frozen_train_registry

PATH = 'textbook_sharing/layout.py'


def save(path, value): path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def freeze(preparation, refresh_trusted=False):
    declared = json.loads(preparation.read_text())
    if declared.get('status') != 'DRAFT_PROSPECTIVE_MULTISTATE_COLLECTION_NOT_FROZEN': raise ValueError('Freeze needs a declared multi-state draft')
    parent_path = Path(declared['parent_rule_collection']).resolve()
    parent, parent_registry, parent_states, _ = parent_collector.load(parent_path)
    if parent['sampling']['mode'] != 'train_collection_rules' or len(parent_states) != 1: raise ValueError('Parent must be a frozen single-state rule collection')
    original = (Path(parent['source_pack']) / PATH).read_text()
    states = [json.loads(line) for line in Path(declared['initial_states_path']).read_text().splitlines() if line.strip()]
    if len(states) != declared['initial_state_count'] or len(states) < 2: raise ValueError('Expected the declared complete states')
    if states[0]['base_source'] != {PATH: original}: raise ValueError('Fresh gold controls must be obtained from the unmodified original first')
    task_ids = {p['contract']['task_id'] for p in parent_registry['configurations'] if p['parent_lineage'] == states[0]['parent_lineage']}
    if len(task_ids) != 1: raise ValueError('Parent registry must bind one train task')
    task_id = next(iter(task_ids))
    for state in states:
        if list(state['base_source']) != [PATH] or state['origin'] not in ('natural', 'injected') or state['editable_paths'] != [PATH]: raise ValueError('Only the complete layout module is editable')
        if state['parent_lineage'] != states[0]['parent_lineage']: raise ValueError('One lineage per collection')
        state['task_id'] = task_id
    if declared['kind'].startswith('faults') and any(s['origin'] != 'injected' for s in states[1:]): raise ValueError('Fault states must be labelled injected')
    if declared['kind'] == 'lattice' and any(s['origin'] != 'natural' for s in states): raise ValueError('Lattice states are natural')
    collection_id = declared['collection_id']; output = ROOT / 'runtime/train_collections' / collection_id
    output.mkdir()
    trusted = output / 'trusted'; shutil.copytree(parent['trusted_bundle'], trusted)
    for path in trusted.rglob('*'): path.chmod(0o755 if path.is_dir() else 0o644)
    trusted.chmod(0o755)
    registry = json.loads(Path(parent['registry_path']).read_text())
    refreshed = None
    if refresh_trusted:
        # Rebuild the evaluator code of the bundle from the current sources (contracts and references stay byte-exact).
        shutil.copyfile(ROOT / 'scripts/corpus_textbook_collection_evaluator.py', trusted / 'evaluate.py')
        shutil.copyfile(ROOT / 'src/corpus_textbook_benches.py', trusted / 'textbook_physical.py')
        for path in (trusted / 'src').glob('*.py'):
            if path.name != '__init__.py': shutil.copyfile(ROOT / 'src' / path.name, path)
        refreshed = {str(q.relative_to(trusted)): hashlib.sha256(q.read_bytes()).hexdigest() for q in sorted(trusted.rglob('*')) if q.is_file()}
        files = {str(q.relative_to(trusted)): q.read_text() for q in sorted(trusted.rglob('*')) if q.is_file()}
        for point in registry['configurations']: point['trusted_evaluator_files'] = files
    registry.update(freeze_scope='unchanged_source_assignments_and_' + collection_id, frozen_at_utc=datetime.now(timezone.utc).isoformat(), main_benchmark_protocol_status='draft')
    frozen_train_registry(registry)
    labels = {**json.loads(Path(parent['label_rule_path']).read_text()), 'version': collection_id + '_area_v1', 'parent_label_rule_version': json.loads(Path(parent['label_rule_path']).read_text())['version']}
    initial = output / 'initial_states.jsonl'; initial.write_text(''.join(json.dumps(s, ensure_ascii=False) + '\n' for s in states))
    shutil.copyfile(declared['rule_proposer_path'], output / 'rule_proposer.py')
    rule_ids = list(declared['rule_ids'])
    sampling = {'mode': 'train_collection_rules', 'backend': 'frozen_rule_proposer', 'rule_ids': rule_ids, 'rule_proposer_path': str(output / 'rule_proposer.py'),
                'model': None, 'seed': None, 'max_new_tokens': 0, 'max_context_tokens': 8192, 'timeout_seconds': 5}
    save(output / 'registry.json', registry); save(output / 'label_rule.json', labels); save(output / 'preparation.json', declared)
    for name in ('capsule_preparation.json', 'calibration.json'):
        if (parent_path.parent / name).exists(): shutil.copyfile(parent_path.parent / name, output / name)
    workers = int(declared['physical']['workers'])
    manifest = {**parent, 'collection_id': collection_id, 'frozen_at_utc': registry['frozen_at_utc'], 'registry_path': str(output / 'registry.json'),
                'label_rule_path': str(output / 'label_rule.json'), 'trusted_bundle': str(trusted), 'initial_states_path': str(initial),
                'output_root': str(ROOT / 'runs/train_collection' / collection_id), 'evidence_root': str(ROOT / 'runs/train_collection' / collection_id),
                'sampling': sampling, 'physical': {**parent['physical'], 'workers': workers},
                'budget': {**parent['budget'], 'proposals_per_initial_state': len(rule_ids), 'initial_batch_initial_states': len(states)},
                'collector': 'scripts/collect_training_v2.py', 'parent_collection': str(parent_path), 'state_kind': declared['kind'],
                'teacher_kind': 'deterministic_rules' if rule_ids else 'none_baseline_only_for_separate_span_teacher_acceptance',
                'trusted_bundle_refreshed_from_current_sources': bool(refresh_trusted), 'trusted_bundle_file_sha256': refreshed,
                'admission': 'Fresh nine-point baseline per declared state (the unmodified original first, for gold controls) and fresh deterministic candidates under this frozen contract. Old outcomes are excluded. One compiler lineage.',
                'source_scope': 'Only layout.py is editable in these states; the enumeration module and every other source file remain byte-exact and frozen for each candidate.',
                'deduplication_scope': 'Within state; separately report unique final AST programs across states, circuits and proposal sources, and natural versus injected states.',
                'old_outcomes_relabelled': False}
    save(output / 'collection.json', manifest)
    names = ['collection.json', 'registry.json', 'label_rule.json', 'initial_states.jsonl', 'preparation.json', 'rule_proposer.py'] + [n for n in ('capsule_preparation.json', 'calibration.json') if (output / n).exists()]
    save(output / 'freeze_identity.json', {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in names})
    collector.load(output / 'collection.json')
    for path in sorted(output.rglob('*'), reverse=True): path.chmod(0o555 if path.is_dir() else 0o444)
    output.chmod(0o555)
    return {'collection': str(output / 'collection.json'), 'status': 'frozen', 'states': len(states), 'rules': len(rule_ids), 'workers': workers, 'launched': False}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--preparation', type=Path, required=True)
    p.add_argument('--refresh-trusted', action='store_true', help='rebuild the evaluator code of the trusted bundle from the current sources'); a = p.parse_args()
    print(json.dumps(freeze(a.preparation, a.refresh_trusted)))
