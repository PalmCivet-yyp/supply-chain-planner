"""Portable audit exports and self-contained Chinese HTML reports."""
import csv
import html
import json
from pathlib import Path

from plan_inventory import safe_cell
from .io import json_safe


def csv_file(path, rows, fields=None):
    rows = list(rows)
    fields = fields or (list(rows[0]) if rows else ["no_records"])
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: safe_cell(v) if isinstance(v, str) else v for k, v in row.items()})


def table(headers, rows):
    def cell(v):
        if v is None:
            return "—"
        if isinstance(v, float):
            return f"{v:,.3f}".rstrip("0").rstrip(".")
        return html.escape(str(v))
    return "<table><thead><tr>" + "".join(f"<th>{cell(v)}</th>" for v in headers) + "</tr></thead><tbody>" + "".join(
        "<tr>" + "".join(f"<td>{cell(v)}</td>" for v in row) + "</tr>" for row in rows) + "</tbody></table>"


def chart(rows):
    if not rows:
        return ""
    values = [r["with_order"]["ending_stock"] for r in rows]
    backlog = [r["with_order"]["ending_backlog"] for r in rows]
    maximum = max(values + backlog + [1])
    def points(series):
        return " ".join(f"{32 + i * 516 / max(1, len(series) - 1):.2f},{146 - v * 120 / maximum:.2f}" for i, v in enumerate(series))
    return f'<svg viewBox="0 0 580 180" role="img" aria-label="逐日预测实物库存与欠单"><path d="M32 20V146H550" fill="none" stroke="#a2acbb"/><polyline points="{points(values)}" fill="none" stroke="#2457a6" stroke-width="2.5"/><polyline points="{points(backlog)}" fill="none" stroke="#c16524" stroke-width="2.5"/><text x="32" y="172">{rows[0]["date"]}</text><text x="450" y="172">{rows[-1]["date"]}</text><text x="35" y="18">最高 {maximum:,.1f} 件</text></svg>'


def write_outputs(report, output, trace=None):
    out = Path(output)
    if out.exists():
        raise ValueError("output directory already exists; choose a new directory")
    out.mkdir(parents=True)
    (out / "report.json").write_text(json.dumps(json_safe(report), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    if report.get("kind") == "policy_backtest":
        csv_file(out / "test_metrics.csv", report["test_runs"])
        csv_file(out / "replay.csv", trace or [])
        headers = ["政策", "交期种子", "即时满足率", "日均库存/项", "运营成本", "采购现金", "期末欠单", "期末在途"]
        rows = [[r["policy"], r["seed"], r["immediate_fill_rate"], r["average_stock_per_item_day"],
                 r["modeled_operating_cost"], r["purchase_cash"], r["ending_backlog"], r["ending_pipeline_units"]]
                for r in report["test_runs"]]
        body = "<h2>样本外政策回测</h2><p>训练、验证、测试按日期切分。政策参数仅按验证期选择，测试期保持不变。</p>"
        body += table(["区间", "开始", "结束"], [[k, *v] for k, v in report["split"].items()])
        body += table(headers, rows)
        body += "<h2>配对比较</h2>" + table(["指标", "结果"], [[k, str(v)] for k, v in report["paired_comparison"].items()])
        gate = report.get("adoption_gate", {}).get("recommendation")
        body += "<h2>采用建议</h2><p>" + ("保留基线；候选未同时满足成本下降、平均即时满足率不下降及显式最低满足率门槛。" if gate == "retain_baseline" else "候选可进入业务复核；回测结果不能替代实际业务验证。") + "</p>"
        body += "<h2>适用范围</h2><ul>" + "".join(f"<li>{html.escape(v)}</li>" for v in report["limitations"]) + "</ul>"
    else:
        flat = [{k: v for k, v in p.items() if not isinstance(v, (dict, list))} for p in report["items"]]
        fields = list(dict.fromkeys(k for r in flat for k in r))
        csv_file(out / "planning.csv", flat, fields)
        projections, issues, forecasts = [], [], []
        for p in report["items"]:
            key = {"sku": p["sku"], "location": p["location"]}
            for row in p["daily_projection"]:
                projections.append({**key, "date": row["date"], **{"baseline_" + k: v for k, v in row["baseline"].items()},
                                    **{"with_order_" + k: v for k, v in row["with_order"].items()}})
            issues.extend({**key, **i} for i in p["issues"])
            forecasts.extend({**key, "method": m, **v} for m, v in p.get("forecast_evaluation", {}).items())
        csv_file(out / "projection.csv", projections)
        csv_file(out / "issues.csv", issues)
        csv_file(out / "forecast_metrics.csv", forecasts)
        body = f'<p>快照 {html.escape(report["parameters"]["as_of"])} · 引擎 {report["engine_version"]} · 模型 {report["parameters"]["shortage_mode"]}</p>'
        body += table(["SKU", "仓库", "状态", "无预算数量", "建议数量", "采购货值", "基准短缺日"],
                      [[p["sku"], p["location"], p["recommendation_state"], p["unconstrained_order_qty"],
                        p["suggested_order_qty"], p.get("estimated_order_goods_value"), p.get("first_shortage_date_baseline")]
                       for p in report["items"]])
        body += "<h2>共享资源分配</h2>" + table(["字段", "结果"], [[k, str(v)] for k, v in report["allocation"].items() if k != "orders"])
        for p in report["items"]:
            body += f'<h2>{html.escape(p["sku"])} / {html.escape(p["location"])}</h2>'
            body += "<p>" + " ".join(html.escape(a) for a in p["actions"]) + "</p>"
            body += chart(p["daily_projection"])
            if p["daily_projection"]:
                body += '<p class="legend">蓝：预测实物库存（件）。橙：累计欠单（件）。到货先于当日需求；曲线为条件点预测。</p>'
            if p["issues"]:
                body += table(["级别", "代码", "说明"], [[i["severity"], i["code"], i["message"]] for i in p["issues"]])
            body += f'<details><summary>预测与缓冲依据</summary><pre>{html.escape(json.dumps({k:p.get(k) for k in ("forecast_method", "segment", "safety_stock", "safety_calibration")},ensure_ascii=False,indent=2))}</pre></details>'
        body += "<h2>成本口径</h2><p>" + html.escape(report["cost_definition"]) + "</p>"
    document = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>供应链运行报告</title><style>body{font:15px/1.65 system-ui,sans-serif;color:#243145;background:#f2f4f8;margin:0}main{max-width:1120px;margin:24px auto;padding:28px 32px;background:white;border-radius:10px}h1{font-size:28px}h2{font-size:20px;margin-top:32px}table{border-collapse:collapse;width:100%;font-size:13px;display:block;overflow:auto}th{background:#223c61;color:white}td,th{padding:10px 12px;text-align:left;border-bottom:1px solid #dce2eb;white-space:nowrap}tr:nth-child(even){background:#f8fafc}svg{max-width:600px;width:100%;font:11px sans-serif}pre{white-space:pre-wrap;background:#f4f6fa;padding:14px}details{margin:14px 0}.legend{font-size:12px;color:#59687a}</style><main><h1>供应链运行报告</h1>'
    document += body + '</main></html>'
    (out / "report.html").write_text(document, encoding="utf-8")
