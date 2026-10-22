"""Independent numerical oracles, conservation checks, and end-to-end CLI regressions."""
import contextlib
import csv
import io
import itertools
import json
import random
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from plan_inventory import Item, Receipt, ContractError
from scm.allocation import options, solve
from scm.backtest import backtest, lead_delay, metrics
from scm.demo import make_demo
from scm.engine import plan
from scm.forecast import compare, predict, protection, segment
from scm.io import canonical_headers, excel_to_csv, load_bundle, settings
from scm.simulation import State, opening, operating_cost, simulate, step
from supply_chain import main

DAY = date(2026, 10, 20)
ECON = {"holding_cost_per_unit_day": 1., "shortage_cost": 10., "order_fixed_cost": 3.}


def item(sku="001", **changes):
    return replace(Item(sku, "GZ", 10, 0, 0, 2, 3, .95, 6, 3, 2., "CNY"), **changes)


def config(**changes):
    return {"as_of": DAY, "history_days": 180, "missing_days": "error", "demand_kind": "orders",
            "shortage_mode": "backorder", "lead_scenarios": [(0, 1.)], "demand_factor": 1.,
            "allocation": "service", "forecast_method": None, "budget": None,
            "capacity_units": None, "currency": "CNY", "safety_scale": 1., **changes}


def history(y):
    return {DAY - timedelta(days=len(y) - i - 1): (v, 0) for i, v in enumerate(y)}


class SimulationChecks(unittest.TestCase):
    def test_lost_sales_do_not_reappear(self):
        state = State(2)
        a = step(state, 5, 0, "lost_sales")
        b = step(state, 1, 4, "lost_sales")
        self.assertEqual((a["lost_units"], b["ending_stock"], b["ending_backlog"]), (3, 3, 0))

    def test_backlog_receipts_first_and_no_double_fill(self):
        state = State(2)
        a = step(state, 5, 0, "backorder")
        b = step(state, 2, 4, "backorder")
        self.assertEqual(a["ending_backlog"], 3)
        self.assertEqual((b["backlog_fulfilled"], b["immediately_fulfilled"], b["new_shortage"]), (3, 1, 1))

    def test_initial_reserved_and_backorders_settle_once(self):
        state = opening(item(on_hand=10, reserved=3, backorders=9), "backorder")
        self.assertEqual((state.stock, state.backlog), (0, 2))
        with self.assertRaises(ValueError):
            opening(item(backorders=1), "lost_sales")

    def test_order_arrival_boundary(self):
        rows = simulate(item(on_hand=0), [2, 2, 2], {}, "lost_sales", 6)
        self.assertEqual([r["lost_units"] for r in rows], [2, 0, 0])
        self.assertEqual(rows[-1]["ending_stock"], 2)

    def test_cost_definitions(self):
        rows = simulate(item(on_hand=0), [2, 1], {}, "backorder")
        self.assertEqual(operating_cost(rows, ECON, "backorder")["modeled_operating_cost"], 50)
        rows = simulate(item(on_hand=0), [2, 1], {}, "lost_sales")
        self.assertEqual(operating_cost(rows, ECON, "lost_sales")["modeled_operating_cost"], 30)

    def test_random_mass_conservation_100_paths_both_modes(self):
        rng = random.Random(442)
        for mode in ("lost_sales", "backorder"):
            for _ in range(100):
                state = State(rng.randrange(20))
                for _ in range(30):
                    old_stock, old_backlog = state.stock, state.backlog
                    demand, receipts = rng.randrange(16), rng.randrange(20)
                    row = step(state, demand, receipts, mode)
                    self.assertEqual(old_stock + receipts,
                                     state.stock + row["backlog_fulfilled"] + row["immediately_fulfilled"])
                    self.assertEqual(demand, row["immediately_fulfilled"] + row["new_shortage"])
                    if mode == "backorder":
                        self.assertEqual(old_stock - old_backlog + receipts - demand, state.stock - state.backlog)
                    else:
                        self.assertEqual(state.backlog, 0)

    def test_bad_simulator_inputs(self):
        for value in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                step(State(0), value, 0, "lost_sales")


