"""PDK-free tests for glayout.floorplan.router (unit grid: pitch 1, wire/pad/spacing 0.5).

Run with pytest, or directly: ``python tests/test_router.py``.
"""
import os

os.environ.setdefault("GLAYOUT_TABLES", "0")

from dataclasses import replace  # noqa: E402

from glayout.floorplan.router import (  # noqa: E402
    AccessOption, RouterPin, RouterTech, RoutingGrid, RoutingProblem, _f, _too_close, bidirectional_astar, detours,
    route,
)


def _pin(net, owner, cell, side, x, y):
    return RouterPin(net, owner, cell, [AccessOption(side, x, y, "met2", 0.5)])


def _rail(net, owner, cell, w, e):
    """A rail reaching both edges of its cell: (x, y) of its W end and of its E end."""
    return RouterPin(net, owner, cell, [AccessOption("W", *w, "met2", 0.5), AccessOption("E", *e, "met2", 0.5)])


_STACK = [(3.0, 2.0, 17.0, 8.0), (3.0, 12.0, 17.0, 18.0)]    # two blocks, one above the other


def _two_cells(extra_cells=(), width=20.0, height=20.0):
    cells = [(2.0, 8.0, 4.0, 12.0), (16.0, 8.0, 18.0, 12.0), *extra_cells]
    nets = {"N": [_pin("N", "A.N", 0, "E", 4.0, 10.0), _pin("N", "B.N", 1, "W", 16.0, 10.0)]}
    return RoutingProblem(width, height, cells, nets)


def _shapes_ok(rr):
    """No two nets' drawn landing shapes break spacing (wires are legal by pitch)."""
    lands = [l for ls in rr.landings.values() for l in ls]
    for i, a in enumerate(lands):
        for b in lands[i + 1:]:
            if a.pin.net == b.pin.net:
                continue
            for la, ra in a.shapes:
                for lb, rb in b.shapes:
                    if la == lb and _too_close(ra, rb, 0.5):
                        return False
    return True


def test_straight_connection():
    rr = route(_two_cells(), RouterTech.abstract())
    assert rr.success and rr.iterations == 1
    assert 12.0 <= rr.wirelength <= 16.0


def test_detour_around_obstacle():
    wall = (9.0, 0.0, 11.0, 17.0)
    rr = route(_two_cells([wall]), RouterTech.abstract())
    assert rr.success
    assert rr.wirelength > 20.0          # had to go over the wall


def test_unroutable_is_reported():
    wall = (9.0, 0.0, 11.0, 20.0)
    rr = route(_two_cells([wall]), RouterTech.abstract())
    assert not rr.success and rr.failed_nets == ["N"]


def test_single_track_gap_fails_two_nets_but_routes_one():
    # walls leave exactly one legal track (y = 9.5) through x = 9..11
    walls = [(9.0, 0.0, 11.0, 8.75), (9.0, 10.25, 11.0, 20.0)]
    cells = [(2.0, 8.0, 4.0, 12.0), (16.0, 8.0, 18.0, 12.0), *walls]
    one = {"N": [_pin("N", "A.N", 0, "E", 4.0, 10.0), _pin("N", "B.N", 1, "W", 16.0, 10.0)]}
    rr1 = route(RoutingProblem(20, 20, cells, one), RouterTech.abstract())
    assert rr1.success
    two = {"N": [_pin("N", "A.N", 0, "E", 4.0, 10.0), _pin("N", "B.N", 1, "W", 16.0, 10.0)],
           "M": [_pin("M", "A.M", 0, "E", 4.0, 9.0), _pin("M", "B.M", 1, "W", 16.0, 9.0)]}
    rr2 = route(RoutingProblem(20, 20, cells, two), RouterTech.abstract(max_iterations=6))
    assert not rr2.success and rr2.iterations == 6 and rr2.conflicts > 0


def test_rip_up_and_reroute_resolves_shared_channel():
    # three-track gap: two nets fit once they negotiate
    walls = [(9.0, 0.0, 11.0, 8.0), (9.0, 12.0, 11.0, 20.0)]
    cells = [(2.0, 8.0, 4.0, 12.0), (16.0, 8.0, 18.0, 12.0), *walls]
    nets = {"N": [_pin("N", "A.N", 0, "E", 4.0, 10.0), _pin("N", "B.N", 1, "W", 16.0, 9.0)],
            "M": [_pin("M", "A.M", 0, "E", 4.0, 9.0), _pin("M", "B.M", 1, "W", 16.0, 10.0)]}
    rr = route(RoutingProblem(20, 20, cells, nets), RouterTech.abstract())
    assert rr.success, rr.summary()
    assert _shapes_ok(rr)


