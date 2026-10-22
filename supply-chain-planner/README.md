# Supply Chain Planner

**简体中文** · [English](README.en.md) · [中英使用与地区口径备注 / Bilingual usage notes](references/international-usage.md)

**可审计的供应链决策、复杂优化与版本评测工作流**

Auditable supply-chain planning and optimization, with complete decisions, independent checks and explicit regression tracking.

`v3.1.0` · `Python 3.10+` · `MIT` · `Agent Skill + Python CLI`

将库存、采购与产销协同问题转化为可运行的计算流程：从明确数据口径，到输出日期与数量，再检查约束、目标和证据。既可作为Agent Skill使用，也可直接运行Python命令行。核心计算、模拟输入、测试、方法契约和逐题评测记录均在仓库中。

[快速开始](#快速开始) · [功能范围](#功能范围) · [实测结果](#实测结果) · [验证说明](docs/VALIDATION.md) · [GitHub发布与作品集](docs/GITHUB_RELEASE.md)

## 项目特点

- **执行与证据同时交付。** 输出完整订单、分配、路线或生产决策，并保留输入指纹、直接重算的约束残差、求解状态和保证范围。
- **按业务数据建模。** 保留SKU/仓库、到货日期、币种、MOQ与箱规；区分欠单和失销，发现数据不足时给出阻断或条件情景。
- **提供可复核的复杂优化。** 支持容量仓网、时间窗配送、配方生产、设备检修、串联库存和有限期材料流联动。
- **保留已有可行解。** 原子保存计算检查点；同一输入有旧方案时，独立核验后择优采用。
- **报告改善，也报告退步。** 公开百题清单、224份完整解答及独立评分复核，不以总分上升掩盖单题负优化。

## 功能范围

| 模块 | 处理内容 | 主要入口 |
| --- | --- | --- |
| 库存计划 | 预测比较、日期在途、保护期缓冲、MOQ/箱规补货 | `plan` |
| 约束分配与回测 | 有限候选订单的预算/件数约束；按时间切分的政策比较 | `plan` / `backtest` |
| 采购分析 | 支出、周期、联合行OTIF、三单核对 | `procure` |
| 采购方案比较 | 硬条件、来源核查状态、同口径TCO、权重敏感性 | `source` |
| 产销协同 | 月度供需、独立产能、欠单结转与待决事项 | `sop` |
| 复杂优化 | 容量仓网、时间窗配送、配方采购、共享检修、正态需求串联库存 | `optimize` |
| 日期联动 | 采购、配方、库存、共享工时、跨仓调拨及延期情景 | `chain` |
| 结果交付 | JSON、CSV、独立HTML及Excel；优化结果支持完整数值导出 | `export` / `optimization-export` |
| 复核与评测 | 已有旧/新方案择优、公开题下载、成对比较、记录解答复算 | `review-optimization` / 评测脚本 |

## 快速开始

在解压后的仓库根目录执行。建议使用独立Python虚拟环境，并安装依赖：

```bash
python -m venv .venv
# 激活虚拟环境后执行：
python -m pip install -r scripts/requirements.txt
python scripts/supply_chain.py doctor
```

Linux/macOS可用`source .venv/bin/activate`激活；Windows PowerShell可用`.venv\Scripts\Activate.ps1`，并用`$env:PYTHONUTF8 = "1"`启用UTF-8模式。

运行一个库存补货演示：

```bash
python scripts/supply_chain.py demo --out outputs/demo-input
python scripts/supply_chain.py plan --config outputs/demo-input/settings.json --items outputs/demo-input/items.csv --demand outputs/demo-input/demand.csv --inbound outputs/demo-input/inbound.csv --out outputs/demo-plan
python scripts/supply_chain.py export --plan outputs/demo-plan/report.json --out outputs/demo-plan.xlsx
```

打开`outputs/demo-plan/report.html`查看建议、前提和逐日轨迹。输出路径须为不存在的新路径；再次运行时换一个名称。演示输入为模拟数据。

运行原料延期、共享工时和跨仓调拨联动：

```bash
python scripts/supply_chain.py chain --input assets/operations/chain.json --seconds 10 --out outputs/chain-demo
python scripts/supply_chain.py optimization-export --input outputs/chain-demo/report.json --out outputs/chain-demo.xlsx
```

运行容量仓网选址：

```bash
python scripts/supply_chain.py optimize --kind facility --input assets/optimization/facility.json --seconds 10 --seed 17 --out outputs/location-demo
```

`--kind`另支持`routing`、`blending`、`production`、`serial`。这些入口需要NumPy/SciPy；Excel导入及公共导出需要openpyxl。基础CSV/service计划、采购、TCO与S&OP可仅用标准库运行。

## 作为Agent Skill使用

仓库根目录即完整Skill目录。将其放入所用客户端支持的Skills目录并命名为`supply-chain-planner`，由[SKILL.md](SKILL.md)提供触发说明、任务路由和执行规范；[agents/openai.yaml](agents/openai.yaml)提供UI元数据。不同客户端的安装与工具权限由各自配置决定。

示例请求：

> 核查这份库存和带日期的在途数据，在MOQ、箱规及预算约束下提出补货建议，并交付可行性核验、完整数量和HTML报告。

> 比较原料按期到货与延迟两天的情景，保持仓库、共享工时和调拨时延口径一致，解释费用及欠交变化。

## 实测结果

2026-10-22，固定求解核心后，对两版原生程序进行同输入、同预算、同评分器比较。主试验每实例每版本10秒、种子17、单线程顺序运行。

| 测试范围 | 3.0达标 | 3.1达标 | 结果 |
| --- | ---: | ---: | --- |
| 100个公开优化实例 | 55/100 | 59/100 | +4.00个百分点 |
| 其中88保留实例 | 46/88 | 51/88 | +5.68个百分点 |
| 六配送实例×三种子 | 12/18 | 11/18 | 达标次数下降 |
| 原七题，另用每题60秒 | 7/7 | 7/7 | 持平 |

**百题30题改善、56题持平、14题退步，两版均100题可行。** R101从19车增加至20车并跌出达标线；因此不能宣称3.1每次都更好。44题仓网成本全部持平，34题有效下界增强；有效界差中位数由18.3596%降至0.0916%，代表证明更紧，不能写成成本节省。

100实例包括44仓网、56配送及有公开参考值的容量变体；它们不是100种独立业务场景。三种子是重复运行，不增加唯一题数。测试比较原生引擎，不估计LLM加载Skill的因果收益。

获取公开输入并复核包内的224份记录解答，不重新调用优化搜索：

```bash
python scripts/benchmark_supply_chain.py fetch --out public-data
python scripts/regrade_benchmark.py --data public-data
```

[全部验证说明与限制](docs/VALIDATION.md) · [版本量化记录](assets/evaluation/optimization-31-summary.json) · [百题CSV](assets/evaluation/benchmark-31/comparison.csv) · [公开来源与数据指纹](assets/evaluation/public-optimization.json)

## 软件验证

```bash
python -m unittest discover -s scripts -p 'test_*.py' -v
python scripts/evaluate_skill.py --skill-dir . --out outputs/acceptance.json
```

已从导出的仓库目录复跑100项软件检查与60项固定模拟验收并通过，详见[发布检查记录](assets/evaluation/github-release-checks.json)；两类检查和公开题数分别统计。GitHub Actions提供Python 3.10/3.12矩阵，包含依赖检查、测试、模拟验收和演示导出；配置存在不表示已经运行过托管CI。

## 结构与方法

| 路径 | 内容 |
| --- | --- |
| `SKILL.md` / `agents/` | Agent工作流、触发说明和UI元数据 |
| `scripts/scm/` | 预测、仿真、整数分配、运营分析、优化与核验模块 |
| `scripts/test_*.py` | 软件检查 |
| `assets/demo/` / `assets/operations/` / `assets/optimization/` | 可运行的模拟输入 |
| `assets/evaluation/` | 固定验收、公开清单、逐题结果及压缩完整解答 |
| `references/` | 数据契约、方法依据、保证范围及借鉴记录 |
| `docs/` / `.github/workflows/` | 验证说明、作品集发布说明与CI配置 |

详细入口：[库存数据契约](references/data-contract.md)、[库存引擎](references/v2-engine.md)、[采购与协同](references/operations.md)、[复杂优化契约](references/advanced-optimization.md)、[日期联动](references/chain-planning.md)、[原始来源](references/sources.md)。

## 适用边界

输出用于业务复核，不自动提交订单、授标、支付、购机或派车。联动模型为给定日历与时延的有限期材料流；当前不提供生产MRP、效期约束、随机交通、任意网络随机多级库存或ERP自动执行。串联库存给出数值收敛结果；受限候选集合最优不能称为原问题全局最优。

采购证据脚本核对调用者提供的记录，不代替阅读原始来源。TCO采用同数量、币种和年限的未折现口径。模拟与公开基准结果不能作为真实企业收益认证。

## 许可

本项目代码采用[MIT License](LICENSE)。第三方题库按来源下载并验证哈希，不在仓库中重新分发原始数据；其适用条件由来源规定。公开方法和项目借鉴记录见[来源](references/sources.md)与[公开Skill学习记录](references/public-skill-lessons.md)。

## 中英使用备注

中文读者可沿用本页与现有方法文档；英文读者从 [English README](README.en.md) 开始。字段解释、状态翻译及中国与其他地区使用时需要确认的日期、计量和费用口径，集中在[中英使用备注](references/international-usage.md)。命令、JSON字段、状态值和SKU/仓库标识保持原样，解释文字可使用需求方的语言。

当前CLI、部分HTML报告和UI元数据仍含中文，没有新增运行时语言切换功能。中国演示中的`CNY`与仓库名称只是模拟输入，不能直接套用到其他地区。英文文档提供对应说明，不代表已完成所有界面翻译或当地业务规则适配。

本次补充仅涉及说明与备注；引擎版本仍为3.1.0，执行代码、配置、模拟数据与已有评测记录保持原样，没有增加新的算法成绩。
