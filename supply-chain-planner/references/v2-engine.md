# 2.1 库存引擎与配置

## 配置和输入

`settings.json` 是唯一运行配置；Excel 的设置展示页不会替代它。未知配置键报错。

```json
{
  "as_of": "2026-10-20",
  "history_days": 180,
  "demand_kind": "orders",
  "missing_days": "error",
  "shortage_mode": "lost_sales",
  "allocation": "economic",
  "currency": "CNY",
  "budget": 1800,
  "capacity_units": 220,
  "lead_time_scenarios": [
    {"delay_days": 0, "probability": 0.8},
    {"delay_days": 3, "probability": 0.2}
  ]
}
```

| 字段 | 默认/定义 |
|---|---|
| as_of | 必填，快照日结束时，严格 YYYY-MM-DD |
| history_days | 180，7–730；明确上市日期后截取上市后历史，未知起点的尾段标为情景 |
| demand_kind | orders；或 sales（只允许可用性已知且无缺货的条件情景） |
| missing_days | error；zero 需显式确认缺日确为零 |
| shortage_mode | backorder；或 lost_sales（要求历史欠单为0） |
| allocation | service：订到目标库存位置；economic：比较运营成本并满足共享资源 |
| budget | null 不限制；非负同币种采购货值上限，每次复核重置 |
| capacity_units | null 不限制；本次总订购件数上限，可为0；不等于容积或生产产能 |
| currency | 经济优化/回测必填，所有SKU成本必须匹配，禁止混币相加 |
| lead_time_scenarios | 默认 delay=0、probability=1；1–10个不同延迟，延迟0–90天，概率正且合计1 |
| forecast_method | null 自动；mean28 / mean7 / seasonal7 / sba / tsb 可强制对照 |
| demand_factor | 1，0.01–100，仅调整未来需求情景，不改已有在途 |
| safety_scale | 1，0–3，仅调整设计缓冲；回测验证候选为0.75/1/1.25 |

固定基本交期、复核期各1–365天，基本交期+最大延迟+复核期≤366天。已确认PO的ETA不随新单交期情景平移。

使用既有 items/demand/inbound 字段。items 增加3个成组可选字段：`holding_cost_per_unit_day`（币种/件/日）、`shortage_cost`（失销时币种/失销件；欠单时币种/欠单件/日）、`order_fixed_cost`（币种/次）。经济优化和回测还必须有 unit_cost、currency。不得将失销成本直接当成欠单日成本而不确认单位。

items 可选增加 `launch_date`（中文“上市日期”）。日期不能晚于快照，需求不能早于上市日；真正上市前不造零。窗口外有更早需求时，老品按完整窗口检查前段缺日；没有上市依据且只见连续尾段时增加 UNVERIFIED_HISTORY_START 情景标记。

Excel 自动识别 items/商品/库存、demand/需求、inbound/在途，且每类恰好一个匹配。第1行字段名，不含合并标题；支持常见中文列名，见 `scripts/scm/io.py::ALIASES`。需要自定义时使用：

```json
{"sheets":{"items":"ERP库存","demand":"客户订单","inbound":"采购未交"},
 "columns":{"items":{"物料编码":"sku","库位代码":"location"}}}
```

映射按源字段→标准字段。重复目标、空表头报错。SKU、仓库、订单行号必须是文本；数字标识无法可靠恢复前导零。公式及错误单元格拒绝读取，不依赖可能陈旧的缓存。日期允许 ISO 字符串或午夜的 Excel 日期；数量不转换单位或地区千分位字符。

## 算法和可解释性

- 基线为近28/7日均值、周季节朴素法；稀疏候选为 SBA、TSB，平滑参数固定0.1。周季节从下一个星期相位开始。SBA启动采用首次正需求和首次到达间隔的显式实现；不声称与所有软件初始化一致。
- 比较最多28个共同过去滚动起点。先按保护期累计需求 MAE、再按日MAE及固定候选顺序选择。少于8个起点回退均值。WAPE分母为0时输出null。
- ADI与正需求CV²用于诊断，阈值1.32与0.49是分层启发式，不作择模强制规则。新品不足7日阻断，7–27日给条件情景；全零历史保留0预测并提示核对。
- 风险校准使用训练后连续不重叠保护期。对各交期情景，取“该情景期间实际需求−基本保护期预测”的加权经验分位，设计缓冲下限0。少于4期则回退独立日方差近似加最长交期增量，并标为情景。没有校准后的概率覆盖保证。
- 所有未来确认在途抵扣库存位置，保留远期数量和时间缺口；普通新单在基本交期当天开始入库。交期情景影响缓冲、经济评分和回测；主图展示基本交期，最晚情景日期另列。
- 逐日先到货、偿还旧欠单、满足新增需求，再记录日末库存/欠单。失销不结转，避免“负净库存截零”造成错误。
- static_cover_days 为扣占用后实物库存/近期日均需求；net_cover_days_after_backlog 再扣旧欠单并以下限0计算。不包含在途，也不替代逐日时序。主投影仅覆盖所有SKU的最长保护期；保护期之后的远期到货另列，不表示已经模拟到该到货日期。

