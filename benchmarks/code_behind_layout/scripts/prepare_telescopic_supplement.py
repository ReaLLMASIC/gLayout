"""Prepare an independent, private DRAFT telescopic 25-point supplement.

This never changes E1/E2/E3 inputs or dispatches a tool. The full domain is
materialized only on the research server; tested policies receive neither this
script nor private/task.json. Existing E2 ancestry is retained explicitly.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SERVER = Path('/srv/code-behind-layout')
TASK = 'supplement_telescopic_5x5_v1'
LINEAGE = 'research_telescopic_ota'
TARGET = 'src/generators/telescopic_ota.py'
WIDTHS = (2.7, 2.85, 3.0, 3.15, 3.3)
LENGTHS = (.96, .98, 1.0, 1.02, 1.04)
BIAS = {'id': 'b00', 'VBN_V': 1.25, 'VBP_V': .45}
PDK = '0fe599b2afb6708d281543108caf8310912f54af'
IMPLEMENTATION = ['scripts/prepare_telescopic_supplement.py',
    'scripts/qualify_telescopic_supplement.py', 'scripts/run_eda_probe.py',
    'scripts/audit_train_pair_nf_rc.py',
    'scripts/profile_probe.py', 'src/candidate_executor.py', 'src/domain_runner.py',
    'src/training.py', 'src/device_intent.py', 'src/measurement.py',
    'src/report_parsers.py', 'src/spice_validation.py']


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def grid(default):
    """Fixed central 3x3 visible block; its center is anchor, perimeter hidden."""
    rows = []
    for wi, width in enumerate(WIDTHS):
        for li, length in enumerate(LENGTHS):
            role = ('anchor' if (wi, li) == (2, 2) else
                    'development' if wi in (1, 2, 3) and li in (1, 2, 3) else 'hidden')
            rows.append({'configuration_id': 'z%02d' % (wi*5+li), 'role': role,
                'parameters': {**default, 'input_width': width, 'input_length': length}})
    return rows


def point_contract(original, row):
    contract = copy.deepcopy(original)
    ident = row['configuration_id']
    contract.update(task_id=TASK, configuration_id=ident, reference_id=TASK+'_'+ident+'_independent',
        immutable_parameters=row['parameters'])
    # The existing E2 objective used "maximize"; the current Store's strict
    # objective schema uses "max". No electrical metric/threshold changes.
    if contract['objective']['direction'] not in ('max', 'maximize'):
        raise ValueError('The original telescopic objective must maximize worst UGB')
    contract['objective']['direction'] = 'max'
    return contract


def copy_files(source, names, destination):
    destination.mkdir(parents=True, exist_ok=False)
    for name in names:
        rel = Path(name)
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError('Source closure must contain relative paths')
        original = source/rel
        if original.is_symlink() or not original.is_file():
            raise ValueError('Snapshot only ordinary files: '+str(original))
        target = destination/rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)


def prepare(e2_manifest, output):
    if ROOT != SERVER:
        raise ValueError('The full private domain may only be prepared on the research server')
    output = Path(output).resolve()
    output.relative_to(ROOT/'runtime/task_preparation')
    manifest_path = Path(e2_manifest).resolve()
    old = read(manifest_path)
    if old.get('status') != 'FROZEN' or old.get('formal_execution_allowed') is not True:
        raise ValueError('Use the actual readonly frozen E2 source/bench binding')
    if manifest_path.stat().st_mode & 0o222:
        raise ValueError('The existing E2 manifest must remain readonly')
    matches = [p for p in old['pools'] if p['pool_id'] == 'telescopic_s1']
    if len(matches) != 1:
        raise ValueError('One exact default telescopic source is required')
    pool = matches[0]
    original_point = read(pool['point'])
    source = Path(pool['source_dir'])
    template = Path(pool['full_trusted'])
    trust_files = sorted(str(p.relative_to(template)) for p in template.rglob('*') if p.is_file())
    original_files = [Path(pool['point']), Path(original_point['reference_file'])]
    original_files += [source/name for name in pool['source_paths']]
    original_files += [template/name for name in trust_files]
    for path in original_files:
        if path.is_symlink() or old['immutable_input_sha256'].get(str(path)) != digest(path):
            raise ValueError('Existing frozen E2 input changed or unbound: '+str(path))
    from src.generators.telescopic_ota_reference import DEFAULT, PORTS, schematic
    for name in [TARGET, 'src/generators/telescopic_ota_reference.py', 'src/generators/terminal_access.py']:
        if (ROOT/name).read_bytes() != (source/name).read_bytes():
            raise ValueError('Live reference/source differs from the frozen E2 ancestry: '+name)
    if original_point['parameters'] != DEFAULT or (template/'reference.spice').read_text() != schematic(DEFAULT):
        raise ValueError('Default independent sized N differs')
    if read(template/'contract.json') != original_point['contract'] or read(template/'telescopic_bias.json') != BIAS:
        raise ValueError('Original benchmark/contract/bias binding differs')
    declaration = read(template/'telescopic_declaration.json')
    if declaration['corners'] != ['tt', 'ss', 'ff'] or declaration['per_analysis_wall_limit_s'] != 180:
        raise ValueError('Original corner/analysis budgets differ')
    output.mkdir(parents=True, exist_ok=False)
    private = output/'private'; private.mkdir(mode=0o700)
    pack = private/'source_pack'
    copy_files(source, pool['source_paths'], pack)
    rows = []
    for row in grid(DEFAULT):
        ident = row['configuration_id']; folder = private/'points'/ident; folder.mkdir(parents=True)
        trusted = folder/'trusted'; copy_files(template, trust_files, trusted)
        reference = folder/'reference.spice'; reference.write_text(schematic(row['parameters']))
        contract = point_contract(original_point['contract'], row)
        (trusted/'reference.spice').write_bytes(reference.read_bytes())
        save(trusted/'contract.json', contract)
        point = {**row, 'reference_id': contract['reference_id'], 'reference_file': str(reference),
            'contract': contract, 'trusted_dir': str(trusted), 'trusted_files': trust_files,
            'parent_lineage': LINEAGE, 'pdk_revision': PDK}
        save(folder/'point.json', point); rows.append(point)
    task = {'status': 'DRAFT_SUPPLEMENT_NOT_POLICY_FROZEN', 'task_id': TASK, 'parent_lineage': LINEAGE,
        'source_group': 'research_telescopic_ota', 'split': 'test_supplement_only',
        'configurations': rows, 'source_pack': str(pack), 'source_files': pool['source_paths'],
        'editable_paths': [TARGET], 'entrypoint': pool['entrypoint'], 'top_cell': pool['top_cell'],
        'configuration_input': {'parameters': 'exact current point parameters'}, 'ports': PORTS,
        'original_E2_manifest': str(manifest_path), 'original_E2_pool_id': pool['pool_id'],
        'train_or_selector_calibration_allowed': False, 'formal_admission': False,
        'source_ancestry': 'Existing E2 independent two-column four-tier telescopic assembly; same lineage across experiments',
        'domain_selection': 'Fixed full Cartesian; anchor center, other central 3x3 points visible, outer perimeter hidden; no new electrical outcome used',
        'coverage_limit': 'This proposed 25-point domain is not established by the previous three fixed-W E2 controls',
        'contract_schema_change': 'Only task/configuration/reference identities, current immutable sizing, and objective direction spelling maximize->max; electrical thresholds/decks/functions/solver unchanged',
        'qualification': {'required': 'all25 complete ideal and all25 complete physical S2 with exact raw Store checks',
            'new_models': 0, 'new_training_labels': 0, 'worker_CPUs': 2, 'worker_memory_GiB': 8,
            'stage_timeout_seconds': {'candidate': 240, 'trusted': 3000},
            'each_phase_dispatch_window_seconds': 86400, 'automatic_retry': False},
        'main_cohort': 'Original 24-task/1730 matrix and seven-cluster primary analysis remain unchanged'}
    save(private/'task.json', task)
    snapshot_files = sorted(str(p.relative_to(private)) for p in private.rglob('*') if p.is_file())
    binding = {'status': 'DRAFT_INPUTS_FIXED_QUALIFICATION_NOT_RUN', 'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'task': str(private/'task.json'), 'source_E2_manifest_sha256': digest(manifest_path),
        'original_input_sha256': {str(p): digest(p) for p in original_files},
        'snapshot_sha256': {name: digest(private/name) for name in snapshot_files},
        'implementation_sha256': {name: digest(ROOT/name) for name in IMPLEMENTATION},
        'declared_configurations': 25, 'roles': {'anchor': 1, 'development': 8, 'hidden': 16},
        'qualification_state': 'NOT_RUN', 'formal_dispatch_allowed': False}
    save(private/'manifest.json', binding)
    public = output/'public'; public.mkdir()
    summary = {'status': binding['status'], 'task_id': TASK, 'existing_source_role': 'E2 evaluation only',
        'declared_configurations': 25, 'roles': binding['roles'], 'new_model_calls': 0, 'new_physical_calls': 0,
        'main_cohort_changed': False, 'formal_dispatch_allowed': False,
        'visible_configurations': [{k: row[k] for k in ('configuration_id', 'role', 'parameters')}
            for row in rows if row['role'] != 'hidden'],
        'private_data_exported': False}
    save(public/'preparation.json', summary)
    for path in private.rglob('*'):
        if path.is_file(): path.chmod(0o444)
    for path in sorted(private.rglob('*'), reverse=True):
        if path.is_dir(): path.chmod(0o500)
    private.chmod(0o500)
    return summary


def validate(preparation, check_live=True):
    private = Path(preparation)/'private'; binding = read(private/'manifest.json')
    for name, expected in binding['snapshot_sha256'].items():
        if digest(private/name) != expected:
            raise ValueError('Prepared source/N/bench/point changed: '+name)
    if check_live:
        for name, expected in binding['implementation_sha256'].items():
            if digest(ROOT/name) != expected: raise ValueError('Qualification implementation drifted: '+name)
    task = read(private/'task.json'); rows = task['configurations']
    if len(rows) != 25 or len({json.dumps(r['parameters'], sort_keys=True) for r in rows}) != 25:
        raise ValueError('The fixed domain must retain all 25 distinct configurations')
    if {role: sum(r['role'] == role for r in rows) for role in ('anchor', 'development', 'hidden')} != binding['roles']:
        raise ValueError('The predeclared visible/hidden split changed')
    return task


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--e2-manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(prepare(args.e2_manifest, args.output), indent=2, allow_nan=False))
