# 中英使用与地区口径备注 / Bilingual usage and regional notes

[中文首页](../README.md) · [English overview](../README.en.md) · [Skill工作流](../SKILL.md)

## 目录 / Contents

1. 语言与字段 / Language and schema
2. 地区口径 / Regional assumptions
3. 库存字段 / Inventory fields
4. 状态与术语 / Status values and terminology
5. 交付前确认 / Before delivery

## 1. 语言与字段 / Language and schema

中文或英文解释均可；命令、JSON键、枚举值、SKU/仓库及订单行标识保持原样。Excel库存导入支持已有中英文别名与显式映射；其他入口按自己的契约校验，不自动识别任意翻译字段。不要向严格JSON输入增加`locale`或`timezone`等未实现的参数。

Use the requested language for explanations, while keeping commands, JSON keys, enums and identifiers unchanged. Inventory Excel imports support the existing aliases and explicit mapping; do not assume arbitrary translated headers work in every CSV or JSON entry. Most detailed references and some generated report labels remain Chinese. These notes add documentation, not a runtime localization feature.

## 2. 地区口径 / Regional assumptions

| 口径 / Topic | 中文备注 | English note |
| --- | --- | --- |
| 日期 / Dates | 使用`YYYY-MM-DD`；先把当地时间归入同一业务日期。模型不转换时区。 | Use unambiguous dates. Normalize timestamps into a declared business date before input; the models do not convert time zones. |
| 日历 / Calendars | 按自然日和已给日期建模，不内置中国调休或其他地区节假日。工作日交期应先转换，或使用支持入口的显式到货日；记录转换依据。 | Calendar days and supplied dates are used. Convert business-day lead times externally or supply supported explicit arrival dates; document the calendar used. |
| 月度 / Monthly periods | 月度S&OP不能说明月内缺货；月度产能与日历联动共享工时属于不同模型。 | Monthly S&OP cannot establish within-month availability. Distinguish monthly capacities from shared daily production hours. |
| 计量 / Units | 库存数量采用统一基本单位“件”，不自动换算箱、托盘、吨或磅；MOQ与箱规须用同一单位。 | Normalize quantities to one base unit for the inventory engine. There is no automatic carton, pallet, mass or imperial-unit conversion. |
| 连续量 / Continuous quantities | 配方、部分生产和调拨模型允许连续量；不要为显示方便擅自取整后继续称为可行。 | Some production and transfer models permit fractional quantities. Rounding a calculated plan can invalidate constraints. |
| 币种 / Currency | 需要金额的入口显式声明币种；不能混加CNY、USD等金额。只改币种名称不会转换数值。 | Declare currencies where required. Do not aggregate mixed currencies or relabel amounts as a substitute for conversion. |
| 汇率 / FX basis | 如需外部换汇，先统一币种并记录使用的汇率、日期和口径；引擎不抓取实时汇率。 | If conversion is needed, normalize outside the engine and record the rate, date and basis. No live FX lookup is provided. |
| 税费与贸易费用 / Cost basis | 明确含税/未税、批次运费、关税、保险与已付款口径；模型只计入对应入口支持并显式给出的成本。 | State tax basis and which freight, duty, insurance or prepaid costs are included. Only documented, explicitly modeled cost fields enter the calculation. |
| 运输单位 / Routing units | 配送把欧氏距离同时作为行程时间；坐标、窗口、服务时长的单位必须一致。不能直接输入经纬度并解释成真实道路时长。 | Routing equates Euclidean arc length with travel time. Use compatible coordinate/time units; raw latitude/longitude and live road travel times are not modeled. |
| 服务水平 / Service | 设计周期服务目标、即时单位满足率和OTIF不同；不能以同一百分比直接替代。 | Cycle-service targets, immediate unit fill and OTIF have different denominators and meanings. |
| 编码与标识 / Encoding | CSV用UTF-8/UTF-8 BOM；标识按文本保留前导零。不同国家同名仓库也不能自动合并。 | Use UTF-8 CSV and textual identifiers. Preserve leading zeros and explicit location keys across regions. |
| 数字格式 / Numbers | 小数用点号；CSV不加千分位分隔符；服务目标填`0.95`，不是`95`或`95%`。 | Use decimal points without thousands separators in machine inputs. Encode a 95% inventory service target as `0.95`. |

`source`的TCO未折现，且每个成本字段有不同单位：`unit_price`为每件；`freight`/`setup`为整批一次性费用；`annual_support`/`annual_energy`为全部数量的年度总费用。详见[采购契约](operations.md)。

For sourcing TCO, `unit_price` is per unit; `freight` and `setup` are one-time totals for the whole purchase; `annual_support` and `annual_energy` are yearly totals for the entire quantity. The horizon-end `disposal` and `residual_value` are whole-purchase totals. Do not supply per-unit values where totals are required.

## 3. 库存字段 / Inventory fields

以下解释补充现有[数据契约](data-contract.md)与[库存引擎说明](v2-engine.md)，不改变输入格式。示例CSV见`assets/demo/`；`demo`命令生成配置文件。复杂优化与采购使用各自的JSON示例，不套用库存表结构。

These definitions supplement the existing inventory contract. For other modules, use the matching JSON example in `assets/operations/` or `assets/optimization/`; inventory columns are not a universal schema.

