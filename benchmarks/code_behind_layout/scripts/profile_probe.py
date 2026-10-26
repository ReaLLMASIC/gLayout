"""Record actual CPU and wall use of a probe, including child EDA/simulator processes."""
import json
from pathlib import Path
import resource
import runpy
import sys
import time

script = Path(sys.argv[1]).resolve()
sys.argv = sys.argv[1:]
started = time.monotonic()
before_self = resource.getrusage(resource.RUSAGE_SELF)
before_children = resource.getrusage(resource.RUSAGE_CHILDREN)
exit_code = 0
try:
    runpy.run_path(str(script), run_name="__main__")
except SystemExit as exc:
    exit_code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    raise
except BaseException:
    exit_code = 1
    raise
finally:
    after_self = resource.getrusage(resource.RUSAGE_SELF)
    after_children = resource.getrusage(resource.RUSAGE_CHILDREN)
    rss_scale = 1024 if sys.platform == "darwin" else 1
    record = {"script": script.name, "exit_code": exit_code,
        "wall_seconds": time.monotonic() - started,
        "self_user_cpu_seconds": after_self.ru_utime-before_self.ru_utime,
        "self_system_cpu_seconds": after_self.ru_stime-before_self.ru_stime,
        "children_user_cpu_seconds": after_children.ru_utime-before_children.ru_utime,
        "children_system_cpu_seconds": after_children.ru_stime-before_children.ru_stime,
        "self_max_rss_KiB": after_self.ru_maxrss/rss_scale,
        "largest_child_max_rss_KiB": after_children.ru_maxrss/rss_scale,
        "rss_scope": "separate process maxima; not a simultaneous aggregate peak"}
    (Path.cwd()/"resource_usage.json").write_text(json.dumps(record,indent=2)+"\n")
