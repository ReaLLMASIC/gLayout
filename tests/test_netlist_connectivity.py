"""Hierarchical netlist connectivity: ``connect_subnets`` / ``connect_node``.

The connection API describes an *equivalence relation* over sub-netlist
terminals ("these terminals are the same electrical net"). The tests check the
generated connectivity against an independent oracle that knows nothing about
how ``Netlist`` stores connections: a plain graph of the requested connections
whose connected components are found by breadth-first search. Two views of the
result are checked: ``netlist_connections`` (the stored label of every
terminal) and the SPICE text from ``generate_netlist()``, parsed back from
scratch, because that text is what LVS consumes.

Pure Python: no PDK, no layout, no external tools.
"""
import itertools
import random
from collections import defaultdict, deque

import pytest

from glayout.spice.netlist import Netlist


# --- independent oracle ------------------------------------------------------------------ #
class Oracle:
    """Graph of requested connections; components via BFS.

    Vertices are ``("T", index, node)`` terminals and ``("N", name)`` for explicitly
    named top-level nets.
    """

    def __init__(self):
        self.adj = defaultdict(set)

    def _edge(self, u, v):
        self.adj[u].add(v)
        self.adj[v].add(u)

    def sub(self, i, a, j, b):
        self._edge(("T", i, a), ("T", j, b))

    def top(self, i, a, name):
        self._edge(("T", i, a), ("N", name))

    def components(self):
        seen, comps = set(), []
        for start in list(self.adj):
            if start in seen:
                continue
            comp, queue = set(), deque([start])
            seen.add(start)
            while queue:
                x = queue.popleft()
                comp.add(x)
                for y in self.adj[x] - seen:
                    seen.add(y)
                    queue.append(y)
            comps.append(comp)
        return comps

    def would_short_named_nets(self, kind, *args):
        """True if applying the request would join two different named nets."""
        trial = Oracle()
        trial.adj = defaultdict(set, {k: set(v) for k, v in self.adj.items()})
        getattr(trial, kind)(*args)
        return any(len({v[1] for v in comp if v[0] == "N"}) > 1 for comp in trial.components())


def make_top(n_subnets, pins=("P",)):
    """A top-level netlist with ``n_subnets`` sub-netlists that each have the given pins."""
    top = Netlist(circuit_name="TOP", nodes=["VDD", "VSS", "OUT"])
    top.add_netlists([Netlist(circuit_name=f"S{k}", nodes=list(pins)) for k in range(n_subnets)])
    return top


def label(top, i, node):
    """Stored net label of terminal ``node`` of sub-netlist ``i``."""
    return top.netlist_connections[i][top.sub_netlists[i].nodes.index(node)]


def S(i, j, a="P", b="P"):
    """Request: join terminal ``a`` of sub-netlist ``i`` to terminal ``b`` of ``j``."""
    return ("sub", i, a, j, b)


def N(i, name, a="P"):
    """Request: connect terminal ``a`` of sub-netlist ``i`` to the top-level net ``name``."""
    return ("top", i, a, name)


def apply(top, oracle, *requests):
    """Perform the requests on the netlist and record them in the oracle."""
    for kind, i, a, x, *b in requests:
        if kind == "sub":
            top.connect_subnets(i, x, [(a, b[0])])
            oracle.sub(i, a, x, b[0])
        else:
            top.connect_node(i, [(a, x)])
            oracle.top(i, a, x)


def assert_matches_oracle(top, oracle):
    """Every terminal the oracle knows about must have the label the relation implies."""
    labels_of_comp = []
    for comp in oracle.components():
        terms = [v for v in comp if v[0] == "T"]
        names = {v[1] for v in comp if v[0] == "N"}
        got = {label(top, i, node) for _, i, node in terms}
        assert len(got) == 1, f"net split: {sorted(terms)} -> labels {sorted(got)}"
        (lab,) = got
        if names:
            assert names == {lab}, f"top-level name lost: wanted {names}, got {lab}"
        labels_of_comp.append(lab)
    assert len(set(labels_of_comp)) == len(labels_of_comp), f"distinct nets were merged: {labels_of_comp}"


