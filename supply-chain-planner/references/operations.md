# 采购、方案比较与 S&OP 的可执行数据契约

## 目录

1. 通用输入输出
2. procure：采购支出、用时、交付、三单核对
3. source：成本、硬条件、证据与权重
4. sop：月度情景和待决事项

## 1. 通用输入输出

三个入口均为 `python scripts/supply_chain.py <procure|source|sop> --input data.json --out new-dir`。均离线执行，输出 report.json、按主题 CSV 和可独立打开的 report.html；JSON 保留输入文件 SHA-256。

根对象与每行对象只接受下列字段；未说明为可选的字段必须提供。拒绝重复 JSON 键、重复标识、NaN/Inf、数字字符串、布尔数值和未知字段。标识使用非空文本，数量和金额用有限非负 JSON 数字。金额币种不自动推断，成本缺失不能写0；明确无该项费用才填0。完整模拟输入在 assets/operations 三个 JSON 中，均不是客户数据或外部核实证据。

## 2. procure

根字段：`as_of`（YYYY-MM-DD）、`spend`；可选 `supplier_aliases`、`cycles`、`deliveries`、`matches`。列表可为空，表示该主题未提供记录，不表示真实业务金额/风险为0。

### spend

每行：`id,supplier,category,period,amount,currency`；可选 `upstream_group,critical`。

- period 为 YYYY-MM，不能晚于快照月份；金额定义为该行在该月份的支出，未折现、不含自动汇率处理。原始行必须具有唯一 id，避免重复计数。
- `supplier_aliases` 为源名称→标准名称的一层显式映射，不用模糊匹配自动合并。供应商数量、份额、HHI 仅在同月份/币种/品类内计算。HHI 使用份额平方和，范围0–1，不套反垄断法判断。
- ABC 是按金额排序的累计80%/95%启发式；跨过边界的行归入该区段，不将单个占比超过80%的最大供应商漏出A类。零金额群体份额/分层为null。
- upstream_group 是已声明的共同上游组；未提供时独立性未知。组名称不同仍不证明已经完成供应链追踪。
- critical 是可选布尔值。缺失保持null（未知），不能推断非关键；任何记录标为关键则整组按关键复核，只有全部明确false才归非关键。关键或未知品类优先核查连续性与备用措施；非关键品类也只提示核对重叠功能、切换成本和条款。输出不估计未经报价支持的整合节省。

### cycles

每行：`id,category,requested,approved,po_created,paid`；日期必须依次不减且 paid≤as_of。统计已完成付款的记录，不能代表所有未结采购单的周期。

输出 request→approval、approval→PO、PO→payment、request→PO 的样本数、中位数和线性插值P90。样本少时保留计数；描述性阶段用时不是全流程吞吐瓶颈的因果证明。

### deliveries

每行：`id,supplier,due_date,delivered_date,ordered_qty,delivered_qty`。

一行代表订单行，ordered_qty 是正整数，delivered_qty 为非负整数；delivered_date 可为null，届时已交数量必须为0。实际交付日不能晚于快照。

分母为 due_date≤as_of 的订单行；未来到期行排除。及时=已交日期≤承诺日期；齐套=累计已交数量≥订单数量；行OTIF=两者同时成立。已逾期而未交的订单行失败，不能从分母删除。该单日期摘要不支持从多次分批交付中重建“到期日已齐套”，需先由真实收货明细形成正确摘要。

### matches

每行：`id,currency,po_qty,received_qty,invoice_qty,unit_price,invoice_amount,amount_tolerance`。

数量为同一订单行的累计整数件数；发票金额为同币种累计税前小计，不处理税费、贷项与多币种。quantity_match 要求 invoice_qty≤received_qty≤po_qty，金额核对按 invoice_qty×unit_price，以显式绝对金额容差判断。部分收货/开票可给 partial_match；所有数量一致为 matched，超量或金额不符为 discrepancy。使用十进制金额比较，容差为0时不暗加宽限。

action 为 review_for_payment 或 investigate_discrepancy，只是复核动作；无付款、审批、PO 提交能力。

## 3. source

根字段：`as_of,currency,quantity,horizon_years,criteria,requirements,sources,options`。
可选 `max_source_age_days`（默认90）、`sensitivity_delta`（默认0.1，权重绝对变动）。

