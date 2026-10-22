"""Plan dated inventory, compare feasible orders, and expose all decision evidence."""
from collections import Counter, defaultdict
from datetime import timedelta
import statistics as st

from plan_inventory import round_order
from . import VERSION
from .allocation import options, solve
from .forecast import compare, predict, protection, segment
from .simulation import operating_cost, simulate
from .io import json_safe


def demand_paths(y, point, method, factor):
    """Up to four disjoint historical error paths, conditional scenarios not a fitted distribution."""
    horizon = len(point)
    origins = list(range(28, len(y) - horizon + 1, horizon))[-4:]
    if len(origins) < 2:
        return [point], "point_forecast_only"
    paths = []
    for o in origins:
        past = predict(y[:o], horizon, method)
        paths.append([max(0., f + (a - p) * factor)
                      for f, a, p in zip(point, y[o:o + horizon], past)])
    return paths, "four_or_fewer_historical_error_paths"


def expected_cost(item, paths, arrivals, mode, econ, qty, scenarios):
    totals = defaultdict(float)
    for delay, weight in scenarios:
        for path in paths:
            rows = simulate(item, path, arrivals, mode, qty, item.lead_time_days + delay)
            cost = operating_cost(rows, econ, mode, qty)
            for k, value in cost.items():
                totals[k] += value * weight / len(paths)
    return dict(totals)


