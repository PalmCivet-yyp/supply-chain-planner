# 模拟案例：消费品仓库补货复核

使用 `assets/demo/` 下三张表。所有标识、销量、库存、成本、订单均为人工模拟，不对应用户雇主、真实品牌或采购记录。

场景：2026-10-20 收盘，广州仓与苏州仓准备复核采购计划。读取过去 56 个自然日需求和当前在途，给出缺货优先级、常规补货数量、到货前缺口与需要确认的信息。

```bash
python <skill-dir>/scripts/plan_inventory.py \
  --items <skill-dir>/assets/demo/items.csv \
  --demand <skill-dir>/assets/demo/demand.csv \
  --inbound <skill-dir>/assets/demo/inbound.csv \
  --as-of 2026-10-20 --history-days 56 --demand-kind orders \
  --out <new-output-dir>
```

观察不同业务情形：常规补货难以及时到达、库存充足但存在远期订单、低需求高覆盖、出库销量受缺货截断、在途 ETA 已过期，以及同一 SKU 在不同仓库的差异。另跑一次 `--demand-kind sales`，比较需求口径变化怎样影响可交付结论。

建议演示顺序：说明问题与输入 → 展示数据诊断 → 解释两条商品建议 → 比较需求增加 20% 情景 → 讲清限制。只描述演示中实际观察到的结果，不编造降库存比例、节省金额或实际上线成效。用户要写简历时，把它标为个人模拟项目，并核对用户实际参与的工作。
