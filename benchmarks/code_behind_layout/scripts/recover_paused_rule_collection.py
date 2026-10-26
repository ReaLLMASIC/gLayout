"""Recover a rule collection that paused on inadmissible (unknown) physical evidence, without touching its originals.

A collection pauses with PAUSED_ADMISSION_UNCERTAINTY when any candidate point produced evidence the independent
admission cannot label (for example a trusted evaluator that was killed by its inner simulation timeout while the host
was oversubscribed). The original run directories are never modified or deleted. This tool
  1. lists every rejected candidate and its non-evaluated points from candidates.jsonl and admission_rejections.json;
  2. with --rerun, executes exactly those points once more (same frozen source snapshot, same contract, same image,
     same trusted bundle, one at a time under the shared gate) into the collection's own physical/ root, recording the
     original failed evidence path beside the new one in recovery.json; points whose rerun fails again are left out;
  3. with --derive, re-admits the candidate pool with the recovered evidence paths through the unchanged
     TrustedPhysicalStore gate, drops any candidate that still lacks admissible evidence, and writes
     T1..T4_recovered.jsonl, yield_recovered.json and completion_recovered.json with the explicit exclusion list.
The frozen label rule and the collection's own collector snapshot are used; no label is invented for a failure.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts.train_collection_queue import resource_sample
from src.candidate_executor import CandidateExecutor
from src.training import TrustedPhysicalStore, admit_candidates, build_matched_samples


def read(p): return json.loads(Path(p).read_text())
def save(p, v): Path(p).write_text(json.dumps(v, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
def now(): return datetime.now(timezone.utc).isoformat()


def collector_module(output):
    spec = importlib.util.spec_from_file_location('recovery_collector_snapshot', output / 'collector_snapshot.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def failed_points(output, rows):
    """Candidate points whose evidence manifest did not evaluate (unknown, never a negative)."""
    failures = []
    for row in rows:
        for outcome in row['outcomes']:
            manifest = read(output / outcome['evidence_path'])
            if manifest.get('status') != 'EVALUATED':
                failures.append({'candidate_id': row['candidate_id'], 'configuration_id': outcome['configuration_id'], 'evidence_path': outcome['evidence_path'],
                                 'manifest_status': manifest.get('status'), 'trusted_status': (manifest.get('trusted') or {}).get('status'),
                                 'candidate_status': (manifest.get('candidate') or {}).get('status')})
    return failures


def gate(max_containers):
    while True:
        resources = resource_sample(); containers = subprocess.run(['docker', 'ps', '-q'], capture_output=True, text=True).stdout.count('\n')
        if containers + 1 <= max_containers and resources['actual_busy_cores'] + 2 <= 24 and resources['RAM_used_GiB'] <= 190: return {**resources, 'running_containers': containers}
        time.sleep(20)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--collection', required=True, help='collection id under runs/train_collection')
    p.add_argument('--rerun', action='store_true'); p.add_argument('--derive', action='store_true')
    p.add_argument('--max-containers', type=int, default=13)
    p.add_argument('--exclude-rules', nargs='*', default=[], help='rule ids whose candidates are excluded as evaluator-limitation unknowns (recorded)')
    a = p.parse_args()
    output = ROOT / 'runs/train_collection' / a.collection
    manifest = read(output / 'collection_manifest.json'); completion = read(output / 'completion.json') if (output / 'completion.json').exists() else {}
    rows = [json.loads(line) for line in (output / 'candidates.jsonl').read_text().splitlines() if line.strip()]
    rejections = read(output / 'admission_rejections.json') if (output / 'admission_rejections.json').exists() else []
    registry = read(output / 'effective_registry.json'); labels = read(manifest['label_rule_path'])
    recovery_path = output / 'recovery.json'
    recovery = read(recovery_path) if recovery_path.exists() else {'collection_id': a.collection, 'original_completion': completion, 'original_rejections': rejections,
                                                                     'failures': failed_points(output, rows), 'reruns': [], 'policy': 'manual recorded rerun of unknown points once; originals retained; no negative label from any failure'}
    print(json.dumps({'collection': a.collection, 'original_status': completion.get('status'), 'rejected_candidates': len(rejections), 'failed_points': len(recovery['failures'])}))
    files = sorted(str(q.relative_to(Path(manifest['source_pack']))) for q in Path(manifest['source_pack']).rglob('*') if q.is_file())
    if a.rerun:
        done = {(r['candidate_id'], r['configuration_id']) for r in recovery['reruns']}
        for failure in recovery['failures']:
            key = (failure['candidate_id'], failure['configuration_id'])
            if key in done: continue
            row = next(r for r in rows if r['candidate_id'] == failure['candidate_id'])
            if row.get('proposal_generation', {}).get('rule_id') in a.exclude_rules: continue
            point = next(c for c in registry['configurations'] if c['configuration_id'] == failure['configuration_id'])
            source = output / row['initial_state_id'] / row['candidate_id'] / 'source'
            actual = {name: (source / name).read_text() for name in row['candidate_source']}
            if actual != row['candidate_source']: raise ValueError('Frozen candidate source snapshot differs from the candidate row: ' + row['candidate_id'])
            resources = gate(a.max_containers)
            context = {'candidate_id': row['candidate_id'], 'initial_state_id': row['initial_state_id'], 'parent_lineage': row['parent_lineage'], 'split': 'train', 'source_role': 'formal_train',
                       'pdk_revision': manifest['pdk_revision'], 'configuration_id': point['configuration_id'], 'reference_id': point['reference_id']}
            runner = CandidateExecutor(ROOT / 'runtime/GLdev', output / 'physical', Path(manifest['magic_runtime']), image=manifest['container_image'], timeout=manifest['physical']['evaluator_timeout_seconds'])
            result = runner.execute(source_dir=source, source_paths=files, entrypoint='generator.py', representation='G2', configuration=point['parameters'], trusted_dir=manifest['trusted_bundle'],
                                    trusted_paths=list(point['trusted_evaluator_files']), fidelity='pex_spice', context=context, phase='formal_train',
                                    generation_timeout_seconds=manifest['physical']['generation_timeout_seconds'], evaluator_timeout_seconds=manifest['physical']['evaluator_timeout_seconds'])
            run = Path(result['run_directory'])
            recovery['reruns'].append({**failure, 'rerun_at_utc': now(), 'resources_before_rerun': resources, 'rerun_evidence_path': str((run / 'manifest.json').relative_to(output)),
                                       'rerun_status': result['status'], 'rerun_trusted_status': (read(run / 'manifest.json').get('trusted') or {}).get('status')})
            save(recovery_path, recovery); print(json.dumps({'rerun': failure['candidate_id'], 'point': failure['configuration_id'], 'status': result['status']}), flush=True)
    if a.derive:
        reruns = {(r['candidate_id'], r['configuration_id']): r for r in recovery['reruns']}
        excluded = []; pool = []
        for row in rows:
            if row.get('proposal_generation', {}).get('rule_id') in a.exclude_rules:
                excluded.append({'candidate_id': row['candidate_id'], 'reason': 'excluded rule ' + row['proposal_generation']['rule_id'] + ': frozen textbook bench v1 wired the DUT by reference pin order, so port-reordered layouts were simulated mis-wired (evaluator limitation, not a physical verdict)'}); continue
            patched = json.loads(json.dumps(row)); usable = True
            for outcome in patched['outcomes']:
                if read(output / outcome['evidence_path']).get('status') == 'EVALUATED': continue
                rerun = reruns.get((row['candidate_id'], outcome['configuration_id']))
                if rerun and rerun['rerun_status'] == 'EVALUATED' and read(output / rerun['rerun_evidence_path']).get('status') == 'EVALUATED':
                    outcome['original_failed_evidence_path'] = outcome['evidence_path']; outcome['evidence_path'] = rerun['rerun_evidence_path']
                else: usable = False
            (pool if usable else excluded).append(patched if usable else {'candidate_id': row['candidate_id'], 'reason': 'point evidence still unknown after one recorded rerun or no rerun'})
        store = TrustedPhysicalStore(output, registry); admitted = []; still = []
        for row in pool:
            try: admitted.extend(admit_candidates([row], registry, store))
            except (ValueError, OSError, KeyError) as exc: still.append({'candidate_id': row['candidate_id'], 'error': str(exc)})
        if still: raise RuntimeError('Recovered evidence still fails independent admission: ' + json.dumps(still)[:800])
        datasets, report = build_matched_samples(admitted, labels) if admitted else ({k: [] for k in ('T1', 'T2', 'T3', 'T4')}, {'initial_states': 0})
        for method, values in datasets.items(): (output / (method + '_recovered.jsonl')).write_text(''.join(json.dumps(v, ensure_ascii=False) + '\n' for v in values))
        (output / 'candidates_recovered.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in pool))
        source_identity = collector_module(output).source_identity
        yield_record = {'collection_id': a.collection, 'phase': 'formal_train_collection', 'main_benchmark_protocol_status': manifest['main_benchmark_protocol_status'], 'recovered': True,
                        'attempts': len(read(output / 'attempts.json')), 'distinct_candidates_with_all_declared_point_attempts': len(rows), 'candidates_excluded_as_unknown': excluded, 'excluded_rules': a.exclude_rules,
                        'admitted_candidate_pool': len(admitted), 'unique_terminal_source_programs': len({source_identity(r['candidate_source'], True) for r in pool}),
                        'distinct_initial_source_programs': len({r['initial_state_id'] for r in rows}), 'effective_samples_by_method': {k: len(v) for k, v in datasets.items()}, 'report': report,
                        'recovery_record': str(recovery_path.relative_to(output)), 'formal_model_training_runs': 0, 'effective_pipeline_pilot_target': manifest['budget']['effective_example_pipeline_pilot_target']}
        save(output / 'yield_recovered.json', yield_record)
        save(output / 'completion_recovered.json', {'status': 'COMPLETED_AFTER_RECORDED_RECOVERY', 'original_status': completion.get('status'), 'initial_states': len({r['initial_state_id'] for r in rows}),
                                                     'attempts': yield_record['attempts'], 'excluded_candidates': [e['candidate_id'] for e in excluded], 'formal_model_training_runs': 0, 'finished_at_utc': now()})
        print(json.dumps({'admitted': len(admitted), 'excluded': [e['candidate_id'] for e in excluded], 'samples': yield_record['effective_samples_by_method']}))


if __name__ == '__main__': main()
