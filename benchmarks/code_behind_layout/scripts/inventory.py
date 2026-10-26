#!/usr/bin/env python3
"""Bounded read-only inventory; usable locally or through `ssh ... python3 -`."""
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=12)
        return {"argv": args, "returncode": result.returncode,
                "stdout": result.stdout[:16000], "stderr": result.stderr[:4000]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"argv": args, "returncode": None, "error": str(exc)}


def collect():
    tools = {name: shutil.which(name) for name in
             ("python3", "git", "nvidia-smi", "magic", "netgen", "ngspice",
              "klayout", "latexmk", "pdflatex", "tmux", "docker", "apptainer")}
    packages = {}
    for name in ("glayout", "gdsfactory", "gdstk", "torch", "transformers", "peft", "trl"):
        try:
            packages[name] = importlib.util.find_spec(name) is not None
        except (ValueError, ImportError):
            packages[name] = False
    home = Path.home()
    try:
        directories = sorted(p.name for p in home.iterdir()
                             if not p.name.startswith(".") and p.is_dir())[:80]
    except OSError as exc:
        directories = {"error": str(exc)}
    result = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "hostname": socket.gethostname(), "os": platform.platform(),
              "python": sys.version, "python_executable": sys.executable,
              "cwd": str(Path.cwd()), "home": str(home), "cpu_count": os.cpu_count(),
              "disk_bytes": dict(zip(("total", "used", "free"), shutil.disk_usage(Path.cwd()))),
              "tools": tools, "python_packages": packages,
              "environment_paths": {k: os.environ.get(k) for k in
                                    ("PDK_ROOT", "PDK", "VIRTUAL_ENV", "CONDA_PREFIX")},
              "home_directory_names": directories}
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        result["memory"] = meminfo.read_text().splitlines()[:3]
    elif platform.system() == "Darwin":
        result["memory"] = command(["sysctl", "-n", "hw.memsize"])
    if tools["nvidia-smi"]:
        result["gpu"] = command([tools["nvidia-smi"],
                                  "--query-gpu=name,memory.total,memory.used,driver_version,utilization.gpu",
                                  "--format=csv"])
        result["gpu_processes"] = command([tools["nvidia-smi"],
                                            "--query-compute-apps=pid,process_name,used_gpu_memory",
                                            "--format=csv"])
    else:
        result["gpu"] = None
    result["git_version"] = command([tools["git"], "--version"]) if tools["git"] else None
    return result


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2))
