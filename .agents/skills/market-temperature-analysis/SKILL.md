---
name: market-temperature-analysis
description: 使用仓库内的市场温度、行业结构和简报管线完成 A 股市场状态分析。适用于市场温度、市场体检、行业轮动、短线节奏、跨周期复盘、重要信号日和投资者解读等请求。
---

# 市场温度分析

## 作用边界

本 skill 只负责把用户需求映射到仓库已有的分析管线，并约束数据使用和结果验收。指标公式、字段清单、权重、产物 schema、路径拼接和写入逻辑由代码、YAML 配置与产物 Manifest 负责，不在这里重复维护。

分析只使用本地 Curated 数据和管线已经生成的上游产物。没有本地事实支撑的点位、政策、新闻或宏观结论必须明确标为缺失或外部背景，不得补造。

## 能力范围

- 市场温度：生成六维市场温度、综合状态、事实、报告和质量结果。
- 行业结构：生成申万行业强弱、轮动和结构机会/风险结果；行业结构分独立于六维综合温度。
- 投资者简报：基于同一观测日的市场温度和行业结构产物，生成参与条件、观察方向和风险提示。
- 量化投研简报：基于同一上游产物，生成量化视角、风险闸门、行业筛选和仓位解释。
- 多日期与跨周期：按交易日批量生成、校验已落盘产物，并进行阶段变化、信号日和结构迁移复盘。
- 盘后复盘：按仓库提供的每日复盘入口生成组合式阅读报告。

## 工作流

1. 先明确分析范围：单日、最近 N 个交易日、指定日期区间，或跨周期复盘。
2. 日期以本地 `stock_daily_bar` 的已落盘交易日为准；用户指定的日期没有数据时，报告缺口并停止。不要用自然日或系统当前日期替代交易日。
3. 按需求选择标准入口：

   - 只要市场温度：`make market-temperature DATE=YYYY-MM-DD`
   - 需要市场温度、行业结构和两类简报：`make scan DATE=YYYY-MM-DD`
   - 需要每日盘后组合报告：`make daily-review DATE=YYYY-MM-DD`
   - 需要多日期产物：使用 `make multi-date ...` 或 `python -m stock_cli.multi_date --help`
   - 需要跨周期复盘：先运行 `make report-consistency START=... END=...`，再运行 `make market-cycle-review START=... END=...`

4. 多日期入口负责串行生成四类运行目录、统一校验并最后发布选定日期的 `latest`；需要更新 Mart 时使用 `--refresh-mart` 增量入口。只有明确进行历史重建或数据修复时，才使用覆盖式构建参数，并先确认备份和历史范围。
   每日复盘默认复用同一交易日已验证的市场温度和行业结构产物；需要强制刷新上游时使用 `make daily-review DATE=YYYY-MM-DD REFRESH_UPSTREAM=1`。
5. 不手工拼装 facts、不直接复制或编辑 `latest/`、不绕过管线写报告。运行失败、质量校验失败或上游日期不一致时，不把部分结果当作完成。
6. 运行成功后核对命令输出的运行目录、观测日期、Manifest 和质量报告；批量任务还要确认区间一致性检查通过，再使用发布后的结果。
7. 输出分析时区分：本地数据验证事实、由事实得到的机制判断、仍受数据时效或覆盖范围限制的内容。报告应注明观测日和关键数据缺口。

## 连续问答 Fast Path

当用户询问今日复盘、量价趋势、冰点场景、历史日期或系统性风险时，优先使用：

```bash
uv run python -m stock_cli.market_context \
  --as-of latest \
  --questions overview,trend,risk \
  --format json
```

遵循以下规则：

1. 首次回答解析并记录 `as_of_date`、`run_id` 和数据质量状态；同一连续会话的追问复用同一运行，除非用户明确要求刷新。
2. 快照和历史索引有效时，不重新运行管线，不遍历全部运行目录，不重复读取同一源码或完整 JSON。
3. 快照缺失、上游运行版本变化、配置/代码版本变化或质量门禁失败时，才回到标准管线；不能用不完整产物冒充有效结果。
4. `explain-date` 必须通过 `--compare-date` 指定日期，并同时返回目标日期与当前运行的来源和质量状态。
5. 输出必须区分：本地数据事实、代码规则、机制推断。机制推断不得表述为评分规则或确定因果。
6. 市场温度和系统性风险是两个独立输出；低温不自动等于低风险，高温也不自动等于高风险。

问题路由约定：

- 今日复盘：`overview,trend,risk`
- 量价趋势：`trend`
- 冰点或历史极值：`history-extremes,trend`
- 指定历史日期：`explain-date` 并传入 `--compare-date`
- 系统性风险：`risk`

查询入口只返回紧凑 JSON；报告渲染和人类可读表达仍由既有报告入口负责。

## 入口与事实来源

标准入口由 `Makefile` 和 `src/stock_cli/` 提供；管线实现位于 `src/stock_analytics/pipelines/`；评分和解释配置位于 `config/analytics/`。需要确认参数、可用能力或当前产物格式时，优先查看对应 CLI 的 `--help`、当前配置和运行产物 Manifest，而不是依据本 skill 猜测。

`latest/` 只表示最近一次成功发布的展示副本。判断观测日期、上游关系和运行版本时，以运行目录中的 Manifest 为准；下游简报必须使用同一观测日且经过校验的上游运行。

## 专题资料

只有在用户需要解释方法或阅读结果时才读取对应参考资料：

- `references/architecture.md`：模块边界和数据流概念。
- `references/composite-temperature-interpretation.md`：综合温度和风险状态的解释框架。
- `references/industry-structure.md`：行业结构和轮动结果的阅读框架。
- `references/scoring.md`：评分结果和短线温度的阅读框架。
- `references/cross-cycle-study.md`、`references/signal-days.md`：多日期复盘和信号日阅读框架。
- `references/investor-interpretation.md`：面向普通投资者的结果表达。
- `references/report-consistency.md`：产物一致性、溯源和验收原则。

这些参考资料用于解释，不是实现契约。具体公式、权重、可用指标、字段和输出结构以当前代码、配置、测试和产物为准。

## 维护原则

只有用户可见的能力或工作流发生变化时才更新本 skill。新增指标、重构模块、改变内部字段或调整产物实现，不应把实现细节复制进这里；若工作流确实变化，只更新对应入口和验收步骤。