class ForecastChecks(unittest.TestCase):
    def test_sparse_and_zero_forecasts_finite(self):
        y = [0] * 180
        for method in ("mean28", "mean7", "seasonal7", "sba", "tsb"):
            self.assertEqual(predict(y, 14, method), [0] * 14)
        y[0], y[70] = 8, 5
        self.assertGreater(predict(y, 1, "sba")[0], predict(y, 1, "tsb")[0])

    def test_segmentation(self):
        self.assertEqual(segment([3] * 100)["label"], "smooth")
        self.assertEqual(segment([0] * 100)["label"], "all_zero")
        self.assertEqual(segment([5, 0, 0, 0] * 25)["label"], "intermittent")

    def test_weekly_forecast_phase(self):
        y = [1, 2, 3, 4, 5, 6, 7] * 30
        method, _ = compare(y, 8)
        self.assertEqual(method, "seasonal7")
        self.assertEqual(predict(y, 8, method), [1, 2, 3, 4, 5, 6, 7, 1])

    def test_constant_analytic_target_and_delay(self):
        risk = protection([10] * 180, 2, 3, .95, "mean28", [(0, .8), (3, .2)])
        self.assertEqual(risk["safety_stock"], 30)
        self.assertEqual(risk["target"], 80)

    def test_short_history_is_labeled(self):
        p = item()
        r = plan([p], {p.key: history([4] * 10)}, [], {}, config())["items"][0]
        self.assertEqual(r["history_observed_days"], 10)
        self.assertEqual(r["recommendation_state"], "scenario_only")
        self.assertEqual(r["forecast_method"], "mean7")

    def test_future_values_cannot_affect_snapshot(self):
        p = item()
        source = history([4] * 180)
        a = plan([p], {p.key: source}, [], {}, config())
        source[DAY + timedelta(days=1)] = (999999, 0)
        b = plan([p], {p.key: source}, [], {}, config())
        self.assertEqual(a, b)


class AllocationChecks(unittest.TestCase):
    def test_pack_moq_and_zero_options(self):
        self.assertEqual(options(0, 100, 6), [0])
        self.assertEqual(options(24, 10, 6), [0, 12, 18, 24])
        with self.assertRaises(ValueError):
            options(10**12, 0, 1)

    def test_budget_and_capacity_binding(self):
        groups = [[{"qty": 0, "spend": 0, "cost": 30}, {"qty": 6, "spend": 12, "cost": 0}],
                  [{"qty": 0, "spend": 0, "cost": 40}, {"qty": 9, "spend": 9, "cost": 0}]]
        self.assertEqual(solve(groups, budget=12)["quantities"], [0, 9])
        self.assertEqual(solve(groups, capacity=6)["quantities"], [6, 0])
        self.assertEqual(solve(groups, budget=0)["quantities"], [0, 0])

    def test_100_independent_exhaustive_integer_oracles(self):
        rng = random.Random(20261021)
        for case in range(100):
            groups = []
            for _ in range(rng.randint(2, 5)):
                pack = rng.randint(1, 5)
                unit_cost = rng.randint(1, 9)
                groups.append([{"qty": k * pack, "spend": k * pack * unit_cost,
                                "cost": rng.randint(0, 200)} for k in range(rng.randint(2, 5))])
            budget, capacity = rng.randint(0, 120), rng.randint(0, 35)
            oracle = min(sum(x["cost"] for x in combination) for combination in itertools.product(*groups)
                         if sum(x["spend"] for x in combination) <= budget and sum(x["qty"] for x in combination) <= capacity)
            result = solve(groups, budget, capacity)
            self.assertTrue(result["optimal"], case)
            self.assertAlmostEqual(result["objective"], oracle, msg=f"case {case}")
            self.assertLessEqual(result["spend"], budget)
            self.assertLessEqual(result["capacity_used"], capacity)

    def test_no_false_optimal_for_invalid_input(self):
        with self.assertRaises(ValueError):
            solve([[{"qty": 1, "spend": 1, "cost": 1}]], 3)
        with self.assertRaises(ValueError):
            solve([[{"qty": 0, "spend": 0, "cost": -1}]], 3)


