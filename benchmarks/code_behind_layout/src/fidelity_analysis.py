"""Finite-pool ranking diagnostics; no candidate selection reads the oracle."""
import math
from itertools import combinations


def _ranks(values):
    ordered = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[start]]:
            end += 1
        for index in ordered[start:end]:
            ranks[index] = (start + end - 1) / 2 + 1
        start = end
    return ranks


def _correlation(left, right):
    a, b = sum(left) / len(left), sum(right) / len(right)
    numerator = sum((x-a)*(y-b) for x, y in zip(left, right))
    denominator = math.sqrt(sum((x-a)**2 for x in left) * sum((y-b)**2 for y in right))
    return numerator / denominator if denominator else None


def rank_diagnostics(predictions, actual, *, prediction_absolute_tolerance,
                     actual_absolute_tolerance, relative_tolerance):
    """Compare estimates of the same declared objective, in the same unit.

    Spearman uses ordinary exact-tie average ranks. Pair diagnostics and tau-b
    additionally ignore declared numerical ties; their tolerance is never fitted
    using the evaluation pool. Undefined correlations remain None.
    """
    if len(predictions) != len(actual) or len(actual) < 2:
        raise ValueError("At least two matched predictions and actual measurements are required")
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in predictions + actual):
        raise ValueError("Ranking requires finite measurements")
    tolerances = [prediction_absolute_tolerance, actual_absolute_tolerance, relative_tolerance]
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in tolerances):
        raise ValueError("Numerical tie tolerances must be frozen finite nonnegative values")
    def sign(x, y, absolute):
        difference = x-y
        return 0 if abs(difference) <= max(absolute, relative_tolerance*max(abs(x), abs(y))) else (1 if difference > 0 else -1)
    concordant = discordant = prediction_ties = actual_ties = both_ties = 0
    for i, j in combinations(range(len(actual)), 2):
        x = sign(predictions[i], predictions[j], prediction_absolute_tolerance)
        y = sign(actual[i], actual[j], actual_absolute_tolerance)
        if x == 0 and y == 0:
            both_ties += 1
        elif x == 0:
            prediction_ties += 1
        elif y == 0:
            actual_ties += 1
        elif x == y:
            concordant += 1
        else:
            discordant += 1
    comparable = concordant + discordant
    denominator = math.sqrt((comparable+prediction_ties)*(comparable+actual_ties))
    return {"n": len(actual), "spearman_exact_ties": _correlation(_ranks(predictions), _ranks(actual)),
            "kendall_tau_b_declared_ties": (concordant-discordant)/denominator if denominator else None,
            "concordant_pairs": concordant, "reversed_pairs": discordant,
            "prediction_only_ties": prediction_ties, "actual_only_ties": actual_ties, "both_ties": both_ties,
            "effective_pair_reversal_rate": discordant/comparable if comparable else None}


def finite_pool_selection(candidates, selected_ids, *, objective, direction):
    """Measure delivered feasibility and regret after selection has completed.

    An infeasible delivery has no invented numeric objective or regret. Its
    explicit feasible_delivery=False stays in the success denominator.
    """
    if direction not in ("min", "max"):
        raise ValueError("Objective direction must be declared")
    by_id = {row["candidate_id"]: row for row in candidates}
    if len(by_id) != len(candidates) or len(set(selected_ids)) != len(selected_ids):
        raise ValueError("Candidate and selection IDs must be distinct")
    if any(name not in by_id for name in selected_ids):
        raise ValueError("Selected candidate is absent from the frozen pool")
    feasible = [row for row in candidates if row["feasible"]]
    for row in feasible:
        value = row.get(objective)
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("Feasible candidates need a measured finite objective")
    choose = min if direction == "min" else max
    oracle = choose(feasible, key=lambda row: row[objective]) if feasible else None
    delivered = [by_id[name] for name in selected_ids if by_id[name]["feasible"]]
    best = choose(delivered, key=lambda row: row[objective]) if delivered else None
    regret = None if best is None else ((best[objective]-oracle[objective]) if direction == "min" else
                                       (oracle[objective]-best[objective]))
    return {"pool_size": len(candidates), "feasible_pool_size": len(feasible),
            "full_evaluation_count": len(selected_ids), "feasible_delivery": best is not None,
            "selected_candidate_id": best["candidate_id"] if best else None,
            "finite_pool_oracle_candidate_id": oracle["candidate_id"] if oracle else None,
            "absolute_regret": regret, "regret_unit": "same_as_declared_objective"}