def spice_instance_nets(top):
    """Parse generate_netlist() text: instance index -> {node: net}."""
    body = top.generate_netlist().split(f".subckt {top.circuit_name}", 1)[1].split(".ends", 1)[0]
    result = {}
    for line in body.splitlines():
        tokens = line.split()
        if tokens and tokens[0].startswith("X"):
            idx = int(tokens[0][1:])
            result[idx] = dict(zip(top.sub_netlists[idx].nodes, tokens[1:-1]))
    return result


def check(top, oracle):
    """Stored labels and re-parsed SPICE both agree with the oracle."""
    assert_matches_oracle(top, oracle)
    inst = spice_instance_nets(top)
    for comp in oracle.components():
        terms = [v for v in comp if v[0] == "T"]
        nets = {inst[i][node] for _, i, node in terms}
        assert len(nets) == 1, f"SPICE text splits a net: {sorted(terms)} -> {sorted(nets)}"


# --- the reported case and its variants -------------------------------------------------- #
@pytest.mark.parametrize("n,requests,expect", [
    (4, [S(0, 1), S(2, 3), S(1, 2)], None),                    # A-B, C-D, then B-C: one net
    (2, [N(0, "VDD"), S(0, 1)], "VDD"),                        # a name survives a later join
    (3, [S(0, 1), S(1, 2), N(0, "VDD")], "VDD"),               # a later name reaches every member
    (4, [S(0, 1), S(2, 3), N(3, "OUT"), S(1, 2)], "OUT"),      # name on one side of a merge
])
def test_merging_connected_groups_gives_one_net(n, requests, expect):
    top, o = make_top(n), Oracle()
    apply(top, o, *requests)
    check(top, o)
    labels = {label(top, i, "P") for i in range(n)}
    assert len(labels) == 1 and (expect is None or labels == {expect})


@pytest.mark.parametrize("order", list(itertools.permutations([(0, 1), (2, 3), (1, 2)])))
@pytest.mark.parametrize("flip", [False, True])
def test_every_connection_order_gives_the_same_relation(order, flip):
    top, o = make_top(4), Oracle()
    apply(top, o, *[S(j, i) if flip else S(i, j) for i, j in order])
    check(top, o)


def test_merge_from_either_argument_side():
    for last in (S(2, 3), S(3, 2)):
        top, o = make_top(6), Oracle()
        apply(top, o, S(0, 1), S(1, 2), S(3, 4), S(4, 5), last)
        assert_matches_oracle(top, o)
        assert len({c[0] for c in top.netlist_connections}) == 1


def test_repeated_and_reversed_connections_are_idempotent():
    top, o = make_top(3), Oracle()
    apply(top, o, *[S(i, j) for i, j in [(0, 1), (0, 1), (1, 0), (1, 2), (2, 1), (0, 2)]])
    assert_matches_oracle(top, o)
    assert top.wire_index == 1, "no extra wires may be minted for already-connected terminals"


def test_already_connected_endpoints_keep_their_wire_name():
    top = make_top(2)
    top.connect_subnets(0, 1, [("P", "P")])
    before = [list(r) for r in top.netlist_connections]
    top.connect_subnets(0, 1, [("P", "P")])
    assert top.netlist_connections == before


def test_unconnected_terminals_are_left_alone():
    top = make_top(4, pins=("P", "Q"))
    apply(top, Oracle(), S(0, 1), S(2, 3), S(1, 2))
    assert all(label(top, i, "Q") == "Q" for i in range(4)), "an untouched pin must stay put"
    assert len({label(top, i, "P") for i in range(4)}) == 1


def test_multiple_pairs_in_one_call():
    top, o = make_top(4, pins=("A", "B")), Oracle()
    for i, j, pairs in [(0, 1, [("A", "A"), ("B", "B")]), (2, 3, [("A", "A"), ("B", "B")]),
                        (1, 2, [("A", "B"), ("B", "A")])]:
        top.connect_subnets(i, j, pairs)
        for a, b in pairs:
            o.sub(i, a, j, b)
    check(top, o)


# --- top-level names, conflicts, naming ------------------------------------------------- #
def test_same_top_level_name_on_both_sides_is_not_a_conflict():
    top = make_top(2)
    top.connect_node(0, [("P", "VDD")])
    top.connect_node(1, [("P", "VDD")])
    top.connect_subnets(0, 1, [("P", "P")])
    assert label(top, 0, "P") == label(top, 1, "P") == "VDD"


