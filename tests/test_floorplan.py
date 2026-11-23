"""Tests for glayout.floorplan that need no PDK (abstract blocks).

Run with pytest, or directly: ``python tests/test_floorplan.py``.
"""
import io
import os
import random
from contextlib import redirect_stdout

os.environ.setdefault("GLAYOUT_TABLES", "0")

from glayout.floorplan.anneal import anneal_floorplan  # noqa: E402
from glayout.floorplan.block import Block, Padding, Pin, Variant  # noqa: E402
from glayout.floorplan.circuit import Circuit, Instance  # noqa: E402
from glayout.floorplan.sequence_pair import pack  # noqa: E402
from glayout.util.process_table import ProcessTable  # noqa: E402


def _overlap(a, b, eps=1e-9):
    return a[0] < b[0] + b[2] - eps and b[0] < a[0] + a[2] - eps and a[1] < b[1] + b[3] - eps and b[1] < a[1] + a[3] - eps


def test_pack_relations():
    x, y = pack([0, 1], [0, 1], [2, 3], [1, 1])      # 0 left of 1
    assert (x, y) == ([0.0, 2.0], [0.0, 0.0])
    x, y = pack([1, 0], [0, 1], [2, 3], [1, 4])      # 0 below 1
    assert (x, y) == ([0.0, 0.0], [0.0, 1.0])


def test_pack_never_overlaps():
    rng = random.Random(1)
    for _ in range(200):
        n = rng.randint(2, 9)
        gp, gn = list(range(n)), list(range(n))
        rng.shuffle(gp)
        rng.shuffle(gn)
        w = [rng.uniform(1, 5) for _ in range(n)]
        h = [rng.uniform(1, 5) for _ in range(n)]
        x, y = pack(gp, gn, w, h)
        boxes = list(zip(x, y, w, h))
        assert not any(_overlap(boxes[i], boxes[j]) for i in range(n) for j in range(i + 1, n))


def _block(name, kind, sizes, nets):
    variants = []
    for w, h in sizes:
        pins = {n: Pin(n, w * (k + 1) / (len(nets) + 1), h / 2, "EW") for k, n in enumerate(nets)}
        variants.append(Variant({}, w, h, pins, None, Padding(1, 1, 0.5, 0.5)))
    return Block(name, kind, variants)


def _toy_circuit():
    dp = _block("DP", "DP", [(10, 6), (14, 4)], ["INP", "INN", "O1", "O2", "T"])
    ld = _block("LD", "CM", [(10, 5), (14, 3.5)], ["O1", "O2", "S"])
    tl = _block("TL", "CM", [(8, 4)], ["T", "B", "S"])
    cs = _block("CS", "CS", [(6, 6), (9, 4)], ["O2", "OUT", "S"])
    return Circuit("toy", [
        Instance("DP", dp, {"INP": "INP", "INN": "INN", "O1": "N1", "O2": "N2", "T": "TAIL"}),
        Instance("LD", ld, {"O1": "N1", "O2": "N2", "S": "VDD"}),
        Instance("TL", tl, {"T": "TAIL", "B": "IB", "S": "VSS"}),
        Instance("CS", cs, {"O2": "N2", "OUT": "OUT", "S": "VDD"}),
    ], self_symmetric=["DP", "LD"])


def test_anneal_is_legal_symmetric_and_deterministic():
    r1 = anneal_floorplan(_toy_circuit(), seed=3)
    boxes = [(p.x, p.y, p.w, p.h) for p in r1.placed.values()]
    assert not any(_overlap(boxes[i], boxes[j]) for i in range(4) for j in range(i + 1, 4))
    assert r1.metrics["hpwl"] <= r1.metrics["hpwl_ref"] * 1.5
    r2 = anneal_floorplan(_toy_circuit(), seed=3)
    assert r1.metrics["cost"] == r2.metrics["cost"]
    axis = r1.metrics["width"] / 2
    for n in ("DP", "LD"):
        p = r1.placed[n]
        if r1.metrics["asym_um"] == 0:
            assert abs(p.x + p.w / 2 - axis) < 1e-9


def test_graph_shape():
    g = _toy_circuit().graph()
    types = [n["type"] for n in g.nodes]
    assert types.count("device") == 4 and types.count("pin") == 14 and types.count("net") == 9
    kinds = {e[2] for e in g.edges}
    assert {"device_has_pin", "pin_in_net", "self_symmetry"} <= kinds


def test_process_table_depth_limit():
    os.environ["GLAYOUT_TABLES"] = "1"
    os.environ["GLAYOUT_TABLES_DEPTH"] = "1"
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            with ProcessTable("outer") as pt:
                with pt.stage("s"):
                    with ProcessTable("inner"):
                        pass
        out = buf.getvalue()
        assert "outer" in out and "inner" not in out
    finally:
        os.environ["GLAYOUT_TABLES"] = "0"
        del os.environ["GLAYOUT_TABLES_DEPTH"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)} passed")
