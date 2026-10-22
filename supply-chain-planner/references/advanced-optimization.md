# 有限预算的复杂优化引擎（3.1）

## 入口与输出

运行 `python <skill-dir>/scripts/supply_chain.py optimize --kind facility|routing|blending|production|serial --input <data.json> --out <new-directory> --seconds 60 --seed 17`。

可先使用 `assets/optimization/<kind>.json` 的五个模拟输入做离线演示，明确标注模拟；例如 `--kind routing --input <skill-dir>/assets/optimization/routing.json --seconds 3`。

复用已有输入时，先完成显式字段映射。所有金额须同币种、同期间；不推算税费、汇率、需求或设备数量。模块需要 NumPy/SciPy，不安装商业求解器。`seconds` 控制一次调用中的搜索与求解预算；求解器和 Python 检查可能有少量停止开销，不是操作系统级硬截止。种子固定构造随机选择，按时间停止的迭代次数仍随机器变化。

读取 `report.json` 的完整 `witness`、直接重算的 `validation`、状态、输入 SHA256、参数和上下界。可行解改善时先原子写入 `checkpoint.json`；失败保留它并写入 `failure.json`。NumPy 标量和数组先转换为 JSON 原生类型，拒绝 NaN/Infinity；失败的替换不覆盖旧文件。检查点可能尚未完成全套审计，交付前仍须核查。

`optimal` 仅用于完整 MIP 的求解器最优状态；`optimal_numerical` 是收敛的数值递归结果；`feasible` 为完整可行方案，不表示全局最优。受限候选集合的界仅对该集合有效。不得用参考题答案、已有输出或网上最佳路线填充新方案。

## facility：可拆分需求的容量选址

输入 `capacity[m]`、`fixed_cost[m]`、`demand[n]`、`allocation_cost_all_customer_demand[n][m]`。可带 `m`/`n` 标签，但数组定义实际形状。各客户需求和仓库容量须正，成本有限非负；仓库与客户 ID 均从 1 开始。

矩阵值是服务该客户**全部需求**的分配成本，目标乘配送比例，不再次乘需求。每户比例和为 1；容量用需求量乘比例；开仓为二元决定。允许一户由多个仓供货，禁止改成每户单仓。尚不接受禁止配送弧、跨仓中转、日期库存或多币种成本。

先生成容量可行的完整方案，再用多起点开仓、精确运输子问题和增/减/交换仓邻域改进，最后在候选仓集合上运行 MIP。输出所有开仓 ID 与稀疏 `[warehouse_id, customer_id, fraction]`，区分全局基本下界和受限集合 MIP 下界。没有全局证书时保留 `feasible`，即使恰好匹配某个公开最优值。

3.1在剩余预算内求解辅助LP，再用其客户/容量乘子在全部原始弧上重算拉格朗日下界。保存乘子与公式，取基本下界、已有有效完整界和新增全弧下界中的最大值。辅助LP限制候选弧时，其LP值本身不是完整问题的界。没有时间或未求得可复核乘子时保留原有效界，不挤占已经完成的可行方案搜索。

## routing：容量与时间窗配送

输入 `max_vehicles`、`vehicle_capacity` 和 `customers_including_depot`。每行依次是 `[id,x,y,demand,ready,due,service]`；ID 连续为 0..n，0 是仓库，仓库需求、服务时间和 ready 为 0。坐标可负，其余数值须有限非负，ready≤due。单客户超过车载重时不支持拆送，明确报错。

每客户恰好一次，路线从仓库出发并返回。允许等待；约束**开始服务**时间在窗口内，回仓不晚于仓库 due。行程时间与成本均为双精度欧氏距离，逐弧不取整。先最少车辆，再最短距离；内部权重大于任何可行车队的距离上限，不使用任意固定大数掩盖目标。

先验证所有可行客户先后关系是否依 ready 严格递增。满足该条件且需求/容量为整数时，使用无环资源约束定价生成路线、扰动对偶值扩展候选，再以集合划分 MIP 组合路线；只有完整定价计算产生的界可列为全局界。未满足无环条件或需求为连续量时，使用通用自适应移除/插入及受限路线组合，不声称定价精确。

输出有序客户列表、独立载重/时间窗检查和界的作用范围。路线候选集最优不代表全路线空间最优。仅支持单仓、同车型、确定行程时间；不支持动态交通、提送货配对、多仓或实时派车。

