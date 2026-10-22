"""Multiple-choice integer allocation: one feasible order option per SKU/location."""
import math


def options(max_qty, moq, pack):
    if not max_qty:
        return [0]
    first = max(pack, math.ceil(moq / pack) * pack)
    if (max_qty - first) // pack + 2 > 20000:
        raise ValueError("more than 20000 discrete order options")
    return [0] + list(range(first, max_qty + 1, pack))


def solve(groups, budget=None, capacity=None, time_limit=30):
    """Exact within enumerated options when HiGHS certifies optimality.

    capacity is total ordered base units for this review, not warehouse occupancy.
    Costs are modeled finite-horizon operating costs; option zero is always feasible.
    """
    if not groups:
        return {"quantities": [], "status": "empty", "optimal": True,
                "objective": 0., "spend": 0., "capacity_used": 0.}
    for bound in (budget, capacity):
        if bound is not None and (not math.isfinite(bound) or bound < 0):
            raise ValueError("resource limits must be finite and nonnegative")
    flat, owner = [], []
    for i, group in enumerate(groups):
        if not group or not any(x["qty"] == 0 for x in group):
            raise ValueError("every item needs a zero-order option")
        for x in group:
            if any(not math.isfinite(x[k]) or x[k] < 0 for k in ("qty", "spend", "cost")):
                raise ValueError("option quantities, spending, costs must be finite and nonnegative")
            flat.append(x)
            owner.append(i)
    if len(flat) > 20000:
        raise ValueError("more than 20000 discrete options; narrow the scope or increase base pack size")
    try:
        import numpy as np
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import lil_matrix
    except ImportError as error:
        raise RuntimeError("constrained allocation requires numpy and scipy; no silent greedy fallback") from error
    n, extra = len(flat), int(budget is not None) + int(capacity is not None)
    matrix = lil_matrix((len(groups) + extra, n))
    for j, i in enumerate(owner):
        matrix[i, j] = 1
    lower, upper = [1.] * len(groups), [1.] * len(groups)
    row = len(groups)
    for bound, field in ((budget, "spend"), (capacity, "qty")):
        if bound is not None:
            matrix[row, :] = [x[field] for x in flat]
            lower.append(-np.inf)
            upper.append(bound)
            row += 1
    result = milp(np.array([x["cost"] for x in flat]), integrality=np.ones(n),
                  bounds=Bounds(np.zeros(n), np.ones(n)),
                  constraints=LinearConstraint(matrix.tocsc(), lower, upper),
                  options={"time_limit": time_limit, "mip_rel_gap": 0.})
    if result.x is None:
        raise RuntimeError(f"allocation failed without feasible incumbent: {result.message}")
    selected = []
    for i in range(len(groups)):
        hits = [flat[j] for j in range(n) if owner[j] == i and result.x[j] > .5]
        if len(hits) != 1:
            raise RuntimeError("solver returned a nonintegral or incomplete allocation")
        selected.append(hits[0])
    spend, used = sum(x["spend"] for x in selected), sum(x["qty"] for x in selected)
    if (budget is not None and spend > budget + 1e-6) or (capacity is not None and used > capacity + 1e-6):
        raise RuntimeError("solver allocation failed independent resource check")
    return {"quantities": [x["qty"] for x in selected], "objective": sum(x["cost"] for x in selected),
            "spend": spend, "capacity_used": used, "optimal": result.status == 0,
            "status": "optimal" if result.status == 0 else "feasible_not_proven_optimal",
            "solver_message": result.message, "mip_gap": getattr(result, "mip_gap", None),
            "option_count": n, "scope": "enumerated_orders_up_to_unconstrained_recommendation"}
