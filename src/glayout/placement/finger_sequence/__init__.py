"""Finger-level placement: one row of unit fingers from several devices that
share diffusion where their nets allow, arranged common-centroid.

- ``model``: geometry-free row model, metrics, diffusion graph
- ``search``: ranks candidate sequences
- ``layout``: draws a chosen sequence for a PDK (imported lazily, needs a PDK)
"""
from glayout.placement.finger_sequence.model import (
    Contact, DeviceSpec, DiffusionGraph, Finger, FingerSequence, RowMetrics, check_shareable,
)
from glayout.placement.finger_sequence.search import (
    Candidate, SearchResult, SequenceWeights, orient, search_sequences,
)

__all__ = [
    "Candidate", "Contact", "DeviceSpec", "DiffusionGraph", "Finger", "FingerSequence",
    "RowMetrics", "SearchResult", "SequenceWeights", "check_shareable", "orient",
    "search_sequences", "finger_sequence_row",
]


def __getattr__(name):
    if name == "finger_sequence_row":
        from glayout.placement.finger_sequence.layout import finger_sequence_row
        return finger_sequence_row
    raise AttributeError(name)
