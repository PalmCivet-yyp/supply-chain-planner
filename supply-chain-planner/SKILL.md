---
name: supply-chain-planner
description: "Run auditable inventory planning, constrained replenishment, chronological backtests, procurement/OTIF and TCO analysis, S&OP, bounded facility/VRPTW/recipe/maintenance/serial inventory optimization, and dated procurement-production-stock-transfer scenarios. Use for 库存补货、采购支出、供应商交付、TCO、产销协同、S&OP、仓网选址、时间窗配送、配方生产、设备检修、多级库存、供应延期、共享产能、跨仓调拨情景 and reproducible CSV/Excel/JSON analysis. Preserve warehouse keys, dated receipts, currencies, MOQ and pack sizes; expose valid global bounds, uncertainty, and paired benchmark regressions. Do not use as a production MRP engine or general job-search assistant."
---

# 供应链决策与验证工具

使用 **3.1 可执行引擎**完成分析。优先运行代码、检查证据，再形成中文建议；不要用文字说明冒充已运行的模型。

## 选择任务路径

| 任务 | 入口与必须读取的依据 |
|---|---|
| 日常库存、缺货、积压和补货 | `scripts/supply_chain.py plan`；[数据口径](references/data-contract.md)、[2.0 引擎与配置](references/v2-engine.md) |
| 共享采购预算、收货件数限制 | `allocation=economic`；显式提供币种和成本，读取引擎说明中的优化边界 |
| 验证补货政策的成本与服务 | `scripts/supply_chain.py backtest`；读取引擎说明的时间切分、初始状态与成本定义 |
| 采购支出、阶段用时、交付与三单核对 | `scripts/supply_chain.py procure`；[采购与协同数据契约](references/operations.md)；使用 [模拟采购输入](assets/operations/procurement.json) 的格式 |
| 带硬条件及证据约束的采购方案比较 | `scripts/supply_chain.py source`；读取数据契约中 TCO 单位、核查状态和敏感性；[模拟方案输入](assets/operations/sourcing.json) |
| 月度供需、产能情景及 S&OP 待决事项 | `scripts/supply_chain.py sop`；读取数据契约中的月度范围及期初日期；[模拟协同输入](assets/operations/sop.json) |
| 完整模拟演示 | `scripts/supply_chain.py demo`，再运行计划、回测和 Excel 构建器；标注模拟数据 |
| 理论题、合同、随机良率、客户宽限或方法审查 | [方法审查](references/method-audit.md)、[原始来源](references/sources.md)；区分条件推导和已实现模型 |
| 容量仓网选址、时间窗配送、配方与检修优化、串联多级库存 | `scripts/supply_chain.py optimize`；必须读取 [复杂优化数据契约与保证范围](references/advanced-optimization.md)；复用原生求解器与校验器，不从零重写 |
| 供应延期、共享产能与跨仓调拨的联合情景 | `scripts/supply_chain.py chain`；读取 [日期联动模型](references/chain-planning.md)，以完整材料流重算每个情景 |
| 公开实例复测与负优化检查 | `scripts/benchmark_supply_chain.py`；读取 [评测协议](references/benchmarking.md)，先固定测试集、版本、预算和判定阈值 |
| 旧版结果复算 | 保留 `scripts/plan_inventory.py` 和 [1.0 计算规则](references/planning-method.md)，不混用版本输出 |

## 先建立可核查的数据口径

1. 确认快照为当日结束时、自然日、基本单位“件”、SKU/仓库和需求对象。区分新增客户需求与出库，确认占用与欠单没有交叉扣减。
2. 明确 `backorder`（欠单结转）或 `lost_sales`（失销）。存在历史欠单时，先解决其处理方式，禁止改成失销后静默清零。
3. 确认在途文件已提供；没有在途也要保留表头。只计算确认且未来到货的剩余未交数量；逾期确认在途会阻断相关 SKU。
4. 保留原文件和字段映射。Excel 支持中英文字段与显式映射；标识必须是文本。遇到重复映射、公式、错误单元格、未知键、负件数或非有限数字时修正原始口径，禁止猜测。
5. 不默认缺日为零。只看到连续尾段不能证明是新品；用可选 `launch_date`/上市日期声明上市依据。已有更早需求的老品按完整窗口检查前段缺日；起点未核实则标为情景。新品至少7天连续历史才给条件情景；上市前不补造零。销量发生缺货或可用性未知时阻断需求推断。
6. 缺失经营费率时使用 `allocation=service`。不要为了跑经济优化补造成本、币种、交期概率或预算。

## 运行并检查结果

先定位本 Skill 实际绝对路径。输出到不存在的新目录；不写入输入文件，不自动连接 ERP 或提交订单。

```bash
python <skill-dir>/scripts/supply_chain.py doctor
python <skill-dir>/scripts/supply_chain.py plan \
  --config <settings.json> --workbook <input.xlsx> --out <new-plan-dir>
```

