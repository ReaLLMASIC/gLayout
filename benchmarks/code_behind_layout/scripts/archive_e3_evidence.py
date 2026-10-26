#!/usr/bin/env python3
"""Archive returned E3 point evidence, retaining source, GDS and join records."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path, PurePosixPath
import resource
import shutil
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
HEAVY = ('candidate_output', 'candidate_stage', 'trusted_stage', 'evidence')
KEEP = {'candidate_stage/resource_usage.json', 'candidate_stage/invocation.json',
        'trusted_stage/resource_usage.json', 'trusted_stage/invocation.json'}


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    temporary = path.with_name(path.name+'.pending')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n');temporary.replace(path)


def safe_member(member):
    name = PurePosixPath(member.name)
    return (not name.is_absolute() and '..' not in name.parts and (member.isdir() or member.isfile())
        and any(member.name == prefix or member.name.startswith(prefix+'/') for prefix in HEAVY))


def compare_archive(run, archive):
    count = size = 0
    with tarfile.open(archive, 'r:gz') as stream:
        for member in stream:
            if not safe_member(member):
                raise ValueError('E3 archive entry is outside its ordinary raw-evidence trees')
            count += 1;original = run/member.name
            if member.isdir():
                if not original.is_dir():
                    raise ValueError('Declared evidence directory is unavailable')
                continue
            if original.is_symlink() or not original.is_file() or original.stat().st_size != member.size:
                raise ValueError('Raw evidence is missing or its size changed')
            size += member.size
            with original.open('rb') as actual:
                stored = stream.extractfile(member)
                while True:
                    chunk = stored.read(1024*1024)
                    if actual.read(len(chunk)) != chunk:
                        raise ValueError('Compressed E3 evidence differs byte for byte')
                    if not chunk:
                        break
    return count, size


def prune(run, names):
    # Only declared verified duplicate files are removed; retained telemetry
    # keeps the ordinary physical CPU ledger readable without decompression.
    # Some actual extracted report subdirectories are inherited read-only from
    # frozen containers. Only verified duplicate raw trees become writable.
    for prefix in HEAVY:
        folder = run/prefix
        if folder.is_dir():
            for path in [folder, *(p for p in folder.rglob('*') if p.is_dir())]:
                path.chmod(path.stat().st_mode | 0o700)
    for name in names:
        path = run/name
        if name not in KEEP and path.is_file():
            path.unlink()
    directories = sorted({(run/name).parent for name in names}, key=lambda path: len(path.parts), reverse=True)
    for path in directories:
        if path != run and path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def archive_point(point, measure_only=False):
    point = point.resolve();record = read(point/'point.json');run = Path(record['run_directory']).resolve()
    return archive_execution(run, point, measure_only)


def archive_execution(run, point, measure_only=False):
    run, point = Path(run).resolve(), Path(point).resolve()
    if not run.is_relative_to(point):
        return {'status': 'CACHED_ORIGIN_NOT_MODIFIED', 'origin_run': str(run), 'new_physical_calls': 0}
    with (run/'archive.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        manifest = read(run/'manifest.json');phase = manifest['phase']
        if not (phase == 'formal_E3' or phase.startswith('development_E3')):
            raise ValueError('This archive accepts actual E3 executions only; no E1/E2 phase relabeling')
        if manifest['status'] == 'RUNNING' or any(manifest[name]['container_state'].get('Running') is not False
                for name in ('candidate', 'trusted') if name in manifest):
            raise ValueError('Physical execution has not terminated')
        index = run/'evidence_archive.json'
        if index.is_file():
            previous = read(index);archive = Path(previous['archive'])
            if not archive.is_file() or archive.stat().st_size != previous['archive_bytes']:
                raise ValueError('Previously retained E3 raw archive is unavailable')
            if previous['status'] == 'COMPRESSED_E3_RAW_RETAINED':
                return previous
            compare_archive(run, archive)
            if not measure_only:
                prune(run, previous['file_members'])
                previous['status'] = 'COMPRESSED_E3_RAW_RETAINED';save(index, previous)
            return previous
        paths = sorted(path for prefix in HEAVY if (run/prefix).is_dir()
            for path in [(run/prefix), *(run/prefix).rglob('*')])
        if any(path.is_symlink() or not (path.is_dir() or path.is_file()) for path in paths):
            raise ValueError('Unexpected evidence object before compression')
        destination = ROOT/'private_checkpoints'/('formal_E3' if phase == 'formal_E3' else 'development_E3')
        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        archive = destination/(run.name+'.tar.gz');temporary = archive.with_suffix('.tar.gz.partial')
        if archive.exists() or temporary.exists():
            raise ValueError('An existing archive without its completion index requires reconciliation')
        began = time.monotonic();cpu = resource.getrusage(resource.RUSAGE_SELF)
        with tarfile.open(temporary, 'x:gz', compresslevel=6) as stream:
            for path in paths:
                stream.add(path, arcname=str(path.relative_to(run)), recursive=False)
        count, raw_size = compare_archive(run, temporary)
        if count != len(paths):
            raise ValueError('The archive omitted a declared raw-evidence member')
        temporary.replace(archive);after = resource.getrusage(resource.RUSAGE_SELF)
        result = {'status': 'VERIFIED_E3_ARCHIVE_RAW_NOT_REMOVED', 'phase_preserved': phase,
            'run_directory': str(run), 'point_directory': str(point), 'archive': str(archive), 'archive_bytes': archive.stat().st_size,
            'raw_regular_file_bytes': raw_size, 'members': count,
            'file_members': [str(path.relative_to(run)) for path in paths if path.is_file()],
            'compression_ratio': archive.stat().st_size/raw_size if raw_size else None,
            'verification': 'Every declared raw file compared byte for byte before duplicate cleanup',
            'archive_wall_seconds': time.monotonic()-began,
            'archive_process_CPU_seconds': after.ru_utime+after.ru_stime-cpu.ru_utime-cpu.ru_stime,
            'verified_at_utc': datetime.now(timezone.utc).isoformat(),
            'retained': 'source, trusted snapshots, configuration, manifest, accepted GDS, point records and resource telemetry',
            'hidden_evidence_exported': False, 'new_physical_calls': 0}
        save(index, result)
        if not measure_only:
            prune(run, result['file_members']);result['status'] = 'COMPRESSED_E3_RAW_RETAINED';save(index, result)
        return result


def restore_run(run):
    run = Path(run);index = run/'evidence_archive.json'
    if not index.is_file():
        return {'status': 'NO_ARCHIVE', 'new_physical_calls': 0}
    with (run/'archive.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        record = read(index)
        if record['status'] != 'COMPRESSED_E3_RAW_RETAINED':
            return record
        if not Path(record['archive']).is_file():
            raise ValueError('Private E3 archive is unavailable')
        began, cpu = time.monotonic(), time.process_time()
        with tarfile.open(record['archive'], 'r:gz') as stream:
            for member in stream:
                if not safe_member(member):
                    raise ValueError('Unexpected archive path or member type')
                path = run/member.name
                if member.isdir():
                    path.mkdir(parents=True, exist_ok=True);continue
                stored = stream.extractfile(member)
                if path.exists():
                    if path.is_symlink() or not path.is_file():
                        raise ValueError('Existing restore target is not an ordinary file')
                    with path.open('rb') as actual:
                        while True:
                            chunk = stored.read(1024*1024)
                            if actual.read(len(chunk)) != chunk:
                                raise ValueError('Retained telemetry differs from its archived bytes')
                            if not chunk:
                                break
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open('xb') as target:
                        shutil.copyfileobj(stored, target)
                    path.chmod(member.mode & 0o777)
        record.update(status='RESTORED_E3_RAW_ARCHIVE_RETAINED',
            last_restore_wall_seconds=time.monotonic()-began,
            last_restore_process_CPU_seconds=time.process_time()-cpu, new_physical_calls=0)
        save(index, record);return record


def archive_episode(episode, measure_only=False):
    episode = episode.resolve();private = episode/'private'
    with (private/'backend.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read(private/'state.json')
        if not state.get('sealed') or state.get('in_flight') or not (episode/'public/episode.json').is_file():
            raise ValueError('E3 source or final deployment/hidden evaluation is not terminal')
        if state.get('phase') not in ('formal_E3', 'development_E3', 'formal_E3_P', 'development_E3_P', 'formal_E3_I', 'development_E3_I'):
            raise ValueError('Unknown E3 episode phase')
        records = [archive_execution(run, point, measure_only) for run, point in returned_executions(episode)]
        result = {'status': 'E3_TERMINAL_EVIDENCE_ARCHIVED', 'episode': str(episode),
            'phase_preserved': state['phase'], 'physical_point_archives': len(records),
            'archive_bytes': sum(row.get('archive_bytes', 0) for row in records),
            'raw_regular_file_bytes': sum(row.get('raw_regular_file_bytes', 0) for row in records),
            'measure_only': measure_only, 'hidden_evidence_exported': False, 'new_physical_calls': 0}
        save(private/'evidence_archive.json', result);return result


def returned_executions(episode):
    result = {}
    for filename in sorted((episode/'private/points').glob('*/point.json')):
        folder = filename.parent;handle = folder/'fidelity_point.json'
        if handle.is_file():
            staged = read(handle)
            for name in ('physical_actual', 'nominal_actual', 'full_actual'):
                row = staged.get(name)
                if row and row.get('run_directory'):
                    result[row['run_directory']] = folder
        else:
            row = read(filename)
            result[row['run_directory']] = folder
    return [(Path(run), point) for run, point in result.items()]


def archive_returned_points(episode):
    """A sealed search/finished arrival can store raw bytes before test release."""
    episode = Path(episode).resolve();state = read(episode/'private/state.json')
    if not state.get('sealed') or state.get('in_flight'):
        raise ValueError('Search source is not sealed or a physical call remains unresolved')
    if state.get('phase') not in ('formal_E3', 'development_E3', 'formal_E3_P', 'development_E3_P',
            'formal_E3_I', 'development_E3_I') or not (episode/'public/search.json').is_file():
        raise ValueError('Only an actual completed E3 search/arrival can be stored')
    if state.get('post_freeze_started') is True and not (episode/'public/episode.json').is_file():
        raise ValueError('Diagnostic/hidden evaluation is still in flight')
    if state['phase'].endswith('_I') and not (episode/'public/episode.json').is_file():
        raise ValueError('Instance deployment must terminate before arrival storage')
    runs = {str(run): point for run, point in returned_executions(episode)}
    # Cache verification may restore a prior own-library record. Recompact its
    # existing verified archive as well; no evidence/source is transferred to C.
    for row in list(state.get('results', {}).values())+[state.get('deployment_record')]:
        if row:
            index = Path(row['run_directory'])/'evidence_archive.json'
            if index.is_file():
                record = read(index)
                if record['status'] == 'RESTORED_E3_RAW_ARCHIVE_RETAINED':
                    runs[str(Path(row['run_directory']))] = Path(record['point_directory'])
    events = []
    for run, point in sorted(runs.items()):
        began, cpu = time.monotonic(), time.process_time();result = archive_execution(Path(run), point)
        events.append({'status': result['status'], 'point_directory': str(point), 'run_directory': run, 'archive_bytes': result.get('archive_bytes'),
            'operation_wall_seconds': time.monotonic()-began, 'operation_process_CPU_seconds': time.process_time()-cpu,
            'new_physical_calls': 0})
    return {'status': 'SEALED_E3_SEARCH_EVIDENCE_STORED', 'phase_preserved': state['phase'],
        'episode_directory': str(episode), 'events': events, 'hidden_evaluation_dispatched': False,
        'hidden_evidence_exported': False, 'new_physical_calls': 0}


def archive_search(episode):
    episode = Path(episode).resolve()
    with (episode/'private/backend.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = archive_returned_points(episode)
        save(episode/'private/search_evidence_archive.json', result)
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--point', type=Path);group.add_argument('--episode', type=Path);group.add_argument('--restore-run', type=Path)
    group.add_argument('--sealed-search', type=Path)
    parser.add_argument('--measure-only', action='store_true');args = parser.parse_args()
    if args.measure_only and (args.sealed_search or args.restore_run):
        parser.error('--measure-only applies to --point or --episode')
    result = archive_search(args.sealed_search) if args.sealed_search else restore_run(args.restore_run) if args.restore_run else archive_point(args.point, args.measure_only) if args.point else archive_episode(args.episode, args.measure_only)
    print(json.dumps({key: value for key, value in result.items() if key != 'file_members'}), flush=True)