- quantity 为正整数；horizon_years 为1–20整数。所有方案用同一币种、采购数量和比较年限。
- criteria 每行 id、weight；权重非负且和为1，最多20个。requirements 为唯一硬条件名称列表，与 criteria 和 costs 不重名。

### 成本单位

每个 options 行包含 `id,name,currency,costs,requirements,scores,evidence`。
costs 必须完整提供：

| 字段 | 单位 |
|---|---|
| unit_price | 币种/采购件 |
| freight、setup | 本次整批采购一次性总费用 |
| annual_support、annual_energy | 全部采购数量每年总费用 |
| disposal、residual_value | 比较期限末整批处置费用、残值 |

TCO = quantity×unit_price + freight + setup + years×(annual_support+annual_energy) + disposal − residual_value。它未折现，不含未提供的税费、融资等，不称为完整经济价值模型。

### 硬条件与证据

- 方案 requirements 是硬条件→pass/fail/unknown 的完整对象。fail 和 unknown 均不能进入符合条件的排名。
- scores 是除 tco 之外所有 criterion→0–100 分值或null的完整对象；null阻止排名。分值由已核查的比较规则提供，不让模型伪造精确评分。
- evidence 必须为 costs、各硬条件和各非tco指标提供来源id列表；空列表保留缺证据状态。未知来源id报错。
- sources 每行 id、url、title、checked_on、status、supports；可选 review_note、publisher_group。status 为 verified/unverified/refuted，verified 必须提供复核说明。supports 明确其支持的主题。日期不能晚于快照，过期来源不作符合条件证据。
- 每个主题至少有一项相关、新鲜且由调用者标记 verified 的来源；任何相关 refuted 来源使该主题存在冲突，不能用另一条乐观证据掩盖它。
- 脚本只检查来源记录和关联，不下载、不交叉证明来源内容。调用者必须先读原文、核对报价数量/期限/税费、反证和独立性。只填写URL不能算完成事实核查。模拟 example.invalid 链接只能用于演示。

### 排名与敏感性

按已声明权重计算分数；同分时按TCO、id确定稳定顺序。tco 只有在显式列为指标时才进入分数：在符合条件方案的最大/最小TCO间线性映射至0–100，成本相同均为100。被剔除或缺证据的方案不参与该映射。

每次将单个权重加减delta，截在0–1，其余权重同比归一；若其余原权重全0，则均分剩余权重。报告有限情景的第一名和保持比例，不当成统计置信度。没有符合条件方案时不输出首选。

## 4. sop

根字段：`as_of,meeting_date,next_meeting_date,opening_date,opening,plan,history`；可选 `owners,scenarios`。

- opening_date 必须等于第一个计划月1日。opening 的 stock/backlog 是该日期的期初情景估计，不直接拿月中快照冒充下月期初状态。会议日期≥as_of，下次会议更晚。
- opening 每行 sku、location、stock、backlog；键唯一，实物库存和欠单先抵消，不能同时为正。
- plan 每行 sku、location、period、demand、planned_supply、capacity。计划月必须晚于快照月份；每个键月份连续，所有键覆盖同一组月份。capacity 是该 SKU/仓库当月可供应件数，不是全工厂共享约束。
- history 每行 sku、location、period、actual、forecast。必须为快照月份之前的已结束月份、已知键、无重复。未提供历史时指标为空，不填造准确率。
- scenarios 每行 id、demand_factor、supply_factor；默认仅base=1。先调整需求和计划供应，再按原始capacity封顶；无需重调产能的情景不能顺带改变capacity。

月度开始可用供应=min(planned_supply×supply_factor,capacity)；先补旧欠单，再满足当月新增需求，剩余不足结转欠单。实物库存和欠单分开。仅有月度汇总，不能判断月内到货先后造成的缺货。

预测指标包含MAE、WAPE、mean_error_units（平均每记录预测−实际）、cumulative_error_units（累计预测−实际）、总量偏差比例、非零实际量MAPE及其覆盖比例、tracking signal；bias_units 保留为平均偏差的兼容字段。WAPE/偏差分母为0时为null；MAPE仅覆盖正实际量，不把零需求全部排除后称完美准确。不同SKU汇总为件数口径，比较各项时读取分项指标。

owners 可含 demand/supply/procurement→责任人文本。缺口输出待决事项、月度、件数、期限、owner和状态；责任人缺失保持awaiting_owner，否则仍为open，不自动标记已完成。议程与待决事项可以导出用于讨论，不发送邀请或消息。
