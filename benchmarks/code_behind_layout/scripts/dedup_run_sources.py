"""Hardlink byte-identical frozen source-pack files inside completed physical run directories (nothing is deleted).

Every isolated physical run keeps a complete copy of the candidate's source tree under <run>/source. All files other
than the edited module are byte-identical to the frozen source pack, so for every finished run (manifest status not
RUNNING, both containers exited) each <run>/source/<file> whose bytes equal <pack>/<file> is replaced by a hard link to
the pack file through an atomic rename. Bytes, paths, names and permissions seen by TrustedPhysicalStore are unchanged
(hard links are ordinary files, not symlinks); only the disk footprint shrinks. A receipt is appended per pass.

    python3 scripts/dedup_run_sources.py --roots runs/train_collection [--dry-run]
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import filecmp

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / 'runtime/train_collections/c01_collection_v1/source_pack'


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--roots', nargs='+', default=['runs/train_collection']); p.add_argument('--dry-run', action='store_true'); a = p.parse_args()
    pack_files = {str(q.relative_to(PACK)): q for q in PACK.rglob('*') if q.is_file()}
    pack_dev = PACK.stat().st_dev; linked = 0; saved = 0; runs = 0; skipped = 0
    for root in a.roots:
        for manifest in (ROOT / root).rglob('executor_*/manifest.json'):
            run = manifest.parent
            try: m = json.loads(manifest.read_text())
            except ValueError: continue
            stages = [m.get(k) for k in ('candidate', 'trusted') if m.get(k)]
            if m.get('status') == 'RUNNING' or not stages or any((s.get('container_state') or {}).get('Running') is not False for s in stages): skipped += 1; continue
            source = run / 'source'
            if not source.is_dir(): continue
            runs += 1
            for name, pack_file in pack_files.items():
                target = source / name
                if not target.is_file() or target.is_symlink(): continue
                st = target.stat()
                if st.st_nlink > 1 and st.st_ino == pack_file.stat().st_ino: continue
                if st.st_dev != pack_dev or st.st_size != pack_file.stat().st_size or not filecmp.cmp(target, pack_file, shallow=False): continue
                if not a.dry_run:
                    tmp = target.with_name(target.name + '.linktmp')
                    os.link(pack_file, tmp); os.replace(tmp, target)
                linked += 1; saved += st.st_size
    receipt = {'at_utc': datetime.now(timezone.utc).isoformat(), 'roots': a.roots, 'finished_runs_seen': runs, 'running_or_unfinished_skipped': skipped,
               'files_hardlinked': linked, 'bytes_freed': saved, 'dry_run': a.dry_run, 'pack': str(PACK), 'bytes_changed': 0, 'files_deleted': 0}
    if not a.dry_run:
        with (ROOT / 'results/derived/run_source_dedup_receipts.jsonl').open('a') as f: f.write(json.dumps(receipt) + '\n')
    print(json.dumps(receipt))


if __name__ == '__main__': main()