CSV 改用 `--items <items.csv> --demand <demand.csv> --inbound <inbound.csv>`；与 `--workbook` 二选一。非标准 Excel 表名或列名增加 `--mapping <mapping.json>`。

- 读取 `report.json` 的状态、issues、输入哈希、预测比较、保护期缓冲、整数求解状态和逐日轨迹。`blocked` 无自动数量；`scenario_only` 为条件情景；`ready_for_review` 为进入业务复核。
- 核对实物库存、欠单和失销分别记账，已确认到货在当日需求之前入账，新单不能早于交期到货。
- 对远期在途同时解释库存位置和时间缺口；不通过忽略远期订单建议重复采购。需另购时同步复核取消、推迟或提前原单。
- 解释预测按保护期累计误差优先选择，含均值、周季节、SBA 和 TSB。分层和短历史标签是诊断；不能保证某一类模型必然更好。
- 把安全库存写成设计缓冲。经验保护期误差、明确交期延迟情景及短样本近似均不等于实际服务达标证明。促销和趋势仅诊断，尚无因果促销模型。
- 经济优化只在从0到无约束建议量的离散可行订单中求解。检查 `optimal`、MOQ、箱规、预算和收货件数；不能称为无限时域或全供应链最优。
- `capacity_units` 是本次复核可订购总件数，不是仓库容积或生产产能。预算按复核事件重置，不是年度预算。
- 采购货值与持有、欠单/失销、固定下单费用分开。缺少税费、运费、残值与期末后影响，不称为完整总成本或真实节省。

## 验证政策并决定是否采用

```bash
python <skill-dir>/scripts/supply_chain.py backtest \
  --config <settings.json> --workbook <input.xlsx> \
  --train-days 120 --validation-days 56 --test-days 56 \
  --seeds 17,23,41 --initial-stock-days 14 --out <new-backtest-dir>
```

该入口要求完整客户需求、同币种明确成本，使用从训练均值构造的共同初始库存情景；不把当前快照或未来在途误当成历史初始状态。需要真实历史起点和历史订单回放时另建数据接口，不套用当前演示。

1. 在验证期比较固定均值、周季节和不同缓冲倍率的自适应政策；冻结选中政策，再计算封存测试。允许预测随新观察更新，不能回看未来。
   核对 `history_access` 及每次决策的 `history_windows`：训练区间定义初始化和选择阶段，滚动预测可以读取更早已观察的 warm-up 历史，必须披露实际日期；不将二者混称同一窗口。
2. 报告即时单位满足率、完整复核周期无新增短缺比例、实物库存、失销/欠单、持有/缺货/下单费用、采购现金和期末在途。复核周期比例不是补货周期 CSL。
3. 比较共同需求、相同约束及按 SKU/下单日固定的交期随机情景。种子范围只是交期情景变异，不冒充业务收益置信区间。
4. 遵守 `adoption_gate`：测试未同时降低模型成本、维持平均即时满足率且达到显式min-fill门槛时保留基线，解释服务与成本取舍。相对改善不能掩盖绝对服务不足。即使通过，也只建议业务复核。
5. 不因测试结果不好而反复调参后继续称同一段为封存测试；修改后的性能结论需要新的测试区间或新数据。

## 交付与复用

交付重点放在具体行动、日期、数量、理由、前提及建议责任角色。提供 `planning.csv`、逐日 `projection.csv`、预测比较和问题明细，以及可独立打开的 `report.html`。保留 `report.json` 供追溯。

需要可独立安装的 Excel 导出时运行 `scripts/supply_chain.py export --plan <plan-dir>/report.json --backtest <backtest-dir>/report.json --out <new-file.xlsx>`，仅需公开包 openpyxl；backtest 可省略。导出保留文本标识、预测轨迹、复核状态和采购货值公式；公式由 Excel 打开后重算，导出器本身不计算公式缓存。修改源数据后重新运行引擎。会话有 Artifact Tool 时，按表格技能检查、重算和渲染；旧 `export_workbook.mjs` 保留为特定运行时的增强输出，不是公共安装的依赖。

## 采购研究与产销协同

```bash
python <skill-dir>/scripts/supply_chain.py procure --input <procurement.json> --out <new-dir>
python <skill-dir>/scripts/supply_chain.py source --input <sourcing.json> --out <new-dir>
python <skill-dir>/scripts/supply_chain.py sop --input <sop.json> --out <new-dir>
```

- 采购支出按月份、币种、品类分组，供应商只按显式别名合并。用联合行 OTIF，分开显示及时率与齐套率；两个供应商不等于独立供应链。集中度和重叠功能只能提示复核，不推算未经验证的整合节省。
- 采购方案先核查硬条件和来源，再解释同数量、同期限、同币种的未折现 TCO。读取来源原文并记录核查日期、支持主题和复核说明；脚本只检查调用者记录，不会浏览或证明证据内容。未核实、过期、反证或未知硬条件不得进入“符合条件”排名。
- 比较权重敏感性时给出发生换位的情景。不得把权重情景占比称为置信度，不自动授标、支付、提交 PO 或发送消息。需系统接入时，先生成供复核的字段映射和操作清单，使用实际可用的连接器验证能力，不编造 ERP/MCP 连接。
- S&OP 明确期初估计日期、完整月份、单位件和各 SKU/仓库独立产能。输出欠单结转、容量缺口、待决事项、责任角色与会议日期。责任人缺失保持 `awaiting_owner`；月度模型不说明月内缺货，也不求解共享生产线。

