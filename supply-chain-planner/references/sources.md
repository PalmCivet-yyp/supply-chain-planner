# 方法来源与核实记录

核实日期：2026-10-20。以下为原始课程、作者教材与官方产品文档；只引用支持的方法部分，不把本 Skill 的诊断阈值或定制规则归于来源。需要当前产品行为时重新核实版本。

| 来源 | 支持的内容 |
|---|---|
| [MIT OCW，15.772J，Lecture 14: Stochastic-demand Inventory Models，2014](https://ocw.mit.edu/courses/15-772j-d-lab-supply-chains-fall-2014/0d50c5c77382852102ee30b98f1d4657_MIT15_772JF14_Lec14.pdf) | 复核周期加交期的保护期、基准库存与正态安全系数。定位 PDF 第 20–22 页。 |
| [Hyndman 与 Athanasopoulos，Forecasting: Principles and Practice，第 3 版，Chapter 5](https://otexts.com/fpp3/toolbox.html) | 保留样本外数据、滚动预测起点、误差评估与百分比指标限制。 |
| [Oracle Fusion Cloud SCM 26C，Min-Max Planning](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26c/famml/min-max-planning.html) | 在手与在途参与补货分析、最小起订量与批量倍数的业务约束。仅作概念参照；本 Skill 未复制 Oracle 算法，也未连接 ERP。 |

将以下内容标明为1.0的实现选择：简单基线择模次序、14个重叠起点、累计误差正偏差缓冲及间歇需求阻断。2.0改为最多28个起点、累计需求误差优先、稀疏候选和经验交期情景缓冲；新增规则同样需要业务验证，不归为教材结论。

## 扩展方法审查所用原始材料

以下题目用于提出并核验条件化推导，不是现有脚本的业务效果认证，也不意味着已实现题目中的全部模型。

| 来源 | 审查用途 |
|---|---|
| [IISc，Inventory Problem Set 4，2000](https://gtl.csa.iisc.ac.in/scm/scm_prob4.html) | 有限产速、报童成本、积欠与失销、多级库存缺失参数、牛鞭的相关结构。 |
| [IISc，Quiz 2，2000](https://gtl.csa.iisc.ac.in/scm/quiz2.html) | 区分成本分位与单位满足率；检查Poisson一件一补的状态与触发定义。 |
| [MIT OCW，15.762J，Inventory Problem Set，2011](https://ocw.mit.edu/courses/15-762j-supply-chain-planning-spring-2011/f4121fdabbc518fd499b01b3d104250b_MIT15_762JS11_assn01.pdf) | CSL与fill rate、客户宽限、双运输时序、随机交期与在制良率。 |
| [MIT OCW，15.772J，Problem Set 3，2014](https://ocw.mit.edu/courses/15-772j-d-lab-supply-chains-fall-2014/e140481b4a71fccdc463856ab8d3a5b2_MIT15_772JF14_ProblemSet3.pdf) | 整数EOQ、离散报童、买回合同利润、采购与库存费用口径。 |

公式与数值结果须独立复算并保留所加假设。公开题目没有给出的交期、分布、日历或当前状态，不得视为已知。

## 2.0 执行依据

2026-10-21核实 [SciPy milp 官方文档](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html) 的整数变量、线性约束、求解状态与 gap 语义。实际运行环境记录为 SciPy 1.17.0；不以网页最新版本代替已运行版本。有限订单候选、误差路径重建、共同时域、收货件数定义及采用规则属于本Skill设计。

[Forecasting: Principles and Practice 第13章](https://otexts.com/fpp3/practical.html)说明计数与间歇需求中的Croston方法及预测限制。SBA、TSB及分层采用可复算的固定参数基线，不声称已研究全部稀疏需求方法或在真实业务中胜过基线。

## 2.1 补充的原始文献定位

2026-10-21核对出版方题名、作者、卷页、DOI与摘要；该核对不等于全文逐项复现：

- Syntetos, A. A., & Boylan, J. E. (2005). *The accuracy of intermittent demand estimates*. International Journal of Forecasting, 21(2), 303–314. [DOI:10.1016/j.ijforecast.2004.10.001](https://doi.org/10.1016/j.ijforecast.2004.10.001)。用于定位SBA原始方法和间歇需求评估，不借用论文实证结果为本工具背书。
- Teunter, R. H., Syntetos, A. A., & Babai, M. Z. (2011). *Intermittent demand: Linking forecasting to inventory obsolescence*. European Journal of Operational Research, 214(3), 606–615. [DOI:10.1016/j.ejor.2011.05.018](https://doi.org/10.1016/j.ejor.2011.05.018)。用于定位TSB对需求发生概率的逐期更新及淘汰风险问题；本文工具未另建停销分类模型。

当前SBA/TSB固定平滑参数0.1及首次正需求初始化仍是代码约定。补齐引用未改变预测算法，不因此声称预测准确率提高。
