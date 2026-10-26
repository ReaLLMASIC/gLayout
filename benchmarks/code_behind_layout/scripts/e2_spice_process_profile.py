"""Actual process costs for E2's frozen serial-corner SPICE benchmark.

Instrument only the independent trusted launcher. The complete measurement
function/loop and each subprocess timeout remain unchanged. Child CPU is safe
to difference here because the frozen research scheduler has exactly1 worker.
"""
import ast
from pathlib import Path
import subprocess


def profiled_measure(measure, *args, **kwargs):
    kind = kwargs["kind"]
    if kind in ["five_t", "compact_miller"]:
        tree = ast.parse(Path(kwargs["bench_snapshot"]).read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "ThreadPoolExecutor"]
        if len(calls) != 1 or not any(k.arg == "max_workers" and isinstance(k.value, ast.Constant) and k.value.value == 1 for k in calls[0].keywords):
            raise ValueError("Per-analysis CPU requires the separately calibrated serial-corner bench")
    original_popen = subprocess.Popen
    prefix = "\n".join([
        "import subprocess,resource,time,json",
        "from pathlib import Path",
        "_e2_actual_run=subprocess.run",
        "def _e2_profile_ngspice(argv,*args,**kwargs):",
        "    if Path(str(argv[0])).name!='ngspice':return _e2_actual_run(argv,*args,**kwargs)",
        "    before=resource.getrusage(resource.RUSAGE_CHILDREN);started=time.monotonic();code=None;failure=None",
        "    try:",
        "        result=_e2_actual_run(argv,*args,**kwargs);code=result.returncode;return result",
        "    except BaseException as error:",
        "        failure=type(error).__name__;raise",
        "    finally:",
        "        after=resource.getrusage(resource.RUSAGE_CHILDREN)",
        "        record={'argv':list(map(str,argv)),'original_timeout_s':kwargs.get('timeout'),'returncode':code,'exception':failure,'wall_seconds':time.monotonic()-started,'waited_child_user_CPU_seconds':after.ru_utime-before.ru_utime,'waited_child_system_CPU_seconds':after.ru_stime-before.ru_stime,'scope':'one actual ngspice process; serial original analyses; component of total trusted-stage CPU, do not add twice'}",
        "        work=Path(kwargs.get('cwd') or Path.cwd());path=work/(Path(str(argv[-1])).stem+'_process_resource.json')",
        "        path.write_text(json.dumps(record,indent=2)+'\\n')",
        "subprocess.run=_e2_profile_ngspice", ""])
    def launch(argv, *launch_args, **launch_kwargs):
        if len(argv) != 2 or Path(str(argv[1])).name != "run_bench.py":
            raise ValueError("Expected one trusted frozen benchmark launcher")
        path = Path(argv[1])
        source = path.read_text()
        (path.parent / "original_unprofiled_launcher.py").write_text(source)
        path.write_text(prefix+"\n"+source)
        return original_popen(argv, *launch_args, **launch_kwargs)
    try:
        subprocess.Popen = launch
        return measure(*args, **kwargs)
    finally:
        subprocess.Popen = original_popen
