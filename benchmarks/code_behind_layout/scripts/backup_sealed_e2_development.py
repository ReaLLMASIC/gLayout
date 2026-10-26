"""Export exactly the sealed four-pool development evidence, without task domains."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def backup(summary, name):
    record = json.loads(summary.read_text())
    if record['all64_attempts_terminal'] is not True or record['candidate_attempts'] != 64:
        raise ValueError('Only the terminal, declared four-pool development study is exportable')
    candidates = [run for pool in record['pools'] for run in pool['raw_candidate_run_ids']]
    if len(candidates) != 64 or len(set(candidates)) != 64:
        raise ValueError('The sealed study must identify all 64 distinct attempts')
    ids = sorted(set(candidates + [pool['pool_id'] for pool in record['pools']]
                     + list(record['collector_run_ids'].values())))
    files = [summary] + [ROOT / pool['derived_pool'] for pool in record['pools']]
    for ident in ids:
        if not ident.startswith('phase0_') or not ident.endswith('_e2_development_pilot') or '/' in ident:
            raise ValueError('The development export cannot include task preparation or other runs')
        directory = ROOT / 'runs/phase0' / ident
        manifest = json.loads((directory / 'pilot_manifest.json').read_text())
        if manifest['status'] not in ('TOOL_COMPLETED', 'FAILED', 'TIMEOUT'):
            raise ValueError('A selected study record is still mutable')
        files.append(directory)
    archive = ROOT / 'private_checkpoints' / (name + '.tar.gz')
    with tarfile.open(archive, 'x:gz') as stream:
        for filename in files:
            stream.add(filename, arcname=str(filename.relative_to(ROOT)))
    result = {'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'Four sealed development pools; 64 attempts, four plans and four collectors; no formal hidden domains',
              'archive': str(archive), 'bytes': archive.stat().st_size,
              'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
              'candidate_attempts': 64, 'run_ids': ids}
    archive.with_suffix('').with_suffix('.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary', type=Path, default=ROOT / 'results/derived/e2_development_four_pool_sealed.json')
    parser.add_argument('--name', required=True)
    args = parser.parse_args()
    print(json.dumps(backup(args.summary, args.name)))
