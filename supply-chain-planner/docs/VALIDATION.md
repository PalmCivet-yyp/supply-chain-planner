# 验证结果与证据边界

本记录对应 Supply Chain Planner 3.1.0，日期为2026-10-22。求解核心与百题试验固定的候选代码一致；发布整理只增加文档、记录评分复核入口及版本文件，不根据保留题调整算法。

## 百题比较

44个OR-Library容量仓网实例，56个Solomon百客户时间窗配送实例。共96个来源文件构成100个有公开参考值的实例，包含7个标明容量的变体。相似位置、容量和时间窗实例之间有关联，不能视为100种业务流程或100个统计独立样本。

主试验逐实例交替运行两个版本，各10秒，种子17，单线程、顺序子进程；同输入、同预算、同评分器。12题预先用于开发，88题在代码固定后用于本轮保留测试。公开题可能存在于模型训练中，“保留”仅指本轮开发划分。

| 范围 | 3.0达标 | 3.1达标 | 变化 |
| --- | ---: | ---: | ---: |
| 100个主试验实例 | 55/100 | 59/100 | +4.00个百分点 |
| 其中88保留实例 | 46/88 | 51/88 | +5.68个百分点 |
| 其中12开发实例 | 9/12 | 8/12 | -8.33个百分点 |
| 44仓网实例 | 39/44 | 39/44 | 持平 |
| 56配送实例 | 16/56 | 20/56 | +7.14个百分点 |
| 六配送实例×三种子 | 12/18 | 11/18 | -5.56个百分点 |
| 原七题另按每题60秒回归 | 7/7 | 7/7 | 持平 |

100题两版都返回完整可行方案。按仓网成本、配送车数优先/距离其次的顺序，30题改善、56题持平、14题退步。R101由19车增至20车，从达标降为未达标。六题种子复测使用17、23、41；18次成对运行不是18道新题，也未覆盖全部题组。

44题仓网成本全部持平；34题有效下界增强，0题变弱。有效最优性差距中位数从18.3596%降至0.0916%，这不能解释为成本下降。原大型H1/L1仍有36.91%/39.65%的有效界差，本轮未解决该短板。

逐题目标、车数与退步标记见 [CSV](../assets/evaluation/benchmark-31/comparison.csv)。完整汇总含全部14题退步明细，见 [实测记录](../assets/evaluation/optimization-31-summary.json)。

## 复核已记录解答

```bash
python -m pip install -r scripts/requirements.txt
python scripts/benchmark_supply_chain.py fetch --out public-data
python scripts/regrade_benchmark.py --data public-data
```

下载器按清单验证原文件与规范化输入的SHA256；来源变化时停止，不静默替换题目。外部原题数据不随本项目重新分发。来源、参考值、开发划分与精度规则见 [公开清单](../assets/evaluation/public-optimization.json) 和 [评分口径](../references/benchmarking.md)。

复核入口读取 [压缩的224份完整解答](../assets/evaluation/benchmark-31/recorded-decisions.json.gz)，包含百题两版的200份解答和12组额外种子运行的24份解答。它重算约束、目标和判定，与记录逐字段比较；允许极小的跨平台浮点差异，不改变质量判定阈值，不调用求解器。对应 [主试验](../assets/evaluation/benchmark-31/primary-results.json) 与 [额外种子](../assets/evaluation/benchmark-31/repeat-results.json)。

原七题的汇总数值保留在版本实测记录中；此复核入口不包含原七题的独立评分流程。发布包没有附上3.0完整源码，因此“复核记录评分”与“重新运行两个版本搜索”是两项不同工作。需要重新搜索时须另行提供两个版本目录：

```bash
python scripts/benchmark_supply_chain.py compare --data public-data --baseline /path/to/3.0 --candidate . --seconds 10 --seeds 17 --out paired-results
```

旧实验Git提交号用于来源追踪；它们属于原开发仓库，并不是在新GitHub仓库中可直接检出的标签。限时启发式可能随主机、依赖和停止时点变化，重跑不承诺逐位相同。

## 采用复核与测试

对同一输入的两份已有解答做独立核验再择优，本轮30题采用新版、70题保留旧版，采用后相对已有方案退步0题。该入口需要两次搜索的已有结果，不能把采用后的60/100达标当作新版单次10秒成绩。

已有100项软件检查和60项固定模拟验收通过。二者分别检查代码行为、开发模拟案例，不能与公开题数相加，也不证明实际企业节省。本次已从导出的仓库目录复跑100项软件检查与60项模拟验收，并验证记录解答复算、联动情景及Excel导出；详细结果见 [发布检查记录](../assets/evaluation/github-release-checks.json)。

GitHub Actions配置提供Python 3.10/3.12检查矩阵；本地验证环境是Python 3.12.14、NumPy 2.3.5、SciPy 1.17.0、openpyxl 3.1.5。配置存在不代表托管CI已经运行，也未进行所有依赖最低版本的兼容性认证。

这些结果比较两版原生程序，不衡量LLM加载Skill相对于不加载的因果收益；共享主机没有物理隔离，不作速度排名、全市场最好或真实运营降本认证。

## 说明补充 / Documentation-only revision

后续中英备注仅增加语言导航、英文概览和地区口径解释，版本仍为3.1.0。执行代码、配置、输入、固定验收与公开评测记录不变；原软件检查结果和负优化记录保留。本次文档检查不计作新的算法复测或新增通过题数。

The bilingual additions only document existing behavior. They do not introduce runtime locale switching, new regional rules or new numerical results. See the [English overview](../README.en.md) and [bilingual notes](../references/international-usage.md).
