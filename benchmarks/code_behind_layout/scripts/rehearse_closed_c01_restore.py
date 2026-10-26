"""One closed C01 pool's review-only archive/restore rehearsal; never delete raw.

Default inspection is local and read-only. Stage/exercise are explicit future
operator actions on the original server; no SSH, model or physical tool is run.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import resource
import shutil
import signal
import stat
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
REMOTE = Path('/srv/code-behind-layout')
COHORT = 'runs/train_collection/c01_collection_v2'
CANONICAL = REMOTE / COHORT
WORK = REMOTE / 'runtime/recovery_staging/closed_c01_restore_rehearsal_v1'
ARCHIVE_SHA256 = 'b7643890cd98ef9423f43d354dafe75275d5b72827a74e11749a709e1ee17349'
ARCHIVE_BYTES = 21405785
GIB = 1024 ** 3


def save(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 ** 2), b''):
            value.update(block)
    return value.hexdigest()


def members(archive):
    """Accept ordinary members of this exact cohort, without path rewriting."""
    rows = []
    names = set()
    for row in archive.getmembers():
        name = PurePosixPath(row.name)
        if (name.is_absolute() or '..' in name.parts or
                not (str(name) == COHORT or str(name).startswith(COHORT + '/')) or
                not (row.isfile() or row.isdir()) or str(name) in names):
            raise ValueError('Unexpected/duplicate/nonordinary cohort archive member: ' + row.name)
        names.add(str(name))
        rows.append((row, Path(*name.parts)))
    return rows


def inspect_archive(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != ARCHIVE_BYTES:
        raise ValueError('Use the exact previously verified complete local archive')
    if digest(path) != ARCHIVE_SHA256:
        raise ValueError('Archive differs from the existing actual verified delivery')
    with tarfile.open(path, 'r:gz') as archive:
        rows = members(archive)
        result = {'status': 'DRAFT_ARCHIVE_INSPECTED_NO_RESTORE', 'cohort': COHORT,
            'archive_sha256': ARCHIVE_SHA256, 'archive_bytes': ARCHIVE_BYTES,
            'members': len(rows), 'regular_files': sum(r.isfile() for r, _ in rows),
            'directories': sum(r.isdir() for r, _ in rows),
            'logical_bytes': sum(r.size for r, _ in rows if r.isfile()),
            'rounded_4KiB_file_and_directory_bytes': sum(
                ((r.size + 4095) // 4096) * 4096 if r.isfile() else 4096 for r, _ in rows),
            'global_training_recipe_freeze_required': False,
            'new_model_calls': 0, 'new_EDA_calls': 0, 'raw_deleted': False}
    return result


def compare_tree(archive_path, tree):
    """Reopen each archived and restored byte, including zero-length files."""
    count = size = 0
    with tarfile.open(archive_path, 'r:gz') as archive:
        rows = members(archive)
        expected = set()
        for member, name in rows:
            relative = name.relative_to(COHORT)
            path = tree / relative
            expected.add(relative.as_posix())
            if path.is_symlink() or not path.exists():
                raise ValueError('Missing/nonordinary restored path: ' + str(relative))
            if stat.S_IMODE(path.stat().st_mode) != member.mode:
                raise ValueError('Restored permission differs: ' + str(relative))
            if member.isdir():
                if not path.is_dir():
                    raise ValueError('Restored directory changed type')
                continue
            if not path.is_file() or path.stat().st_size != member.size:
                raise ValueError('Restored file changed type/size: ' + str(relative))
            with archive.extractfile(member) as archived, path.open('rb') as restored:
                while True:
                    block = archived.read(4 * 1024 ** 2)
                    actual = restored.read(len(block) if block else 1)
                    if block != actual:
                        raise ValueError('Restored bytes differ: ' + str(relative))
                    if not block:
                        break
            count += 1
            size += member.size
        actual = {'.'} | {p.relative_to(tree).as_posix() for p in tree.rglob('*')}
        if actual != expected:
            raise ValueError('Restored closed inventory has missing/additional paths')
    return {'regular_files_reopened': count, 'bytes_compared': size,
            'path_bytes_and_modes_exact': True, 'inode_or_ctime_equality_claimed': False}


def require_server():
    if ROOT != REMOTE:
        raise ValueError('Stage/exercise only on the original private server project')
    if WORK.is_symlink() or CANONICAL.is_symlink():
        raise ValueError('No path aliases or symlink replacement')


def stage(path):
    require_server()
    inventory = inspect_archive(path)
    required = 4 * GIB + inventory['rounded_4KiB_file_and_directory_bytes'] + 128 * 1024 ** 2
    if shutil.disk_usage(ROOT).free < required:
        raise RuntimeError('Keep4GiB reserve plus complete fresh staging and128MiB metadata allowance')
    WORK.mkdir(parents=True, exist_ok=False)
    record = {'status': 'STAGING', 'inventory': inventory, 'required_free_bytes_before_stage': required}
    start, cpu = time.monotonic(), time.process_time()
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        target = WORK / 'restored'
        with tarfile.open(path, 'r:gz') as archive:
            rows = members(archive)
            for member, name in rows:
                output = target / name
                if member.isdir():
                    output.mkdir(parents=True, exist_ok=True)
                else:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as source, output.open('xb') as destination:
                        shutil.copyfileobj(source, destination, 4 * 1024 ** 2)
                    output.chmod(member.mode)
            for member, name in sorted(rows, key=lambda item: len(item[1].parts), reverse=True):
                if member.isdir():
                    (target / name).chmod(member.mode)
        record.update(status='STAGED_BYTES_VERIFIED_NO_SWAP',
            comparison=compare_tree(path, target / COHORT), restored_cohort=str(target / COHORT))
    except BaseException as error:
        record.update(status='STAGING_FAILED_RETAINED', error=repr(error))
        raise
    finally:
        final_children = resource.getrusage(resource.RUSAGE_CHILDREN)
        record.update(wall_seconds=time.monotonic()-start, parent_CPU_seconds=time.process_time()-cpu,
                      child_CPU_seconds=(final_children.ru_utime+final_children.ru_stime-children.ru_utime-children.ru_stime),
                      network_bytes=None, network_wall_seconds=None,
                      raw_deleted=False, model_calls=0, EDA_calls=0)
        save(WORK / 'stage.json', record)
    return record


def reverse_and_active_check():
    """Block every foreign TRAIN metadata reference into the physical tree."""
    files = set()
    for directory in (REMOTE / 'runtime').iterdir():
        if directory.is_dir() and directory.name.startswith('train') and 'venv' not in directory.name:
            for pattern in ('*.json', '*.jsonl'):
                files.update(p for p in directory.rglob(pattern) if p.is_file() and not p.is_symlink())
    for directory in (REMOTE / 'runs/train_collection').iterdir():
        if directory.is_dir() and directory != CANONICAL and not directory.is_symlink():
            files.update(p for p in directory.iterdir() if p.is_file() and p.suffix in ('.json', '.jsonl'))
            files.update(directory.glob('*/baseline_results.json'))
    references = []
    start = time.monotonic()
    for path in sorted(files):
        if time.monotonic()-start > 55:
            raise RuntimeError('Reverse-reference metadata scan exceeded55s; no swap')
        if COHORT + '/physical' in path.read_text():
            references.append(str(path))
    active = []
    definition = str(REMOTE / 'runtime/train_collections/c01_collection_v2/collection.json')
    for process in Path('/proc').glob('[0-9]*'):
        try:
            if process.stat().st_uid != os.getuid() or int(process.name) == os.getpid():
                continue
            command = (process / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
            if (str(CANONICAL) in command or definition in command or
                    'scripts/training_pilot_status.py' in command):
                active.append(int(process.name))
        except FileNotFoundError:
            continue
    if references or active:
        raise ValueError('Pool still referenced/active; no swap: ' + json.dumps(
            {'foreign_metadata': references, 'active_process_ids': active}))
    terminal_manifests = list((CANONICAL / 'physical').glob('executor_*/manifest.json'))
    if len(terminal_manifests) != 36:
        raise ValueError('The fixed closed pool must retain all36 actual point manifests')
    for manifest in terminal_manifests:
        row = json.loads(manifest.read_text())
        if row.get('phase') != 'formal_train' or row.get('status') not in ('EVALUATED','CANDIDATE_FAILED','REJECTED_OUTPUT'):
            raise ValueError('Nonterminal/nonformal_train point in the fixed closed pool')
        for stage_name in ('candidate', 'trusted'):
            if stage_name in row and row[stage_name].get('container_state', {}).get('Running') is not False:
                raise ValueError('Point lacks stopped container state')
    return {'metadata_files_read': len(files), 'foreign_physical_references': [], 'active_process_ids': [],
            'terminal_point_manifests':len(terminal_manifests),
            'wall_seconds': time.monotonic()-start}


def readmit():
    sys.path.insert(0, str(REMOTE))
    from scripts.prepare_student_data import bound_registry, re_admit
    from scripts.run_frozen_training_collection import load_definition
    manifest, frozen, _, _ = load_definition(REMOTE / 'runtime/train_collections/c01_collection_v2/collection.json')
    if manifest != json.loads((CANONICAL / 'collection_manifest.json').read_text()):
        raise ValueError('Original pool differs from its frozen collection')
    registry = bound_registry(frozen, json.loads((CANONICAL / 'effective_registry.json').read_text()))
    candidates = [json.loads(line) for line in (CANONICAL / 'candidates.jsonl').read_text().splitlines() if line.strip()]
    if len(candidates) != 1 or len(candidates[0]['outcomes']) != 9:
        raise ValueError('This rehearsal is only for the actual one-candidate/nine-point closed pool')
    groups, report = re_admit(CANONICAL, registry, json.loads(Path(manifest['label_rule_path']).read_text()))
    if groups is None or report['status'] != 'RE_ADMITTED_FROM_RAW':
        raise ValueError('Current Store raw admission failed: ' + json.dumps(report))
    return groups, {**report, 'all_nine_candidate_and_baseline_points_reopened': True}


def swap_physical(original, restored, held, failed, verify, record, persist):
    """Two renames; on ordinary failure put the old physical tree back. No delete."""
    if not original.is_dir() or not restored.is_dir() or held.exists() or failed.exists():
        raise ValueError('Expected fresh exact directories; automatic resume is forbidden')
    if original.stat().st_dev != restored.stat().st_dev:
        raise ValueError('Rehearsal requires same-filesystem directory renames')
    moved = installed = False
    try:
        record['status'] = 'ORIGINAL_RENAME_RESERVED'; persist()
        original.rename(held); moved = True
        record['status'] = 'ORIGINAL_HELD'; persist()
        restored.rename(original); installed = True
        record['status'] = 'RESTORED_AT_CANONICAL'; persist()
        result = verify()
        record.update(status='RESTORE_DRILL_COMPLETED_ORIGINAL_RETAINED', validation=result)
        persist()
        return result
    except BaseException as primary_error:
        try:
            if installed:
                original.rename(failed)
            if moved:
                held.rename(original)
        except BaseException as rollback_error:
            record.update(status='ROLLBACK_FAILED_MANUAL_RECOVERY_REQUIRED',
                          original_restored=False, primary_error=repr(primary_error),
                          rollback_error=repr(rollback_error))
            persist()
            raise
        record.update(status='RESTORE_DRILL_FAILED_ORIGINAL_RESTORED', original_restored=moved,
                      failed_restored_directory=str(failed) if installed else None)
        persist()
        raise


def exercise(path):
    require_server(); inspect_archive(path)
    staged = json.loads((WORK / 'stage.json').read_text())
    if staged['status'] != 'STAGED_BYTES_VERIFIED_NO_SWAP':
        raise ValueError('A complete fresh byte-verified stage is required')
    journal = WORK / 'exercise.json'
    with journal.open('x') as stream:
        stream.write('{}\n')
    record = {'status':'PREFLIGHT', 'scope':'engineering_restore_control_not_new_physical_measurement',
              'global_training_recipe_freeze_required':False, 'raw_deleted':False}
    start, cpu = time.monotonic(), time.process_time()
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        record['canonical_bytes_before'] = compare_tree(path, CANONICAL)
        record['fresh_stage_bytes'] = compare_tree(path, WORK / 'restored' / COHORT)
        before_groups, before = readmit(); record['current_Store_before'] = before
        record['fresh_reverse_and_active_check'] = reverse_and_active_check()
        if shutil.disk_usage(ROOT).free < 4 * GIB:
            raise RuntimeError('Less than4GiB root reserve; no swap')
        gate_names = ('src/training.py','src/domain_runner.py','src/device_intent.py')
        gate = {name:(REMOTE/name).read_bytes() for name in gate_names}
        record['current_gate_sha256'] = {name:hashlib.sha256(value).hexdigest() for name,value in gate.items()}
        def verify():
            byte_report = compare_tree(path, CANONICAL)
            after_groups, after = readmit()
            if after_groups != before_groups or after != before:
                raise ValueError('Actual source-bound labels/admission changed after canonical restore')
            if any((REMOTE/name).read_bytes() != value for name,value in gate.items()):
                raise ValueError('Current Store implementation changed during rehearsal')
            return {'canonical_bytes_after':byte_report, 'current_Store_after':after,
                    'candidate_rows_labels_and_metadata_unchanged':True}
        swap_physical(CANONICAL/'physical', WORK/'restored'/COHORT/'physical',
            WORK/'original_physical', WORK/'failed_restored_physical', verify, record, lambda:save(journal,record))
    except BaseException as error:
        record.setdefault('status','PREFLIGHT_FAILED_NO_SWAP')
        if record['status']=='PREFLIGHT': record['status']='PREFLIGHT_FAILED_NO_SWAP'
        record['error']=repr(error)
        raise
    finally:
        final_children = resource.getrusage(resource.RUSAGE_CHILDREN)
        record.update(wall_seconds=time.monotonic()-start, parent_CPU_seconds=time.process_time()-cpu,
                      child_CPU_seconds=(final_children.ru_utime+final_children.ru_stime-children.ru_utime-children.ru_stime),
                      network_bytes=None, network_wall_seconds=None,
                      model_calls=0, EDA_calls=0)
        save(journal,record)
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('inspect','stage','exercise'),default='inspect')
    parser.add_argument('--archive',type=Path,required=True)
    args=parser.parse_args()
    if args.mode=='exercise':
        def interrupted(signum, frame): raise InterruptedError('Rehearsal interrupted; rollback required')
        signal.signal(signal.SIGTERM,interrupted)
    result={'inspect':inspect_archive,'stage':stage,'exercise':exercise}[args.mode](args.archive)
    print(json.dumps(result,indent=2,allow_nan=False))


if __name__=='__main__':main()