class EngineChecks(unittest.TestCase):
    def test_hand_calculated_constant_plan(self):
        p = item()
        r = plan([p], {p.key: history([10] * 180)}, [], {}, config())["items"][0]
        self.assertEqual((r["target_inventory_position"], r["raw_gap"], r["suggested_order_qty"]), (50, 40, 42))
        self.assertEqual(r["new_unfilled_units_before_base_arrival"], 0)
        self.assertEqual(r["daily_projection"][1]["with_order"]["received"], 42)

    def test_lost_sales_plan_differs_from_backorder(self):
        p = item(on_hand=0, lead_time_days=3)
        a = plan([p], {p.key: history([10] * 180)}, [], {}, config())["items"][0]
        b = plan([p], {p.key: history([10] * 180)}, [], {}, config(shortage_mode="lost_sales"))["items"][0]
        self.assertEqual(a["daily_projection"][2]["with_order"]["ending_stock"], 30)
        self.assertEqual(b["daily_projection"][2]["with_order"]["ending_stock"], 50)

    def test_late_po_is_not_double_purchased(self):
        p = item()
        receipt = Receipt("p", *p.key, 500, DAY + timedelta(days=40), "confirmed")
        r = plan([p], {p.key: history([10] * 180)}, [receipt], {}, config())["items"][0]
        self.assertEqual(r["suggested_order_qty"], 0)
        self.assertEqual(r["confirmed_after_horizon_qty"], 500)
        self.assertTrue(any("远期" in x for x in r["actions"]))

    def test_missing_internal_day_blocks_but_launch_does_not_fill(self):
        p = item()
        h = history([4] * 180)
        del h[DAY - timedelta(days=10)]
        r = plan([p], {p.key: h}, [], {}, config())["items"][0]
        self.assertIsNone(r["suggested_order_qty"])

    def test_censored_sales_block(self):
        p = item()
        h = history([4] * 180)
        h[DAY] = (1, 1)
        r = plan([p], {p.key: h}, [], {}, config(demand_kind="sales"))["items"][0]
        self.assertIsNone(r["suggested_order_qty"])

    def test_zero_demand_stays_zero_without_obligations(self):
        p = item(on_hand=0)
        r = plan([p], {p.key: history([0] * 180)}, [], {}, config())["items"][0]
        self.assertEqual(r["suggested_order_qty"], 0)
        self.assertIsNone(r["static_cover_days"])