3.1通用搜索缓存每条路线的可插入成本，只更新被修改路线，并结合四类移除、遗憾插入和带车数约束的路线组合。无环路径先保留原有搜索，在剩余预算允许时再做通用改进，输出更好的已核查方案。固定总预算的启发式搜索仍可能单题退步，必须由成对复测揭示。

## blending：跨月采购、配方与原料库存

输入 `months[T]`、`oils[K]`、`purchase_cost[T][K]`、`hardness[K]`、`price`、`init_store`、`target_store_per_oil`、`max_store_per_oil`、`holding_cost`、`veg_cap`、`oil_cap`、`min_hardness`、`max_hardness`、`min_consume`、`max_ingredients`。

用 `vegetable_oil_indices`（0 起点）显式声明第一组原料；兼容以 VEG 开头的旧数据。`use_implications=[[i,j],...]` 表示使用 i 必须使用 j；兼容旧数据中 VEG 必须使用名为 OIL3 的原料。原料每月可采购并使用，无损耗，不能存成品。产量等于消耗总量；按采购额收费，所有月末包括末月存货收取持有费。最小启用批量、最多原料种数、硬度与两组产能共同约束。输出 buy/consume/store/use/produce 完整矩阵。

## production：共享设备工时与检修

输入 `months[T]`、`products[P]`、`machines[K]`、`max_sales[T][P]`、`processing_hours[K][P]`、`installed[K]`、`down_req[K]`、`profit_per_sold_unit[P]`、`holding_cost`、`max_inventory`、`store_target`、`hours_per_month`。

生产、销售和存货为连续量，停机台数为整数。初始存货为零，期末须达到目标，贡献按**销售**计。全部产品共同占用设备工时，每台设备检修时整月不能生产。总检修要求不得超过原始设备数，以保证能给不同原始设备安排一次检修。

`counterfactual={"machine":"borer","count":1}` 添加在整个期间可用、期间内不新增检修义务的设备，兼容缺省的额外一台 borer 情景。两次求解共享总预算。输出基准和购机后重新优化的完整矩阵与经营贡献增量；不把 LP 影子价格当作整数模型的购机价值。尚无换线顺序、BOM 或生产 MRP。

## serial：正态需求的串联随机服务模型

输入上游到下游 `node_order_upstream_to_downstream=[N,...,1]`，以字符串节点 ID 为键的 `echelon_holding_cost`、`local_holding_cost`、`shipment_lead_time`，以及 `stockout_cost`、`per_period_normal_demand_mean`、`per_period_normal_demand_sd`、`baseline_echelon_levels`。要求正的标准差、欠交成本和级持有费，本地持有费等于本节点到上游级持有费之和。

全额欠交、独立同分布且不截断的正态需求。以 `u0(x)=(p+local_h1)*max(-x,0)` 开始，按 j=1..N 计算 `g_j(y)=E[h_j*(y-D_j)+u_(j-1)(y-D_j)]`、`S_j=argmin g_j`、`u_j(x)=g_j(min(S_j,x))`。D_j 的均值、方差均随本级提前期相应累积。

使用解析第一阶段、补充线性尾部的高斯卷积、标量极小化与四级网格。输出级库存及本地差分、期望成本、指定基准政策成本、改进比例和逐级收敛记录。核对最优点没有贴住边界、最后两次成本差以及库存口径。网格超过 300000 状态时明确停止，不默默降低精度。模型不是任意网络或任意需求分布的通用多级库存求解器。

## 方法依据

- [OR-Library 容量选址格式](https://people.brunel.ac.uk/~mastjjb/jeb/orlib/capinfo.html)：整客户需求成本、容量实例生成。
- [SINTEF Solomon 基准](https://www.sintef.no/projectweb/top/vrptw/100-customers/)：车辆优先的分层目标、双精度距离与时间。
- [SciPy milp](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html)：状态、限时、有效界和 gap。
- [Stockpyl SSM 递归](https://stockpyl.readthedocs.io/en/latest/api/meio/ssm_serial.html)：Chen-Zheng / Clark-Scarf 定义。公开默认网格值有离散误差，不当作精确解析答案。

- [Gurobi Food Manufacture II](https://github.com/Gurobi/modeling-examples/blob/58aa9a00c3bd0e5c609f6e7127e07751c3ad6ce4/food_manufacturing/food_manufacture_2.ipynb) 与 [Factory Planning II](https://github.com/Gurobi/modeling-examples/blob/58aa9a00c3bd0e5c609f6e7127e07751c3ad6ce4/factory_planning/factory_planning_2.ipynb)：配方及检修案例。经济定义遵从业务与可执行目标中的采购、销售口径，另行明确教程公式的差异。