完整可复现演示：

```bash
python <skill-dir>/scripts/supply_chain.py demo --out <new-demo-dir>
# 使用该目录的 settings.json、items.csv、demand.csv、inbound.csv 运行上述两个入口。
python -m unittest discover -s <skill-dir>/scripts -p 'test_*.py' -v
```

代码按 `scripts/scm/` 的预测、状态仿真、整数分配、回测、输入及报告模块组织。基础计划仅需 Python 3.10+ 标准库；Excel 导入用 openpyxl，整数分配用 NumPy/SciPy。先用 doctor 核对依赖；不假装缺失依赖时已经完成优化。

用 `scripts/evaluate_skill.py --skill-dir <skill-dir> --out <new-results.json>` 重现 [60 项固定模拟验收](assets/evaluation/fixtures.json)。新增能力未实现记 unsupported，与已有能力算错分开。参考 [复现与评估口径](references/reproduction.md) 和 [公开项目借鉴记录](references/public-skill-lessons.md)。

将题目核对、软件测试、开发验收、模拟回测和真实运营效果分开陈述。既有公开题核对不转化为代码覆盖或业务效果认证。`chain` 仅支持给定日历、到货和调拨时延的有限期间材料流；生产 MRP、任意拓扑随机多级库存、效期、随机交通、预算跨期结转和真实 ERP 执行仍在范围外。

## 复杂优化与结果保存

```bash
python <skill-dir>/scripts/supply_chain.py optimize \
  --kind facility --input <location.json> --seconds 60 --seed 17 --out <new-dir>
```

依题面选择 `facility`、`routing`、`blending`、`production` 或 `serial`；读取完整契约，映射数据后直接调用原生入口。不得把某个公开基准的名称、最优值或路线写入输入替代实际求解。已有脚本覆盖题面时不再临时编写另一套求解器。

先检查 `report.json` 的 `validation.passed`、全部 witness、全局/受限界的范围及输入哈希。限时仅获得可行解时照实报告差距；候选路线或候选仓集合的最优不能扩大成全局最优。串联库存仅称数值收敛，不称精确解析证书。使用不同题集、预算或评分阈值时，不计算伪装成同口径的通过率提升。

先保存可行检查点，再做后续搜索；异常时读取 `failure.json` 与保留的 `checkpoint.json`，核查后再决定是否能交付。不要重跑超出题目预算的搜索后仍称同一次限时运行。所有新优化功能默认只生成供复核的方案，不执行真实订单、购机或派车。

3.1 在未使用的预算内计算仓网全弧拉格朗日下界，并保存可重算的乘子；不能将辅助限制弧 LP 的值冒充全局界。配送保留已验证无环定价路径，通用路径采用缓存插入更新与路线组合；有剩余预算时保留两条路径中的更好可行方案，不能声称限时搜索永不退步。

复杂优化与 `chain` 均输出可独立打开的 `report.html`。需要完整决策 Excel 时运行 `scripts/supply_chain.py optimization-export --input <report.json> --out <new.xlsx>`；仅导出已计算值与决策路径，编辑单元格不会重新优化。必须同时交代可行性、解质量、有效界差、预算、适用范围及仍未解决的需求。

已有仓网或配送旧方案时，先运行 `review-optimization --input <同一输入.json> --baseline <旧report.json> --candidate <新report.json> --out <复核目录>`。复核输入哈希与完整方案，按仓网成本或配送车数/距离择优；持平保留旧方案，两者均无效时阻断。该入口不补算搜索，不抹去独立限时运行中的负优化；跨输入、参数口径或币种不同的方案不得直接比较。

## 中英交付与地区口径备注 / Language and regional notes

按需求方的语言解释结论；使用英文时先读 [English overview](README.en.md)，跨语言或跨地区数据先读 [Bilingual usage notes](references/international-usage.md)。保留命令、字段名、状态值、来源、SKU和仓库标识；不要为了翻译修改机器可读键，或将不同地区的同名指标直接合并。

明确自然日、快照日期、基本计量单位、单一费用币种及税费口径。引擎不自动处理中国调休、其他地区节假日、时区换算、汇率或本地税费；应先把数据转换为各入口支持的口径并记录依据。不要向输入增加未实现的`locale`、`timezone`、税率或节假日日历字段。

Explain results in the user's requested language. Keep CLI commands, schema keys, status values and identifiers unchanged. Read the linked English overview and bilingual notes before interpreting regional units, dates or cost assumptions. Translate explanations alongside the original status values; do not imply that report labels, UI metadata or all reference documents have already been translated. These are documentation additions, not new runtime localization or optimization capabilities.
