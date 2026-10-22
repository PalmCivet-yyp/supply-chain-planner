# Supply Chain Planner

[简体中文](README.md) · **English** · [Bilingual usage and regional notes](references/international-usage.md)

**Auditable supply-chain planning, constrained optimization and paired evaluation.**

`v3.1.0` · `Python 3.10+` · `MIT` · `Agent Skill + Python CLI`

Turn inventory, procurement and planning inputs into executable decisions, then check quantities, dates, feasibility and evidence. Use the repository as an Agent Skill or run its Python commands directly. It includes working models, synthetic examples, software checks and recorded public benchmark decisions.

This English entry and the bilingual notes supplement the existing Chinese documentation. Some report labels and UI metadata remain in Chinese; there is no runtime language selector. An assistant can explain results in English while preserving the original machine-readable keys and status values.

## Capabilities

| Area | Supported scope | Entry |
| --- | --- | --- |
| Inventory | Forecast comparison, dated inbound supply, replenishment, MOQ and order multiples | `plan` |
| Allocation and backtesting | Budget/quantity constraints over finite order candidates; chronological policy evaluation | `plan`, `backtest` |
| Procurement | Spend, completed process stages, order-line OTIF and three-way matching | `procure` |
| Sourcing | Hard requirements, caller-verified evidence, comparable TCO and weight sensitivity | `source` |
| S&OP | Monthly supply/demand scenarios, separate item/location capacity, backlog and review actions | `sop` |
| Optimization | Capacitated facility location, VRPTW, blending, machine maintenance and serial Normal-demand inventory | `optimize` |
| Dated material flow | Procurement, recipes, stock, shared hours, warehouse transfers and delay scenarios | `chain` |
| Delivery and review | JSON, CSV, standalone HTML, Excel and independently checked selection between existing plans | `export`, `optimization-export`, `review-optimization` |

The regional notes explain important modeling differences, including calendar days, currencies, unit conversions and delivery-metric definitions. Do not assume that the China-oriented demo labels impose the only supported geography or that changing a currency label converts monetary amounts.

## Quick start

Run commands from the repository root. Create a virtual environment, activate it, then install the dependencies:

```bash
python -m venv .venv
python -m pip install -r scripts/requirements.txt
python scripts/supply_chain.py doctor
```

Activate with `source .venv/bin/activate` on Linux/macOS, or `.venv\Scripts\Activate.ps1` in Windows PowerShell. For Windows text handling, set `$env:PYTHONUTF8 = "1"` before running the commands. Use UTF-8 or UTF-8 BOM for CSV input, plain numeric cells and unambiguous `YYYY-MM-DD` dates.

Generate a synthetic inventory example and export a plan:

```bash
python scripts/supply_chain.py demo --out outputs/demo-input
python scripts/supply_chain.py plan --config outputs/demo-input/settings.json --items outputs/demo-input/items.csv --demand outputs/demo-input/demand.csv --inbound outputs/demo-input/inbound.csv --out outputs/demo-plan
python scripts/supply_chain.py export --plan outputs/demo-plan/report.json --out outputs/demo-plan.xlsx
```

Open `outputs/demo-plan/report.html`. The inputs are synthetic. Choose new output paths on subsequent runs; existing output destinations are protected against overwrite.

Run the dated material-flow example and export all calculated values:

```bash
python scripts/supply_chain.py chain --input assets/operations/chain.json --seconds 10 --out outputs/chain-demo
python scripts/supply_chain.py optimization-export --input outputs/chain-demo/report.json --out outputs/chain-demo.xlsx
```

Run facility location:

```bash
python scripts/supply_chain.py optimize --kind facility --input assets/optimization/facility.json --seconds 10 --seed 17 --out outputs/location-demo
```

Other optimization kinds are `routing`, `blending`, `production` and `serial`. Reuse the matching example in `assets/optimization/`; the blending example is named `blending.json`. Procurement, sourcing and S&OP examples are in `assets/operations/`:

```bash
python scripts/supply_chain.py procure --input assets/operations/procurement.json --out outputs/procurement-demo
python scripts/supply_chain.py source --input assets/operations/sourcing.json --out outputs/sourcing-demo
python scripts/supply_chain.py sop --input assets/operations/sop.json --out outputs/sop-demo
```

Basic CSV/service inventory planning, procurement, sourcing and S&OP can run using the Python standard library. Economic allocation and advanced optimization need NumPy/SciPy; Excel import and public export need openpyxl. The optional legacy JavaScript exporter is not required for these commands.

## Agent Skill use

The repository root contains the complete Skill. Place it in the Skills location supported by your client under the name `supply-chain-planner`. [SKILL.md](SKILL.md) contains the workflow; its existing detailed body is primarily Chinese. [Bilingual notes](references/international-usage.md) provide English field meanings, status explanations and modeling precautions. Client installation and tool permissions remain client-specific.

