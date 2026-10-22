"""Behavioral checks for quantities, timing, provenance, and blocked inputs."""
import contextlib
import csv
import io
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from plan_inventory import (Config, ContractError, Item, Receipt, analyze, evaluate,
                            load_inputs, main, predict, round_order, safe_cell)

AS_OF = date(2026, 10, 20)


def item(**changes):
    base = Item("001", "GZ", 20, 0, 0, 7, 7, 0.95, 50, 10, 12.0, "CNY")
    return replace(base, **changes)


def history(value=10, n=56, flag=0):
    return {AS_OF - timedelta(days=n - i - 1): (value, flag) for i in range(n)}


def plan(product=None, rows=None, receipts=None, config=None):
    product = product or item()
    return analyze([product], {product.key: rows if rows is not None else history()},
                   receipts or [], config or Config(AS_OF))["items"][0]


def write_table(path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class PlanningBehavior(unittest.TestCase):
    def test_known_constant_demand_with_moq_pack(self):
        receipt = Receipt("P1", "001", "GZ", 15, AS_OF + timedelta(days=4), "confirmed")
        result = plan(receipts=[receipt])
        self.assertEqual(result["forecast_method"], "mean28")
        self.assertEqual(result["safety_stock"], 0)
        self.assertEqual(result["target_inventory_position"], 140)
        self.assertEqual(result["inventory_position"], 35)
        self.assertEqual(result["raw_inventory_position_gap"], 105)
        self.assertEqual(result["suggested_order_qty"], 110)
        self.assertEqual(result["estimated_order_goods_value"], 1320)
        self.assertEqual(result["first_shortage_date_baseline"], "2026-10-23")
        self.assertEqual(result["peak_net_shortfall_before_normal_arrival"], 25)
        self.assertEqual(result["priority"], "P1")

    def test_no_order_does_not_trigger_moq(self):
        self.assertEqual(round_order(0, 1000, 12), 0)
        self.assertEqual(round_order(1, 10, 6), 12)
        self.assertEqual(round_order(24, 10, 6), 24)

    def test_far_future_supply_is_not_purchased_twice(self):
        receipt = Receipt("P1", "001", "GZ", 500, AS_OF + timedelta(days=40), "confirmed")
        result = plan(receipts=[receipt])
        self.assertEqual(result["suggested_order_qty"], 0)
        self.assertEqual(result["confirmed_after_horizon_qty"], 500)
        self.assertGreater(result["peak_net_shortfall_with_regular_order"], 0)
        self.assertTrue(any("催交" in a for a in result["actions"]))

    def test_receipts_arrive_before_that_days_demand(self):
        product = item(on_hand=10)
        receipt = Receipt("P1", "001", "GZ", 1000, AS_OF + timedelta(days=2), "confirmed")
        result = plan(product, receipts=[receipt])
        self.assertIsNone(result["first_shortage_date_baseline"])
        self.assertEqual(result["daily_projection"][1]["projected_net_baseline"], 990)

    def test_new_order_not_credited_before_lead_time(self):
        result = plan()
        self.assertEqual(result["daily_projection"][5]["proposed_regular_receipt_qty"], 0)
        self.assertEqual(result["daily_projection"][6]["proposed_regular_receipt_qty"], 120)

    def test_backorders_carry_until_fulfilled(self):
        result = plan(item(on_hand=20, reserved=5, backorders=30))
        self.assertEqual(result["available_net_at_snapshot"], -15)
        self.assertEqual(result["first_shortage_date_baseline"], AS_OF.isoformat())
        self.assertEqual(result["daily_projection"][0]["projected_net_baseline"], -25)

    def test_overdue_supply_blocks_quantity(self):
        receipt = Receipt("P1", "001", "GZ", 1000, AS_OF, "confirmed")
        result = plan(receipts=[receipt])
        self.assertEqual(result["recommendation_state"], "blocked")
        self.assertIsNone(result["suggested_order_qty"])
        self.assertEqual(result["confirmed_future_qty"], 0)
        self.assertIsNone(result["daily_projection"][0]["projected_net_with_regular_order"])

    def test_cancelled_and_unconfirmed_supply_not_credited(self):
        receipts = [Receipt("P1", "001", "GZ", 1000, AS_OF + timedelta(days=1), "cancelled"),
                    Receipt("P2", "001", "GZ", 1000, AS_OF + timedelta(days=1), "unconfirmed")]
        result = plan(receipts=receipts)
        self.assertEqual(result["inventory_position"], 20)
        self.assertEqual(result["recommendation_state"], "scenario_only")

    def test_missing_day_is_not_silently_zero(self):
        rows = history()
        rows.pop(AS_OF - timedelta(days=6))
        result = plan(rows=rows)
        self.assertIsNone(result["suggested_order_qty"])
        self.assertEqual(result["history_missing_dates"], ["2026-10-14"])
        filled = plan(rows=rows, config=replace(Config(AS_OF), missing_days="zero"))
        self.assertEqual(filled["recommendation_state"], "scenario_only")
        self.assertIsNotNone(filled["suggested_order_qty"])

    def test_new_item_history_not_invented(self):
        result = plan(rows=history(n=12))
        self.assertEqual(result["history_observed_days"], 12)
        self.assertIsNone(result["suggested_order_qty"])

    def test_sales_with_stockout_or_unknown_are_blocked(self):
        for flag in (1, None):
            with self.subTest(flag=flag):
                result = plan(rows=history(flag=flag), config=replace(Config(AS_OF), demand_kind="sales"))
                self.assertEqual(result["recommendation_state"], "blocked")
                self.assertIsNone(result["suggested_order_qty"])

    def test_uncensored_sales_remain_a_proxy(self):
        result = plan(config=replace(Config(AS_OF), demand_kind="sales"))
        self.assertEqual(result["recommendation_state"], "scenario_only")

    def test_zero_demand_does_not_create_infinite_cover(self):
        result = plan(rows=history(value=0))
        self.assertEqual(result["recommendation_state"], "blocked")
        self.assertIsNone(result["static_cover_days"])
        self.assertIsNone(result["suggested_order_qty"])
        self.assertIsNone(result["forecast_evaluation"]["mean28"]["wape"])
        json.dumps(result, allow_nan=False)

    def test_intermittent_demand_requires_another_method(self):
        rows = history()
        for i, day in enumerate(sorted(rows)):
            rows[day] = (10 if i % 7 == 0 else 0, 0)
        self.assertIsNone(plan(rows=rows)["suggested_order_qty"])

    def test_limited_cv_marks_fallback_scenario(self):
        result = plan(rows=history(n=28), config=replace(Config(AS_OF), history_days=28))
        self.assertEqual(result["safety_method"], "iid_daily_demand_approximation")
        self.assertEqual(result["recommendation_state"], "scenario_only")

    def test_independent_warehouse_keys(self):
        one, two = item(), item(location="SZ", on_hand=200)
        report = analyze([one, two], {one.key: history(), two.key: history(1)}, [], Config(AS_OF))
        values = {r["location"]: r for r in report["items"]}
        self.assertEqual(values["GZ"]["suggested_order_qty"], 120)
        self.assertEqual(values["SZ"]["suggested_order_qty"], 0)

    def test_held_out_spike_cannot_leak_into_training(self):
        chosen, metrics, errors = evaluate([10] * 55 + [1000], 14)
        self.assertEqual(chosen, "mean28")
        self.assertEqual(len(errors), 14)
        self.assertEqual(errors[-1], 990)
        self.assertGreater(metrics["mean28"]["mae_daily"], 0)
        self.assertEqual(predict([1, 2, 3, 4, 5, 6, 7], 9, "seasonal7"), [1, 2, 3, 4, 5, 6, 7, 1, 2])

    def test_weekly_pattern_selects_seasonal_baseline(self):
        chosen, metrics, errors = evaluate([4, 6, 8, 10, 12, 14, 16] * 8, 14)
        self.assertEqual(chosen, "seasonal7")
        self.assertEqual(metrics[chosen]["mae_daily"], 0)
        self.assertEqual(sum(map(abs, errors)), 0)

    def test_scenario_changes_demand_and_proposed_lead_only(self):
        receipt = Receipt("P1", "001", "GZ", 15, AS_OF + timedelta(days=4), "confirmed")
        result = plan(receipts=[receipt], config=replace(Config(AS_OF), demand_factor=1.2, lead_delay_days=3))
        self.assertEqual(result["normal_arrival_date"], "2026-10-30")
        self.assertEqual(result["forecast_mean_daily"], 12)
        self.assertEqual(result["daily_projection"][3]["confirmed_receipt_qty"], 15)
        self.assertEqual(result["recommendation_state"], "scenario_only")

    def test_formula_text_escaped_but_numeric_negatives_preserved(self):
        self.assertEqual(safe_cell("=HYPERLINK(x)"), "'=HYPERLINK(x)")
        self.assertEqual(safe_cell(" @SUM(1)"), "' @SUM(1)")
        self.assertEqual(safe_cell(-10), -10)


class InputAndCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.paths = [self.root / f"{name}.csv" for name in ("items", "demand", "inbound")]
        self.item_rows = [{"sku": "001", "location": "GZ", "on_hand": 20, "reserved": 0,
                           "backorders": 0, "lead_time_days": 7, "review_period_days": 7,
                           "service_level": .95, "moq": 50, "pack_size": 10,
                           "unit_cost": 12, "currency": "CNY"}]
        self.demand_rows = [{"sku": "001", "location": "GZ", "date": d.isoformat(),
                             "demand_qty": q, "stockout": f} for d, (q, f) in history().items()]
        self.inbound_rows = []
        self.save()

    def save(self):
        write_table(self.paths[0], list(self.item_rows[0]), self.item_rows)
        write_table(self.paths[1], ["sku", "location", "date", "demand_qty", "stockout"], self.demand_rows)
        write_table(self.paths[2], ["order_id", "sku", "location", "qty", "eta", "status"], self.inbound_rows)

    def load(self):
        return load_inputs(*self.paths, Config(AS_OF))

    def test_rejects_nan_negative_and_fractional_units(self):
        for value in ("NaN", "inf", "-1", "1.2"):
            with self.subTest(value=value):
                self.item_rows[0]["on_hand"] = value
                self.save()
                with self.assertRaises(ContractError):
                    self.load()

    def test_rejects_invalid_service_and_unpaired_currency(self):
        for value in (0.5, 1, 1.1):
            self.item_rows[0]["service_level"] = value
            self.save()
            with self.assertRaises(ContractError):
                self.load()
        self.item_rows[0]["service_level"] = .95
        self.item_rows[0]["currency"] = ""
        self.save()
        with self.assertRaises(ContractError):
            self.load()

    def test_rejects_duplicate_demand_and_unknown_keys(self):
        self.demand_rows.append(self.demand_rows[-1].copy())
        self.save()
        with self.assertRaises(ContractError):
            self.load()
        self.demand_rows.pop()
        self.demand_rows[0]["location"] = "unknown"
        self.save()
        with self.assertRaises(ContractError):
            self.load()

    def test_rejects_future_history_and_duplicate_inbound_ids(self):
        self.demand_rows[0]["date"] = "2026-10-21"
        self.save()
        with self.assertRaises(ContractError):
            self.load()
        self.demand_rows[0]["date"] = "2026-08-26"
        r = {"order_id": "P1", "sku": "001", "location": "GZ", "qty": 20,
             "eta": "2026-10-23", "status": "confirmed"}
        self.inbound_rows = [r, r.copy()]
        self.save()
        with self.assertRaises(ContractError):
            self.load()

    def test_cli_outputs_reproducible_report_and_refuses_overwrite(self):
        destination = self.root / "result"
        args = ["--items", str(self.paths[0]), "--demand", str(self.paths[1]),
                "--inbound", str(self.paths[2]), "--as-of", AS_OF.isoformat(),
                "--demand-kind", "orders", "--out", str(destination)]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(args), 0)
            self.assertEqual(main(args), 2)
        report = json.loads((destination / "report.json").read_text())
        self.assertEqual(len(report["input_sha256"]["demand"]), 64)
        self.assertEqual(report["items"][0]["sku"], "001")
        self.assertTrue((destination / "planning.csv").exists())
        self.assertTrue((destination / "projection.csv").exists())

    def test_invalid_input_creates_no_output(self):
        self.item_rows[0]["on_hand"] = "NaN"
        self.save()
        destination = self.root / "invalid"
        args = ["--items", str(self.paths[0]), "--demand", str(self.paths[1]),
                "--inbound", str(self.paths[2]), "--as-of", AS_OF.isoformat(),
                "--demand-kind", "orders", "--out", str(destination)]
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(args), 2)
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
