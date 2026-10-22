"""Business-boundary regressions beyond the fixed development acceptance examples."""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from plan_inventory import ContractError
from scm import procurement, sourcing, sop
from scm.analysis_report import write_analysis
from scm.contracts import load_json
from supply_chain import main

ASSETS = Path(__file__).resolve().parents[1] / "assets/operations"


def sample(name):
    return json.loads((ASSETS / f"{name}.json").read_text())


class OperationalBoundaries(unittest.TestCase):
    def test_alias_chain_is_not_silently_merged(self):
        data = sample("procurement")
        data["supplier_aliases"] = {"A Co.": "A", "A": "B"}
        with self.assertRaises(ContractError): procurement.analyze(data)

    def test_abc_dominant_supplier_stays_in_a(self):
        data = sample("procurement")
        data["spend"][0]["amount"] = 999
        data["spend"][1]["amount"] = 1
        group = next(x for x in procurement.analyze(data)["spend_groups"] if x["currency"] == "CNY")
        self.assertEqual(group["suppliers"][0]["abc"], "A")

    def test_zero_spend_has_no_concentration_percentage(self):
        data = sample("procurement")
        for r in data["spend"]: r["amount"] = 0
        self.assertTrue(all(x["hhi_fraction"] is None and x["top_supplier_share"] is None
                            for x in procurement.analyze(data)["spend_groups"]))

    def test_boolean_is_not_money(self):
        data = sample("procurement"); data["spend"][0]["amount"] = True
        with self.assertRaises(ContractError): procurement.analyze(data)

    def test_exact_decimal_tolerance_not_binary_float_slack(self):
        data = sample("procurement")
        match = data["matches"][0]
        match.update(po_qty=3, received_qty=3, invoice_qty=3, unit_price=.1, invoice_amount=.3, amount_tolerance=0)
        self.assertEqual(procurement.analyze(data)["three_way_matches"][0]["status"], "matched")
        match["invoice_amount"] = .3000000001
        self.assertEqual(procurement.analyze(data)["three_way_matches"][0]["status"], "discrepancy")

    def test_overreceipt_requires_investigation(self):
        data = sample("procurement"); data["matches"][0]["received_qty"] = 101
        self.assertEqual(procurement.analyze(data)["three_way_matches"][0]["action"], "investigate_discrepancy")

    def test_overdue_unreceived_line_remains_in_population(self):
        data = sample("procurement")
        data["deliveries"] = [{"id": "open", "supplier": "A", "due_date": "2026-10-01", "delivered_date": None,
                               "ordered_qty": 20, "delivered_qty": 0}]
        result = procurement.analyze(data)["supplier_otif"][0]
        self.assertEqual((result["due_line_count"], result["line_otif"]), (1, 0))

    def test_no_invented_consolidation_savings(self):
        result = procurement.analyze(sample("procurement"))
        self.assertTrue(all(r["estimated_savings"] is None for r in result["spend_groups"]))

    def test_irrelevant_verified_source_is_not_cost_evidence(self):
        data = sample("sourcing")
        for s in data["sources"]: s["supports"] = ["quality"]
        self.assertEqual(sourcing.compare(data)["ranking"], [])

    def test_refutation_cannot_be_outvoted_by_verified_source(self):
        data = sample("sourcing")
        refuted = {**data["sources"][0], "id": "contradiction", "status": "refuted"}
        data["sources"].append(refuted)
        data["options"][0]["evidence"]["costs"].append("contradiction")
        result = sourcing.compare(data)
        self.assertFalse(result["options"][0]["eligible_for_comparison"])
        self.assertTrue(result["options"][0]["evidence_audit"][0]["conflict_or_refutation"])

    def test_missing_score_stays_incomplete(self):
        data = sample("sourcing"); data["options"][0]["scores"]["quality"] = None
        self.assertIsNone(sourcing.compare(data)["options"][0]["weighted_score"])

    def test_zero_weight_others_sensitivity_stays_finite(self):
        data = sample("sourcing")
        data["criteria"][0]["weight"], data["criteria"][1]["weight"] = 1, 0
        result = sourcing.compare(data)
        self.assertTrue(all(abs(sum(r["weights"].values()) - 1) < 1e-9 for r in result["sensitivity"]))
        self.assertTrue(result["sensitivity"])

    def test_empty_history_is_unavailable_not_perfect_accuracy(self):
        data = sample("sop"); data["history"] = []
        result = sop.analyze(data)["forecast_metrics"]
        self.assertIsNone(result["mae"]); self.assertIsNone(result["wape"])

    def test_opening_date_must_match_plan_start(self):
        data = sample("sop"); data["opening_date"] = "2026-10-20"
        with self.assertRaises(ContractError): sop.analyze(data)

    def test_monthly_mass_balance_for_noninteger_forecasts(self):
        data = sample("sop")
        data["scenarios"] = [{"id": "fractional", "demand_factor": 1.17, "supply_factor": .93}]
        for r in sop.analyze(data)["balance"]:
            self.assertAlmostEqual(r["opening_stock"] - r["opening_backlog"] + r["received"] - r["demand"],
                                   r["ending_stock"] - r["ending_backlog"])

    def test_future_date_is_not_a_source_verification(self):
        data = sample("sourcing"); data["sources"][0]["checked_on"] = "2027-01-01"
        with self.assertRaises(ContractError): sourcing.compare(data)

    def test_duplicate_json_keys_do_not_overwrite_evidence(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "input.json"; p.write_text('{"status":"refuted","status":"verified"}')
            with self.assertRaises(ContractError): load_json(p)

    def test_operational_reports_escape_html_and_csv(self):
        data = sample("procurement"); data["spend"][0]["category"] = '=x<script>alert(1)</script>'
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "out"; write_analysis(procurement.analyze(data), out)
            self.assertNotIn('<script>alert(1)</script>', (out / "report.html").read_text())
            self.assertIn("'=x", (out / "spend_groups.csv").read_text(encoding="utf-8-sig"))

    def test_invalid_cli_leaves_no_output(self):
        with tempfile.TemporaryDirectory() as t:
            p, out = Path(t) / "bad.json", Path(t) / "out"
            data = sample("sourcing"); del data["options"][0]["costs"]["setup"]
            p.write_text(json.dumps(data))
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["source", "--input", str(p), "--out", str(out)]), 2)
            self.assertFalse(out.exists())

    def test_padded_source_identifiers_are_rejected(self):
        data = sample("sourcing"); data["sources"][0]["id"] = " quote_a "
        with self.assertRaises(ContractError): sourcing.compare(data)

    def test_missing_criticality_does_not_mean_noncritical(self):
        data = sample("procurement")
        for r in data["spend"]: r.pop("critical", None)
        self.assertTrue(all(r["critical"] is None for r in procurement.analyze(data)["spend_groups"]))

    def test_mean_and_cumulative_bias_are_distinct(self):
        result = sop.analyze(sample("sop"))["forecast_metrics"]
        self.assertEqual(result["mean_error_units"], -5)
        self.assertEqual(result["cumulative_error_units"], -10)


if __name__ == "__main__":
    unittest.main()
