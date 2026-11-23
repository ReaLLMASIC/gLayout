"""``route``: one routing pass, the tie fallback, and detour re-landing, with a process table."""
from __future__ import annotations

from glayout.floorplan.router.access import combo_key
from glayout.floorplan.router.metrics import detours, route_cost
from glayout.floorplan.router.negotiate import attempt
from glayout.floorplan.router.problem import RoutingProblem, RoutingResult
from glayout.floorplan.router.tech import RouterTech
from glayout.util.process_table import ProcessTable, print_table


def reland_detours(problem: RoutingProblem, tech: RouterTech, result: RoutingResult, st,
                   spread: bool = True) -> RoutingResult:
    """Retry detoured nets with their side combination excluded; keep a retry only if it is cheaper.

    Rip-up and reroute fixes conflicts, not detours: a net walled off by other nets' landings
    routes around a block and counts as routed. Worst detour first, at most ``max_relands``
    tries; each retry routes everything again, and is kept only if it routes and lowers
    wirelength + c_via·vias. ``st`` is the process-table stage to report to.
    """
    found = detours(result)
    if not found:
        st.detail("none")
        return result
    best, exclude, tried, kept = result, {}, set(), []
    for _ in range(tech.max_relands):
        cand = {n: e for n, e in detours(best).items() if n not in tried}
        if not cand:
            break
        net = max(cand, key=lambda n: (cand[n], n))
        tried.add(net)
        pins = problem.nets[net]
        landed = {l.pin.owner: l.option for l in best.landings.get(net, [])}
        if any(p.owner not in landed for p in pins):
            continue
        # exclusions accumulate: a kept change stays excluded while later nets are tried
        trial_ex = {**exclude, net: set(exclude.get(net, ())) | {combo_key(pins, [landed[p.owner] for p in pins])}}
        trial = attempt(problem, tech, ProcessTable("detour retry"), trial_ex, spread)     # never printed
        if trial.success and route_cost(trial) < route_cost(best) - 1e-9:
            best, exclude = trial, trial_ex
            kept.append(net)
    found_txt = ", ".join(f"{n} +{e:.1f}µm" for n, e in sorted(found.items()))
    if kept:
        st.detail(f"{found_txt}; re-landed {', '.join(kept)}: wirelength {result.wirelength:.1f} -> "
                  f"{best.wirelength:.1f}µm, vias {result.vias} -> {best.vias}")
    else:
        st.detail(f"{found_txt}; no re-landing was cheaper")
    return best


def route(problem: RoutingProblem, tech: RouterTech, title: str = "Route", verbose: bool = True) -> RoutingResult:
    """Route every net of ``problem``; prints a process table titled ``title``.

    First a pass with side ties spread by channel load. If that fails, a pass with the
    original first-listed tie rule, whose result is kept either way. If the result routes,
    detoured nets are re-landed (``tech.detour_ratio > 0``). ``verbose`` also prints the
    rip-up/reroute history when there was more than one iteration.
    """
    with ProcessTable(title, f"{len(problem.nets)} nets, pitch {tech.pitch}µm on {'/'.join(tech.layers)}") as pt:
        result, spread = attempt(problem, tech, pt), True
        if not result.success:
            # spreading ties ignores how many pins a cell side can land: it can
            # take the spot a pin with no other legal side needed. The original
            # tie rule reproduces the old router's landings, so never route worse.
            # On a double failure the plain result is kept too, so the closed
            # loop sees the same failure spots and grows the same padding.
            with pt.stage("Ties fallback") as st:
                result, spread = attempt(problem, tech, ProcessTable("plain ties"), spread=False), False    # never printed
                if result.success:
                    st.detail("spread side ties did not route; first-listed sides do")
                else:
                    st.warn("first-listed sides do not route either")
        if result.success and tech.detour_ratio > 0:
            with pt.stage("Detours") as st:
                result = reland_detours(problem, tech, result, st, spread)
        with pt.stage("Result") as st:
            st.detail(f"wirelength {result.wirelength:.2f}µm, {result.vias} via stacks")
            if not result.success:
                st.fail(f"failed nets {result.failed_nets}"
                        + (f", unreachable pins {result.unreachable}" if result.unreachable else ""))
        pt.result("routed", "yes" if result.success else "NO")
        pt.result("iterations", result.iterations)
        pt.result("wirelength_um", f"{result.wirelength:.2f}")
        pt.result("vias", result.vias)
    if verbose and len(result.history) > 1:
        print_table(f"{title}: rip-up/reroute", ["iteration", "conflict nodes", "ripped", "unroutable"],
                    [(h["iteration"], h["conflict_nodes"], h["ripped"], h["unroutable"]) for h in result.history])
    return result
