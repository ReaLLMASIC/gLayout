#!/usr/bin/env python3
"""Prepare public model files and preserve an existing service; never use a GPU."""
import argparse
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import resource
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request

REPO = "Qwen/Qwen2.5-Coder-32B-Instruct"
REVISION = "381fc969f78efac66bc87ff7ddeadb7e73c218a7"
GIB = 1024 ** 3
REMOTE_ROOT = "/srv/code-behind-layout"
FORMAL_E4_CHECKPOINT_ROOT = "/dev/shm/cbl-formal-e4/checkpoints"
BACKUP_INVOCATION_LOG = Path(__file__).resolve().parents[1]/'checkpoints/backup_invocations.jsonl'
SSH = ["ssh", "-i", "~/.ssh/cbl_server_key", "-o", "BatchMode=yes",
       "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=12",
       "-o", "ControlPath=/tmp/cbl-ssh-control", "cbl-server"]


def compile_data(args):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src.training import TrustedPhysicalStore, admit_candidates, build_matched_samples, sample_identity
    registry = json.loads(args.registry.read_text())
    candidates = [json.loads(line) for line in args.candidates.read_text().splitlines() if line.strip()]
    rule = json.loads(args.label_rule.read_text())
    admitted = admit_candidates(candidates, registry, TrustedPhysicalStore(args.evidence_root, registry))
    datasets, report = build_matched_samples(admitted, rule)
    if any(not rows for rows in datasets.values()):
        raise ValueError("Real candidate pool does not yet yield all four matched training datasets: " + json.dumps(report))
    if args.output.exists():
        raise ValueError("Prepared data directory already exists; preserve the earlier candidate pool")
    args.output.mkdir(parents=True)
    for method, rows in datasets.items():
        (args.output / (method + ".jsonl")).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    (args.output / "admitted_candidates.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in admitted))
    (args.output / "trusted_evidence_manifest.json").write_text(json.dumps({"status": "admitted", "role": "formal_train",
        "evidence_root": str(args.evidence_root.resolve()), "admitted_sample_ids": [row["sample_id"] for rows in datasets.values() for row in rows],
        "sample_sha256": {row["sample_id"]: sample_identity(row) for rows in datasets.values() for row in rows},
        "registry_sha256": hashlib.sha256(args.registry.read_bytes()).hexdigest(),
        "candidate_ids": [row["candidate_id"] for row in admitted], "label_rule": rule}, indent=2) + "\n")
    shutil.copyfile(args.registry, args.output / "split_registry.json")
    shutil.copyfile(args.training_config, args.output / "training_config.json")
    (args.output / "preparation_report.json").write_text(json.dumps(report, indent=2) + "\n")
    config = json.loads(args.training_config.read_text())
    manifest = {"status": "draft_prepared", "role": "formal_training", "training_config": "training_config.json",
                "split_registry": "split_registry.json", "trusted_evidence_manifest": "trusted_evidence_manifest.json",
                "backbone_snapshot": str(args.backbone_snapshot), "seeds": config["seeds"],
                "methods": {method: {"samples": method + ".jsonl"} for method in datasets}}
    for method in ("T3", "T4"):
        manifest["methods"][method]["starting_t1_checkpoints"] = {}
    manifest["methods"]["T1"]["selected_checkpoints"] = {}
    (args.output / "training_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"status": "PREPARED_NOT_FROZEN", "report": report, "output": str(args.output)}))


def remote_python(code, *arguments):
    command = "python3 -c " + shlex.quote(code) + " " + " ".join(shlex.quote(str(value)) for value in arguments)
    result = subprocess.run(SSH + [command], text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


CHECKPOINT_INVENTORY = r'''
import hashlib,json,pathlib,sys
root=pathlib.Path("/srv/code-behind-layout/checkpoints").resolve()
formal=pathlib.Path("/dev/shm/cbl-formal-e4/checkpoints").resolve()
checkpoint=pathlib.Path(sys.argv[1])
if checkpoint.is_symlink() or not any(checkpoint.resolve().is_relative_to(p) for p in (root,formal)):
    raise ValueError("Only this study's checkpoint tree can be backed up")
checkpoint=checkpoint.resolve()
if checkpoint.is_relative_to(formal):
    import re
    if not re.fullmatch(r'T[1-4]/seed-(41|73|109)/checkpoint-[0-9]{7}',checkpoint.relative_to(formal).as_posix()):
        raise ValueError("Unexpected formal E4 checkpoint identity")
if not (checkpoint/"complete.json").is_file() or not (checkpoint/"training_state.pt").is_file():
    raise ValueError("Incomplete/nonresumable checkpoint")
rows=[]
for path in sorted(checkpoint.rglob("*")):
    if path.is_symlink():raise ValueError("Checkpoint contains a symlink")
    if path.is_file():
        digest=hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda:stream.read(8*1024*1024),b""):digest.update(chunk)
        rows.append({"path":str(path.relative_to(checkpoint)),"bytes":path.stat().st_size,"sha256":digest.hexdigest()})
if not any(row["path"].endswith(".safetensors") for row in rows):raise ValueError("Adapter weights missing")
print(json.dumps({"checkpoint":str(checkpoint),"files":rows,"bytes":sum(row["bytes"] for row in rows)}))
'''


def checkpoint_backup_relative(checkpoint):
    """The existing disk tree plus one explicitly owned formal tmpfs tree."""
    checkpoint=Path(checkpoint)
    if not checkpoint.is_absolute() or '..' in checkpoint.parts:
        raise ValueError('A canonical absolute checkpoint path is required')
    canonical=Path(REMOTE_ROOT)/'checkpoints';formal=Path(FORMAL_E4_CHECKPOINT_ROOT)
    if checkpoint.is_relative_to(canonical):return checkpoint.relative_to(canonical)
    if checkpoint.is_relative_to(formal):
        relative=checkpoint.relative_to(formal)
        if not re.fullmatch(r'T[1-4]/seed-(41|73|109)/checkpoint-[0-9]{7}',relative.as_posix()):
            raise ValueError('Unexpected formal E4 checkpoint identity')
        return Path('formal_e4')/relative
    raise ValueError('Checkpoint is outside the two explicit study roots')


def backup_checkpoint(args):
    """Checksum a completed checkpoint, copy it locally, then optionally retire it.

    Cleanup is opt-in and requires a host-owned retention manifest naming active
    recovery points and T1 references. Missing retention information fails closed.
    """
    started=time.monotonic();cpu_started=time.process_time();child_started=resource.getrusage(resource.RUSAGE_CHILDREN)
    local_project = Path(__file__).resolve().parents[1]
    local_root = (local_project / "checkpoints").resolve()
    args.local_root = args.local_root.resolve()
    if not args.local_root.is_relative_to(local_root):
        raise ValueError("Local checkpoint backup must remain inside this study's ignored checkpoints directory")
    inventory = remote_python(CHECKPOINT_INVENTORY, args.remote_checkpoint)
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", inventory["checkpoint"]):
        raise ValueError("Checkpoint path contains unsupported transfer characters")
    relative = checkpoint_backup_relative(inventory["checkpoint"])
    if relative.parts[0]=='formal_e4' and args.local_root!=local_root:
        raise ValueError('Formal E4 backups use this project checkpoints/formal_e4 only')
    if relative.parts[0]=='formal_e4' and args.cleanup_remote:
        raise ValueError('Formal E4 backup never retires remote checkpoints; explicit coordinator review is required')
    destination = args.local_root / relative
    if destination.exists():
        raise ValueError("Backup destination already exists; do not overwrite a prior delivery")
    if shutil.disk_usage(local_project).free < inventory["bytes"] + 2 * GIB:
        raise RuntimeError("Insufficient local backup space")
    staging = destination.with_name(destination.name + ".backup-in-progress")
    if staging.exists():
        raise ValueError("An incomplete earlier backup exists; inspect/recover it explicitly")
    staging.parent.mkdir(parents=True, exist_ok=True)
    scp = ["scp", "-r", "-i", "~/.ssh/cbl_server_key", "-o", "BatchMode=yes",
           "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=12", "-o", "ControlPath=/tmp/cbl-ssh-control",
           "cbl-server:" + inventory["checkpoint"], str(staging)]
    subprocess.run(scp, check=True)
    actual = []
    for path in sorted(staging.rglob("*")):
        if path.is_symlink():
            raise ValueError("Backup unexpectedly contains a symlink")
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                    digest.update(chunk)
            actual.append({"path": str(path.relative_to(staging)), "bytes": path.stat().st_size, "sha256": digest.hexdigest()})
    if actual != inventory["files"]:
        raise ValueError("Backup checksum/size inventory differs; remote source retained")
    manifest = {**inventory, "status": "CHECKSUM_VERIFIED", "local_checkpoint": str(destination),
                "verified_at_utc": datetime.now(timezone.utc).isoformat(), "remote_cleanup": "not_requested"}
    child=resource.getrusage(resource.RUSAGE_CHILDREN)
    manifest['backup_costs']={'wall_seconds':time.monotonic()-started,'local_process_CPU_seconds':time.process_time()-cpu_started,
        'local_child_CPU_seconds':child.ru_utime+child.ru_stime-child_started.ru_utime-child_started.ru_stime,
        'remote_CPU_seconds':None,'transferred_file_bytes':inventory['bytes'],
        'scope':'This backup invocation; network wall is not CPU time. Remote inventory CPU was not observed.'}
    (staging / "backup_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    staging.rename(destination)
    if args.cleanup_remote:
        cleanup = r'''
import hashlib,json,pathlib,shutil,sys
root=pathlib.Path("/srv/code-behind-layout/checkpoints").resolve()
checkpoint=pathlib.Path(sys.argv[1]).resolve()
expected=json.loads(sys.argv[2])
retention=json.loads((root/"retention.json").read_text())
protected={str(pathlib.Path(p).resolve()) for name in ("active_checkpoints","t1_reference_checkpoints") for p in retention[name]}
if not checkpoint.is_relative_to(root) or str(checkpoint) in protected or checkpoint==root:
    raise ValueError("Active recovery points and T1 references cannot be cleaned")
if str(checkpoint) not in retention.get("retired_checkpoints",[]):
    raise ValueError("Checkpoint has not been explicitly retired by the orchestrator")
actual=[]
for path in sorted(checkpoint.rglob("*")):
    if path.is_symlink():raise ValueError("Checkpoint changed after backup")
    if path.is_file():
        digest=hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda:stream.read(8*1024*1024),b""):digest.update(chunk)
        actual.append({"path":str(path.relative_to(checkpoint)),"bytes":path.stat().st_size,"sha256":digest.hexdigest()})
if actual!=expected:raise ValueError("Checkpoint changed after backup; retained")
shutil.rmtree(checkpoint)
print(json.dumps({"status":"RETIRED_AFTER_VERIFIED_LOCAL_BACKUP","checkpoint":str(checkpoint)}))
'''
        result = remote_python(cleanup, inventory["checkpoint"], json.dumps(inventory["files"]))
        manifest["remote_cleanup"] = result["status"]
        (destination / "backup_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"status": manifest["status"], "local_checkpoint": str(destination),
                      "bytes": inventory["bytes"], "remote_cleanup": manifest["remote_cleanup"]}))
    return manifest


def write_private(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
    path.chmod(0o600)


def snapshot_service(pid, destination):
    """Keep argv private. Save only explicitly noncredential environment variables."""
    proc = Path("/proc") / str(pid)
    argv = [part.decode() for part in (proc / "cmdline").read_bytes().split(b"\0") if part]
    if not argv or "vllm" not in " ".join(argv).lower():
        raise ValueError("Requested PID is not the expected vLLM service")
    entries = [part.split(b"=", 1) for part in (proc / "environ").read_bytes().split(b"\0") if b"=" in part]
    allow = {"PATH", "VIRTUAL_ENV", "LD_LIBRARY_PATH", "PYTHONPATH", "CUDA_VISIBLE_DEVICES",
             "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "LANG", "LC_ALL",
             "HF_HOME", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE",
             "VLLM_USE_V1", "VLLM_ATTENTION_BACKEND", "NCCL_P2P_DISABLE",
             "NCCL_IB_DISABLE", "CUDA_DEVICE_ORDER", "TOKENIZERS_PARALLELISM"}
    environment = {k.decode(): v.decode() for k, v in entries if k.decode() in allow}
    record = {"pid": pid, "captured_at_utc": datetime.now(timezone.utc).isoformat(),
              "argv": argv, "cwd": os.readlink(str(proc / "cwd")),
              "environment": environment, "environment_policy": "explicit_noncredential_allowlist",
              "proc_starttime_ticks": (proc / "stat").read_text().split()[21],
              "executable": os.readlink(str(proc / "exe"))}
    write_private(destination, record)
    restore = Path(destination).with_name("restore_vllm.py")
    restore.write_text('''#!/usr/bin/env python3
import json, os, pathlib, socket, subprocess
root = pathlib.Path(__file__).resolve().parent
record = json.loads((root / "vllm_restart.json").read_text())
with socket.socket() as connection:
    if connection.connect_ex(("127.0.0.1", 8113)) == 0:
        raise SystemExit("Port 8113 already occupied; service not started")
environment = {key: value for key, value in os.environ.items()
               if not any(word in key.upper() for word in ("TOKEN", "SECRET", "API_KEY", "PASSWORD"))}
environment.update(record["environment"])
with (root / "vllm_restore.log").open("ab") as log:
    process = subprocess.Popen(record["argv"], cwd=record["cwd"], env=environment,
                               stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                               start_new_session=True)
(root / "restored_pid.txt").write_text(str(process.pid) + "\\n")
print("Service restart submitted; PID", process.pid)
''')
    restore.chmod(0o700)
    print(json.dumps({"status": "SNAPSHOT_SAVED_SERVICE_UNCHANGED", "path": str(destination),
                      "restore_program": str(restore), "argv_items": len(argv),
                      "environment_keys": sorted(environment)}))


def model_metadata():
    request = urllib.request.Request("https://huggingface.co/api/models/" + REPO + "/revision/" + REVISION + "?blobs=true",
                                     headers={"User-Agent": "iscas-training-preparation/1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.load(response)
    if data.get("sha") != REVISION or data.get("cardData", {}).get("license") != "apache-2.0":
        raise ValueError("Public model revision/license differs from the selected metadata")
    files = [{"name": row["rfilename"], "bytes": row.get("size", row.get("lfs", {}).get("size"))}
             for row in data["siblings"] if row["rfilename"].endswith(".safetensors")]
    if len(files) != 14 or any(not isinstance(row["bytes"], int) for row in files):
        raise ValueError("Unexpected shard inventory")
    return {"repo_id": REPO, "revision": REVISION, "license": "apache-2.0", "weight_files": files,
            "weight_bytes": sum(row["bytes"] for row in files),
            "source": "https://huggingface.co/" + REPO + "/tree/" + REVISION}


def download_model(cache_root, status_path):
    begin = time.monotonic()
    cache_root = Path(cache_root).resolve()
    if not str(cache_root).startswith("/dev/shm/cbl-hf-cache"):
        raise ValueError("Model preparation requires the explicitly assigned shared-memory cache")
    cache_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    cache_root.chmod(0o700)
    # Deliberately disable implicit credentials and Xet; all caches still have explicit locations.
    os.environ.update({"HF_HOME": str(cache_root), "HF_HUB_CACHE": str(cache_root / "hub"),
                       "HF_XET_CACHE": str(cache_root / "xet"), "HF_ASSETS_CACHE": str(cache_root / "assets"),
                       "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "HF_HUB_DISABLE_XET": "1",
                       "HF_HUB_ENABLE_HF_TRANSFER": "0", "TOKENIZERS_PARALLELISM": "false",
                       "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2"})
    if hasattr(os, "sched_getaffinity"):
        os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:4])
    metadata = model_metadata()
    already = sum(p.stat().st_size for p in cache_root.rglob("*") if p.is_file() and not p.is_symlink())
    remaining = max(0, metadata["weight_bytes"] - already)
    available = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                         if line.startswith("MemAvailable:"))) * 1024
    if available < remaining + 24 * GIB or shutil.disk_usage(cache_root).free < remaining + 2 * GIB:
        raise RuntimeError("Insufficient available RAM/shared memory while retaining a 24 GiB RAM reserve")
    status = {**metadata, "status": "DOWNLOADING", "cache_root": str(cache_root),
              "started_at_utc": datetime.now(timezone.utc).isoformat(), "reserve_ram_bytes": 24 * GIB,
              "max_workers": 2, "maximum_cpu_affinity": 4,
              "persistence": "Weights reside in /dev/shm and disappear after reboot; rerun this command at fixed revision",
              "redownload_command": [sys.executable, str(Path(__file__).resolve()), "download",
                                     "--cache-root", str(cache_root), "--status-path", str(status_path)]}
    write_private(status_path, status)
    try:
        from huggingface_hub import snapshot_download
        snapshot = Path(snapshot_download(repo_id=REPO, revision=REVISION, token=False,
                    cache_dir=str(cache_root / "hub"), max_workers=2,
                    allow_patterns=["*.safetensors", "*.json", "tokenizer*", "vocab*", "merges.txt", "README.md", "LICENSE*"]))
        for row in metadata["weight_files"]:
            if (snapshot / row["name"]).stat().st_size != row["bytes"]:
                raise ValueError("Downloaded shard size differs from public metadata")
        for name in ["config.json", "tokenizer_config.json", "tokenizer.json", "model.safetensors.index.json"]:
            if not (snapshot / name).is_file():
                raise ValueError("Missing model/tokenizer artifact: " + name)
        status.update(status="READY_ON_SHARED_MEMORY", snapshot=str(snapshot),
                      completed_at_utc=datetime.now(timezone.utc).isoformat())
    except BaseException as exc:
        status.update(status="FAILED_RETRYABLE", error_type=type(exc).__name__,
                      ended_at_utc=datetime.now(timezone.utc).isoformat())
        write_private(status_path, status)
        raise
    usage = resource.getrusage(resource.RUSAGE_SELF)
    status.update(wall_seconds=time.monotonic() - begin, cpu_user_seconds=usage.ru_utime,
                  cpu_system_seconds=usage.ru_stime, maximum_process_rss_kib=usage.ru_maxrss,
                  gpu_allocated_seconds=0)
    write_private(status_path, status)
    print(json.dumps({k: status[k] for k in ["status", "snapshot", "revision", "weight_bytes"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    service = sub.add_parser("snapshot-service")
    service.add_argument("--pid", type=int, required=True)
    service.add_argument("--destination", type=Path, required=True)
    download = sub.add_parser("download")
    download.add_argument("--cache-root", type=Path, required=True)
    download.add_argument("--status-path", type=Path, required=True)
    compile_parser = sub.add_parser("compile-data")
    for name in ["registry", "candidates", "label-rule", "evidence-root", "training-config", "backbone-snapshot", "output"]:
        compile_parser.add_argument("--" + name, type=Path, required=True)
    backup = sub.add_parser("backup-checkpoint")
    backup.add_argument("--remote-checkpoint", required=True)
    backup.add_argument("--local-root", type=Path, default=Path(__file__).resolve().parents[1] / "checkpoints")
    backup.add_argument("--cleanup-remote", action="store_true")
    args = parser.parse_args()
    if args.command == "snapshot-service":
        snapshot_service(args.pid, args.destination)
    elif args.command == "download":
        download_model(args.cache_root, args.status_path)
    elif args.command == "compile-data":
        compile_data(args)
    else:
        started=time.monotonic();cpu=time.process_time();before=resource.getrusage(resource.RUSAGE_CHILDREN)
        success=False;completed=None
        try:
            completed=backup_checkpoint(args);success=True
        finally:
            after=resource.getrusage(resource.RUSAGE_CHILDREN)
            row={'ended_at_utc':datetime.now(timezone.utc).isoformat(),'remote_checkpoint':args.remote_checkpoint,
                'success':success,'wall_seconds':time.monotonic()-started,'local_process_CPU_seconds':time.process_time()-cpu,
                'local_child_CPU_seconds':after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
                'remote_CPU_seconds':None,'payload_file_bytes':completed['bytes']if success else None,
                'transferred_file_bytes':completed['bytes']if success else None,'wire_bytes':None,
                'scope':'This backup CLI invocation; inclusive totals, not additional to manifest backup_costs. Failed transfer bytes unknown.'}
            try:
                BACKUP_INVOCATION_LOG.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                fd=os.open(str(BACKUP_INVOCATION_LOG),os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
                with os.fdopen(fd,'w')as stream:stream.write(json.dumps(row)+'\n')
            except OSError as error:
                print(json.dumps({'backup_invocation_telemetry':row,'ledger_write_error':str(error)}),file=sys.stderr)


if __name__ == "__main__":
    main()
