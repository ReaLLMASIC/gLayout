"""Compress one terminal E2 executor run; retain geometry needed for de-dup.

This execution-host-only archive includes every original regular file. Before
removing duplicated heavy working trees, compare every archived member byte by
byte with its original. Private references and raw traces stay on this host.
"""
import argparse
import json
from pathlib import Path
import stat
import tarfile
import time


def archive(run, *, retain_accepted_gds):
    run = Path(run).resolve()
    if not run.name.startswith("executor_"):
        raise ValueError("Expected one E2 executor run")
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest["status"] == "RUNNING" or "E2" not in manifest["phase"]:
        raise ValueError("Only terminal E2 evidence may be compressed")
    result = run / "raw_archive.json"
    if result.exists():
        previous = json.loads(result.read_text())
        if previous.get("cleanup_complete"):
            return previous
    else:
        previous = None
    started, cpu = time.monotonic(), time.thread_time()
    archive_path = run / "terminal_raw.tar.gz"
    temporary = run / "terminal_raw.tar.gz.partial"
    originals = sorted(p for p in run.rglob("*") if p.is_file() and p not in [archive_path, temporary, result])
    if any(p.is_symlink() for p in originals):
        raise ValueError("Raw archive requires regular original files")
    directory_modes = {str(p.relative_to(run)): stat.S_IMODE(p.stat().st_mode)
        for p in run.rglob("*") if p.is_dir()}
    reused_complete_archive = archive_path.exists()
    if not reused_complete_archive:
        with tarfile.open(temporary, "w:gz", compresslevel=5) as output:
            for relative in sorted(directory_modes):
                output.add(run / relative, arcname=relative, recursive=False)
            for path in originals:
                output.add(path, arcname=str(path.relative_to(run)), recursive=False)
    verified_path = archive_path if reused_complete_archive else temporary
    with tarfile.open(verified_path, "r:gz") as saved:
        members = {member.name: member for member in saved.getmembers() if member.isfile()}
        additional = []
        for path in originals:
            relative = str(path.relative_to(run))
            if relative not in members:
                if reused_complete_archive:
                    additional.append(relative)
                    continue
                raise ValueError("Original file is absent from newly created archive: "+relative)
            with path.open("rb") as original, saved.extractfile(relative) as compressed:
                while True:
                    left, right = original.read(1024*1024), compressed.read(1024*1024)
                    if left != right:
                        raise ValueError("Archive differs from original: "+str(path))
                    if not left:
                        break
        # Read members whose working copy was already removed by an earlier
        # interrupted cleanup. Never replace a complete archive with a subset.
        for relative in members:
            if not (run / relative).exists():
                with saved.extractfile(relative) as compressed:
                    while compressed.read(1024*1024):
                        pass
    if not reused_complete_archive:
        temporary.replace(archive_path)
    record = previous or {"scope": "execution_host_private_E2_terminal_raw_archive", "archive": str(archive_path),
        "archive_bytes": archive_path.stat().st_size, "original_files": len(members),
        "byte_exact_all_members_verified": True, "directory_modes": directory_modes,
        "recovered_complete_archive_without_previous_index": reused_complete_archive,
        "additional_unarchived_files_retained": additional,
        "accepted_GDS_retained_for_exact_mask_comparison": retain_accepted_gds,
        "private_or_hidden_data_exported": False, "all_original_raw_recoverable": True}
    record.update(cleanup_complete=False, status="VERIFIED_CLEANUP_PENDING")
    # Persist the verified original inventory before modifying permissions or
    # removing any redundant working file. Retrying cleanup is then idempotent.
    result.write_text(json.dumps(record, indent=2)+"\n")
    evidence_keep = {"validation.json", "reference.spice", "extracted_lvs.spice", "device_intent.json", "rc_inventory.json", "provenance.json"}
    removed, removed_bytes = [], 0
    heavy = {"source", "library", "trusted", "candidate_output", "geometry_packages", "headless_mask", "blocked_package", "empty"}
    for name, member in members.items():
        relative, path = Path(name), run / name
        delete = relative.parts[0] in heavy
        if relative.parts[0] == "accepted":
            delete = not retain_accepted_gds
        elif relative.parts[0] == "evidence":
            delete = relative.name not in evidence_keep and not relative.name.endswith(("_analysis_validation.json", "_process_resource.json"))
        elif relative.parts[0] in ["candidate_stage", "trusted_stage"]:
            delete = relative.name not in ["resource_usage.json", "invocation.json"]
        if delete:
            removed_bytes += member.size
            removed.append(str(relative))
            if path.exists():
                path.parent.chmod(stat.S_IMODE(path.parent.stat().st_mode) | stat.S_IRWXU)
                path.unlink()
    for directory in sorted((p for p in run.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        if not any(directory.iterdir()):
            directory.parent.chmod(stat.S_IMODE(directory.parent.stat().st_mode) | stat.S_IRWXU)
            directory.rmdir()
    record.update(cleanup_complete=True, status="COMPLETE", removed_redundant_working_files=removed,
        removed_uncompressed_bytes=removed_bytes, wall_seconds=time.monotonic()-started,
        software_CPU_seconds=time.thread_time()-cpu,
        CPU_scope="actual archive-caller thread CPU; component of total host controller CPU")
    result.write_text(json.dumps(record, indent=2)+"\n")
    return record


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    p.add_argument("--retain-accepted-gds", action="store_true")
    a = p.parse_args()
    print(json.dumps(archive(a.run, retain_accepted_gds=a.retain_accepted_gds)))