| 字段 / Field | 中文 | English meaning |
| --- | --- | --- |
| `sku`, `location` | 商品、仓库；联合唯一，不跨仓汇总 | Text item/location identifiers; preserve the pair throughout the analysis. |
| `on_hand` | 可销售实物库存，包含已占用，不含在途 | Sellable physical stock, including `reserved`, excluding inbound or unusable stock. |
| `reserved` | 已在实物库存内分配的待交数量 | Allocated stock already included in `on_hand`; do not add it again. |
| `backorders` | 历史欠单，不与已占用重复 | Existing undelivered obligations, disjoint from `reserved`. |
| `lead_time_days`, `review_period_days` | 自然日交期、复核间隔 | Calendar-day lead time and review interval; each 1–365, combined at most 366. |
| `service_level` | 设计周期服务目标，严格介于0.5与1 | Design cycle-service target, strictly between 0.5 and 1; not a measured achieved rate. |
| `moq`, `pack_size` | 起订量、订购倍数 | Nonnegative integer MOQ and positive integer order multiple in the same base unit. |
| `unit_cost`, `currency` | 同时提供或同时为空 | Provide both or neither; cost is per base unit, with no automatic currency conversion. |
| `date`, `demand_qty` | 每SKU/仓/日一行的新增需求或已声明销量 | One record per item/location/day; new demand or explicitly declared sales, not outstanding order balance. |
| `stockout` | 0/1；空值是未知 | A 0/1 stockout flag; blank means unknown, not zero. Sales constrained by stock availability are not unconstrained demand. |
| `order_id`, `qty`, `eta` | 订单行标识、剩余未交量、到货日期 | Unique inbound line ID, remaining positive integer quantity and arrival date. Split receipts need distinct IDs. |
| `status`（在途 / inbound） | `confirmed`、`unconfirmed`、`cancelled` | Keep these enum values unchanged; only eligible future confirmed receipts count as reliable supply. |

库存快照为`as_of`当日结束时；当日已到货应已进入`on_hand`。确认在途ETA仍为快照当天或更早时，需要先核对，不能自动改到明天。确认无在途也需提供只有表头的文件。缺失需求日期默认不当成零。

The inventory snapshot is end-of-day `as_of`. Receipts already received that day belong in `on_hand`. An overdue confirmed ETA needs reconciliation, not an invented future date. Supply a header-only inbound file when there are no receipts; missing demand dates do not automatically mean zero demand. Future forecasts represent new demand and must not duplicate existing reserved or backordered obligations.

## 4. 状态与术语 / Status values and terminology

| 原值或术语 / Original | 中文解释 | English interpretation |
| --- | --- | --- |
| `ready_for_review` | 可进入业务复核 | Ready for review, not approval or automatic execution. |
| `scenario_only` | 仅为有前提的情景 | Conditional scenario; its assumptions still require confirmation. |
| `blocked` | 当前数据或方案不足以建议 | No actionable recommendation under the reported conditions. |
| `partial`（联动 / chain） | 仅部分情景有可核验方案 | Some scenarios have a checked plan; review each scenario separately. |
| `feasible` | 满足已建模约束，不保证全局最优 | Feasible for the stated model; not a global optimality claim. |
| `optimal` | 完整模型的求解器最优状态，仍需看保证范围 | Solver-reported optimal status; inspect the model scope and validation. |
| `optimal_numerical` | 数值递归收敛，非精确解析证书 | Numerical convergence, not an exact analytic proof. |
| MOQ / 箱规 | 起订量 / 数量倍数 | Minimum order quantity / order multiple; a pack size alone does not convert units. |
| OTIF | 同一到期订单行同时及时与齐套 | On time and in full for the same due order line; not the product of two aggregate rates. |
| TCO | 同数量、币种、年限的建模总成本 | Modeled total cost of ownership on a common basis; current implementation is undiscounted. |
| 有效最优性差距 / Valid gap | 可行成本与原问题有效下界的差距 | Difference between the feasible cost and a valid bound for the full problem; distinct from error versus a published reference. |
| 改善 / 退步 | 原先固定口径下目标变好 / 变差 | Better/worse under the declared paired rules; routing compares vehicle count before distance. |
| 百分点 / Percentage points | 如55%至59%是增加4个百分点 | A rise from 55% to 59% is +4 percentage points; it is not a 4% relative increase. |

`chain`的`partial`/`blocked`对应CLI退出码2；日常库存也可能在成功生成的报告中包含被阻断的SKU。进程正常结束与每一行都有可采用建议不能混为一谈。

For `chain`, `partial` and `blocked` produce exit code 2. Inventory reports can also contain blocked item rows even when a report is generated successfully. Inspect row/scenario status rather than treating process completion as universal plan success.

## 5. 交付前确认 / Before delivery

用需求方语言说明行动、日期、数量、成本口径与剩余问题，同时保留原始状态、字段及来源。明确模拟数据、公开基准和真实业务数据的区别。遇到当前模型不支持的地区规则，应说明所需数据转换或模型扩展，不假装已自动适配。

Deliver actions, dates, quantities, cost assumptions and unresolved issues in the requested language, alongside the original identifiers and status values. Distinguish synthetic examples, public benchmarks and real operations. Where regional requirements exceed the implemented model, state the necessary data preparation or extension rather than implying automatic support. The documentation-only revision leaves all existing benchmark improvements and regressions unchanged.
