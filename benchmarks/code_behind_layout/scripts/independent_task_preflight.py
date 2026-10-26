"""Generate every private sizing once using a prepared independent source pack."""
import importlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
import gdstk

folder = Path(os.environ["PROBE_INPUT"])
task = json.loads((folder / "task.json").read_text())
sys.path.insert(0, str(folder / "source_pack"))
name = task["parent_lineage"].removeprefix("research_")
builder = importlib.import_module("src.generators." + name).build
out = Path.cwd()
rows = []
for point in task["configurations"]:
    start = time.monotonic()
    row = {"configuration_id": point["configuration_id"], "role": point["role"]}
    try:
        gds = builder(out / point["configuration_id"], point["parameters"])
        library = gdstk.read_gds(gds)
        top, = library.top_level()
        row.update(generation_passed=True, gds=str(gds), top=top.name,
                   bbox_um=[list(v) for v in top.bounding_box()], polygons=len(top.polygons))
    except Exception as exc:
        row.update(generation_passed=False, error=type(exc).__name__ + ": " + str(exc), traceback=traceback.format_exc())
    row["generation_wall_seconds"] = time.monotonic() - start
    rows.append(row)
    (out / "generation.json").write_text(json.dumps({"task": task["task_id"], "rows": rows}, indent=2) + "\n")
print(json.dumps({"task": task["task_id"], "attempts": len(rows), "passed": sum(row["generation_passed"] for row in rows)}), flush=True)
raise SystemExit(0 if all(row["generation_passed"] for row in rows) else 2)
