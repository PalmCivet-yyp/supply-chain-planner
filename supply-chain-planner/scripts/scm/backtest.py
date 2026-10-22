"""Chronological policy replay with frozen validation choice and paired lead scenarios."""
import hashlib
import math
import statistics as st
from collections import defaultdict
from dataclasses import replace
from datetime import timedelta

from plan_inventory import ContractError, Receipt
from .engine import plan
from .simulation import State, operating_cost, step
from .io import json_safe


def lead_delay(seed, key, day, scenarios):
    """Common random numbers keyed to item and order date, never policy/order count."""
    digest = hashlib.sha256(f"{seed}|{key[0]}|{key[1]}|{day.isoformat()}".encode()).digest()
    u = int.from_bytes(digest[:8], "big") / 2 ** 64
    cumulative = 0.
    for delay, probability in scenarios:
        cumulative += probability
        if u < cumulative:
            return delay
    return scenarios[-1][0]


def metrics(rows, currency):
    demand = sum(r["demand"] for r in rows)
    cycles = defaultdict(bool)
    for r in rows:
        cycle = (r["sku"], r["location"], r["cycle"])
        cycles[cycle] |= r["new_shortage"] > 1e-8
    # Only completed review cycles are included; phase-edge fragments are excluded.
    full = [v for k, v in cycles.items() if all(
        r["cycle_complete_in_phase"] for r in rows if (r["sku"], r["location"], r["cycle"]) == k)]
    return {"currency": currency, "demand_units": demand,
            "immediate_fill_rate": sum(r["immediately_fulfilled"] for r in rows) / demand if demand else None,
            "review_cycle_no_new_shortage_rate": 1 - sum(full) / len(full) if full else None,
            "completed_review_cycles": len(full),
            "lost_units": sum(r["lost_units"] for r in rows),
            "backlog_unit_days": sum(r["ending_backlog"] for r in rows),
            "average_stock_per_item_day": st.mean(r["ending_stock"] for r in rows) if rows else None,
            "holding_cost": sum(r["holding_cost"] for r in rows),
            "shortage_cost": sum(r["shortage_cost"] for r in rows),
            "ordering_cost": sum(r["ordering_cost"] for r in rows),
            "modeled_operating_cost": sum(r["modeled_operating_cost"] for r in rows),
            "purchase_cash": sum(r["order_spend"] for r in rows),
            "orders": sum(r["order_qty"] > 0 for r in rows),
            "ending_stock": sum(r["ending_stock"] for r in rows if r["is_last_phase_day"]),
            "ending_backlog": sum(r["ending_backlog"] for r in rows if r["is_last_phase_day"]),
            "ending_pipeline_units": sum(r["pipeline_qty"] for r in rows if r["is_last_phase_day"])}


def replay(products, histories, economics, c, start, validation_days, test_days,
           policy, seed, initial_stock_days=14):
    """Explicit reset scenario: start stock from TRAINING mean; no historical POs assumed."""
    states, pipeline = {}, defaultdict(list)
    for p in products:
        y = [histories[p.key][start - timedelta(days=i)][0] for i in range(1, 29)]
        states[p.key] = State(math.ceil(st.mean(y) * initial_stock_days))
    rows, decisions = [], []
    total_days = validation_days + test_days
    for offset in range(total_days):
        day, as_of = start + timedelta(days=offset), start + timedelta(days=offset - 1)
        due = [p for p in products if offset % p.review_period_days == 0]
        orders = {p.key: 0 for p in products}
        if due:
            snapshots = [replace(p, on_hand=int(round(states[p.key].stock)), reserved=0,
                                 backorders=int(round(states[p.key].backlog))) for p in due]
            inbound = [r for p in due for r in pipeline[p.key]]
            pc = {**c, "as_of": as_of, "forecast_method": policy["method"],
                  "safety_scale": policy["safety_scale"]}
            result = plan(snapshots, histories, inbound, economics, pc)
            decisions.append({"as_of": as_of.isoformat(), "allocation": result["allocation"],
                              "history_windows": [{"sku": x["sku"], "location": x["location"],
                                  "start": x.get("history_effective_start"),
                                  "end": x.get("history_last_date"),
                                  "observed_days": x["history_observed_days"]} for x in result["items"]]})
            by_key = {p.key: p for p in due}
            for proposed in result["items"]:
                key = proposed["sku"], proposed["location"]
                q = proposed["suggested_order_qty"]
                if q is None:
                    raise ContractError(f"backtest policy blocked at {as_of}: {key}")
                orders[key] = q
                if q:
                    delay = lead_delay(seed, key, as_of, c["lead_scenarios"])
                    eta = as_of + timedelta(days=by_key[key].lead_time_days + delay)
                    pipeline[key].append(Receipt(f"replay-{key}-{offset}", *key, q, eta, "confirmed"))
        phase = "validation" if offset < validation_days else "test"
        phase_start = 0 if phase == "validation" else validation_days
        phase_end = validation_days if phase == "validation" else total_days
        for p in products:
            arrivals = sum(r.qty for r in pipeline[p.key] if r.eta == day)
            pipeline[p.key] = [r for r in pipeline[p.key] if r.eta > day]
            event = step(states[p.key], histories[p.key][day][0], arrivals, c["shortage_mode"])
            cycle_start = offset // p.review_period_days * p.review_period_days
            complete = cycle_start >= phase_start and cycle_start + p.review_period_days <= phase_end
            costs = operating_cost([event], economics[p.key], c["shortage_mode"], orders[p.key])
            rows.append({"date": day.isoformat(), "sku": p.sku, "location": p.location,
                         "phase": phase, "policy": policy["name"], "seed": seed,
                         "cycle": offset // p.review_period_days, "cycle_complete_in_phase": complete,
                         "is_last_phase_day": offset + 1 == phase_end,
                         "order_qty": orders[p.key], "order_spend": orders[p.key] * p.unit_cost,
                         "pipeline_qty": sum(r.qty for r in pipeline[p.key]), **event, **costs})
    return {phase: metrics([r for r in rows if r["phase"] == phase], c["currency"])
            for phase in ("validation", "test")}, rows, decisions