def plan(products, histories, receipts, economics, c, provenance=None):
    mode, as_of = c["shortage_mode"], c["as_of"]
    max_delay = max(d for d, _ in c["lead_scenarios"])
    common_h = max(p.lead_time_days + p.review_period_days + max_delay for p in products)
    by_key = defaultdict(list)
    for r in receipts:
        by_key[r.key].append(r)
    plans, groups, active, private = [], [], [], {}
    scenario_steps = 0
    for product in products:
        key, issues = product.key, []
        def issue(code, severity, message):
            issues.append({"code": code, "severity": severity, "message": message})
        source = histories.get(key, {})
        dates = [as_of - timedelta(days=i) for i in range(c["history_days"] - 1, -1, -1)]
        observed = [d for d in dates if d in source]
        first = min(observed) if observed else None
        launch = getattr(product, "launch_date", None)
        older = any(d < dates[0] for d in source)
        if launch and any(d < launch for d in source):
            issue("HISTORY_BEFORE_LAUNCH", "block", "需求记录早于明确上市日期，先核对上市依据。")
        if launch and launch > as_of:
            issue("LAUNCH_AFTER_SNAPSHOT", "block", "上市日期晚于快照。")
        # A visible tail is not evidence of a new launch. Older records establish a mature item.
        coverage_start = max(dates[0], launch) if launch else (dates[0] if older else first)
        usable = [d for d in dates if coverage_start and d >= coverage_start]
        if first and first > dates[0] and not launch and not older:
            issue("UNVERIFIED_HISTORY_START", "scenario", "历史只覆盖窗口尾段；未提供上市日期，不能确认前段属于上市前。")
        missing = [d for d in usable if d not in source]
        if not first:
            issue("NO_HISTORY", "block", "没有可用历史，须提供需求依据。")
        if first and len(usable) < 28:
            issue("NEW_SHORT_HISTORY", "scenario", "历史少于28天，使用短历史基线，尚未验证预测效果。")
        if missing:
            issue("MISSING_DAYS", "scenario" if c["missing_days"] == "zero" else "block",
                  "历史中存在缺日；仅在显式确认后补零。")
        if len(usable) < 7:
            issue("INSUFFICIENT_HISTORY", "block", "有效历史不足7天，无法自动确定数量。")
        if c["demand_kind"] == "sales":
            issue("SALES_PROXY", "scenario", "出库代理需求，结果为条件情景。")
            if any(source[d][1] != 0 for d in observed):
                issue("CENSORED_OR_UNKNOWN_SALES", "block", "销量曾缺货或可用性未知，不能当作完整需求。")
        item_receipts = by_key[key]
        if any(r.status == "confirmed" and r.eta <= as_of for r in item_receipts):
            issue("OVERDUE_INBOUND", "block", "逾期确认在途需要更新ETA或收货状态。")
        if any(r.status == "unconfirmed" for r in item_receipts):
            issue("UNCONFIRMED_INBOUND", "scenario", "未确认供应未计入可靠供应。")
        future = [r for r in item_receipts if r.status == "confirmed" and r.eta > as_of]
        future_qty = sum(r.qty for r in future)
        arrivals = defaultdict(float)
        for r in future:
            arrivals[(r.eta - as_of).days] += r.qty
        physical = product.on_hand - product.reserved
        ip = physical - product.backorders + future_qty
        result = {"sku": product.sku, "location": product.location, "issues": issues,
                  "recommendation_state": "blocked", "unconstrained_order_qty": None,
                  "suggested_order_qty": None, "history_observed_days": len(observed),
                  "history_requested_start": dates[0].isoformat(),
                  "history_effective_start": usable[0].isoformat() if usable else None,
                  "history_last_date": as_of.isoformat(),
                  "history_missing_days": len(missing),
                  "history_start_basis": "explicit_launch" if launch else ("older_record" if older else "observed_data"),
                  "inventory_position": ip, "confirmed_future_qty": future_qty,
                  "currency": product.currency, "unit_cost": product.unit_cost,
                  "moq": product.moq, "pack_size": product.pack_size,
                  "shortage_mode": mode, "daily_projection": [], "actions": []}
        plans.append(result)
        if any(x["severity"] == "block" for x in issues):
            result["actions"] = ["先处理数据阻断项；已有欠单和临期缺口同步人工处理。"]
            continue
        y = [source.get(d, (0, None))[0] for d in usable]
        h = product.lead_time_days + product.review_period_days + max_delay
        method, metrics = compare(y, h, c["forecast_method"])
        risk = protection(y, product.lead_time_days, product.review_period_days,
                          product.service_level, method, c["lead_scenarios"])
        if risk["nonoverlapping_calibration_periods"] < 4:
            issue("LIMITED_RISK_CALIBRATION", "scenario", "保护期校准样本不足，缓冲仅为独立日需求近似情景。")
        factor = c["demand_factor"]
        point = [v * factor for v in predict(y, common_h, method)]
        safety = risk["safety_stock"] * c["safety_scale"] * factor
        target = sum(point[:product.lead_time_days + product.review_period_days]) + safety
        raw = max(0., target - ip)
        qty = round_order(raw, product.moq, product.pack_size)
        if sum(y) == 0:
            issue("ALL_ZERO_HISTORY", "scenario", "历史全零；默认不补充预测需求，仅清偿明确欠单。")
        if len(y) >= 28 and st.mean(y[-28:-7]) > 0 and not 2 / 3 <= st.mean(y[-7:]) / st.mean(y[-28:-7]) <= 1.5:
            issue("DEMAND_SHIFT", "scenario", "近期需求发生变化，核对促销、趋势及一次性大单。")
        if c["demand_factor"] != 1 or c["safety_scale"] != 1:
            issue("EXPLICIT_SCENARIO", "scenario", "使用了显式需求或缓冲倍率。")
        late = sum(r.qty for r in future if (r.eta - as_of).days > common_h)
        if late:
            issue("LATE_INBOUND", "notice", "远期在途已抵扣库存位置；近期缺口需催交或协调取消后另购。")
        result.update({"forecast_method": method, "forecast_evaluation": metrics,
                       "forecast_selection_metric": "mae_protection_total_then_daily",
                       "segment": segment(y), "safety_stock": safety, "safety_calibration": risk,
                       "design_cycle_service_level": product.service_level,
                       "target_inventory_position": target, "raw_gap": raw,
                       "unconstrained_order_qty": qty, "suggested_order_qty": qty,
                       "common_projection_horizon_days": common_h,
                       "confirmed_after_horizon_qty": late,
                       "base_arrival_date": (as_of + timedelta(days=product.lead_time_days)).isoformat(),
                       "latest_scenario_arrival_date": (as_of + timedelta(days=product.lead_time_days + max_delay)).isoformat()})
        daily_mean = st.mean(point)
        result["static_cover_days"] = physical / daily_mean if daily_mean else None
        result["net_cover_days_after_backlog"] = max(0., physical - product.backorders) / daily_mean if daily_mean else None
        if result["static_cover_days"] is not None and result["static_cover_days"] > 90:
            issue("EXCESS_COVER", "notice", "静态覆盖超过90天情景阈值；复核生命周期及后续订单，不能直接认定呆滞。")
        paths, cost_method = demand_paths(y, point, method, factor)
        private[key] = (product, point, arrivals, paths)
        result["cost_scenario_method"] = cost_method
        if c["allocation"] == "economic":
            choices = options(qty, product.moq, product.pack_size)
            if len(choices) > 20000:
                raise ValueError("SKU exceeds 20000 order options; reduce scope or use service mode")
            scenario_steps += len(choices) * len(paths) * len(c["lead_scenarios"]) * common_h
            if scenario_steps > 3000000:
                raise ValueError("economic scenario evaluation exceeds 3 million daily events; narrow scope or use service mode")
            group = [{"qty": q, "spend": q * product.unit_cost,
                      "cost": expected_cost(product, paths, arrivals, mode, economics[key], q,
                                            c["lead_scenarios"])["modeled_operating_cost"]} for q in choices]
            groups.append(group)
            active.append(result)
    allocation = {"status": "service_order_up_to", "optimal": None}
    if groups:
        allocation = solve(groups, c["budget"], c["capacity_units"])
        chosen_quantities = allocation.pop("quantities")
        allocation["orders"] = [{"sku": p["sku"], "location": p["location"], "qty": q}
                                for p, q in zip(active, chosen_quantities)]
        for result, q in zip(active, chosen_quantities):
            result["suggested_order_qty"] = q
            if q < result["unconstrained_order_qty"]:
                result["issues"].append({"code": "ECONOMIC_ALLOCATION_REDUCED", "severity": "notice",
                    "message": "按有限期成本与共享约束减少数量；不保证达到原服务设计目标。"})
    for result in plans:
        key = result["sku"], result["location"]
        if key not in private:
            continue
        product, point, arrivals, paths = private[key]
        q = result["suggested_order_qty"]
        baseline = simulate(product, point, arrivals, mode)
        proposed = simulate(product, point, arrivals, mode, q)
        first = next((as_of + timedelta(days=r["day"]) for r in baseline if r["new_shortage"] > 1e-8), None)
        initial_gap = max(0, product.backorders - (product.on_hand - product.reserved))
        new_before = sum(r["new_shortage"] for r in baseline if r["day"] < product.lead_time_days)
        before = initial_gap + new_before
        if initial_gap:
            first = as_of
        result["first_shortage_date_baseline"] = first.isoformat() if first else None
        result["new_unfilled_units_before_base_arrival"] = new_before
        result["initial_backlog_after_stock_allocation"] = initial_gap
        result["projected_immediate_fill_rate"] = (sum(r["immediately_fulfilled"] for r in proposed) / sum(point)) if sum(point) else None
        result["estimated_order_goods_value"] = q * product.unit_cost if product.unit_cost is not None else None
        result["moq_pack_uplift_qty"] = max(0., result["unconstrained_order_qty"] - result["raw_gap"])
        result["daily_projection"] = [{"date": (as_of + timedelta(days=a["day"])).isoformat(),
                                       "baseline": a, "with_order": b} for a, b in zip(baseline, proposed)]
        if key in economics:
            result["modeled_expected_cost_without_order"] = expected_cost(product, paths, arrivals, mode, economics[key], 0, c["lead_scenarios"])
            result["modeled_expected_cost_with_order"] = expected_cost(product, paths, arrivals, mode, economics[key], q, c["lead_scenarios"])
        result["recommendation_state"] = "scenario_only" if any(i["severity"] == "scenario" for i in result["issues"]) else "ready_for_review"
        result["priority"] = "P1" if before > 1e-8 else ("P2" if first or q else "P3")
        result["actions"] = (["计划员在下次需求日之前核对催交或调拨；常规订单不能覆盖到货前缺口。"] if before else [])
        if q:
            result["actions"].append("采购按建议数量复核供应承诺，财务核对采购货值及预算。")
        if result["confirmed_after_horizon_qty"]:
            result["actions"].append("采购复核远期在途；另购时同步协商原订单，避免重复采购。")
        if not result["actions"]:
            result["actions"] = ["按复核周期监控需求、库存及在途；当前不新增常规订单。"]
    return json_safe({"engine_version": VERSION, "parameters": c, "provenance": provenance or {},
                      "summary": {"item_location_count": len(plans),
                                  "state_counts": dict(Counter(p["recommendation_state"] for p in plans))},
                      "allocation": allocation,
                      "cost_definition": "End-of-day stock holding + daily backlog OR lost units penalty + order fixed cost. Purchase cash separate. No tax, transport, terminal value or post-horizon cost modeled.",
                      "items": sorted(plans, key=lambda p: (p.get("priority", "P0"), p["sku"], p["location"]))})
