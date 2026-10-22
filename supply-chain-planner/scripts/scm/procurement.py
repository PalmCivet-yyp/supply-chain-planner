"""Currency-separated spend, stage times, joint line OTIF, and cumulative three-way matching."""
from collections import defaultdict
import math
import statistics
from decimal import Decimal

from plan_inventory import ContractError
from . import VERSION
from .contracts import day, month, num, object_, percentile, rows, text, unique


def analyze(data):
    object_(data, ("as_of", "spend"), ("cycles", "deliveries", "matches", "supplier_aliases"))
    as_of = day(data["as_of"], "as_of")
    aliases = data.get("supplier_aliases", {})
    if not isinstance(aliases, dict):
        raise ContractError("supplier_aliases: require explicit text-to-text map")
    normalized = [(text(a, "alias"), text(b, "canonical supplier")) for a, b in aliases.items()]
    if len(dict(normalized)) != len(normalized):
        raise ContractError("supplier_aliases: duplicate aliases after trimming")
    aliases = dict(normalized)
    for a, b in aliases.items():
        if b in aliases and aliases[b] != b:
            raise ContractError("supplier_aliases: use one-hop canonical names; chains/cycles are ambiguous")
    spend = rows(data["spend"], "spend", empty=True)
    unique(spend, context="spend")
    buckets = defaultdict(list)
    for r in spend:
        object_(r, ("id", "supplier", "category", "period", "amount", "currency"),
                ("upstream_group", "critical"), "spend row")
        supplier = text(r["supplier"], "supplier")
        supplier = aliases.get(supplier, supplier)
        period = month(r["period"], "period")
        if period > as_of.strftime("%Y-%m"):
            raise ContractError("spend: period is after as_of")
        currency = text(r["currency"], "currency")
        category = text(r["category"], "category")
        amount = num(r["amount"], "amount")
        if "critical" in r and not isinstance(r["critical"], bool):
            raise ContractError("critical: require boolean")
        upstream = text(r["upstream_group"], "upstream_group") if r.get("upstream_group") is not None else None
        buckets[(period, currency, category)].append({**r, "supplier": supplier, "amount": amount,
                                                     "upstream_group": upstream})
    summaries = []
    for (period, currency, category), group in sorted(buckets.items()):
        by_supplier = defaultdict(list)
        for r in group:
            by_supplier[r["supplier"]].append(r["amount"])
        amounts = {k: math.fsum(v) for k, v in by_supplier.items()}
        total = math.fsum(amounts.values())
        ranked, cumulative = [], 0.
        for supplier, amount in sorted(amounts.items(), key=lambda kv: (-kv[1], kv[0])):
            prior = cumulative
            share = amount / total if total else None
            cumulative += share or 0
            ranked.append({"supplier": supplier, "amount": amount, "share": share,
                           "cumulative_share": cumulative if total else None,
                           "abc": ("A" if prior < .8 else "B" if prior < .95 else "C") if total else None})
        upstream = defaultdict(set)
        for r in group:
            upstream[r["supplier"]].add(r["upstream_group"])
        if any(len(v - {None}) > 1 for v in upstream.values()):
            raise ContractError("one supplier has conflicting upstream_group within a category-period")
        all_known = all(None not in v for v in upstream.values())
        groups = {next(iter(v)) for v in upstream.values()} if all_known else set()
        flags = [r.get("critical") for r in group]
        critical = True if True in flags else False if all(v is False for v in flags) else None
        summaries.append({"period": period, "currency": currency, "category": category,
                          "total_spend": total, "supplier_count": len(amounts),
                          "top_supplier_share": ranked[0]["share"],
                          "hhi_fraction": math.fsum((x / total)**2 for x in amounts.values()) if total else None,
                          "upstream_group_count": len(groups) if all_known else None,
                          "independence_status": "shared_upstream_exposure" if all_known and len(groups) < len(amounts)
                              else "groups_declared_distinct_not_independently_verified" if all_known else "unknown",
                          "critical": critical, "suppliers": ranked,
                          "action": "review_function_overlap_and_switching_cost_before_consolidation" if critical is False else "review_resilience_before_any_consolidation",
                          "estimated_savings": None})
    cycle_rows = rows(data.get("cycles", []), "cycles", empty=True)
    unique(cycle_rows, context="cycles")
    stages = defaultdict(list)
    for r in cycle_rows:
        object_(r, ("id", "category", "requested", "approved", "po_created", "paid"), context="cycle row")
        category = text(r["category"], "category")
        dates = [day(r[k], k) for k in ("requested", "approved", "po_created", "paid")]
        if dates != sorted(dates) or dates[-1] > as_of:
            raise ContractError("cycles: require requested <= approved <= PO <= paid <= as_of")
        for stage, a, b in (("request_to_approval", 0, 1), ("approval_to_po", 1, 2),
                            ("po_to_payment", 2, 3), ("request_to_po", 0, 2)):
            stages[(category, stage)].append((dates[b] - dates[a]).days)
    cycles = [{"category": c, "stage": s, "sample_count": len(v),
               "median_days": statistics.median(v), "p90_days": percentile(v, .9)}
              for (c, s), v in sorted(stages.items())]
    deliveries = rows(data.get("deliveries", []), "deliveries", empty=True)
    unique(deliveries, context="deliveries")
    delivery_result, supplier_result = [], defaultdict(list)
    for r in deliveries:
        object_(r, ("id", "supplier", "due_date", "delivered_date", "ordered_qty", "delivered_qty"), context="delivery row")
        supplier = text(r["supplier"], "supplier")
        supplier = aliases.get(supplier, supplier)
        due = day(r["due_date"], "due_date")
        delivered = day(r["delivered_date"], "delivered_date") if r["delivered_date"] is not None else None
        oq = num(r["ordered_qty"], "ordered_qty", minimum=1, whole=True)
        dq = num(r["delivered_qty"], "delivered_qty", whole=True)
        if delivered and delivered > as_of:
            raise ContractError("delivery date is after as_of")
        if delivered is None and dq:
            raise ContractError("delivered quantity requires delivered_date")
        in_population = due <= as_of
        on_time = delivered is not None and delivered <= due
        full = dq >= oq
        row = {"id": r["id"], "supplier": supplier, "due_date": r["due_date"],
               "included_due_by_as_of": in_population, "on_time": on_time,
               "in_full": full, "line_otif": on_time and full if in_population else None}
        delivery_result.append(row)
        if in_population:
            supplier_result[supplier].append(row)
    otif = [{"supplier": k, "due_line_count": len(v),
             "on_time_rate": sum(x["on_time"] for x in v) / len(v),
             "in_full_rate": sum(x["in_full"] for x in v) / len(v),
             "line_otif": sum(x["line_otif"] for x in v) / len(v)} for k, v in sorted(supplier_result.items())]
    matches = rows(data.get("matches", []), "matches", empty=True)
    unique(matches, context="matches")
    match_result = []
    for r in matches:
        object_(r, ("id", "currency", "po_qty", "received_qty", "invoice_qty", "unit_price", "invoice_amount", "amount_tolerance"), context="match row")
        currency = text(r["currency"], "currency")
        q, received, invoiced = [num(r[k], k, whole=True) for k in ("po_qty", "received_qty", "invoice_qty")]
        if q == 0:
            raise ContractError("po_qty must be positive")
        price = num(r["unit_price"], "unit_price")
        amount = num(r["invoice_amount"], "invoice_amount")
        tolerance = num(r["amount_tolerance"], "amount_tolerance")
        expected_decimal = Decimal(str(invoiced)) * Decimal(str(price))
        expected = float(expected_decimal)
        quantity_ok = invoiced <= received <= q
        amount_ok = abs(Decimal(str(amount)) - expected_decimal) <= Decimal(str(tolerance))
        status = "discrepancy" if not (quantity_ok and amount_ok) else "matched" if invoiced == received == q else "partial_match"
        match_result.append({"id": r["id"], "currency": currency, "expected_invoice_subtotal": expected,
                             "quantity_match": quantity_ok, "amount_match": amount_ok, "status": status,
                             "action": "investigate_discrepancy" if status == "discrepancy" else "review_for_payment",
                             "amount_tolerance": tolerance})
    return {"kind": "procurement_analysis", "engine_version": VERSION, "as_of": as_of.isoformat(),
            "spend_groups": summaries, "cycle_metrics": cycles, "delivery_lines": delivery_result,
            "supplier_otif": otif, "three_way_matches": match_result,
            "limitations": ["Spend is separated by period, currency and supplied category; no exchange rates or automatic supplier merging.",
                "OTIF population is order lines due on or before as_of; no claim of order-level OTIF or upstream independence.",
                "Matching uses cumulative quantities and pre-tax invoice subtotal for one PO line; tolerance is explicit. No payment is executed.",
                "Concentration and duplicate-function review do not prove consolidation savings."]}
