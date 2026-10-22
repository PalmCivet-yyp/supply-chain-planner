"""Seeded synthetic case, never customer data or evidence of achieved savings."""
import csv
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path


def make_demo(output, seed=20261021):
    out = Path(output)
    if out.exists():
        raise ValueError("demo output directory already exists")
    out.mkdir(parents=True)
    rng, last = random.Random(seed), date(2026, 10, 20)
    products, demand = [], []
    for i, name in enumerate(("stable", "weekly", "intermittent", "trend", "all_zero", "lumpy"), 1):
        sku, location = f"{i:04d}", "GZ" if i <= 3 else "SH"
        products.append({"sku": sku, "location": location, "on_hand": [12, 35, 5, 110, 0, 16][i - 1],
                         "reserved": 0, "backorders": 0, "lead_time_days": [3, 5, 4, 7, 3, 5][i - 1],
                         "review_period_days": 7, "service_level": .95, "moq": 12,
                         "pack_size": [6, 12, 3, 6, 1, 4][i - 1], "unit_cost": 5 + i,
                         "currency": "CNY", "holding_cost_per_unit_day": .03 + .01 * i,
                         "shortage_cost": 2 + i, "order_fixed_cost": 6})
        for t in range(300):
            if name == "stable":
                value = max(0, round(rng.gauss(8, 2)))
            elif name == "weekly":
                value = max(0, [2, 3, 4, 5, 10, 18, 16][t % 7] + rng.choice([-1, 0, 1]))
            elif name == "intermittent":
                value = rng.choice([3, 5, 8]) if rng.random() < .18 else 0
            elif name == "trend":
                value = max(0, round(2 + .035 * t + rng.gauss(0, 2)))
            elif name == "all_zero":
                value = 0
            else:
                value = rng.choice([2, 4, 20, 45]) if rng.random() < .22 else 0
            demand.append({"sku": sku, "location": location,
                           "date": (last - timedelta(days=299 - t)).isoformat(),
                           "demand_qty": value, "stockout": 0})
    inbound = [{"order_id": "PO-LATE-001", "sku": "0001", "location": "GZ", "qty": 120,
                "eta": (last + timedelta(days=40)).isoformat(), "status": "confirmed"},
               {"order_id": "PO-002", "sku": "0002", "location": "GZ", "qty": 36,
                "eta": (last + timedelta(days=4)).isoformat(), "status": "confirmed"},
               {"order_id": "PO-UNCONF-004", "sku": "0004", "location": "SH", "qty": 30,
                "eta": (last + timedelta(days=8)).isoformat(), "status": "unconfirmed"}]
    for name, rows in (("items", products), ("demand", demand), ("inbound", inbound)):
        with (out / f"{name}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    config = {"as_of": last.isoformat(), "history_days": 180, "demand_kind": "orders",
              "shortage_mode": "lost_sales", "allocation": "economic", "currency": "CNY",
              "budget": 1800, "capacity_units": 220,
              "lead_time_scenarios": [{"delay_days": 0, "probability": .8}, {"delay_days": 3, "probability": .2}]}
    (out / "settings.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    (out / "provenance.json").write_text(json.dumps({"synthetic": True, "seed": seed,
        "item_locations": 6, "days_per_item": 300, "purpose": "reproducible software demonstration"}, indent=2), encoding="utf-8")
    return out