def test_top_level_name_equal_to_pin_name_is_still_a_name():
    # n_block.py connects ('GND', 'GND'): same spelling as the pin.
    top = Netlist(circuit_name="TOP", nodes=["GND"])
    top.add_netlists([Netlist(circuit_name=f"S{k}", nodes=["GND"]) for k in range(2)])
    top.connect_node(0, [("GND", "GND")])
    top.connect_subnets(0, 1, [("GND", "GND")])
    assert label(top, 0, "GND") == label(top, 1, "GND") == "GND"


@pytest.mark.parametrize("names", [("VDD", "VSS"), ("VSS", "VDD"), ("VDD", "OUT")])
def test_connecting_two_different_named_nets_is_rejected(names):
    top = make_top(2)
    top.connect_node(0, [("P", names[0])])
    top.connect_node(1, [("P", names[1])])
    with pytest.raises(ValueError):
        top.connect_subnets(0, 1, [("P", "P")])
    assert (label(top, 0, "P"), label(top, 1, "P")) == names  # nothing was silently rewired


def test_short_through_an_intermediate_net_is_rejected():
    top = make_top(3)
    apply(top, Oracle(), N(0, "VDD"), N(2, "VSS"), S(0, 1))
    with pytest.raises(ValueError):
        top.connect_subnets(1, 2, [("P", "P")])
    assert [label(top, i, "P") for i in range(3)] == ["VDD", "VDD", "VSS"]


def test_renaming_a_net_that_already_has_a_name_is_rejected():
    top = make_top(2)
    apply(top, Oracle(), S(0, 1), N(0, "VDD"))
    with pytest.raises(ValueError):
        top.connect_node(1, [("P", "VSS")])


def test_default_pin_label_that_matches_a_net_name_is_not_a_connection():
    """diff_pair_cmirrorbias: the cmirror's B goes to net 'B'; an antenna diode added afterwards
    has an unconnected pin that is *also* called 'B' and is then connected to VSS."""
    top = Netlist(circuit_name="TOP", nodes=["B", "VSS"])
    top.connect_netlist(Netlist(circuit_name="NMOS", nodes=["B"]), [("B", "B")])
    idx = top.connect_netlist(Netlist(circuit_name="NMOS", nodes=["B"]), [("B", "VSS")])  # must not raise
    assert top.netlist_connections[0] == ["B"] and top.netlist_connections[idx] == ["VSS"]


def test_user_net_named_like_an_auto_wire_does_not_alias_a_generated_wire():
    top = make_top(4)
    apply(top, Oracle(), N(0, "wire0"), S(1, 2))      # a user-chosen name, then an auto wire
    assert label(top, 1, "P") != label(top, 0, "P")
    assert label(top, 1, "P") == label(top, 2, "P")


def test_connect_netlist_then_composite_hierarchy():
    """connect_netlist (used by every composite generator) + subnets."""
    child = Netlist(circuit_name="CH", nodes=["A", "B"])
    top = Netlist(circuit_name="TOP", nodes=["VDD", "VSS"])
    r0 = top.connect_netlist(child, [("A", "VDD")])
    r1 = top.connect_netlist(child, [("B", "VSS")])
    r2 = top.connect_netlist(child, [])
    top.connect_subnets(r0, r1, [("B", "A")])     # two unnamed terminals -> auto wire
    top.connect_subnets(r1, r2, [("A", "A")])
    assert label(top, r0, "A") == "VDD" and label(top, r1, "B") == "VSS"
    assert label(top, r0, "B") == label(top, r1, "A") == label(top, r2, "A")


@pytest.mark.parametrize("seed", range(40))
def test_random_connection_sequences_match_oracle(seed):
    rng = random.Random(seed)
    n, pins = 6, ("P", "Q")
    top, o = make_top(n, pins=pins), Oracle()
    for _ in range(14):
        i, j, a, b = rng.randrange(n), rng.randrange(n), rng.choice(pins), rng.choice(pins)
        if (i, a) == (j, b):
            continue
        request = S(i, j, a, b) if rng.random() < 0.7 else N(i, rng.choice(["VDD", "VSS", "OUT"]), a)
        kind, *args = request
        if o.would_short_named_nets(kind, *args):
            with pytest.raises(ValueError):
                apply(top, Oracle(), request)
        else:
            apply(top, o, request)
    check(top, o)