class IOAndReplayChecks(unittest.TestCase):
    def test_mapping_collision_blocked(self):
        self.assertEqual(canonical_headers(["货号", "仓库"], "items"), ["sku", "location"])
        with self.assertRaises(ContractError):
            canonical_headers(["sku", "货号"], "items")

    def test_excel_optional_empty_tail_is_a_valid_blank_cell(self):
        def cells(values):
            return [SimpleNamespace(value=v, data_type="s", coordinate=f"C{i}") for i, v in enumerate(values)]
        class Book:
            sheetnames = ["items", "demand", "inbound"]
            def __getitem__(self, name):
                return SimpleNamespace(iter_rows=lambda: iter([
                    cells(["sku", "location", "optional"]), cells(["001", "W"])]))
            def close(self):
                pass
        with tempfile.TemporaryDirectory() as t, patch("openpyxl.load_workbook", return_value=Book()):
            paths, _ = excel_to_csv("input.xlsx", Path(t))
            with paths["items"].open() as stream:
                self.assertEqual(list(csv.DictReader(stream)), [{"sku": "001", "location": "W", "optional": ""}])

    def test_invalid_excel_returns_cli_error_without_output(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            bad = root / "bad.xlsx"
            bad.write_bytes(b"this is not an Excel file")
            c = root / "settings.json"
            c.write_text(json.dumps({"as_of": DAY.isoformat()}))
            out = root / "out"
            with contextlib.redirect_stderr(io.StringIO()):
                result = main(["plan", "--config", str(c), "--workbook", str(bad), "--out", str(out)])
            self.assertEqual(result, 2)
            self.assertFalse(out.exists())

    def test_bad_scenario_probabilities_and_unsupported_budget(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "settings.json"
            for extra in ({"lead_time_scenarios": [{"delay_days": 2, "probability": .2}]},
                          {"budget": 100}, {"demand_kind": "mystery"}, {"unknown": 1}):
                p.write_text(json.dumps({"as_of": DAY.isoformat(), **extra}))
                with self.assertRaises(ContractError):
                    settings(p)

    def test_demo_cli_end_to_end_and_provenance(self):
        with tempfile.TemporaryDirectory() as t:
            root = make_demo(Path(t) / "demo")
            out = Path(t) / "plan"
            args = ["plan", "--config", str(root / "settings.json"), "--items", str(root / "items.csv"),
                    "--demand", str(root / "demand.csv"), "--inbound", str(root / "inbound.csv"), "--out", str(out)]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 0)
                self.assertEqual(main(args), 2)
            report = json.loads((out / "report.json").read_text())
            self.assertEqual(len(report["items"]), 6)
            self.assertEqual(len(report["provenance"]["settings_sha256"]), 64)
            self.assertLessEqual(report["allocation"]["spend"], 1800)
            self.assertLessEqual(report["allocation"]["capacity_used"], 220)
            keyed = {(r["sku"], r["location"]): r["qty"] for r in report["allocation"]["orders"]}
            self.assertEqual(keyed, {(r["sku"], r["location"]): r["suggested_order_qty"] for r in report["items"]})
            self.assertNotIn("quantities", report["allocation"])
            self.assertTrue((out / "report.html").exists())

    def test_crn_uses_date_not_order_sequence(self):
        a = lead_delay(17, ("x", "w"), DAY, [(0, .5), (3, .5)])
        self.assertEqual(a, lead_delay(17, ("x", "w"), DAY, [(0, .5), (3, .5)]))

    def test_test_spike_cannot_change_selected_policy(self):
        p = item(review_period_days=7)
        h = history([3] * 112)
        c = config(allocation="service", history_days=56)
        a, _ = backtest([p], {p.key: h}, {p.key: ECON}, c, 56, 28, 28, (17,))
        h[DAY] = (3000, 0)
        b, _ = backtest([p], {p.key: h}, {p.key: ECON}, c, 56, 28, 28, (17,))
        self.assertEqual(a["validation"], b["validation"])
        self.assertEqual(a["selected_adaptive"], b["selected_adaptive"])
        self.assertNotEqual(a["test_runs"], b["test_runs"])

    def test_malformed_mapping_fails_as_contract_error(self):
        for mapping in ([], {"other": {}}, {"columns": []}, {"columns": {"items": []}}):
            with self.assertRaises(ContractError):
                load_bundle(config(), workbook="unused.xlsx", mapping=mapping)

    def test_replay_rejects_sales_and_incomplete_history(self):
        p = item()
        with self.assertRaises(ContractError):
            backtest([p], {}, {p.key: ECON}, config(demand_kind="sales"))
        with self.assertRaises(ContractError):
            backtest([p], {}, {p.key: ECON}, config())

    def test_relative_improvement_cannot_bypass_absolute_service_gate(self):
        p = item()
        def measured(*args):
            policy = args[7]
            adaptive = policy["name"].startswith("adaptive")
            m = {"immediate_fill_rate": .6 if adaptive else .5,
                 "modeled_operating_cost": 90 if adaptive else 100}
            return {"validation": m, "test": m}, [], []
        with patch("scm.backtest.replay", side_effect=measured):
            report, _ = backtest([p], {p.key: history([3] * 112)}, {p.key: ECON}, config(),
                                 56, 28, 28, (17,), min_fill=.95)
        self.assertEqual(report["paired_comparison"]["verdict"], "cost_and_service_improved_in_replay")
        self.assertEqual(report["adoption_gate"]["recommendation"], "retain_baseline")


if __name__ == "__main__":
    unittest.main(verbosity=2)
