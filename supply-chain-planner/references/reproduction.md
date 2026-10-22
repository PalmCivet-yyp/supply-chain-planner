# 复现与评估口径

## 安装与运行

Python 3.10+。CSV/service 库存计划、采购、方案比较和 S&OP 使用标准库。经济分配与原有完整测试需要 NumPy/SciPy；Excel 导入和公共导出需要 openpyxl。

```bash
python -m venv .venv
# 激活虚拟环境后：
python -m pip install -r scripts/requirements.txt
python scripts/supply_chain.py doctor
python scripts/supply_chain.py demo --out /tmp/scm-demo
python scripts/supply_chain.py plan --config /tmp/scm-demo/settings.json --items /tmp/scm-demo/items.csv --demand /tmp/scm-demo/demand.csv --inbound /tmp/scm-demo/inbound.csv --out /tmp/scm-plan
python scripts/supply_chain.py backtest --config /tmp/scm-demo/settings.json --items /tmp/scm-demo/items.csv --demand /tmp/scm-demo/demand.csv --inbound /tmp/scm-demo/inbound.csv --out /tmp/scm-backtest
python scripts/supply_chain.py export --plan /tmp/scm-plan/report.json --backtest /tmp/scm-backtest/report.json --out /tmp/scm.xlsx
```

Windows 将 /tmp 路径换为新的工作目录。所有输出必须为不存在的新路径，避免覆盖。公共默认路径不依赖 Node、Artifact Tool 或专用运行时环境变量。openpyxl 写入公式但不计算其缓存，Excel 打开后重算；需要验证公式结果时，用实际可用的表格引擎另行重算和检查，不能将只读取公式文本称为完成重算。

三个运营示例均为模拟输入：

```bash
python scripts/supply_chain.py procure --input assets/operations/procurement.json --out /tmp/scm-procure
python scripts/supply_chain.py source --input assets/operations/sourcing.json --out /tmp/scm-source
python scripts/supply_chain.py sop --input assets/operations/sop.json --out /tmp/scm-sop
python -m unittest discover -s scripts -p 'test_*.py' -v
python scripts/evaluate_skill.py --skill-dir . --out /tmp/scm-acceptance.json
```

## 定量比较

验收输入与60项用途固定于 assets/evaluation/fixtures.json；独立算术、状态不变量和拒绝规则写在 scripts/evaluate_skill.py。用**同一份评测器、同一份fixtures**分别加载旧版与新版技能目录，输出 fixture_sha256 和 runner_sha256；不要让旧版评测器缺少新任务后只比较分母不同的结果。

- 16项已有库存能力的边界与日期追溯；分别报告通过、失败。
- 12项采购、12项TCO证据比较、12项S&OP；旧版未实现的入口记unsupported，不能冒充旧版数值计算错误。
- 8项公共Excel导出检查，衡量该新入口的文件结构、标识、空值和覆盖保护；不等于验证所有Excel原生行为。

分项通过数/固定分母用于表示本验收集覆盖。新增功能覆盖与已有功能正确率改善分别报告，不把综合通过率增加解释为“算法准确率提升若干倍”。评测器使用开发用模拟样例，不能作为独立真实需求数据上的模型泛化证明。

历史 2.0→2.1 开发验收随包保留 assets/evaluation/results-before.json、results-after.json、provenance.json，包含实际逐项结果、两版文件指纹与环境；它们记录开发验收，不是独立业务认证。

跨版本结果需要同时保留：原版源码指纹、固定输入及评测器指纹、两份逐项结果、运行环境、独立试用原始输出。修复后重复跑同一开发验收集属于回归，不重新称为全新封存测试。

## 研究与业务效果

软件测试、60项模拟验收、公开教材题核对、需求样本回测、真实运营效果分别陈述。现有预测方法未因新增采购或S&OP能力而获得准确率提升；库存缓冲与MILP仍有原有范围限制。当前不提供真实业务成本节省、全市场排名或教授水平认证。

100道公开题的来源、原题定位、答案、评分与修订记录需要作为单独可复现题集保留。不能把随机循环次数、代码行数或本轮60项模拟用例补算成已完成该题集。

## 3.0 复杂优化复现

`optimize` 的五个原生模块及输入见 [复杂优化契约](advanced-optimization.md)。使用 `assets/optimization/<kind>.json` 的模拟输入执行 CLI；这些功能不改变旧版60项模拟验收的分母。新增软件检查覆盖分数配送、独立枚举、共享检修、库存解析分位点和原子保存故障。

原五道公开复杂题已用于开发和回归，其重做结果必须标为开发回归。另取未用于开发的容量仓网与时间窗配送实例，只在代码和评分规则固定后评价；不得根据这些结果继续调参后仍称同一轮为留出测试。评估报告、原始提交和封存指纹作为单独成果保存，禁止把题目参考答案放进原生求解器。
