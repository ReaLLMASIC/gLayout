"""Render the actual independent transistor intent; never a physical result."""
from html import escape
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.generators.telescopic_ota_reference import schematic


def render(path):
    groups = {}
    for line in schematic().splitlines():
        if not line.startswith("X"):
            continue
        fields = line.split()
        group = re.fullmatch(r"X([NP][1-4]|NT|NR)_\d+", fields[0])[1]
        signature = fields[1:]
        if group not in groups:
            groups[group] = {"count": 0, "signature": signature}
        if groups[group]["signature"] != signature:
            raise ValueError("A displayed transistor group has unequal per-finger intent")
        groups[group]["count"] += 1
    # The central sense route is critical to this particular mirror topology.
    if groups["P1"]["signature"][:4] != ["pl", "mirror", "VDD", "VDD"]:
        raise ValueError("The rendering no longer matches the independent reference-stack feedback")
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1060" viewBox="0 0 1000 1060">',
        '<rect width="1000" height="1060" fill="#fff"/>',
        '<style>text{font-family:Arial,sans-serif;fill:#162c3c}.wire{fill:none;stroke:#263e4d;stroke-width:2.2;stroke-linejoin:round}.device{stroke:#162c3c;stroke-width:3;fill:none}.node{fill:#263e4d}.note{fill:#576d7b}</style>']

    def line(points, css="wire"):
        svg.append('<polyline class="'+css+'" points="'+" ".join(f"{x},{y}" for x, y in points)+'"/>')

    def text(x, y, value, size=16, anchor="start", css=""):
        svg.append(f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" class="{css}">{escape(value)}</text>')

    def dot(x, y):
        svg.append(f'<circle class="node" cx="{x}" cy="{y}" r="4"/>')

    def mos(name, x, y, gate_side):
        line([(x, y-28), (x, y+28)], "device")
        gx = x+20*gate_side
        line([(gx, y-21), (gx, y+21)], "device")
        line([(gx, y), (x+50*gate_side, y)])
        if name.startswith("P"):
            svg.append(f'<circle cx="{x+31*gate_side}" cy="{y}" r="5" fill="white" stroke="#162c3c" stroke-width="2"/>')
        # Annotation belongs on the side opposite the gate lead.
        tx = x-60 if gate_side > 0 else x+60
        anchor = "end" if gate_side > 0 else "start"
        g = groups[name]
        width = next(v[2:] for v in g["signature"] if v.startswith("w="))
        length = next(v[2:] for v in g["signature"] if v.startswith("l="))
        text(tx, y-3, f"{name} ×{g['count']}", 17, anchor)
        text(tx, y+18, f"W/L {width}/{length} µm", 13, anchor, "note")

    text(48, 48, "Telescopic cascode-mirror OTA", 29)
    text(48, 79, "Independent transistor intent · 9T signal core + 1 bias reference · 32 per-finger MOS", 16, css="note")
    left, right, center = 300, 680, 490
    line([(left, 130), (right, 130)])
    text(center, 119, "VDD 1.8 V", 17, "middle")
    for x in [left, right]:
        line([(x, 130), (x, 197)])
        line([(x, 253), (x, 342)])
        line([(x, 398), (x, 492)])
        line([(x, 548), (x, 632)])
        line([(x, 688), (x, 740)])
    for name, x, y, side in [
        ("P1", left, 225, 1), ("P2", right, 225, -1),
        ("P3", left, 370, -1), ("P4", right, 370, 1),
        ("N3", left, 520, -1), ("N4", right, 520, 1),
        ("N1", left, 660, -1), ("N2", right, 660, 1),
        ("NR", 180, 820, 1), ("NT", center, 820, -1)]:
        mos(name, x, y, side)
    # Explicit reference-stack mirror feedback.
    line([(350, 225), (630, 225)])
    line([(center, 225), (center, 450), (left, 450)])
    dot(center, 225); dot(left, 450)
    text(315, 436, "mirror", 15)
    text(315, 299, "pl", 15)
    text(695, 299, "pr", 15)
    text(315, 592, "nl", 15)
    text(695, 592, "nr", 15)
    # Output and the fixed application capacitor.
    line([(right, 450), (930, 450)])
    dot(right, 450); dot(895, 450)
    text(940, 456, "VOUT", 16)
    line([(895, 450), (895, 566)])
    line([(880, 566), (910, 566)])
    line([(880, 580), (910, 580)])
    line([(895, 580), (895, 610)])
    for yy, half in [(610, 14), (616, 10), (622, 5)]:
        line([(895-half, yy), (895+half, yy)])
    text(922, 578, "2 pF", 15)
    for yy, label in [(370, "VBP"), (520, "VBN"), (660, "VP")]:
        line([(170, yy), (250, yy)])
        text(158, yy+5, label, 17, "end")
    for yy, label in [(370, "VBP"), (520, "VBN"), (660, "VN")]:
        line([(730, yy), (810, yy)])
        text(824, yy+5, label, 17)
    # Differential tail and explicit NMOS current reference.
    line([(left, 740), (right, 740)])
    line([(center, 740), (center, 792)])
    dot(center, 740)
    text(center+12, 766, "tail", 15)
    line([(180, 792), (180, 760), (280, 760), (280, 820)])
    line([(230, 820), (440, 820)])
    dot(280, 820); dot(180, 760)
    line([(60, 760), (180, 760)])
    text(48, 730, "IBIAS", 16)
    text(48, 750, "10 µA from VDD", 13, css="note")
    for x in [180, center]:
        line([(x, 848), (x, 910)])
    line([(180, 910), (right, 910)])
    dot(center, 910)
    text(center, 936, "GND", 17, "middle")
    text(48, 978, "NMOS bulks → GND; PMOS bulks → VDD. Widths are per finger, not summed widths.", 15, css="note")
    text(48, 1005, "Predeclared controls: VBN {1.25, 1.40} V × VBP {0.45, 0.60} V; input common mode 1.0 V.", 15, css="note")
    text(48, 1032, "DRAFT intent only. This drawing establishes no simulation, layout, extraction, or S2 result.", 15, css="note")
    svg.append("</svg>")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(svg)+"\n")
    return path


if __name__ == "__main__":
    print(render(ROOT / "docs/assets/telescopic_ota_intent.svg"))