def backtest(products, histories, economics, c, train_days=120, validation_days=56,
             test_days=56, seeds=(17, 23, 41), initial_stock_days=14, min_fill=.95):
    if c["demand_kind"] != "orders":
        raise ContractError("policy replay requires observed new customer demand (orders), not censored sales")
    if train_days < 28 or validation_days < 1 or test_days < 1 or initial_stock_days < 0:
        raise ContractError("backtest requires train>=28, positive validation/test and nonnegative initial stock days")
    if not .5 < min_fill <= 1 or not seeds or len(seeds) != len(set(seeds)):
        raise ContractError("backtest requires distinct seeds and min-fill in (.5,1]")
    if any(p.key not in economics or p.unit_cost is None for p in products):
        raise ContractError("business replay requires explicit operating costs and unit cost for every item")
    if {p.currency for p in products} != {c["currency"]}:
        raise ContractError("business replay requires one explicit matching currency")
    last = c["as_of"]
    first = last - timedelta(days=train_days + validation_days + test_days - 1)
    all_days = [first + timedelta(days=i) for i in range(train_days + validation_days + test_days)]
    for p in products:
        if any(d not in histories.get(p.key, {}) for d in all_days):
            raise ContractError(f"backtest requires complete consecutive demand for {p.key}")
    start = first + timedelta(days=train_days)
    # The rolling lookback can exceed the initialization interval. Declare and validate warm-up.
    history_start = start - timedelta(days=c["history_days"])
    for p in products:
        source = histories[p.key]
        actual_start = max(history_start, min(d for d in source if d <= start - timedelta(days=1)))
        for n in range((start - actual_start).days):
            if actual_start + timedelta(days=n) not in source:
                raise ContractError(f"backtest warm-up history has missing days for {p.key}")
    policies = [{"name": "baseline_mean28", "method": "mean28", "safety_scale": 1.},
                {"name": "baseline_seasonal7", "method": "seasonal7", "safety_scale": 1.}]
    policies += [{"name": f"adaptive_{scale:g}", "method": None, "safety_scale": scale}
                 for scale in (.75, 1., 1.25)]
    validation = []
    # Test days are not replayed during selection, including hidden terminal statistics.
    for policy in policies:
        result, _, _ = replay(products, histories, economics, c, start, validation_days, 0,
                              policy, seeds[0], initial_stock_days)
        validation.append({"policy": policy, "metrics": result["validation"]})
    def rank(record):
        m = record["metrics"]
        fill = m["immediate_fill_rate"]
        passed = fill is not None and fill >= min_fill
        return (0 if passed else 1, m["modeled_operating_cost"] if passed else -(fill or 0),
                m["modeled_operating_cost"])
    adaptive = min(validation[2:], key=rank)["policy"]
    baseline = min(validation[:2], key=rank)["policy"]
    results, traces, decision_audits = [], [], []
    for seed in seeds:
        for policy in (baseline, adaptive):
            metric, rows, decisions = replay(products, histories, economics, c, start,
                                            validation_days, test_days, policy, seed, initial_stock_days)
            results.append({"seed": seed, "policy": policy["name"], **metric["test"]})
            traces.extend(rows)
            decision_audits.append({"seed": seed, "policy": policy["name"], "decisions": decisions})
    differences = []
    fill_differences = []
    for seed in seeds:
        a = next(r for r in results if r["seed"] == seed and r["policy"] == adaptive["name"])
        b = next(r for r in results if r["seed"] == seed and r["policy"] == baseline["name"])
        differences.append(a["modeled_operating_cost"] - b["modeled_operating_cost"])
        if a["immediate_fill_rate"] is not None and b["immediate_fill_rate"] is not None:
            fill_differences.append(a["immediate_fill_rate"] - b["immediate_fill_rate"])
    mean_cost, mean_fill = st.mean(differences), st.mean(fill_differences) if fill_differences else None
    candidate_fills = [r["immediate_fill_rate"] for r in results
                       if r["policy"] == adaptive["name"] and r["immediate_fill_rate"] is not None]
    candidate_mean_fill = st.mean(candidate_fills) if candidate_fills else None
    verdict = "cost_and_service_improved_in_replay" if mean_cost < 0 and mean_fill is not None and mean_fill >= 0 else (
        "cost_service_tradeoff" if mean_cost < 0 else "no_cost_improvement_in_replay")
    report = {"kind": "policy_backtest", "shortage_mode": c["shortage_mode"],
              "split": {"training": [first.isoformat(), (start - timedelta(days=1)).isoformat()],
                        "validation": [start.isoformat(), (start + timedelta(days=validation_days - 1)).isoformat()],
                        "test": [(start + timedelta(days=validation_days)).isoformat(), last.isoformat()]},
              "initial_state": {"type": "explicit_reset_scenario", "stock_days_from_training_mean28": initial_stock_days,
                                "backlog": 0, "pipeline": 0, "historical_snapshot_and_inbound_used": False},
              "history_access": {"lookback_days": c["history_days"],
                                 "initialization_interval": [first.isoformat(), (start - timedelta(days=1)).isoformat()],
                                 "first_review_requested_start": history_start.isoformat(),
                                 "first_review_actual_starts": [{"sku": p.sku, "location": p.location,
                                     "start": max(history_start, min(d for d in histories[p.key] if d < start)).isoformat()}
                                     for p in products],
                                 "warmup_before_training_allowed": True,
                                 "rule": "training labels initialization and policy-selection setup; rolling forecasts may use earlier observed warm-up history. Every decision exposes its actual dates; end must be <= as_of."},
              "selection_rule": {"minimum_validation_fill": min_fill,
                                 "rule": "minimum operating cost among eligible; otherwise highest fill then cost",
                                 "validation_seed": seeds[0], "test_used_for_selection": False},
              "validation": validation, "selected_baseline": baseline, "selected_adaptive": adaptive,
              "test_runs": results,
              "paired_comparison": {"adaptive_minus_baseline_operating_cost": differences,
                                    "mean_operating_cost_difference": mean_cost,
                                    "mean_fill_rate_difference": mean_fill,
                                    "lead_scenario_cost_difference_range": [min(differences), max(differences)],
                                    "verdict": verdict},
              "adoption_gate": {"recommendation": "review_candidate" if verdict == "cost_and_service_improved_in_replay" and candidate_mean_fill is not None and candidate_mean_fill >= min_fill else "retain_baseline",
                                "candidate_mean_immediate_fill_rate": candidate_mean_fill,
                                "minimum_immediate_fill_rate": min_fill,
                                "basis": "Require lower modeled cost, nondecreasing mean immediate fill AND the explicit minimum fill target in held-out replay. Audit gate only, not automatic deployment."},
              "limitations": ["Historical demand is one observed path; lead scenarios are user assumptions.",
                              "Seed range measures lead-scenario variation, not a confidence interval for business savings.",
                              "Review-cycle no-new-shortage rate is not replenishment-cycle CSL.",
                              "Operating cost excludes purchase cash, tax, transport, terminal value and costs after test end.",
                              "Capacity and budget reset per review event; they are not warehouse occupancy or annual budgets."],
              "decision_audits": decision_audits}
    return json_safe(report), traces
