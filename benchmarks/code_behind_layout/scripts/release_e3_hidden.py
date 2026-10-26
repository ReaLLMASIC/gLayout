"""Open E3 test oracles only after every declared source and all models are sealed.

Run on the trusted backend with the complete suite search indices. This command
does no model inference or physical evaluation. Missing or unresolved searches
retain their original identities and prevent release.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.e3_episode import project, read, verify
from src.e3_dispatch import identity, plan
from src.e4_methods import frozen_serving_method

PARTS = ('gpt', 'parameter', 'local', 'signals', 'fidelity')
COUNTS = {'gpt': 480, 'parameter': 80, 'local': 1080, 'signals': 80, 'fidelity': 10}


def readonly(filename):
    filename = project(filename)
    if not filename.is_file() or filename.is_symlink() or filename.stat().st_mode & 0o222:
        raise ValueError('An actual readonly freeze is required: '+str(filename))
    return filename, read(filename)


def source_proof(manifest, fidelity, job):
    directory = project(job['episode_directory']).resolve()
    if directory.parent != (ROOT/'runs/formal/E3').resolve():
        raise ValueError('Search directory is outside the trusted formal backend')
    private = directory/'private'
    value, task = read(private/'state.json'), read(private/'task.json')
    own = fidelity if job['part'] == 'fidelity' else manifest
    if read(private/'manifest.json') != own:
        raise ValueError('Search used a different prospective freeze')
    if (value.get('formal_trial') is not True or not value.get('sealed') or value.get('in_flight')
            or value.get('post_freeze_started') is not False or (directory/'public/episode.json').exists()):
        raise ValueError('Source is unsealed, unresolved, or has already opened a test oracle')
    if (task['task_id'] != job['task_id'] or str(value['trial_id']) != job['trial_id']
            or value.get('policy_variant', 'GPT') != job['policy_variant']
            or value.get('evaluation_seed_slot') != job['evaluation_seed_slot']
            or value.get('selector_variant', 'main') != job.get('selector_variant', 'main')):
        raise ValueError('Actual source identity differs from the fixed search matrix')
    expected_method = 'C' if job['part'] == 'parameter' else job['method']
    expected_phase = 'formal_E3_P' if job['part'] == 'parameter' else 'formal_E3'
    if value['method'] != expected_method or value['phase'] != expected_phase:
        raise ValueError('Actual selector or phase differs from its declared comparison')
    if (job['part'] == 'parameter' and
            value.get('parameter_strategy') != job['method'].removeprefix('P_')):
        raise ValueError('Parameter strategy differs from the declared search')
    seed = job['evaluation_seed_slot'] if job['policy_variant'] in ('T1', 'T2', 'T3', 'T4') else None
    if value.get('training_seed') != seed or value['seed'] != job['selection_seed']:
        raise ValueError('Actual training/selection seed differs')
    if any(event['stage'] != 'search' or event['status'] != 'RETURNED' for event in value['physical_events']):
        raise ValueError('An unresolved or post-search physical event prevents global release')
    search = read(directory/'public/search.json')
    if search['status'] != value['status'] or search['selection'] != value['selection']:
        raise ValueError('Published search summary differs from the actual sealed state')
    revision = value['selection']['revision']
    source = private/('revisions/%03d/source' % revision)
    bindings = {}
    for name in task['source_files']:
        filename = source/name
        if not filename.is_file() or filename.is_symlink():
            raise ValueError('Selected complete source is absent: '+name)
        bindings[name] = hashlib.sha256(filename.read_bytes()).hexdigest()
    return {**{key: job.get(key) for key in ('part', 'task_id', 'method', 'policy_variant',
        'selector_variant', 'evaluation_seed_slot', 'trial_id', 'selection_seed')},
        'episode_directory': str(directory), 'selected_revision': revision,
        'search_status': value['status'], 'sealed_at_utc': value['sealed_at_utc'],
        'selected_source_sha256': bindings}


def inspect_indices(manifest, filenames):
    expected = {identity(row): row for part in PARTS for row in plan(manifest, part)}
    if any(len(plan(manifest, part)) != COUNTS[part] for part in PARTS):
        raise ValueError('The frozen shared evaluation matrix differs from its declared denominator')
    observed = {}
    for filename in filenames:
        rows = read(filename)
        if not isinstance(rows, list):
            raise ValueError('Supply complete suite search_index.json lists')
        for row in rows:
            key = identity(row)
            if key not in expected or key in observed:
                raise ValueError('Unexpected or duplicate search identity')
            if row.get('status') != 'RECORDED':
                raise ValueError('Every declared search must be sealed and recorded before hidden evaluation')
            fixed = expected[key]
            if any(row.get(name) != fixed[name] for name in ('selection_seed', 'job_id')):
                raise ValueError('A dispatch seed or trial identity changed')
            observed[key] = row
    if set(observed) != set(expected):
        raise ValueError('Missing declared searches remain NOT_RUN and prevent global release')
    return [observed[identity(row)] for part in PARTS for row in plan(manifest, part)]


def release(manifest_path, indices):
    filename, manifest = readonly(manifest_path)
    if (manifest['status'] != 'FROZEN_E3' or manifest['formal_dispatch'] is not True
            or manifest['global_release_parts'] != list(PARTS)):
        raise ValueError('The complete prospectively frozen shared E3 matrix is required')
    verify(manifest)
    destination = project(manifest['hidden_release_file'])
    if destination.exists():
        raise ValueError('The global release already exists; it is never rewritten')
    _, fidelity = readonly(manifest['fidelity_manifest'])
    if (fidelity['status'] != 'FROZEN_E3_FIDELITY_METHOD' or fidelity['formal_dispatch'] is not True
            or fidelity['main_freeze_id'] != manifest['freeze_id']
            or fidelity['hidden_release_file'] != manifest['hidden_release_file']
            or {(r['task_id'], str(r['trial_id'])) for r in fidelity['search_plan']} !=
               {(r['task_id'], r['trial_id']) for r in plan(manifest, 'fidelity')}):
        raise ValueError('The actual F3 freeze does not match all ten predeclared shared sources')
    verify(fidelity)
    methods_path, methods = readonly(manifest['e4_methods_manifest'])
    if methods.get('formal_training_runs') != 12:
        raise ValueError('All twelve actual training runs must be frozen before any shared hidden oracle')
    # This one-time read verifies all selected actual weights, rather than
    # trusting preparation records or rehashing large adapters every episode.
    models = [frozen_serving_method(methods_path, variant, slot)
        for variant in ('T1', 'T2', 'T3', 'T4') for slot in (41, 73, 109)]
    if (methods['student_interface']['max_context_tokens'] != manifest['budget']['maximum_context_tokens']
            or methods['student_interface']['max_new_tokens'] != manifest['budget']['maximum_output_tokens']):
        raise ValueError('Actual local and GPT methods have different common budgets')
    jobs = inspect_indices(manifest, indices)
    proofs = [source_proof(manifest, fidelity, job) for job in jobs]
    if len({row['episode_directory'] for row in proofs}) != len(proofs):
        raise ValueError('A backend source cannot stand in for multiple independent trials')
    result = {'status': 'FROZEN_E3_EVALUATION_RELEASE', 'freeze_id': manifest['freeze_id'],
        'fidelity_freeze_id': fidelity['freeze_id'], 'source_revision': manifest['source_revision'],
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'all_declared_searches_sealed': True, 'all_models_frozen': True,
        'search_counts': COUNTS, 'sealed_searches': proofs,
        'original_baseline_plan': manifest['original_baseline_plan'],
        'e4_methods_manifest': str(methods_path),
        'e4_methods_manifest_sha256': hashlib.sha256(methods_path.read_bytes()).hexdigest(),
        'actual_trained_models': len(models), 'T0_actual_model_count': 1,
        'hidden_calls_dispatched_by_release': 0,
        'independent_instance_streams': 'Excluded from shared-code feedback and source release; each stream exposes only its current/past arrivals.'}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x') as stream:
        json.dump(result, stream, indent=2, allow_nan=False);stream.write('\n')
    destination.chmod(0o444)
    return {'status': result['status'], 'path': str(destination), 'search_counts': COUNTS,
        'actual_trained_models': len(models), 'hidden_calls': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--search-index', type=Path, action='append', required=True)
    args = parser.parse_args()
    print(json.dumps(release(args.manifest, args.search_index)), flush=True)
