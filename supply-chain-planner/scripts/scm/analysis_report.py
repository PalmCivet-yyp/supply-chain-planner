"""Common escaped HTML and CSV exports for the operational decision workflows."""
import html
import json
from pathlib import Path

from .report import csv_file, table


def write_analysis(report, output):
    out = Path(output)
    if out.exists():
        raise ValueError("output already exists")
    sections = {
        "procurement_analysis": [("支出与集中度", "spend_groups"), ("采购阶段用时", "cycle_metrics"),
                                  ("供应商交付", "supplier_otif"), ("三单核对", "three_way_matches")],
        "sourcing_comparison": [("方案成本与约束", "options"), ("符合条件的比较", "ranking"),
                                 ("权重敏感性", "sensitivity"), ("来源核查记录", "sources")],
        "sop_analysis": [("预测指标", "forecast_by_item"), ("月度供需平衡", "balance"),
                          ("待决事项", "actions"), ("会议议题", "agenda")],
    }[report["kind"]]
    serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    out.mkdir(parents=True)
    (out / "report.json").write_text(serialized, encoding="utf-8")
    body = f"<h1>供应链分析</h1><p>{html.escape(report['kind'])} · {html.escape(report['as_of'])}</p>"
    for title, key in sections:
        values = report[key]
        def display(v):
            if isinstance(v, dict): return {k: display(x) for k, x in v.items()}
            if isinstance(v, list): return [display(x) for x in v]
            return round(v, 12) if isinstance(v, float) else v
        flat = [{k: json.dumps(display(v), ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in r.items()} for r in values]
        fields = list(dict.fromkeys(k for r in flat for k in r))
        csv_file(out / f"{key}.csv", flat, fields or None)
        body += f"<h2>{title}</h2>" + (table(fields, [[r.get(k) for k in fields] for r in flat]) if flat else "<p>无记录</p>")
    if report["kind"] == "sop_analysis":
        body += "<h2>总体预测指标</h2>" + table(["指标", "数值"], list(report["forecast_metrics"].items()))
    body += "<h2>计算口径</h2><ul>" + "".join(f"<li>{html.escape(v)}</li>" for v in report["limitations"]) + "</ul>"
    document = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>供应链分析</title><style>body{font:15px/1.6 system-ui,sans-serif;margin:24px;color:#243145}main{max-width:1200px;margin:auto}table{border-collapse:collapse;display:block;overflow:auto;font-size:13px}td,th{padding:9px 12px;border-bottom:1px solid #d6dde6;max-width:420px;min-width:70px;overflow-wrap:anywhere}th{background:#203b61;color:white;text-align:left}h2{margin-top:30px}tr:nth-child(even){background:#f2f5f9}</style><main>'
    (out / "report.html").write_text(document + body + "</main></html>", encoding="utf-8")
