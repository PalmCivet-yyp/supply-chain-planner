# 日期联动模型（3.1）

```bash
python scripts/supply_chain.py chain --input assets/operations/chain.json --seconds 10 --out chain-demo
python scripts/supply_chain.py optimization-export --input chain-demo/report.json --out chain-demo.xlsx
```

输入是明确标注的模拟示例。模型在给定逐日日历上联合决定采购、固定配方生产、库存、交付和跨仓调拨；场景分别重新优化，共享一次总时间预算。目标是输入声明的采购、生产、调拨、持有和欠交费用之和，不能推断实际企业节省。

## 输入契约

| 字段 | 定义 |
|---|---|
| `currency` | 全模型统一的三位币种；采购记录显式币种必须相同。无自动换汇。 |
| `dates` | 非空连续自然日，ISO日期，数组顺序即时间。 |
| `locations`、`items` | 唯一文本仓库和SKU；每个SKU必须声明`holding_cost`（每件每日）与正的`backlog_cost`（每欠交件每日）。 |
| `initial_stock`、`initial_backlog` | 可选`item,location,qty`记录；默认无库存或欠交，不从未来快照推断。 |
| `demand` | `date,item,location,qty`；按SKU/仓/日聚合，不支持客户优先级、失销或效期。 |
| `purchases` | 唯一`id,item,location,order_date,arrival_date,max_qty,unit_cost`；可声明`pack_size`（默认1）、`moq`（默认0）、每次`order_cost`（默认0）和已经承诺的`fixed_qty`。采购数量按箱规整数倍。 |
| `capacities` | 共享产能组到逐日可用工时数组的映射。 |
| `production` | 唯一`id,location,inputs,output,capacity_group,hours_per_unit,max_per_day,unit_cost`及可选`lead_days`（默认0）；`inputs`为每单位产出所需原料系数。必须为无环配方网络，生产数量连续。 |
| `transfers` | 唯一`id,item,from,to,lead_days,max_per_day,unit_cost`；不同仓，时延至少1天，数量连续。 |
| `storage_capacity_units` | 可选各仓日末总件数上限，非体积或重量。不同SKU的“件”相加须先确认业务意义。 |
| `purchase_budget` | 可选全部建模采购费用上限，包含建模的已承诺数量与固定下单费；不是年度可用资金，也不自动扣除历史已付款。 |
| `end_backlog_cap` | 可选期末欠交总件数上限。未声明时由显式欠交费用权衡。 |
| `scenarios` | 唯一`name`，可带`purchase_delays:{采购id:非负整数天}`和`capacity_factors:{组:非负倍率}`。禁止未知采购、产能组和场景字段。 |

## 时间与费用

采购仅在声明的到货日进入库存，不能借用未来到货。过去下单的采购必须显式给定已承诺数量。期末之后的已承诺到货保留为在途并计入已声明采购费用；不能误作期初库存。新增采购、生产和调拨在本期末之后到货时不安排新数量。

生产在开工日消耗配方原料，在开工日加交期后增加产出。同日零交期工序按无环配方和日汇总平衡，不表示已验证小时级顺序。调拨在发运日扣源仓、到货日加目的仓，正时延避免当日循环借货。交付不能提前冲抵尚未发生的需求；全部未交需求结转欠单。

以日末实物库存和欠交计费。没有税费、资金时间价值、期末残值或期末之后的欠交成本；期末库存与欠交另行披露。成本权衡只在声明范围内最优。承诺采购若已付款，应由调用者明确所用费用及预算口径，不能静默当作免费或重复付款。

## 输出与验证

`report.json`保存每情景完整采购量、开单标志、生产与调拨矩阵、日末库存、欠交、交付、坐标轴、有效求解状态和约束残差。直接回放每条到货、生产、调拨与需求，独立于MILP系数矩阵重算材料守恒、共享工时、MOQ/箱规及费用。

`report.html`展示情景费用、每日交付/欠交/库存和适用范围；Excel导出完整决策路径和数值。用成本变化、欠交件·日变化及期末欠交共同解释供应风险，不能仅按成本排名。

所有情景均有可复核方案时，顶层为`ready_for_review`；部分可行是`partial`，全部无方案为`blocked`。后两者CLI退出码为2，不以进程完成冒充方案成功。已承诺正数量低于声明MOQ等可直接判断的矛盾在求解前带采购ID拒绝。

该模型没有路线访问顺序、换线、工序排序、随机需求服务率、失销、效期或ERP写回。它与日常补货引擎的失销/欠单设置分开；不能把本模型的有限日历情景称为全供应链联合最优。
