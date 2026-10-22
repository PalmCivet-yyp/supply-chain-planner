# GitHub发布与作品集说明

建议仓库名：`supply-chain-planner`。

建议About描述：

> Auditable supply-chain planning and optimization: inventory, procurement, S&OP, constrained models, and paired benchmarks with explicit regression tracking.

建议Topics：`supply-chain`、`inventory-management`、`operations-research`、`optimization`、`agent-skills`、`python`、`reproducible-research`。

## 上传

解压发布包，将里面的`README.md`、`SKILL.md`、`scripts/`、`references/`、`assets/`、`docs/`及`.github/`等内容放到新仓库根目录。不要只上传压缩包，也不要额外套一层目录，否则默认首页和Actions相对路径会不正确。

使用Git提交时，在解压后的项目根目录执行；将最后两行的占位地址替换为自己新建的空仓库地址：

```bash
git init
git add .
git commit -m "Release Supply Chain Planner 3.1.0"
git branch -M main
git remote add origin <YOUR_GITHUB_REPOSITORY_URL>
git push -u origin main
```

随后在GitHub检查README、License和Actions结果。主分支CI通过以后再创建`v3.1.0`标签或Release；当前包附带的是本地验证结果，不预先承诺托管CI成功。

## 作品集表述

> 构建可审计的供应链决策与优化Agent Skill，覆盖库存补货、采购分析、TCO、S&OP及仓网、配送、配方生产、设备检修和串联库存模型；将输入约束、求解决策和独立核验贯通，支持HTML与Excel交付。设计100个公开优化实例的同预算版本评测，达标数由55提升至59，同时披露14个退步实例，并提供完整解答、评分复核与已有方案择优机制。

该表述描述项目功能和实验事实。用于简历时，另行根据本人实际完成的工作说明AI辅助程度及职责，不将自动生成工作全部写成独立手工开发，也不将模拟结果写成企业落地收益。

本次只是准备发布包，没有替用户创建或公开GitHub仓库。项目代码使用MIT许可；外部题库与方法来源保留各自的适用条件，见[来源](../references/sources.md)和[评测清单](../assets/evaluation/public-optimization.json)。
