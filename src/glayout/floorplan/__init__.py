"""Routing-aware analog floorplanning (Level 1 of the notes' hierarchy).

Pipeline: build ``Block``s with shape variants -> ``apply_drr`` pads them for
routing -> describe the ``Circuit`` (instances, nets, symmetry) ->
``anneal_floorplan`` -> ``realize_floorplan`` places the cells.
"""
from glayout.floorplan.block import Block, Padding, Pin, Variant, build_block, extract_pins, print_blocks
from glayout.floorplan.drr import apply_drr, block_keepout, routing_track
from glayout.floorplan.circuit import Circuit, CircuitGraph, Instance
from glayout.floorplan.anneal import FloorplanResult, FloorplanWeights, Placed, anneal_floorplan, print_placement
from glayout.floorplan.realize import realize_floorplan

__all__ = [
    "Block", "Circuit", "CircuitGraph", "FloorplanResult", "FloorplanWeights", "Instance", "Padding",
    "Pin", "Placed", "Variant", "anneal_floorplan", "apply_drr", "block_keepout", "build_block",
    "extract_pins", "print_blocks", "print_placement", "realize_floorplan", "routing_track",
]