Example requests:

> Check these SKU/location inventory and dated inbound files. Produce a replenishment plan under the stated MOQ, pack-size and budget constraints, with complete quantities, validation and an HTML report. Explain the result in English and preserve all original field names and status values.

> Compare on-time raw-material arrivals with a two-day delay. Keep shared capacity, warehouse identities and transfer lead times consistent. Explain modeled costs, backlog unit-days and ending backlog separately.

Use `review-optimization` when both an existing and a candidate facility/routing result are available for the same input. It checks input identity, feasibility and objectives before selecting a plan. It performs no additional search.

## Recorded evaluation

On 2026-10-22, the two native engine releases were compared using the same inputs and scoring rules. The primary experiment used 10 seconds per instance per version, seed 17 and sequential single-threaded workers. The 88 holdout instances were evaluated after the candidate optimizer was fixed.

| Evaluation scope | Version 3.0 meets target | Version 3.1 meets target | Change |
| --- | ---: | ---: | --- |
| 100 public instances | 55/100 | 59/100 | +4.00 percentage points |
| Included 88 holdout instances | 46/88 | 51/88 | +5.68 percentage points |
| Included 12 development instances | 9/12 | 8/12 | -8.33 percentage points |
| Six routing instances, three seeds | 12/18 | 11/18 | Lower target count |
| Original seven cases, separately at 60 seconds each | 7/7 | 7/7 | Unchanged |

Both versions returned feasible decisions on all 100 primary instances. Objectives improved on 30, tied on 56 and worsened on 14. R101 increased from 19 to 20 vehicles and lost target status. Version 3.1 is therefore not consistently better across every instance or seed.

All 44 facility costs tied. Valid lower bounds improved on 34 instances and weakened on none; the median valid optimality gap fell from 18.3596% to 0.0916%. This indicates tighter evidence, not cost savings. The original large H1/L1 cases still have valid-bound gaps of 36.91%/39.65%.

The dataset contains 44 facility and 56 routing instances, including explicitly identified capacity variants. These are related public benchmark instances, not 100 distinct business processes or independent statistical samples. Seed repeats do not add unique instances. This evaluates native programs, not the causal benefit of adding a Skill to an LLM.

Download the pinned public inputs and regrade the 224 recorded decisions without invoking optimization:

```bash
python scripts/benchmark_supply_chain.py fetch --out public-data
python scripts/regrade_benchmark.py --data public-data
```

The 224 decisions comprise 200 primary decisions and 24 extra-seed decisions. Public source changes cause hash checks to stop. External raw datasets are not redistributed here. The regrade command does not reproduce the separate original-seven-case grading workflow or rerun the historical 3.0 optimizer; that source snapshot is not bundled.

See [numeric results](assets/evaluation/optimization-31-summary.json), [all primary comparisons](assets/evaluation/benchmark-31/comparison.csv), [pinned sources](assets/evaluation/public-optimization.json) and [detailed validation notes, Chinese](docs/VALIDATION.md).

## Software checks and interpretation

```bash
python -m unittest discover -s scripts -p 'test_*.py' -v
python scripts/evaluate_skill.py --skill-dir . --out outputs/acceptance.json
```

The preceding repository release passed 100 software checks and 60 fixed synthetic acceptance cases from its exported directory. This revision only adds documentation; executable files, fixtures and recorded results are unchanged. Software checks, synthetic acceptance and public benchmark instances are separate evidence categories.

The GitHub Actions configuration defines Python 3.10/3.12 jobs. Local release validation used Python 3.12.14, NumPy 2.3.5, SciPy 1.17.0 and openpyxl 3.1.5; the presence of a workflow does not mean hosted CI has run. See the [release check record](assets/evaluation/github-release-checks.json).

## Scope and license

Outputs support human review; the tools do not place orders, award contracts, pay invoices, buy machinery or dispatch vehicles. Dated material flow is a finite-horizon model, not production MRP. Shelf life, stochastic traffic, arbitrary-network stochastic inventory and ERP execution are outside the current scope. Serial inventory results are numerical convergence results; optimality over a restricted candidate set is not global optimality for the full problem.

Sourcing evidence is supplied and verified by the caller; recording a URL does not verify its contents. TCO uses a common quantity, currency and horizon without discounting or automatic local tax treatment. Synthetic or benchmark results do not establish enterprise savings.

Project code is under the [MIT License](LICENSE). Third-party datasets retain their source conditions. The [source register, Chinese](references/sources.md) and [method contracts, Chinese](references/advanced-optimization.md) retain the detailed provenance and computational definitions.
