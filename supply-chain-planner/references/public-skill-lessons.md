# 公开 Skill 学习与本版落实记录

审查日期：2026-10-21。仅借鉴方法和工作流；以下是读取过的原始仓库快照。新增核心代码自行实现，不整段复制外部程序或领域包。

| 公开仓库与快照 | 学习重点 | 本版落实与边界 |
|---|---|---|
| [travisjneuman/.claude](https://github.com/travisjneuman/.claude/tree/7a2b5ca4ef808b232d72a07390466eef6e83f31a) · `7a2b5ca4ef80` | 供应链任务框架与业务指标 | 保持入口任务路由；计算仍由程序完成，目标值与实际结果分开。 |
| [cbrock84/headcount](https://github.com/cbrock84/headcount/tree/7d3ddf170a85a67565cbbdcda4e9539d32e5a2c4) · `7d3ddf170a85` | 来源治理、联合OTIF及共同上游风险 | procurement 输出联合行OTIF、上游组未知状态；source 强制主题、日期及核查记录。 |
| [alirezarezvani/claude-skills](https://github.com/alirezarezvani/claude-skills/tree/19392f7a08264ed00486a251f5b2098321771f94) · `19392f7a0826` | 采购支出、周期、整合前风险核查 | 新增币种分离的支出/HHI、阶段用时与关键品类复核动作；不假设整合全部支出即可省去。 |
| [zavora-ai/skill-procurement](https://github.com/zavora-ai/skill-procurement/tree/0444e812ff2f2bd534d8216fc0b8465974e29117) · `0444e812ff2f` | 采购操作序列与三单匹配 | 新增累计数量、显式金额容差的行匹配；动作仅供复核，没有复制其MCP工具声明或假装已接服务。 |
| [emircbngl/claude-procurement-skill](https://github.com/emircbngl/claude-procurement-skill/tree/9ae056dc4e3c1c7256f5138148c473daf50c5180) · `9ae056dc4e3c` | TCO、硬条件、证据核查与不确定性 | 新增生命周期成本、硬条件剔除、证据关联、冲突/过期状态和权重敏感性；核查记录不等于脚本验证事实。 |
| [kishorkukreja/awesome-supply-chain](https://github.com/kishorkukreja/awesome-supply-chain/tree/397d95172e374225574f1fb580c1a77376fff836) · `397d95172e37` | 模型覆盖与代码示例 | 将模型覆盖列为扩展方向；本版未实现多级网络，不将文档中的算法方向写成已有能力。 |
| [takusaotome/claude-skills-library](https://github.com/takusaotome/claude-skills-library/tree/b542ac73ab54a40299a9f407b0ebdb425d107e96) · `b542ac73ab54` | 库存/KPI/S&OP的明确产物 | 新增零需求安全的KPI、月度供需与S&OP待决事项；容量和责任人缺失状态保留。 |
| [a5c-ai/babysitter](https://github.com/a5c-ai/babysitter/tree/feb68abe397acc14f32b34984975c48fedba2b33) · `feb68abe397a` | 工作流输入输出及阶段组织 | 用独立可执行入口与数据契约组织任务；未引入其上层编排框架。 |

比较范围是8个仓库的12个入口，不代表穷尽市场。单个Skill有脚本、父仓库有CI、真实系统已接入，是三种不同证据；分别核查。

文档中的方法广度不自动转化为数值可靠性。零分母、费用率、混币、提前/逾期、缺证据与历史完整性等边界必须通过实际用例检查。
