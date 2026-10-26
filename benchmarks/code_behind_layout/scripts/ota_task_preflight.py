"""Actual private OTA-domain generation and anchor geometry qualification."""
from datetime import datetime, timezone
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
builder = importlib.import_module("component_build").build
out = Path.cwd()
kind = task.get("source_family", folder.name)
old = {
    "five_t": "phase0_20261019T011132007923Z_e2_development_pilot/five_t_ota.gds",
    "compact_miller": "phase0_20261019T012240915060Z_e2_development_pilot/compact_miller_ota.gds",
    "fvf": "phase0_20261019T013422659988Z_e2_development_pilot/fvf7.gds",
    "legacy_miller": "phase0_20261019T014057607044Z_e2_development_pilot/ota7.gds",
}


def comparison(first, second):
    def read(path):
        lib = gdstk.read_gds(str(path))
        top, = lib.top_level()
        top.flatten()
        groups = {}
        for p in top.get_polygons():
            groups.setdefault((p.layer, p.datatype), []).append(p)
        labels = sorted((x.text, tuple(x.origin), x.layer, x.texttype, x.rotation, x.magnification, x.x_reflection) for x in top.labels)
        return lib, groups, labels
    first_lib, first_groups, first_labels = read(first)
    second_lib, second_groups, second_labels = read(second)
    if first_lib.unit != second_lib.unit:
        raise ValueError("Geometry unit differs from actual original anchor")
    changed = [list(layer) for layer in sorted(set(first_groups)|set(second_groups))
        if gdstk.boolean(first_groups.get(layer, []), second_groups.get(layer, []), "xor",
            precision=min(first_lib.precision, second_lib.precision)/first_lib.unit)]
    return {"scope": "all_GDS_layers_and_all_labels_no_physics_reuse_claim", "original_GDS": str(second),
        "changed_layer_datatypes": changed, "filled_geometry_equal": not changed,
        "all_labels_equal": first_labels == second_labels, "cell_names_excluded": True}


record = {"scope": "development_OTA_25point_source_generation_not_physical_or_formal", "task": task["task_id"],
    "input_task": str(folder / "task.json"), "rows": [], "started_at_utc": datetime.now(timezone.utc).isoformat(),
    "anchor_geometry_equivalence": None, "formal_trials": 0, "training_examples": 0}
started = time.monotonic()
for point in task["configurations"]:
    start = time.monotonic()
    row = {"configuration_id": point["configuration_id"], "role": point["role"]}
    try:
        path = builder(point["parameters"], out / (point["configuration_id"]+".gds"))
        library = gdstk.read_gds(str(path))
        top, = library.top_level()
        if top.name != task["cell_name"]:
            raise ValueError("Actual generated top does not match immutable intended top")
        row.update(generation_passed=True, gds=str(path), top=top.name, GDS_bytes=Path(path).stat().st_size,
            bbox_um=[list(v) for v in top.bounding_box()], polygons=len(top.get_polygons()))
        if point["role"] == "anchor":
            record["anchor_geometry_equivalence"] = comparison(path, Path("/work/runs/phase0") / old[kind])
    except Exception as error:
        row.update(generation_passed=False, error=type(error).__name__+": "+str(error), traceback=traceback.format_exc())
    row["generation_wall_seconds"] = time.monotonic()-start
    record["rows"].append(row)
    record["wall_seconds"] = time.monotonic()-started
    (out / "generation.json").write_text(json.dumps(record, indent=2)+"\n")
    print(json.dumps({k: v for k, v in row.items() if k != "traceback"}), flush=True)
record["all25_generated"] = len(record["rows"]) == 25 and all(r["generation_passed"] for r in record["rows"])
record["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
(out / "generation.json").write_text(json.dumps(record, indent=2)+"\n")
raise SystemExit(0 if record["all25_generated"] else 2)
