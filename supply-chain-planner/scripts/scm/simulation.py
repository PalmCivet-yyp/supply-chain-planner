"""Explicit physical stock, backlog, and lost-sales event accounting."""
from dataclasses import dataclass
import math


@dataclass
class State:
    stock: float
    backlog: float = 0.


def opening(item, mode):
    if mode not in ("backorder", "lost_sales"):
        raise ValueError("mode must be backorder or lost_sales")
    if mode == "lost_sales" and item.backorders:
        raise ValueError("lost_sales requires backorders=0; resolve historical obligations first")
    available = item.on_hand - item.reserved
    fill = min(available, item.backorders)
    return State(available - fill, item.backorders - fill)


def step(state, demand, received, mode):
    if mode not in ("backorder", "lost_sales"):
        raise ValueError("unknown shortage mode")
    if any(not math.isfinite(x) or x < 0 for x in (demand, received, state.stock, state.backlog)):
        raise ValueError("state, demand, receipts must be finite and nonnegative")
    if mode == "lost_sales" and state.backlog:
        raise ValueError("lost-sales state cannot contain backlog")
    initial_stock, initial_backlog = state.stock, state.backlog
    stock = state.stock + received
    old_fulfilled = min(stock, state.backlog)
    stock -= old_fulfilled
    immediately_fulfilled = min(stock, demand)
    short = max(0., demand - immediately_fulfilled)
    state.stock = max(0., stock - immediately_fulfilled)
    state.backlog = state.backlog - old_fulfilled + (short if mode == "backorder" else 0.)
    return {"opening_stock": initial_stock, "opening_backlog": initial_backlog,
            "demand": demand, "received": received, "backlog_fulfilled": old_fulfilled,
            "immediately_fulfilled": immediately_fulfilled, "new_shortage": short,
            "lost_units": short if mode == "lost_sales" else 0.,
            "ending_stock": state.stock, "ending_backlog": state.backlog}


def simulate(item, demands, receipts, mode, order_qty=0, lead=None):
    """Receipts at START of day; order at snapshot close arrives on day L."""
    state, rows = opening(item, mode), []
    lead = item.lead_time_days if lead is None else lead
    for day, demand in enumerate(demands, 1):
        received = receipts.get(day, 0) + (order_qty if day == lead else 0)
        rows.append({"day": day, **step(state, demand, received, mode)})
    return rows


def operating_cost(rows, economics, mode, order_qty=0):
    """Operating costs only. Purchase cash is reported separately, never added twice."""
    holding = sum(r["ending_stock"] for r in rows) * economics["holding_cost_per_unit_day"]
    base = "ending_backlog" if mode == "backorder" else "lost_units"
    shortage = sum(r[base] for r in rows) * economics["shortage_cost"]
    ordering = economics["order_fixed_cost"] if order_qty else 0.
    return {"holding_cost": holding, "shortage_cost": shortage, "ordering_cost": ordering,
            "modeled_operating_cost": holding + shortage + ordering}
