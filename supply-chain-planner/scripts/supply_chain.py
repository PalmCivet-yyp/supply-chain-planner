#!/usr/bin/env python3
"""Offline supply-chain CLI: inventory, procurement, sourcing, S&OP and portable export."""
import argparse
import json
import sys
from pathlib import Path

from plan_inventory import ContractError
from scm import VERSION
from scm.backtest import backtest
from scm.demo import make_demo
from scm.engine import plan
from scm.io import load_bundle, settings
from scm.report import write_outputs


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--version", action="version", version=VERSION)
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="report Python and optional capability versions")
    demo = commands.add_parser("demo", help="write seeded synthetic CSV inputs and settings")
    demo.add_argument("--out", required=True)
    demo.add_argument("--seed", type=int, default=20261021)
    for name in ("procure", "source", "sop"):
        p = commands.add_parser(name)
        p.add_argument("--input", required=True, help="documented JSON data; see references/operations.md")
        p.add_argument("--out", required=True)
    export = commands.add_parser("export", help="portable XLSX from calculated inventory JSON")
    export.add_argument("--plan", required=True, help="plan report.json")
    export.add_argument("--backtest", help="optional backtest report.json")
    export.add_argument("--out", required=True, help="new .xlsx file")
    advanced = commands.add_parser("optimize", help="bounded facility, VRPTW, blending, production or serial inventory optimization")
    advanced.add_argument("--kind", required=True, choices=["facility", "routing", "blending", "production", "serial"])
    advanced.add_argument("--input", required=True)
    advanced.add_argument("--out", required=True)
    advanced.add_argument("--seconds", type=float, default=60)
    advanced.add_argument("--seed", type=int, default=17)
    chain = commands.add_parser("chain", help="dated procurement, shared production, inventory and transfer scenarios")
    chain.add_argument("--input", required=True)
    chain.add_argument("--out", required=True)
    chain.add_argument("--seconds", type=float, default=60)
    delivery = commands.add_parser("optimization-export", help="portable XLSX of complete optimization or chain decisions")
    delivery.add_argument("--input", required=True, help="calculated report.json")
    delivery.add_argument("--out", required=True, help="new .xlsx file")
    review = commands.add_parser("review-optimization", help="validate and choose between an existing baseline and a candidate facility/routing plan")
    review.add_argument("--input", required=True)
    review.add_argument("--baseline", required=True)
    review.add_argument("--candidate", required=True)
    review.add_argument("--out", required=True)
    for name in ("plan", "backtest"):
        p = commands.add_parser(name)
        p.add_argument("--config", required=True)
        p.add_argument("--workbook")
        p.add_argument("--items")
        p.add_argument("--demand")
        p.add_argument("--inbound")
        p.add_argument("--mapping", help="explicit JSON sheet/column mapping")
        p.add_argument("--out", required=True)
        if name == "backtest":
            p.add_argument("--train-days", type=int, default=120)
            p.add_argument("--validation-days", type=int, default=56)
            p.add_argument("--test-days", type=int, default=56)
            p.add_argument("--seeds", default="17,23,41")
            p.add_argument("--initial-stock-days", type=int, default=14)
            p.add_argument("--min-fill", type=float, default=.95)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "doctor":
            import importlib.util
            import importlib.metadata
            print(json.dumps({"engine_version": VERSION, "python": sys.version.split()[0],
                "optional_dependencies": {name: importlib.metadata.version(name)
                    if importlib.util.find_spec(name) else None for name in ("numpy", "scipy", "openpyxl")}}, indent=2))
            return 0
        if Path(args.out).exists():
            raise ContractError("output already exists; choose a new directory")
        if args.command == "optimize":
            from scm.optimization import run
            result = run(args.kind, args.input, args.out, args.seconds, args.seed)
            print(json.dumps({"status": result["status"], "objective": result["objective"], "validation": result["validation"]["passed"], "engine_version": VERSION}))
            return 0
        if args.command == "chain":
            from scm.chain_flow import run
            result = run(args.input,args.out,args.seconds)
            print(json.dumps({"status":result["status"],"scenarios":len(result["scenarios"]),"feasible_scenarios":result["feasible_scenarios"],"deltas":result["deltas"],"engine_version":VERSION},ensure_ascii=False))
            return 0 if result["status"]=="ready_for_review" else 2
        if args.command == "optimization-export":
            from scm.optimization_delivery import export_xlsx
            print(json.dumps(export_xlsx(args.input,args.out),ensure_ascii=False))
            return 0
        if args.command == "review-optimization":
            from scm.optimization_review import review
            result = review(args.input,args.baseline,args.candidate,args.out)
            print(json.dumps(result,ensure_ascii=False))
            return 0 if result["selected"] else 2
        if args.command == "export":
            from scm.workbook import export
            print(json.dumps(export(args.plan, args.out, args.backtest), ensure_ascii=False))
            return 0
        if args.command in ("procure", "source", "sop"):
            from scm import procurement, sourcing, sop
            from scm.contracts import load_json, provenance
            from scm.analysis_report import write_analysis
            functions = {"procure": procurement.analyze, "source": sourcing.compare, "sop": sop.analyze}
            result = functions[args.command](load_json(args.input))
            result["provenance"] = provenance(args.input)
            write_analysis(result, args.out)
            print(json.dumps({"status": "created", "kind": result["kind"], "engine_version": VERSION}))
            return 0
        if args.command == "demo":
            make_demo(args.out, args.seed)
            print(json.dumps({"status": "created", "synthetic": True, "seed": args.seed}))
            return 0
        if args.workbook and any((args.items, args.demand, args.inbound)):
            raise ContractError("choose workbook OR three CSV files")
        c = settings(args.config)
        mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8")) if args.mapping else None
        products, history, receipts, economics, provenance = load_bundle(c, workbook=args.workbook,
            items=args.items, demand=args.demand, inbound=args.inbound, mapping=mapping)
        import hashlib
        provenance["settings_sha256"] = hashlib.sha256(Path(args.config).read_bytes()).hexdigest()
        if args.mapping:
            provenance["mapping_sha256"] = hashlib.sha256(Path(args.mapping).read_bytes()).hexdigest()
        if args.command == "plan":
            result = plan(products, history, receipts, economics, c, provenance)
            trace = None
        else:
            result, trace = backtest(products, history, economics, c, args.train_days,
                                    args.validation_days, args.test_days,
                                    tuple(int(x) for x in args.seeds.split(",")),
                                    args.initial_stock_days, args.min_fill)
            result["provenance"] = provenance
            result["engine_version"] = VERSION
            from scm.io import json_safe
            result["parameters"] = json_safe(c)
        write_outputs(result, args.out, trace)
        print(json.dumps({"status": "created", "engine_version": VERSION,
                          "summary": result.get("summary", result.get("paired_comparison"))}, ensure_ascii=False))
        return 0
    except (ContractError, ValueError, RuntimeError, OSError, KeyError) as error:
        print(f"Input/analysis error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
