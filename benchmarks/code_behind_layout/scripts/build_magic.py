#!/usr/bin/env python3
"""Build pinned official Magic separately, preserving the existing tool install."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time

root = Path(__file__).resolve().parents[1]
source = root/"vendor/magic-current"
version = (source/"VERSION").read_text().strip()
if version != "8.3.685":
    raise SystemExit("Unexpected source version; inspect it before changing the build")
out = root/"logs/magic_build_8.3.685"
out.mkdir(parents=True, exist_ok=True)
command = ["docker","run","--rm","--pull=never","--network","none",
    "--user",f"{os.getuid()}:{os.getgid()}","--cpus","4","--memory","4g",
    "-v",str(root)+":/work","-w","/work/vendor/magic-current",
    "--entrypoint","/bin/bash","hpretl/iic-osic-tools:chipathon","-c",
    "./configure --prefix=/work/runtime/magic-8.3.685 --without-x --disable-magic-builddate --disable-ccache && make -j4 && make install"]
record = {"version":version,"source_url":"https://github.com/RTimothyEdwards/magic.git",
    "source_revision":subprocess.check_output(["git","-C",str(source),"rev-parse","HEAD"],text=True).strip(),
    "argv":command,"started_at_utc":datetime.now(timezone.utc).isoformat(),"status":"RUNNING"}
(out/"manifest.json").write_text(json.dumps(record,indent=2)+"\n")
started = time.monotonic()
with (out/"build.log").open("w") as log:
    run = subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=900)
record.update(returncode=run.returncode,status="COMPLETED" if run.returncode==0 else "FAILED",
    wall_seconds=time.monotonic()-started,ended_at_utc=datetime.now(timezone.utc).isoformat())
(out/"manifest.json").write_text(json.dumps(record,indent=2)+"\n")
print(json.dumps(record,indent=2))
raise SystemExit(run.returncode)
