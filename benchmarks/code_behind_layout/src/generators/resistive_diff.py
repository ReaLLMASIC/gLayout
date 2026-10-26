"""Four-group differential stage with separated upper inputs and lower bias.

Explicit M4 branch paths meet distinct M5 collectors outside the device block.
No existing differential-pair assembly or graph-to-layout compiler is imported.
"""
import json
from pathlib import Path
from gdsfactory.component import Component
from glayout import sky130
from glayout.primitives.fet import nmos
from src.generators.terminal_access import expose, wire, via, pin, finish
from src.generators.resistive_diff_reference import DEFAULT


def build(output, sizing=None, input_gap=48., row_gap=28., collector_width=.8):
    s = {**DEFAULT, **(sizing or {})}
    sky130.activate()
    top = Component("resistive_diff")
    remove = [v for k, v in sky130.glayers.items() if k.endswith(("_label", "_pin"))] + [(64, 44)]
    inp = nmos(sky130, width=s["input_width"], length=s["input_length"], fingers=s["fingers"],
        with_dummy=False, with_tie=True, with_dnwell=False).copy().remove_layers(remove, include_labels=True)
    bias = nmos(sky130, width=s["bias_width"], length=s["bias_length"], fingers=s["fingers"],
        with_dummy=False, with_tie=True, with_dnwell=False).copy().remove_layers(remove, include_labels=True)
    positive, negative, tail, reference = top << inp, top << inp, top << bias, top << bias
    positive.move(origin=(positive.xmin, positive.ymin), destination=(0, 0))
    negative.move(origin=(negative.xmin, negative.ymin), destination=(positive.xmax + input_gap, 0))
    tail.move(origin=(tail.xmin, tail.ymax), destination=((positive.xmax + negative.xmin) / 2, -row_gap))
    reference.move(origin=(reference.xmax, reference.ymax), destination=(-28, -row_gap))
    p, n, t, b = [expose(top, device) for device in (positive, negative, tail, reference)]
    left = float(reference.xmin) - 28
    right = float(negative.xmax) + 20
    middle = -row_gap / 2

    def branch(start, track_y, collector_x, width=.6):
        turn = (start[0], track_y)
        wire(top, "met3", start, turn, width)
        via(top, "met3", "met4", turn)
        wire(top, "met4", turn, (collector_x, track_y), width)
        via(top, "met4", "met5", (collector_x, track_y))

    def collector(name, x, points):
        ys = [point[1] for point in points]
        wire(top, "met5", (x, min(ys)), (x, max(ys)), collector_width)
        # Labels remain on M4 so the existing port extraction contract applies.
        via(top, "met4", "met5", (x, ys[0]))
        wire(top, "met4", (x - 1, ys[0]), (x + 1, ys[0]), collector_width)
        pin(top, name, (x, ys[0]))

    # The source-coupled tail takes three separated branch levels in the channel.
    x = left + 12
    levels = [middle + 6, middle + 3, middle]
    for start, y in zip((p["S"], n["S"], t["D"]), levels):
        branch(start, y, x)
    collector("TAIL", x, [(x, y) for y in levels])
    # Diode reference and tail gate occupy a lower set of levels and collector.
    x = left + 4
    levels = [middle - 4, middle - 7, middle - 10]
    for start, y in zip((b["D"], b["G"], t["G"]), levels):
        branch(start, y, x)
    collector("IBIAS", x, [(x, y) for y in levels])
    # Four body contacts and two lower sources use distinct ground branches.
    x = right
    floor = float(min(reference.ymin, tail.ymin)) - 8
    levels = [floor - 3 * i for i in range(6)]
    for start, y in zip((p["B"], n["B"], t["B"], b["B"], t["S"], b["S"]), levels):
        branch(start, y, x)
    collector("VSS", x, [(x, y) for y in levels])
    # Each signal has its own high-level output or input path, without a common bus.
    for name, start, y, x in [
        ("OUTP", p["D"], float(positive.ymax) + 6, left + 20),
        ("OUTN", n["D"], float(negative.ymax) + 10, right - 4),
        ("VINP", p["G"], float(positive.ymax) + 14, left + 16),
        ("VINN", n["G"], float(negative.ymax) + 18, right - 8)]:
        branch(start, y, x)
        collector(name, x, [(x, y), (x, y + 2)])
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "sizing.json").write_text(json.dumps(s, indent=2) + "\n")
    return finish(top, output)
