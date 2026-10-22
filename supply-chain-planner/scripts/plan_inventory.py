#!/usr/bin/env python3
"""Auditable, offline single-echelon replenishment baseline; Python 3.10+."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics as stats
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

VERSION = "1.0.0"
METHODS = ("mean28", "mean7", "seasonal7")
ITEM_FIELDS = {"sku", "location", "on_hand", "reserved", "backorders",
               "lead_time_days", "review_period_days", "service_level", "moq", "pack_size"}
DEMAND_FIELDS = {"sku", "location", "date", "demand_qty"}
INBOUND_FIELDS = {"order_id", "sku", "location", "qty", "eta", "status"}
WARNINGS = {
    "MISSING_HISTORY": "历史窗口存在缺日，不能默认缺失即零。",
    "HISTORY_FILLED_ZERO": "按显式选项将缺日补零，需用户确认无记录确为零需求。",
    "TOO_SHORT_HISTORY": "有效连续历史不足 28 天。",
    "ZERO_DEMAND": "历史需求全零，需核对新品、停销或数据完整性。",
    "INTERMITTENT_DEMAND": "至少一半日期需求为零，当前常态近似不适用。",
    "CENSORED_SALES": "出库销量期间发生缺货，销量可能低估真实需求。",
    "UNKNOWN_SALES_AVAILABILITY": "部分销售日缺货状态未知，无法确认销量是否受限。",
    "SALES_PROXY": "使用出库销量代理新增需求，数量只作条件情景。",
    "OVERDUE_CONFIRMED_INBOUND": "已确认在途 ETA 已到或已过，需更新状态和日期。",
    "UNCONFIRMED_INBOUND": "未确认在途未计入可靠供应，需确认供应承诺。",
    "LIMITED_BACKTEST": "完整保护期滚动起点不足 8 个，采用独立日需求近似。",
    "DEMAND_SHIFT": "近 7 日与此前 21 日均值变化明显，需核对趋势和活动。",
    "SCENARIO_PARAMETERS": "改变了未来需求倍率或普通新单交期，属于条件情景。",
    "LATE_INBOUND": "部分供应在保护期之后；已抵扣库存位置但不能解决近期缺口。",
    "TIMING_GAP": "普通新单到达前存在预测净缺口，需要独立时序干预。",
    "GAP_AFTER_REGULAR_ORDER": "加入常规补货后仍存在预测欠单，需检查到货时序。",
    "EXCESS_COVER": "静态库存覆盖超过设定情景阈值，需核对品类与生命周期。",
    "MOQ_PACK_UPLIFT": "起订量或整箱倍数使订单高于原始库存位置缺口。",
}


class ContractError(ValueError):
    """Input cannot be interpreted unambiguously."""


@dataclass(frozen=True)
class Item:
    sku: str
    location: str
    on_hand: int
    reserved: int
    backorders: int
    lead_time_days: int
    review_period_days: int
    service_level: float
    moq: int
    pack_size: int
    unit_cost: float | None = None
    currency: str | None = None
    launch_date: date | None = None

    @property
    def key(self):
        return self.sku, self.location


@dataclass(frozen=True)
class Receipt:
    order_id: str
    sku: str
    location: str
    qty: int
    eta: date
    status: str

    @property
    def key(self):
        return self.sku, self.location


@dataclass(frozen=True)
class Config:
    as_of: date
    history_days: int = 56
    demand_kind: str = "orders"
    missing_days: str = "error"
    demand_factor: float = 1.0
    lead_delay_days: int = 0
    excess_cover_days: float = 90.0


def parse_date(value, context):
    try:
        parsed = date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ContractError(f"{context}: expected YYYY-MM-DD") from None
    if parsed.isoformat() != value:
        raise ContractError(f"{context}: expected canonical YYYY-MM-DD")
    return parsed


def number(value, context, *, integer=False, low=0, high=10**12):
    try:
        n = float(value)
    except (ValueError, TypeError):
        raise ContractError(f"{context}: expected a number") from None
    if not math.isfinite(n) or not low <= n <= high:
        raise ContractError(f"{context}: expected finite value in [{low}, {high}]")
    if integer and not n.is_integer():
        raise ContractError(f"{context}: expected whole units")
    return int(n) if integer else n


def read_table(path, required):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ContractError(f"{path}: missing or duplicated headers")
        missing = required - set(reader.fieldnames)
        if missing:
            raise ContractError(f"{path}: missing columns {sorted(missing)}")
        rows = []
        for line, row in enumerate(reader, 2):
            if None in row or any(v is None for v in row.values()):
                raise ContractError(f"{path}:{line}: wrong number of cells")
            if not any(v.strip() for v in row.values()):
                continue
            clean = {k: v.strip() for k, v in row.items()}
            if not clean["sku"] or not clean["location"]:
                raise ContractError(f"{path}:{line}: sku and location must be nonempty")
            rows.append((line, clean))
    return rows


def load_inputs(items_path, demand_path, inbound_path, config):
    items, known = [], set()
    for line, row in read_table(items_path, ITEM_FIELDS):
        ctx = f"{items_path}:{line}"
        key = row["sku"], row["location"]
        if key in known:
            raise ContractError(f"{ctx}: duplicate SKU/location")
        known.add(key)
        values = {f: number(row[f], f"{ctx}:{f}", integer=True) for f in
                  ("on_hand", "reserved", "backorders", "moq")}
        for field in ("lead_time_days", "review_period_days"):
            values[field] = number(row[field], f"{ctx}:{field}", integer=True, low=1, high=365)
        values["pack_size"] = number(row["pack_size"], f"{ctx}:pack_size", integer=True, low=1)
        service = number(row["service_level"], f"{ctx}:service_level", high=1)
        if not 0.5 < service < 1:
            raise ContractError(f"{ctx}: service_level must be strictly between 0.5 and 1")
        if values["reserved"] > values["on_hand"]:
            raise ContractError(f"{ctx}: reserved exceeds physical on_hand")
        if values["lead_time_days"] + values["review_period_days"] + config.lead_delay_days > 366:
            raise ContractError(f"{ctx}: protection horizon exceeds 366 days")
        cost, currency = row.get("unit_cost", ""), row.get("currency", "")
        launch = parse_date(row["launch_date"], f"{ctx}:launch_date") if row.get("launch_date") else None
        if launch and launch > config.as_of:
            raise ContractError(f"{ctx}: launch_date is after snapshot")
        if bool(cost) != bool(currency):
            raise ContractError(f"{ctx}: unit_cost and currency must be supplied together")
        items.append(Item(*key, **values, service_level=service,
                          unit_cost=number(cost, f"{ctx}:unit_cost") if cost else None,
                          currency=currency or None, launch_date=launch))
    if not items:
        raise ContractError("items: no item rows")
    demand = defaultdict(dict)
    launch_dates = {p.key: p.launch_date for p in items}
    for line, row in read_table(demand_path, DEMAND_FIELDS):
        ctx = f"{demand_path}:{line}"
        key = row["sku"], row["location"]
        day = parse_date(row["date"], f"{ctx}:date")
        if key not in known or day > config.as_of:
            raise ContractError(f"{ctx}: unknown SKU/location or demand after snapshot")
        launch = launch_dates[key]
        if launch and day < launch:
            raise ContractError(f"{ctx}: demand record precedes launch_date")
        if day in demand[key]:
            raise ContractError(f"{ctx}: duplicate SKU/location/date")
        qty = number(row["demand_qty"], f"{ctx}:demand_qty", integer=True)
        flag = row.get("stockout", "")
        if flag not in ("", "0", "1"):
            raise ContractError(f"{ctx}: stockout must be 0, 1, or empty")
        demand[key][day] = (qty, None if flag == "" else int(flag))
    receipts, order_ids = [], set()
    for line, row in read_table(inbound_path, INBOUND_FIELDS):
        ctx = f"{inbound_path}:{line}"
        key = row["sku"], row["location"]
        if key not in known:
            raise ContractError(f"{ctx}: unknown SKU/location")
        if not row["order_id"] or row["order_id"] in order_ids:
            raise ContractError(f"{ctx}: empty or duplicate order_id")
        order_ids.add(row["order_id"])
        if row["status"] not in ("confirmed", "unconfirmed", "cancelled"):
            raise ContractError(f"{ctx}: invalid inbound status")
        receipts.append(Receipt(row["order_id"], *key,
                                number(row["qty"], f"{ctx}:qty", integer=True, low=1),
                                parse_date(row["eta"], f"{ctx}:eta"), row["status"]))
    return items, demand, receipts


def predict(training, horizon, method):
    if method == "seasonal7":
        return [training[-7:][i % 7] for i in range(horizon)]
    window = 7 if method == "mean7" else 28
    return [stats.mean(training[-window:])] * horizon


def evaluate(history, horizon):
    """Common rolling origins, training strictly before the predicted period."""
    last = len(history) - horizon
    origins = list(range(max(28, last - 13), last + 1))
    metrics, errors = {}, {}
    for method in METHODS:
        absolute, actual_sum, cumulative_errors = 0.0, 0.0, []
        for origin in origins:
            forecast = predict(history[:origin], horizon, method)
            actual = history[origin:origin + horizon]
            absolute += sum(abs(a - f) for a, f in zip(actual, forecast))
            actual_sum += sum(actual)
            cumulative_errors.append(sum(actual) - sum(forecast))
        n = len(origins)
        metrics[method] = {
            "origins": n,
            "mae_daily": absolute / (n * horizon) if n else None,
            "wape": absolute / actual_sum if actual_sum else None,
            "mae_horizon_total": stats.mean(map(abs, cumulative_errors)) if n else None,
            "bias_horizon_actual_minus_forecast": stats.mean(cumulative_errors) if n else None,
        }
        errors[method] = cumulative_errors
    if len(origins) >= 8:
        chosen = min(METHODS, key=lambda m: (metrics[m]["mae_daily"],
                                            metrics[m]["mae_horizon_total"], METHODS.index(m)))
    else:
        chosen = "mean28"
    return chosen, metrics, errors[chosen]


def round_order(raw_gap, moq, pack_size):
    if raw_gap <= 1e-9:
        return 0
    packs = max(raw_gap, moq) / pack_size
    nearest = round(packs)
    ceiling = nearest if math.isclose(packs, nearest, rel_tol=0, abs_tol=1e-10) else math.ceil(packs)
    return ceiling * pack_size


def plan_one(item, history_rows, receipts, config):
    issues = []

    def issue(code, level):
        if not any(x["code"] == code for x in issues):
            issues.append({"code": code, "level": level, "message": WARNINGS[code]})

    lead = item.lead_time_days + config.lead_delay_days
    horizon = lead + item.review_period_days
    a0 = item.on_hand - item.reserved - item.backorders
    arrivals = defaultdict(int)
    confirmed_future = 0
    late_qty = 0
    for receipt in receipts:
        if receipt.status == "unconfirmed":
            issue("UNCONFIRMED_INBOUND", "scenario")
        if receipt.status != "confirmed":
            continue
        if receipt.eta <= config.as_of:
            issue("OVERDUE_CONFIRMED_INBOUND", "block")
            continue
        confirmed_future += receipt.qty
        arrivals[receipt.eta] += receipt.qty
        if receipt.eta > config.as_of + timedelta(days=horizon):
            late_qty += receipt.qty
    if late_qty:
        issue("LATE_INBOUND", "notice")
    if config.demand_factor != 1 or config.lead_delay_days:
        issue("SCENARIO_PARAMETERS", "scenario")
    days = [config.as_of - timedelta(days=config.history_days - i - 1)
            for i in range(config.history_days)]
    missing = [d.isoformat() for d in days if d not in history_rows]
    if missing:
        issue("HISTORY_FILLED_ZERO" if config.missing_days == "zero" else "MISSING_HISTORY",
              "scenario" if config.missing_days == "zero" else "block")
    present = [history_rows[d] for d in days if d in history_rows]
    if len(present) < 28:
        issue("TOO_SHORT_HISTORY", "block")
    if config.demand_kind == "sales":
        issue("SALES_PROXY", "scenario")
        if any(flag == 1 for _, flag in present):
            issue("CENSORED_SALES", "block")
        if any(flag is None for _, flag in present):
            issue("UNKNOWN_SALES_AVAILABILITY", "block")
    result = {
        "sku": item.sku, "location": item.location, "priority": "P0",
        "recommendation_state": "blocked", "issues": issues,
        "history_observed_days": len(present), "history_missing_dates": missing,
        "available_net_at_snapshot": a0, "confirmed_future_qty": confirmed_future,
        "confirmed_after_horizon_qty": late_qty, "inventory_position": a0 + confirmed_future,
        "lead_time_days": lead, "review_period_days": item.review_period_days,
        "protection_days": horizon, "design_cycle_service_level": item.service_level,
        "normal_arrival_date": (config.as_of + timedelta(days=lead)).isoformat(),
        "suggested_order_qty": None, "estimated_order_goods_value": None,
        "currency": item.currency, "actions": ["先核对阻断项，再确认采购数量。"],
        "daily_projection": [],
    }
    if len(present) < 28 or (missing and config.missing_days != "zero"):
        return result
    history = [history_rows.get(d, (0, None))[0] for d in days]
    if sum(history) == 0:
        issue("ZERO_DEMAND", "block")
    elif sum(x == 0 for x in history) / len(history) >= 0.5:
        issue("INTERMITTENT_DEMAND", "block")
    recent, previous = stats.mean(history[-7:]), stats.mean(history[-28:-7])
    if (previous == 0 and recent > 0) or (previous > 0 and
                                          (recent / previous > 1.5 or recent / previous < 2 / 3)):
        issue("DEMAND_SHIFT", "scenario")
    method, metrics, cumulative_errors = evaluate(history, horizon)
    prediction = [x * config.demand_factor for x in predict(history, horizon, method)]
    z = stats.NormalDist().inv_cdf(item.service_level)
    if len(cumulative_errors) >= 8:
        bias = stats.mean(cumulative_errors)
        sigma = stats.stdev(cumulative_errors)
        safety = (max(0, bias) + z * sigma) * config.demand_factor
        safety_method = "rolling_horizon_errors_plus_positive_bias"
    else:
        issue("LIMITED_BACKTEST", "scenario")
        bias = None
        sigma = stats.stdev(history[-28:]) * math.sqrt(horizon)
        safety = z * sigma * config.demand_factor
        safety_method = "iid_daily_demand_approximation"
    target = sum(prediction) + safety
    raw_gap = max(0.0, target - result["inventory_position"])
    blocked = any(x["level"] == "block" for x in issues)
    qty = None if blocked else round_order(raw_gap, item.moq, item.pack_size)
    if qty is not None and qty - raw_gap > 1e-8:
        issue("MOQ_PACK_UPLIFT", "notice")
    mu = stats.mean(prediction)
    cover = max(0, a0) / mu if mu > 0 else None
    if cover is not None and cover > config.excess_cover_days:
        issue("EXCESS_COVER", "notice")
    net, planned = float(a0), float(a0)
    first = config.as_of.isoformat() if a0 < 0 else None
    min_before, min_baseline = float(a0), float(a0)
    min_with_order = float(a0)
    for d, forecast in enumerate(prediction, 1):
        day = config.as_of + timedelta(days=d)
        received = arrivals.get(day, 0)
        net += received - forecast
        proposal = qty if qty is not None and d == lead else 0
        planned += received + proposal - forecast
        if net < -1e-8 and first is None:
            first = day.isoformat()
        min_baseline = min(min_baseline, net)
        min_with_order = min(min_with_order, planned)
        if d < lead:
            min_before = min(min_before, net)
        result["daily_projection"].append({
            "sku": item.sku, "location": item.location, "date": day.isoformat(),
            "forecast_new_demand": forecast, "confirmed_receipt_qty": received,
            "proposed_regular_receipt_qty": proposal if qty is not None else None,
            "projected_net_baseline": net,
            "projected_net_with_regular_order": planned if qty is not None else None,
        })
    if min_before < -1e-8:
        issue("TIMING_GAP", "notice")
    if qty is not None and min_with_order < -1e-8:
        issue("GAP_AFTER_REGULAR_ORDER", "notice")
    state = "blocked" if blocked else (
        "scenario_only" if any(x["level"] == "scenario" for x in issues) else "ready_for_review")
    priority = "P0" if blocked else (
        "P1" if min_before < -1e-8 else ("P2" if first is not None or qty else "P3"))
    actions = []
    if blocked:
        actions.append("先核对阻断项，再确认采购数量；已有短缺风险同步人工处理。")
    else:
        if min_before < -1e-8 or (min_with_order < -1e-8 and late_qty):
            actions.append("评估催交、分批提前或跨仓调拨；若新增采购，同步复核原订单以免重复采购。")
        if qty:
            actions.append("复核预算、供应能力与交期后，安排常规补货。")
        if cover is not None and cover > config.excess_cover_days:
            actions.append("复核高覆盖原因、后续订单与生命周期，评估推迟采购或消化库存。")
        if not actions:
            actions.append("按复核周期跟踪需求与在途到货；有短缺时优先调整到货计划。")
    result.update({
        "recommendation_state": state, "priority": priority, "actions": actions,
        "forecast_method": method, "forecast_evaluation": metrics,
        "forecast_evaluation_horizon_days": horizon, "overlapping_cv_windows": True,
        "forecast_mean_daily": mu, "safety_method": safety_method,
        "safety_error_bias_before_scenario_scale": bias,
        "safety_error_std_before_scenario_scale": sigma, "safety_stock": safety,
        "target_inventory_position": target, "raw_inventory_position_gap": raw_gap,
        "suggested_order_qty": qty, "moq": item.moq, "pack_size": item.pack_size,
        "moq_pack_uplift_qty": max(0, qty - raw_gap) if qty is not None else None,
        "static_cover_days": cover, "first_shortage_date_baseline": first,
        "peak_net_shortfall_before_normal_arrival": max(0.0, -min_before),
        "peak_net_shortfall_in_horizon_baseline": max(0.0, -min_baseline),
        "peak_net_shortfall_with_regular_order": max(0.0, -min_with_order) if qty is not None else None,
        "proposed_receipt_date": result["normal_arrival_date"] if qty else None,
        "estimated_order_goods_value": qty * item.unit_cost
            if qty is not None and item.unit_cost is not None else None,
    })
    return result


def analyze(items, demand, receipts, config):
    by_key = defaultdict(list)
    for receipt in receipts:
        by_key[receipt.key].append(receipt)
    plans = [plan_one(item, demand.get(item.key, {}), by_key[item.key], config) for item in items]
    plans.sort(key=lambda p: (p["priority"], p["sku"], p["location"]))
    parameters = asdict(config)
    parameters["as_of"] = config.as_of.isoformat()
    return {
        "engine_version": VERSION, "parameters": parameters,
        "summary": {"item_location_count": len(plans),
                    "state_counts": dict(Counter(p["recommendation_state"] for p in plans)),
                    "priority_counts": dict(Counter(p["priority"] for p in plans))},
        "assumptions": ["calendar_days", "end_of_day_snapshot", "receipts_before_daily_demand",
                        "backlogged_unmet_demand", "deterministic_new_order_lead_time",
                        "cycle_service_design_target_not_achieved_fill_rate",
                        "overlapping_out_of_sample_forecast_windows",
                        "no_budget_capacity_or_shelf_life_optimization"],
        "items": plans,
    }


def safe_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def write_csv(path, rows, fields):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({k: safe_cell(v) for k, v in row.items()} for row in rows)


def write_report(report, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    fields = ["sku", "location", "priority", "recommendation_state", "forecast_method",
              "forecast_mean_daily", "inventory_position", "safety_stock", "target_inventory_position",
              "raw_inventory_position_gap", "suggested_order_qty", "normal_arrival_date",
              "first_shortage_date_baseline", "peak_net_shortfall_before_normal_arrival",
              "peak_net_shortfall_with_regular_order", "confirmed_after_horizon_qty", "static_cover_days",
              "estimated_order_goods_value", "currency", "issue_codes", "actions_text"]
    rows, projection = [], []
    for item in report["items"]:
        rows.append({**item, "issue_codes": "|".join(x["code"] for x in item["issues"]),
                     "actions_text": " ".join(item["actions"])})
        projection.extend(item["daily_projection"])
    write_csv(directory / "planning.csv", rows, fields)
    write_csv(directory / "projection.csv", projection,
              ["sku", "location", "date", "forecast_new_demand", "confirmed_receipt_qty",
               "proposed_regular_receipt_qty", "projected_net_baseline", "projected_net_with_regular_order"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("items", "demand", "inbound", "as-of", "demand-kind", "out"):
        kwargs = {"required": True}
        if field == "demand-kind":
            kwargs["choices"] = ("orders", "sales")
        parser.add_argument("--" + field, **kwargs)
    parser.add_argument("--history-days", type=int, default=56)
    parser.add_argument("--missing-days", choices=("error", "zero"), default="error")
    parser.add_argument("--demand-factor", default="1")
    parser.add_argument("--lead-delay-days", type=int, default=0)
    parser.add_argument("--excess-cover-days", default="90")
    args = parser.parse_args(argv)
    try:
        if not 28 <= args.history_days <= 730 or not 0 <= args.lead_delay_days <= 365:
            raise ContractError("history-days must be 28..730; lead-delay-days must be 0..365")
        config = Config(parse_date(args.as_of, "as-of"), args.history_days, args.demand_kind,
                        args.missing_days, number(args.demand_factor, "demand-factor", low=0.01, high=100),
                        args.lead_delay_days,
                        number(args.excess_cover_days, "excess-cover-days", low=1, high=36500))
        if Path(args.out).exists():
            raise ContractError("out directory already exists; choose a new path")
        items, demand, receipts = load_inputs(args.items, args.demand, args.inbound, config)
        report = analyze(items, demand, receipts, config)
        report["input_sha256"] = {field: hashlib.sha256(Path(getattr(args, field)).read_bytes()).hexdigest()
                                  for field in ("items", "demand", "inbound")}
        write_report(report, args.out)
    except (ContractError, OSError, UnicodeError, csv.Error) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"output": str(Path(args.out).resolve()), **report["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