def test_close_pins_on_one_side_are_staggered():
    cells = [(2.0, 4.0, 4.0, 16.0), (16.0, 4.0, 18.0, 16.0)]
    nets = {n: [_pin(n, f"A.{n}", 0, "E", 4.0, y), _pin(n, f"B.{n}", 1, "W", 16.0, y)]
            for n, y in (("P", 9.0), ("Q", 10.0), ("R", 11.0))}   # legal rail pitch: pad + spacing
    rr = route(RoutingProblem(20, 20, cells, nets), RouterTech.abstract())
    assert rr.success
    assert _shapes_ok(rr)
    xs = sorted(l.x for ls in rr.landings.values() for l in ls if l.option.side == "E")
    assert len(set(xs)) > 1              # could not all land on the same column


def test_same_net_via_pads_overlap_only_when_concentric():
    # a block's rail and its tie ring on one net, 0.49 apart on the same side (sch_c07_routed, gf180):
    # their via pads overlap, and off-centre via cuts break the cut spacing (V2.2a/V3.2a).
    # gf180-like numbers: pitch 0.8, via pads 0.5, spacing 0.3
    pads = {"met2": 0.5, "met3": 0.5, "met4": 0.5}
    tech = RouterTech(("met3", "met4"), 0.8, (0.5, 0.5), (0.3, 0.3), {f"met{i}": 0.3 for i in range(1, 6)},
                      {(pl, z): dict(pads) for pl in ("met1", "met2") for z in (0, 1)})
    cells = [(2.0, 4.0, 4.0, 16.0), (16.0, 4.0, 18.0, 16.0)]
    nets = {"V": [_pin("V", "A.rail", 0, "E", 4.0, 9.6), _pin("V", "A.B", 0, "E", 4.0, 10.09),
                  _pin("V", "B.rail", 1, "W", 16.0, 10.0)]}     # the old rule landed both at x=5.2
    rr = route(RoutingProblem(20, 20, cells, nets), tech)
    assert rr.success
    lands = rr.landings["V"]
    for i, a in enumerate(lands):
        for b in lands[i + 1:]:
            concentric = abs(a.x - b.x) < 1e-6 and abs(a.y - b.y) < 1e-6
            for la, ra in a.shapes[1:]:
                for lb, rb in b.shapes[1:]:
                    assert concentric or la != lb or not _too_close(ra, rb, 0.3), (a.pin.owner, b.pin.owner)


class _ReversedSet(set):
    """A set that iterates in another order, as a different string-hash seed can make it do."""
    def __iter__(self):
        return iter(sorted(set.__iter__(self), key=repr, reverse=True))


def test_astar_does_not_depend_on_the_target_sets_order():
    # two targets equally far from the source: the tie used to be broken by the set's iteration order,
    # which follows string hashing (pin nodes are ("P", k)), so routes changed between interpreters
    grid = RoutingGrid(RoutingProblem(10.0, 10.0, [], {}), RouterTech.abstract())
    tree = [(0, 9, 3), (0, 9, 7)]
    a = bidirectional_astar(grid, "N", (0, 0, 5), set(tree), tree[0], {}, {})
    b = bidirectional_astar(grid, "N", (0, 0, 5), _ReversedSet(tree), tree[0], {}, {})
    assert a == b


def test_side_ties_spread_over_both_channels():
    # each net's W/W and E/E choices have the same HPWL; they used to both take
    # the first-listed side (W) and share one channel
    nets = {"A": [_rail("A", "T.A", 1, (3.0, 16.0), (17.0, 16.0)), _rail("A", "B.A", 0, (3.0, 6.0), (17.0, 6.0))],
            "B": [_rail("B", "T.B", 1, (3.0, 15.0), (17.0, 15.0)), _rail("B", "B.B", 0, (3.0, 5.0), (17.0, 5.0))]}
    rr = route(RoutingProblem(20.0, 20.0, list(_STACK), nets), RouterTech.abstract())
    sides = {net: {l.option.side for l in lands} for net, lands in rr.landings.items()}
    assert rr.success and sides == {"A": {"W"}, "B": {"E"}}
    assert _shapes_ok(rr)


def test_detour_is_relanded_on_the_other_side():
    # W/W has the smaller HPWL (10 vs 14, not a tie), but a third block seals the
    # left channel between the pins, so the W route has to go around both blocks
    wall = (0.0, 8.0, 3.0, 12.0)
    nets = {"A": [_rail("A", "T.A", 1, (3.0, 16.0), (17.0, 17.0)), _rail("A", "B.A", 0, (3.0, 6.0), (17.0, 3.0))]}
    prob = RoutingProblem(20.0, 20.0, list(_STACK) + [wall], nets)
    plain = route(prob, replace(RouterTech.abstract(), detour_ratio=0))
    assert plain.success and {l.option.side for l in plain.landings["A"]} == {"W"}
    rr = route(prob, RouterTech.abstract())
    assert rr.success and {l.option.side for l in rr.landings["A"]} == {"E"}
    assert rr.wirelength < plain.wirelength / 2 and detours(rr) == {}
    assert _shapes_ok(rr)


def test_dynamic_weighting_eq5():
    assert _f(1.0, 3.0, 3.0) == 4.0                 # g < h: plain A*
    assert _f(3.0, 1.0, 3.0) == (3.0 + 5.0) / 3.0   # g >= h: (g + (2κ-1)h)/κ


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)} passed")