## 经济优化边界

每个 SKU/仓库的候选为 `0` 和满足 MOQ/箱规、且不超过无约束订到目标量的订单。以最多4条过去不重叠误差路径加当前点预测重建需求情景，与显式交期情景加权，计算每个候选的有限期运营成本。样本不够时仅用点预测，报告标明。重建负预测截到0属于明确的情景构造，不称为原始正态模型。

所有商品使用相同最大投影期限。目标为日末库存持有费、每日欠单费或每件失销费、固定下单费之和。采购现金只进预算并单列，不重复并入运营成本。费用模型不含运输、税、销售利润、残值及期限之后的影响；不能当成全生命周期最优。

用 SciPy MILP/HiGHS 在每个组恰选一个候选，约束总货值≤budget、总件数≤capacity_units。`optimal=true` 仅表示求解器在该有限候选集合与情景目标下证明最优；超时有可行解时显示未证明最优。任何解再次核对整数性、预算与件数。最多20000候选、300万逐日情景事件；超限明确失败，不偷偷改贪心算法。

在途到货前短缺可能无法通过常规新单消除；经济解可以因成本或资源选择0，不保证达到原服务目标。该工具没有采购加急、调拨或取消订单的决策变量，只给复核动作。

## 回测口径

从截至as_of的连续数据末尾切出 train/validation/test，默认120/56/56天。训练数据构造每项初始库存 `ceil(最近28日均值×initial_stock_days)`，初始欠单与在途为0，历史快照和历史PO不用作该起点。这是明确标注的重置情景，不是公司历史实盘重演。

训练区间用于初始化和选择阶段定义，预测按 history_days 使用当时已观察的滚动历史，可能早于列出的训练起点。history_access 披露首次请求/实际起点及允许warm-up；每条 decision_audits 决策保留 history_windows。额外warm-up中的内部缺日也报错，不能将隐藏缺日当新品。

按各项复核周期在每日开始前的收盘快照下单，最早L=1时当天开始到货。在线只能读取当时已观察的需求；下单日/SKU/种子确定交期延迟，不依赖政策下单次数。各政策拥有自己的库存与管道。

验证期选两类基线中更优者，以及3个自适应缓冲倍率中的更优者；先满足 min-fill 再比较运营成本，均不达标则优先满足率。冻结后跑所有测试种子，保留逐日轨迹与求解审计。

即时满足率只计算新增需求当天交付的件数；后续补交旧欠单不能再加入分子。完整复核周期无新增短缺比例排除阶段边缘的不完整周期，不能冒充到货周期CSL。期末实物库存、欠单及在途分别显示。

`adoption_gate` 只在平均模型成本下降、平均即时满足率不下降且达到显式min-fill门槛时建议复核候选，否则保留基线。相对改善不能掩盖绝对服务不足。它不重调政策，也不自动部署。交期种子范围不是实际需求收益的置信区间。真实业务需要另接历史初始状态、订单、费用与新测试区间。

## 输出和依赖

计划：report.json、planning.csv、projection.csv、issues.csv、forecast_metrics.csv、report.html。回测：report.json、test_metrics.csv、replay.csv、report.html。JSON保留原标识、参数、版本、原始文件和配置哈希；CSV转义危险文本。输出目录必须尚不存在。

`scripts/supply_chain.py export --plan <plan-dir>/report.json --backtest <backtest-dir>/report.json --out <new.xlsx>` 为公共默认导出，仅依赖openpyxl，不依赖Node或专用运行时。采购货值公式由Excel打开重算；导出器不填造缓存。标识保持文本，输入中形似公式的字符串不作为公式执行。

旧 `scripts/export_workbook.mjs <demo-input-dir> <plan-dir> <backtest-dir> <output.xlsx> <preview-dir>` 用 Artifact Tool 生成包含实际结果和输入的示例工作簿；需在可解析运行时依赖的临时目录启动，并遵循会话表格技能的创建/检查流程。工作簿货值公式可重算，改变源数据不会在Excel内重新训练预测或重新优化。

Python 3.10+；基本CSV/service计划使用标准库，Excel读入需要openpyxl，economic分配需要NumPy和SciPy。`doctor`报告版本与可用模块。旧入口及其26项行为测试独立保留，不将两版输出直接拼接。
