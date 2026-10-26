"""Trace an actual all-metal connection between FVF bias and supply pins."""
import json
import os
from pathlib import Path
from collections import deque
import gdstk

source = Path(os.environ["PROBE_INPUT"])
top, = gdstk.read_gds(source / "fvf7.gds").top_level()
polygons = top.get_polygons()
metals = {layer: gdstk.boolean([p for p in polygons if p.layer == layer and p.datatype in [20, 16]], [], "or", precision=.001)
          for layer in range(66, 72)}
metals[65] = gdstk.boolean([p for p in polygons if p.layer == 65 and p.datatype == 20],
                          metals[66], "not", precision=.001)
nodes = {(layer, i): poly for layer, group in metals.items() for i, poly in enumerate(group)}
boxes = {node: poly.bounding_box() for node, poly in nodes.items()}
graph = {node: [] for node in nodes}

def contains(layer, point):
    x, y = point
    result = []
    for i, poly in enumerate(metals[layer]):
        box = boxes[layer, i]
        if box[0][0] <= x <= box[1][0] and box[0][1] <= y <= box[1][1] and gdstk.inside([point], [poly])[0]:
            result.append((layer, i))
    return result

for via in [p for p in polygons if p.layer in range(66, 71) and p.datatype == 44]:
    box = via.bounding_box()
    point = ((box[0][0]+box[1][0])/2, (box[0][1]+box[1][1])/2)
    below = contains(via.layer, point)
    if via.layer == 66:
        below += contains(65, point)
    above = contains(via.layer+1, point)
    for n1 in below:
        for n2 in above:
            graph[n1].append((n2, point)); graph[n2].append((n1, point))
ports = json.loads((source / "debug_ports.json").read_text())
start = ports["cmirr_1_fet_A_drain_E"]
target = ports["cmirr_1_welltie_N_top_met_N"]
starts = contains(start["layer"][0], start["center_um"])
targets = contains(target["layer"][0], target["center_um"])
queue = deque(starts); previous = {node: None for node in starts}
found = None
while queue:
    node = queue.popleft()
    if node in targets:
        found = node; break
    for neighbor, via in graph[node]:
        if neighbor not in previous:
            previous[neighbor] = (node, via); queue.append(neighbor)
path = []
while found is not None:
    prior = previous[found]
    path.append({"metal_node": list(found), "bbox_um": boxes[found], "via_to_previous_um": prior[1] if prior else None})
    found = prior[0] if prior else None
record = {"scope": "geometric_metal_short_diagnosis_not_LVS", "start_nodes": starts,
          "target_nodes": targets, "connected": bool(path), "path": list(reversed(path))}
(Path.cwd() / "short_trace.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps(record, indent=2))
