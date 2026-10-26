"""Retain completed E1 raw evidence in verified private compressed archives."""
import argparse
from datetime import datetime,timezone
import fcntl
import json
import os
from pathlib import Path,PurePosixPath
import resource
import shutil
import tarfile
import time

ROOT=Path(__file__).resolve().parents[1]
HEAVY=('private/physical','private/capsules','private/point_inputs')


def save(filename,value):
    temporary=filename.with_suffix(filename.suffix+'.tmp')
    temporary.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n');temporary.replace(filename)


def remove_verified_duplicate(directory):
    # Frozen candidate capsules contain directories with mode0555. Only their
    # verified duplicate copies are made writable, after the archive index exists.
    for current,_,_ in os.walk(directory):
        path=Path(current);path.chmod(path.stat().st_mode|0o700)
    shutil.rmtree(directory)


def archive(episode,measure_only=False):
    episode=episode.resolve();private=episode/'private'
    expected=ROOT/('runs/development/E1_matched' if measure_only else 'runs/formal/E1')
    if episode.parent!=expected.resolve():raise ValueError('Only a declared E1 episode can be archived')
    with (private/'backend.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        state=json.loads((private/'state.json').read_text())
        if not state['sealed'] or state.get('in_flight_point') or state['post_freeze_status'] not in ('COMPLETE','INCOMPLETE_UNKNOWN','ANCHOR_ONLY_DEVELOPMENT_SMOKE'):
            raise ValueError('The episode still has work in flight or an unsealed source')
        if not measure_only and (state['formal_trial'] is not True or state['post_freeze_status']=='ANCHOR_ONLY_DEVELOPMENT_SMOKE'):
            raise ValueError('Development records cannot be archived as formal episodes')
        index=private/'evidence_archive.json'
        if index.exists():
            previous=json.loads(index.read_text());target=Path(previous['archive'])
            if not target.is_file() or target.stat().st_size!=previous['archive_bytes']:
                raise ValueError('Previously verified private evidence archive is unavailable')
            if previous['measure_only']!=measure_only:raise ValueError('An archive cannot change its declared purpose')
            if not measure_only:
                for relative in HEAVY:
                    if (episode/relative).exists():remove_verified_duplicate(episode/relative)
                previous['status']='COMPRESSED_RAW_RETAINED';save(index,previous)
            return previous
        directories=[episode/name for name in HEAVY if (episode/name).is_dir()]
        files=sorted(path for directory in directories for path in [directory,*directory.rglob('*')])
        if any(path.is_symlink() or not (path.is_dir() or path.is_file()) for path in files):
            raise ValueError('The declared evidence tree contains an unexpected nonregular object')
        destination=ROOT/'private_checkpoints'/('E1_compression_controls' if measure_only else 'formal_E1')
        destination.mkdir(parents=True,exist_ok=True,mode=0o700)
        target=destination/(episode.name+'.tar.gz');temporary=target.with_suffix(target.suffix+'.partial')
        if target.exists():raise ValueError('Reconcile an existing archive without its completion index; never overwrite raw evidence')
        started=time.monotonic();before=resource.getrusage(resource.RUSAGE_SELF)
        with tarfile.open(temporary,'x:gz',compresslevel=6) as stream:
            for filename in files:stream.add(filename,arcname=str(filename.relative_to(episode)),recursive=False)
        members=0;raw_bytes=0
        with tarfile.open(temporary,'r:gz') as stream:
            for member in stream:
                name=PurePosixPath(member.name)
                if name.is_absolute() or '..' in name.parts or not any(member.name==p or member.name.startswith(p+'/') for p in HEAVY):
                    raise ValueError('Archive member escapes the completed evidence trees')
                original=episode/member.name;members+=1
                if member.isdir():
                    if not original.is_dir():raise ValueError('Archived directory changed')
                elif member.isfile():
                    if original.stat().st_size!=member.size:raise ValueError('Archived evidence length differs')
                    raw_bytes+=member.size
                    with original.open('rb') as actual:
                        stored=stream.extractfile(member)
                        while True:
                            chunk=stored.read(1024*1024)
                            if actual.read(len(chunk))!=chunk:raise ValueError('Archived raw evidence differs byte for byte')
                            if not chunk:break
                else:raise ValueError('Archive contains an unexpected object')
        if members!=len(files):raise ValueError('Evidence archive omitted a declared member')
        temporary.replace(target);after=resource.getrusage(resource.RUSAGE_SELF)
        record={'status':'VERIFIED_ARCHIVE_RAW_NOT_YET_REMOVED','verified_at_utc':datetime.now(timezone.utc).isoformat(),
            'episode':str(episode),'archive':str(target),'archive_bytes':target.stat().st_size,'regular_file_bytes':raw_bytes,
            'members':members,'compression_ratio':target.stat().st_size/raw_bytes if raw_bytes else None,
            'verification':'Every declared regular file streamed and compared byte for byte before removing its uncompressed copy',
            'archive_wall_seconds':time.monotonic()-started,'archive_CPU_seconds':after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
            'measure_only':measure_only,'hidden_evidence_exported':False,
            'retention':'All raw bytes stay on the trusted endpoint; summaries/state/source and the private archive index remain in place',
            'restore_command':'python3 scripts/archive_e1_episode.py --episode '+str(episode)+' --restore'}
        save(index,record)
        if not measure_only:
            for directory in directories:remove_verified_duplicate(directory)
            record['status']='COMPRESSED_RAW_RETAINED';save(index,record)
        return record


def restore(episode):
    episode=episode.resolve();record=json.loads((episode/'private/evidence_archive.json').read_text())
    if any((episode/name).exists() for name in HEAVY):raise ValueError('Restore requires absent uncompressed evidence trees; never overwrite')
    with tarfile.open(record['archive'],'r:gz') as stream:
        members=stream.getmembers()
        for member in members:
            name=PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts or not any(member.name==p or member.name.startswith(p+'/') for p in HEAVY) or not (member.isfile() or member.isdir()):
                raise ValueError('Archive entry is outside the recorded ordinary evidence trees')
        # All paths/types above are checked before extraction. extractall delays
        # directory attributes so original readonly capsules can be restored.
        stream.extractall(path=episode,members=members,filter='fully_trusted')
    return {'status':'RESTORED_RAW_WITHOUT_NEW_SIMULATION','episode':str(episode),'archive_retained':True}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--episode',type=Path,required=True)
    p.add_argument('--measure-only',action='store_true');p.add_argument('--restore',action='store_true');a=p.parse_args()
    if a.restore and a.measure_only:p.error('Choose restoration or development compression measurement')
    print(json.dumps(restore(a.episode) if a.restore else archive(a.episode,a.measure_only)))
