"""Monthly S&OP balance scenarios, zero-safe forecast KPIs and accountable meeting actions."""
from collections import defaultdict
import math

from plan_inventory import ContractError
from . import VERSION
from .contracts import day, month, num, object_, rows, text, unique
from .simulation import State, step


def kpis(records):
    actual = math.fsum(r["actual"] for r in records)
    error = math.fsum(r["forecast"] - r["actual"] for r in records)
    absolute = math.fsum(abs(r["forecast"] - r["actual"]) for r in records)
    nonzero = [r for r in records if r["actual"] > 0]
    n = len(records)
    return {"records": n, "actual_total": actual, "forecast_total": math.fsum(r["forecast"] for r in records),
            "mae": absolute / n if n else None, "wape": absolute / actual if actual else None,
            "bias_units": error / n if n else None, "bias_fraction": error / actual if actual else None,
            "mean_error_units": error / n if n else None, "cumulative_error_units": error if n else None,
            "mape_nonzero_actual": math.fsum(abs(r["forecast"] - r["actual"]) / r["actual"] for r in nonzero) / len(nonzero) if nonzero else None,
            "mape_coverage": len(nonzero) / n if n else None,
            "tracking_signal": error / (absolute / n) if absolute and n else 0. if n else None}


def analyze(data):
    object_(data, ("as_of", "meeting_date", "next_meeting_date", "opening_date", "opening", "plan", "history"),
            ("owners", "scenarios"))
    as_of = day(data["as_of"], "as_of")
    meeting, following = day(data["meeting_date"], "meeting_date"), day(data["next_meeting_date"], "next_meeting_date")
    if not as_of <= meeting < following:
        raise ContractError("require as_of <= meeting_date < next_meeting_date")
    owners = data.get("owners", {})
    if not isinstance(owners, dict) or set(owners) - {"demand", "supply", "procurement"}:
        raise ContractError("owners: allowed roles demand, supply, procurement")
    owners = {k: text(v, f"owners.{k}") for k, v in owners.items()}
    opening = rows(data["opening"], "opening")
    states = {}
    for r in opening:
        object_(r, ("sku", "location", "stock", "backlog"), context="opening row")
        key = text(r["sku"], "sku"), text(r["location"], "location")
        if key in states:
            raise ContractError("opening: duplicate SKU/location")
        stock, backlog = num(r["stock"], "stock"), num(r["backlog"], "backlog")
        if stock and backlog:
            raise ContractError("opening: settle available stock against backlog first")
        states[key] = (stock, backlog)
    plans = rows(data["plan"], "plan")
    by_key, seen = defaultdict(list), set()
    for r in plans:
        object_(r, ("sku", "location", "period", "demand", "planned_supply", "capacity"), context="plan row")
        key = text(r["sku"], "sku"), text(r["location"], "location")
        period = month(r["period"], "period")
        if key not in states or (*key, period) in seen or period <= as_of.strftime("%Y-%m"):
            raise ContractError("plan: unknown/duplicate key or month not after the snapshot month")
        seen.add((*key, period))
        for k in ("demand", "planned_supply", "capacity"):
            num(r[k], k)
        by_key[key].append(r)
    if set(by_key) != set(states):
        raise ContractError("each opening key needs a plan")
    period_sets = []
    for key in by_key:
        by_key[key].sort(key=lambda r: r["period"])
        periods = [r["period"] for r in by_key[key]]
        numbers = [int(p[:4]) * 12 + int(p[5:]) for p in periods]
        if numbers != list(range(numbers[0], numbers[0] + len(numbers))):
            raise ContractError("plan months must be consecutive for each key")
        period_sets.append(periods)
    if any(p != period_sets[0] for p in period_sets):
        raise ContractError("all plan keys require the same months")
    opening_date = day(data["opening_date"], "opening_date")
    if opening_date.isoformat() != period_sets[0][0] + "-01":
        raise ContractError("opening_date must be the first planned month start; opening quantities are scenario estimates at that date")
    history = rows(data["history"], "history", empty=True)
    history_keys = set()
    by_history = defaultdict(list)
    for r in history:
        object_(r, ("sku", "location", "period", "actual", "forecast"), context="history row")
        key = text(r["sku"], "sku"), text(r["location"], "location")
        period = month(r["period"], "period")
        if key not in states or (*key, period) in history_keys or period >= as_of.strftime("%Y-%m"):
            raise ContractError("history: unknown/duplicate key or month not completed before snapshot month")
        history_keys.add((*key, period))
        num(r["actual"], "actual"); num(r["forecast"], "forecast")
        by_history[key].append(r)
    scenarios = rows(data.get("scenarios", [{"id": "base", "demand_factor": 1., "supply_factor": 1.}]), "scenarios")
    unique(scenarios, context="scenarios")
    if len(scenarios) > 20:
        raise ContractError("maximum 20 S&OP scenarios")
    output, actions = [], []
    for s in scenarios:
        object_(s, ("id", "demand_factor", "supply_factor"), context="scenario")
        df = num(s["demand_factor"], "demand_factor", maximum=10)
        sf = num(s["supply_factor"], "supply_factor", maximum=10)
        for key, records in sorted(by_key.items()):
            state = State(*states[key])
            for r in records:
                demand = r["demand"] * df
                planned = r["planned_supply"] * sf
                supply = min(planned, r["capacity"])
                start_stock, start_backlog = state.stock, state.backlog
                event = step(state, demand, supply, "backorder")
                row = {"scenario": s["id"], "sku": key[0], "location": key[1], "period": r["period"],
                       "opening_stock": start_stock, "opening_backlog": start_backlog, "demand": demand,
                       "planned_supply": planned, "capacity": r["capacity"], "effective_supply": supply,
                       "capacity_excess": max(0., planned - r["capacity"]), **event}
                output.append(row)
                if row["capacity_excess"] or row["ending_backlog"]:
                    actions.append({"id": f"{s['id']}:{key[0]}:{key[1]}:{r['period']}",
                                    "scenario": s["id"], "sku": key[0], "location": key[1], "period": r["period"],
                                    "decision": "review_capacity_and_supply_gap", "gap_units": row["ending_backlog"],
                                    "capacity_excess": row["capacity_excess"], "owner": owners.get("supply"),
                                    "due_date": meeting.isoformat(), "status": "open" if owners.get("supply") else "awaiting_owner"})
    return {"kind": "sop_analysis", "engine_version": VERSION, "as_of": as_of.isoformat(),
            "meeting_date": meeting.isoformat(), "next_meeting_date": following.isoformat(), "quantity_unit": "pieces",
            "opening_date": opening_date.isoformat(),
            "forecast_metrics": kpis(history),
            "forecast_by_item": [{"sku": k[0], "location": k[1], **kpis(v)} for k, v in sorted(by_history.items())],
            "balance": output, "actions": actions, "owners": owners,
            "agenda": [{"topic": "Demand review", "owner": owners.get("demand"), "decision": "confirm forecast and assumptions"},
                       {"topic": "Supply and capacity", "owner": owners.get("supply"), "decision": "resolve the listed monthly gaps"},
                       {"topic": "Procurement and resilience", "owner": owners.get("procurement"), "decision": "confirm receipt timing and dependencies"}],
            "limitations": ["Monthly aggregate balance carries backlog; it cannot identify within-month stockouts, production routing or BOM requirements.",
                             "Planned supply and capacity are supplied per SKU/location; shared line capacity is not optimized.",
                             "MAPE excludes zero-actual rows and exposes coverage; zero denominators produce null, never perfect accuracy.",
                             "Missing owners remain awaiting_owner; no meeting, order or message is sent."]}
