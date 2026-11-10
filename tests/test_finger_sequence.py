"""Geometry-free tests for glayout.placement.finger_sequence.

Run with pytest, or directly: ``python tests/test_finger_sequence.py``.
"""
import os

os.environ.setdefault("GLAYOUT_TABLES", "0")

from glayout.placement.finger_sequence import (  # noqa: E402
    DeviceSpec, DiffusionGraph, FingerSequence, orient, search_sequences,
)

MIRROR = {"A": DeviceSpec("A", "VSS", "VREF", "VREF", 4), "B": DeviceSpec("B", "VSS", "VOUT", "VREF", 4)}


def test_notes_example_is_break_free_and_balanced():
    seq = FingerSequence.from_compact(MIRROR, "A+ A- B+ B- B+ B- A+ A-")
    assert seq.diagram() == "VSS |A| VREF |A| VSS |B| VOUT |B| VSS |B| VOUT |B| VSS |A| VREF |A| VSS"
    m = seq.metrics()
    assert m.breaks == 0
    assert m.centroid_error == 0
    assert m.drain_imbalance == 0          # each drain sits between two own fingers


def test_plain_abba_has_unbalanced_drains():
    devs = {"A": DeviceSpec("A", "S", "DA", "G", 2), "B": DeviceSpec("B", "S", "DB", "G", 2)}
    seq = FingerSequence.from_compact(devs, "A- B+ B- A+")   # DA |A| S |B| DB |B| S |A| DA
    m = seq.metrics()
    assert m.breaks == 0 and m.centroid_error == 0
    assert m.drain_per_finger == {"A": 1.0, "B": 0.5}


def test_breaks_and_segments():
    devs = {"A": DeviceSpec("A", "X", "Y", "G1", 1), "B": DeviceSpec("B", "P", "Q", "G2", 1)}
    seq = FingerSequence.from_compact(devs, "A+ B+")
    assert seq.breaks == 1
    assert seq.segments() == [[0], [1]]
    assert seq.positions() == [0.0, 2.0]   # one break_gap pitch inserted


def test_euler_lower_bound():
    assert DiffusionGraph.build(list(MIRROR.values())).min_breaks() == 0
    cascode = [DeviceSpec("A", "X", "Y", "G1", 2), DeviceSpec("B", "P", "Q", "G2", 2)]
    assert DiffusionGraph.build(cascode).min_breaks() == 1
    odd = [DeviceSpec("A", "S", "D", "G", 3)]   # S and D both odd degree: one trail
    assert DiffusionGraph.build(odd).min_breaks() == 0


def test_orient_finds_zero_break_orientation():
    fingers = orient(list("AABBBBAA"), MIRROR)
    assert FingerSequence(MIRROR, fingers).breaks == 0


def test_search_mirror_prefers_balanced_common_centroid():
    res = search_sequences(list(MIRROR.values()))
    m = res.best.metrics
    assert res.best.sequence.labels() in ("AABBBBAA", "BBAAAABB")
    assert m.breaks == 0 and m.centroid_error == 0 and m.drain_imbalance == 0


def test_search_ratio_mirror():
    res = search_sequences([DeviceSpec("A", "VSS", "VREF", "VREF", 2), DeviceSpec("B", "VSS", "VOUT", "VREF", 4)])
    assert res.best.metrics.centroid_error == 0 and res.best.metrics.breaks == 0


def test_search_three_devices_uses_palindromes():
    devs = [DeviceSpec("R", "VSS", "IB", "IB", 4), DeviceSpec("T", "VSS", "VT", "IB", 8),
            DeviceSpec("K", "VSS", "VO", "IB", 8)]
    res = search_sequences(devs, limit=5000)
    assert res.mode in ("palindromes", "sampled palindromes")
    assert res.best.metrics.centroid_error == 0


def test_search_no_common_net_respects_bound():
    res = search_sequences([DeviceSpec("A", "X", "Y", "G1", 2), DeviceSpec("B", "P", "Q", "G2", 2)])
    assert res.best.metrics.breaks >= res.lower_bound_breaks
    assert res.best.metrics.centroid_error == 0


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)} passed")
