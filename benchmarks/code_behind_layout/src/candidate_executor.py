"""Two-container experiment boundary: source -> GDS -> trusted physical evidence.

Run this module on the execution host. Neither the research root nor the complete
generator repository is mounted in the candidate container. The policy's visible
action gateway is separate from the backend's hidden-configuration entry point.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import time
import uuid

from src.model_adapter import validate_action,remaining_utc_budget


IMAGE = "hpretl/iic-osic-tools@sha256:7ef29be71a33b5b8994cde7f7476dfefd1af94f2922354242d1579346feec462"
PREFIX = "/headless/conda-env/miniconda3/envs/GLdev"

# PID 1 is trusted code, never imported into the candidate interpreter. Its child
# has no capabilities and cannot access the root-only telemetry volume. resource
# reports actual waited-for child CPU, not allocated CPUs multiplied by wall time.
LAUNCHER = r'''import json, os, pathlib, resource, subprocess, sys, time
uid, gid = int(sys.argv[1]), int(sys.argv[2])
os.chmod("/telemetry",0o700)
def drop():
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)
started=time.monotonic()
before=resource.getrusage(resource.RUSAGE_CHILDREN)
process=subprocess.run(sys.argv[3:], preexec_fn=drop)
after=resource.getrusage(resource.RUSAGE_CHILDREN)
result={"wall_seconds":time.monotonic()-started,
 "child_user_cpu_seconds":after.ru_utime-before.ru_utime,
 "child_system_cpu_seconds":after.ru_stime-before.ru_stime,
 "largest_child_max_rss_bytes":after.ru_maxrss*1024,
 "cpu_scope":"waited-for child processes; not an allocated CPU estimate",
 "returncode":process.returncode}
pathlib.Path("/telemetry/resource_usage.json").write_text(json.dumps(result,indent=2)+"\n")
sys.exit(process.returncode)
'''

# Candidate GDS text later becomes Magic/SPICE identifiers. The current interface
# requires simple names; reject embedded program delimiters before either tool.
GDS_BOUNDARY = r'''import json,pathlib,re,runpy,sys
import gdstk
gds=pathlib.Path(sys.argv[sys.argv.index("--gds")+1])
out=pathlib.Path(sys.argv[sys.argv.index("--output")+1])
try:
    library=gdstk.read_gds(gds)
except (ValueError,RuntimeError,OSError) as exc:
    (out/"gds_boundary.json").write_text(json.dumps({"accepted":False,"gds_parse_complete":False,
        "reason":"unreadable_candidate_GDS","parser_error":str(exc)},indent=2)+"\n")
    raise SystemExit(3)
bad=[]
for cell in library.cells:
    if not re.fullmatch(r"[A-Za-z0-9_$]+",cell.name):bad.append({"kind":"cell_name","cell":cell.name})
    for label in cell.labels:
        if not re.fullmatch(r"[A-Za-z0-9_$]+",label.text):bad.append({"kind":"label","cell":cell.name})
record={"accepted":not bad,"gds_parse_complete":True,"checks":"all GDS cell names and labels are simple nonempty ASCII identifiers",
        "cell_count":len(library.cells),"rejected_identifiers":bad}
(out/"gds_boundary.json").write_text(json.dumps(record,indent=2)+"\n")
if bad:raise SystemExit(3)
sys.argv[0]="/trusted/evaluate.py"
runpy.run_path("/trusted/evaluate.py",run_name="__main__")
'''


def _relative(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or str(path) != name:
        raise ValueError("A declared file must have a canonical relative path")
    return path


def copy_declared_files(source, names, destination):
    """Copy exact regular files; an editable checkout or directory is not an API."""
    source = Path(source).resolve()
    destination = Path(destination)
    for name in names:
        relative = _relative(name)
        original = source / relative
        if original.is_symlink() or not original.is_file() or original.resolve().is_relative_to(source) is False:
            raise ValueError("Declared source is absent, not regular, or escapes its root: " + name)
        # Parent symlinks could otherwise expose an undeclared external tree.
        if any(parent.is_symlink() for parent in original.parents if parent != source.parent):
            raise ValueError("Symlink components are outside the file declaration")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        target.chmod(0o444)


def apply_source_patch(source, patch, allowed_paths):
    packet = {"allowed_paths": list(allowed_paths), "visible_sources": {}, "visible_configurations": []}
    action = {"action":"propose_patch", "path":"", "patch":patch,
              "configuration_ids":[], "fidelity":"", "summary":"source edit"}
    validate_action(action, packet)
    # The source workspace contains only the declared ordinary files. git apply
    # adds a second independent path/hunk check and does not execute candidate code.
    source = Path(source).resolve()
    for name in allowed_paths:
        path = source / _relative(name)
        if path.exists() and (path.is_symlink() or not path.is_file()):
            raise ValueError("Patch destination is not an ordinary source file")
    args = ["git", "apply", "--whitespace=nowarn", "-"]
    subprocess.run(args[:2]+["--check"]+args[2:], input=patch, text=True, cwd=source,
                   check=True, capture_output=True)
    subprocess.run(args, input=patch, text=True, cwd=source, check=True, capture_output=True)


def accepted_gds(output, maximum_bytes=256*1024*1024):
    """Only this file crosses the candidate/trusted boundary, after termination."""
    output = Path(output)
    paths = list(output.iterdir())
    expected = output / "candidate.gds"
    if paths != [expected] or expected.is_symlink():
        raise ValueError("Candidate output must contain only candidate.gds, never reports or links")
    mode = expected.lstat().st_mode
    if not stat.S_ISREG(mode) or not 0 < expected.stat().st_size <= maximum_bytes:
        raise ValueError("Candidate GDS is absent, nonregular, empty, or exceeds the declared limit")
    return expected


class CandidateExecutor:
    def __init__(self, runtime, output_root, magic_runtime, image=IMAGE, timeout=600):
        self.runtime = Path(runtime).resolve()
        self.output_root = Path(output_root).resolve()
        self.magic_runtime = Path(magic_runtime).resolve()
        self.image = image
        self.timeout = timeout
        self.output_root.mkdir(parents=True, exist_ok=True)

    def _base(self, name, launcher):
        return ["docker", "run", "--pull=never", "--name", name,
            "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--cap-add", "SETUID", "--cap-add", "SETGID", "--cap-add", "KILL",
            "--security-opt", "no-new-privileges", "--pids-limit", "128",
            "--cpus", "2", "--memory", "8g", "--user", "0:0",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=512m,mode=1777",
            "--mount", "type=volume,target=/telemetry",
            "-v", str(self.runtime)+":"+PREFIX+":ro",
            "-v", str(launcher)+":/launcher.py:ro",
            "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1",
            "-e", "OMP_NUM_THREADS=1", "-e", "OPENBLAS_NUM_THREADS=1"]

    def _run(self, stage, name, command, timeout_seconds=None):
        stage.mkdir(parents=True)
        timeout_seconds=self.timeout if timeout_seconds is None else timeout_seconds
        started = time.monotonic()
        record = {"argv":command, "timeout_seconds":timeout_seconds,
                  "started_at_utc":datetime.now(timezone.utc).isoformat()}
        with (stage/"console.log").open("w") as log:
            try:
                process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=timeout_seconds)
                record.update(returncode=process.returncode, status="COMPLETED" if process.returncode==0 else "FAILED")
            except subprocess.TimeoutExpired:
                subprocess.run(["docker","kill",name], stdout=log, stderr=subprocess.STDOUT, timeout=20)
                record.update(returncode=None, status="TIMEOUT")
        record["wall_seconds"] = time.monotonic()-started
        # The container has stopped before evidence is copied or another stage is
        # started. Keeping it until this copy avoids trusting a writable mount.
        state = subprocess.run(["docker","inspect","--format","{{json .State}}",name],
                               text=True,capture_output=True,check=True)
        record["container_state"] = json.loads(state.stdout)
        if record["container_state"]["Running"]:
            raise RuntimeError("Candidate/evaluator container is still running")
        copied = subprocess.run(["docker","cp",name+":/telemetry/resource_usage.json",
                                 str(stage/"resource_usage.json")],capture_output=True,text=True)
        record["resource_usage_available"] = copied.returncode==0
        subprocess.run(["docker","rm","-v",name],capture_output=True,text=True,check=True)
        record["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
        (stage/"invocation.json").write_text(json.dumps(record,indent=2)+"\n")
        return record

    def execute(self, *, source_dir, source_paths, entrypoint, representation,
                configuration, trusted_dir, trusted_paths, library_dir=None,
                library_paths=(), fidelity="pex_spice", context=None,phase="development_boundary_calibration",
                generation_timeout_seconds=None,evaluator_timeout_seconds=None,execution_deadline_utc=None):
        context=dict(context or {})
        timeouts={"candidate":self.timeout if generation_timeout_seconds is None else generation_timeout_seconds,
                  "trusted":self.timeout if evaluator_timeout_seconds is None else evaluator_timeout_seconds}
        if any(type(value) not in (int,float) or not 0<value<float("inf") for value in timeouts.values()):
            raise ValueError("Each execution stage requires a finite positive timeout")
        if not (phase.startswith("development_") or phase in ("formal_train","formal_E1","formal_E2","formal_E3")):
            raise ValueError("Unsupported backend execution phase")
        if phase=="formal_train" and context.get("source_role") not in ("formal_train","trusted_evaluator_control"):
            raise ValueError("Formal execution requires an explicit backend source role")
        if phase=="formal_E1" and context.get("source_role") not in ("formal_E1_candidate","trusted_evaluator_control"):
            raise ValueError("Formal E1 execution requires its declared backend source role")
        if phase=="formal_E2" and context.get("source_role") not in ("formal_E2_candidate","trusted_evaluator_control"):
            raise ValueError("Formal E2 execution requires its declared backend source role")
        if phase=="formal_E3" and context.get("source_role") not in ("formal_E3_candidate","trusted_evaluator_control"):
            raise ValueError("Formal E3 execution requires its declared backend source role")
        if representation not in ["G0", "G1", "G2", "reuse"]:
            raise ValueError("Unknown composition interface")
        if fidelity not in ["geometry", "basic", "pex", "pex_spice"]:
            raise ValueError("Unknown physical fidelity")
        if entrypoint not in source_paths or "evaluate.py" not in trusted_paths:
            raise ValueError("Both declared source and trusted entrypoints are required")
        if representation=="G0" and library_paths:
            raise ValueError("G0 has no cell or composition library")
        if representation=="G1" and any(Path(p).suffix not in [".gds",".json"] for p in library_paths):
            raise ValueError("G1 exposes only frozen PCell GDS and pin metadata")
        run_id = "executor_"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ_")+uuid.uuid4().hex[:8]
        work = self.output_root/run_id
        work.mkdir()
        source = work/"source";source.mkdir()
        library = work/"library";library.mkdir()
        trusted = work/"trusted";trusted.mkdir()
        output = work/"candidate_output";output.mkdir();output.chmod(0o777)
        evidence = work/"evidence";evidence.mkdir();evidence.chmod(0o777)
        copy_declared_files(source_dir,source_paths,source)
        copy_declared_files(trusted_dir,trusted_paths,trusted)
        if library_paths:
            if library_dir is None:
                raise ValueError("Declared library files require a library root")
            copy_declared_files(library_dir,library_paths,library)
        config = work/"configuration.json"
        config.write_text(json.dumps(configuration,indent=2)+"\n");config.chmod(0o444)
        launcher = work/"launcher.py";launcher.write_text(LAUNCHER);launcher.chmod(0o444)
        gds_boundary=work/"gds_boundary.py";gds_boundary.write_text(GDS_BOUNDARY);gds_boundary.chmod(0o444)
        empty = work/"empty";empty.mkdir();empty.chmod(0o555)
        blocked = work/"blocked_package";blocked.mkdir()
        (blocked/"__init__.py").write_text("raise ModuleNotFoundError('Module is outside the declared composition interface')\n")
        (blocked/"__init__.py").chmod(0o444);blocked.chmod(0o555)
        headless = work/"headless_mask"
        (headless/"conda-env/miniconda3/envs/GLdev").mkdir(parents=True)
        manifest = {"run_id":run_id,"phase":phase,"source_role":context.get("source_role"),
            "representation":representation,"source_files":list(source_paths),
            "library_files":list(library_paths),"trusted_files":list(trusted_paths),
            "fidelity":fidelity,"status":"RUNNING","stage_timeouts_seconds":timeouts,
            "context":context,
            "boundary":"terminated candidate; single regular GDS; separate trusted container"}
        if execution_deadline_utc is not None:manifest['execution_deadline_utc']=execution_deadline_utc
        def stage_timeout(stage):
            remaining=remaining_utc_budget({'budget':{'deadline_utc':execution_deadline_utc}})
            return timeouts[stage] if remaining is None else min(timeouts[stage],max(0,remaining))
        def finish():
            if execution_deadline_utc is not None and stage_timeout('candidate')<=0:
                manifest['execution_status_before_budget_classification']=manifest['status']
                manifest.update(status='BUDGET_EXHAUSTED',reason='Absolute episode UTC budget exhausted; no further container stage permitted')
            (work/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
            return {'run_directory':str(work),'status':manifest['status'],
                'physical_result':manifest.get('physical_result'),'reason':manifest.get('reason')}
        (work/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
        name = "iscas-"+run_id.lower().replace("_","-")+"-candidate"
        candidate = self._base(name,launcher)
        # Mask image-bundled PDKs, examples, user homes and global Python
        # packages. No research/vendor/evaluator directory is mounted here.
        for hidden in ["/foss","/home","/root","/opt","/work","/usr/local/lib/python3.12/dist-packages",
                       "/usr/local/lib/python3.12/site-packages","/usr/lib/python3/dist-packages"]:
            candidate += ["-v",str(empty)+":"+hidden+":ro"]
        # Replace /headless without losing the nested explicitly mounted runtime.
        idx=candidate.index("-v")
        candidate[idx:idx] = ["-v",str(headless)+":/headless:ro"]
        packages=self.runtime/"lib/python3.10/site-packages"
        masked=[]
        runtime_packages=[]
        if representation in ["G0","G1"]:
            geometry_names=["gdstk","gdstk-0.9.62.dist-info","gdstk.libs",
                            "numpy","numpy-1.24.0.dist-info","numpy.libs"]
            geometry=work/"geometry_packages";geometry.mkdir()
            for package in geometry_names:
                original=packages/package
                if not original.is_dir():
                    raise ValueError("Pinned geometry dependency is absent: "+package)
                (geometry/package).mkdir()
            site=PREFIX+"/lib/python3.10/site-packages"
            candidate += ["-v",str(geometry)+":"+site+":ro"]
            for package in geometry_names:
                candidate += ["-v",str(packages/package)+":"+site+"/"+package+":ro"]
            masked.append(site+" (all except declared geometry dependencies)")
            runtime_packages=geometry_names
        for path in sorted(packages.iterdir()) if representation in ["G2","reuse"] else []:
            if path.name.startswith(("glayout", "__editable__")) or path.name.endswith(".egg-link") or (
                    representation in ["G0","G1"] and path.name.startswith("gdsfactory")):
                container=PREFIX+"/lib/python3.10/site-packages/"+path.name
                if path.is_dir():
                    candidate += ["-v",str(blocked)+":"+container+":ro"]
                else:
                    blank=work/("mask_"+str(len(masked)));blank.write_text("");blank.chmod(0o444)
                    candidate += ["-v",str(blank)+":"+container+":ro"]
                masked.append(container)
            else:
                runtime_packages.append(path.name)
        candidate += ["-v",str(source)+":/source:ro","-v",str(library)+":/library:ro",
            "-v",str(config)+":/configuration.json:ro","-v",str(output)+":/output:rw",
            "-w","/source","-e","PYTHONPATH=/library:"+PREFIX+"/lib/python3.10/site-packages",
            "-e","PATH="+PREFIX+"/bin:/usr/bin:/bin",
            "--entrypoint",PREFIX+"/bin/python",self.image,"-S","/launcher.py",
            str(os.getuid()),str(os.getgid()),PREFIX+"/bin/python","-S","/source/"+entrypoint,
            "--configuration","/configuration.json","--output","/output/candidate.gds"]
        manifest["masked_runtime_paths"]=masked
        manifest["visible_runtime_packages"]=runtime_packages
        candidate_limit=stage_timeout('candidate')
        if candidate_limit<=0:return finish()
        manifest["candidate"] = self._run(work/"candidate_stage",name,candidate,candidate_limit)
        if execution_deadline_utc is not None and stage_timeout('trusted')<=0:return finish()
        if manifest["candidate"]["returncode"]!=0:
            manifest["status"]="CANDIDATE_FAILED"
        else:
            try:
                gds=accepted_gds(output)
            except ValueError as exc:
                manifest.update(status="REJECTED_OUTPUT",reason=str(exc))
            else:
                accepted=work/"accepted";accepted.mkdir()
                shutil.copyfile(gds,accepted/"candidate.gds")
                (accepted/"candidate.gds").chmod(0o444)
                name="iscas-"+run_id.lower().replace("_","-")+"-trusted"
                command=self._base(name,launcher)
                command += ["-v",str(accepted)+":/candidate:ro",
                    "-v",str(trusted)+":/trusted:ro","-v",str(config)+":/configuration.json:ro",
                    "-v",str(gds_boundary)+":/gds_boundary.py:ro",
                    "-v",str(evidence)+":/evidence:rw",
                    "-v",str(self.magic_runtime)+":/work/runtime/magic-8.3.685:ro",
                    "-w","/evidence","-e","PYTHONPATH=/trusted",
                    "-e","PDK_ROOT=/foss/pdks",
                    "-e","PATH="+PREFIX+"/bin:/work/runtime/magic-8.3.685/bin:/foss/tools/netgen/bin:/foss/tools/ngspice/bin:/usr/bin:/bin",
                    "--entrypoint",PREFIX+"/bin/python",self.image,"/launcher.py",
                    str(os.getuid()),str(os.getgid()),PREFIX+"/bin/python","/gds_boundary.py",
                    "--gds","/candidate/candidate.gds","--output","/evidence","--fidelity",fidelity]
                trusted_limit=stage_timeout('trusted')
                if trusted_limit<=0:return finish()
                manifest["trusted"] = self._run(work/"trusted_stage",name,command,trusted_limit)
                provenance={"producer":"trusted_container","run_id":run_id,
                    "phase":manifest["phase"],"source_role":manifest["source_role"],"context":manifest["context"],
                    "candidate_container_stopped":not manifest["candidate"]["container_state"]["Running"],
                    "source_snapshot":"../source", "configuration":"../configuration.json",
                    "accepted_gds":"../accepted/candidate.gds", "trusted_evaluator_snapshot":"../trusted",
                    "trusted_invocation":"../trusted_stage/invocation.json"}
                (evidence/"provenance.json").write_text(json.dumps(provenance,indent=2)+"\n")
                result=evidence/"validation.json"
                if result.is_file() and not result.is_symlink():
                    manifest["physical_result"]=json.loads(result.read_text())
                manifest["status"]="EVALUATED" if manifest["trusted"]["returncode"]==0 and result.is_file() else "EVALUATION_FAILED"
        return finish()


class VisibleActionGateway:
    """A policy can evaluate visible IDs only; hidden runs call execute directly."""
    def __init__(self, packet, workspace, evaluate_visible):
        self.packet=packet
        self.workspace=Path(workspace).resolve()
        self.evaluate_visible=evaluate_visible

    def dispatch(self, action):
        validate_action(action,self.packet)
        kind=action["action"]
        if kind=="read_source":
            return {"path":action["path"],"content":(self.workspace/_relative(action["path"])).read_text()}
        if kind=="propose_patch":
            apply_source_patch(self.workspace,action["patch"],self.packet["allowed_paths"])
            return {"patch_applied":True}
        if kind=="request_evaluation":
            return {name:self.evaluate_visible(name,action["fidelity"]) for name in action["configuration_ids"]}
        return {"finished":True}
