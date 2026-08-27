# Factor Spec P5：因子组合分数管线 + 策略层回测闭环

> 状态：实施完成（P5A `feat(analytics): 因子组合分数管线 factor_portfolio`、
> P5B `feat(strategy): 因子组合分数回测器与报告` 已实现并全量验证通过，待提交）。
> 前置：P0+P1（`82f5db1`）、P2（`b1fe26d`）、P3（`df9903f` + `df3dd1d` + `f9a102c`）、
> P4A（`a457078`）、P4B（`4da1fe7`）已完成并提交。

## 1. 背景与目标

P4 计划"后续候选项"第 2 项（`factor_spec_plan_p4.md:127`）：**组合器 + 回测接线到
`stock_strategy`（准入报告作为输入门槛）**。P0 长期链路（`factor_spec_plan.md:48`）：
因子资产化（P1）→ 因子质量评估闭环（P4）→ `stock_strategy` 侧组合与回测——**P5 是
长期链路的最后一步**。

现状缺口：

1. `stock_strategy` 只有**信号生成**能力：`StrategyRunner`（`runner.py`）按标的跑
   `DoubleSmaRsiStrategy` 输出 `SignalReport`，**全仓无回测器实现**（grep 无
   `backtest`/回测代码，仅文档提及）；`Context`/`Position` 是只读账户视图，没有
   净值/成交/持仓历史的记录与统计。
2. `factor_research`（P4B）已产出**因子准入报告**（每因子 verdict pass/fail/
   insufficient + IC/ICIR/t/多空价差），但报告**没有任何下游消费方**——P5 把它接成
   组合器的输入门槛：**只允许通过准入的因子进入组合**。

P5 目标：准入 pass 因子 → 截面标准化合成组合分数 → 组合分数面板落盘（analytics 侧）→
策略层回测器按分数面板模拟调仓，产出净值曲线与收益/风险统计报告（strategy 侧）。
整条链路以 mock 面板可端到端复现、手工可核对。

## 2. 范围

- **P5A（先做，analytics 侧新管线）** `pipelines/factor_portfolio/`：
  数据装配（复用 P4B 面板装配逻辑）→ `FactorEngine.compute_all_factors` →
  按准入报告 pass 因子过滤（或白名单覆盖）→ 截面 z-score（direction 对齐）→
  等权合成 → **组合分数面板落盘**（分数 CSV + 组合说明 json + manifest + latest）。
- **P5B（后做，strategy 侧新模块）** `stock_strategy/portfolio/backtester.py`：
  **独立面板级回测器**（非 `BaseStrategy` 事件驱动形态）：输入组合分数面板 + 价格面板 →
  定期调仓（top-N 等权多头，可选空仓）→ 净值序列 + 统计
  （总/年化收益、年化波动、Sharpe、最大回撤、Calmar、期胜率、换手）× 基准对照 →
  回测报告 markdown + json + nav CSV 落盘。
- **CLI**：`factor-combine`（P5A）与 `factor-backtest`（P5B）两个子命令 + Makefile target，
  与 `factor-research` 同模式（`python -m stock_cli.<name>`）。
- **不做**：不做 `BaseStrategy` 化 / 事件驱动回测引擎；不做多空实盘组合（A 股多头简化，
  多空价差只作评估指标，已在 P4 报告输出）；不重构 `primitives` 评估算子；
  不加复权价（沿用未复权 `close`，同 P4 风险 1）；不做交易成本 / T+1 / 涨跌停建模
  （研究版简化，报告标注）；不做准入结论自动回流（FeatureSpec 版本升级仍为后续候选）；
  不改 `factor_research` 行为与产物 Schema。

## 3. 现状盘点（关键事实）

| 项 | 位置 | 事实 |
|---|---|---|
| 回测器 | 全仓 | 无实现（grep 仅文档/注释提及 "回测"）；`runner.py:56` 硬编码 `DoubleSmaRsiStrategy` |
| 策略上下文 | `stock_strategy/context.py` | `Context`（cash/positions/total_value）+ `Position`，只读账户视图，无净值历史 |
| 信号模型 | `stock_strategy/signal.py` | `Signal`(symbol, direction BUY/SELL/CLOSE, target_weight∈[0,1]) |
| 策略配置 | `stock_strategy/config.py` | `StrategyConfig`（SMA/RSI 技术指标 + 风控），无因子组合配置 |
| 数据装配（评估） | `pipelines/factor_research/pipeline.py` | `_assemble_panel` / `_load_optional_dataset` 私有函数：stock_daily_bar 必需，daily_basic/moneyflow 可选 |
| 因子引擎 | `features/factors.py:99` | `compute_all_factors` spec 驱动（12 步），派生列 ⊆ 注册 spec 硬校验 |
| 横截面原语 | `primitives/cross_sectional.py:62` | `cross_sectional_zscore`（ddof=1 样本标准差，缺 std=0/样本<2 输出缺失）；`mad_winsorize`（MAD 去极值）已导出（`primitives/__init__.py:9-12`） |
| 准入报告产物 | `pipelines/factor_research/report.py` + `artifacts.py` | JSON 每因子含 feature_id/unit/direction/verdict/icir/t_stat；落盘 `data/analytics/factor_research/{run}/` + `latest/` |
| 依赖边界 | `docs/architecture/analytics-boundaries.md:26` | `stock_cli`/`stock_strategy` 禁止直连 pipelines 实现模块；2-dot 包门面（如 `pipelines.factor_research`）自动放行 |
| 职责地图 | `docs/architecture/domain-responsibilities.md:28` | `stock_strategy` 负责"策略上下文、信号生成、**组合/回测运行器**" |
| CLI 模式 | `stock_cli/factor_research.py` + Makefile `factor-research` target（:164） | `uv run python -m stock_cli.<name>` |

## 4. 决策点

| 编号 | 决策点 | 默认执行 | 备选 |
|---|---|---|---|
| D1 | 组合分数落点 | `pipelines/factor_portfolio/`（analytics 侧，跨领域组合按职责地图放 pipelines 编排；分数面板是分析产物） | 分数计算放 stock_strategy（会引入 analytics→strategy 反向依赖或 strategy 重复实现，不推荐） |
| D2 | 回测器落点 | `stock_strategy/portfolio/`（职责地图归属）读取 analytics 产物（分数面板 latest）+ stock_daily_bar 价格；依赖方向 strategy→analytics 2-dot 门面/产物，与 `double_sma_rsi.py` 已依赖 primitives 同向 | 独立回测放 analytics（把策略层职责上移，违背职责地图，不推荐） |
| D3 | 合成权重 | **等权**：各因子截面 z-score（direction=negative 取负）后按有效因子均值合成；缺失处理：当日有效因子 < `min_valid_factors`（默认 3）则该日分数为缺失 | 按 IC/ICIR 加权（依赖评估窗口统计量，有样本内过拟合倾向，列为后续候选） |
| D4 | 因子池来源 | 默认读 `factor_research` **latest 报告 JSON 的 pass 因子**（manifest 定位 run 目录）；config 可指定报告目录或 `factor_whitelist` 显式覆盖 | 全因子直接入池（失去"准入门槛"意义，不推荐） |
| D5 | 数据装配复用 | 把 `factor_research` 的 `_assemble_panel` / `_load_optional_dataset` 提取为 `pipelines/_shared/panel.py` 公共模块，两管线共用、行为不变（P4B 测试锁定行为） | 复制粘贴两份（漂移风险，不推荐） |
| D6 | 组合/回测窗口 | config 独立配置（默认 3 年 ≈ 评估窗 2 年之外留 1 年验证；可配）；**窗口覆盖不足 fail-closed**（可回溯交易日 < `min_trade_days` 默认 200 时报错） | 与评估窗口固定一致（统计意义不足，不推荐） |
| D7 | 调仓与建仓 | `rebalance_days`（默认 5，对齐 decision_horizon）每期按当日分数选 top-N（默认 10）等权持仓、现金兜底；**调仓日 close 成交**（close-to-close 简化，报告标注未建模 T+1/成本） | 收盘价次日成交（更贴近 A 股现实，但增加实现与标注复杂度，列为后续） |
| D8 | 回测统计集 | 总收益/年化收益/年化波动/Sharpe（rf=0）/最大回撤/Calmar/期胜率/年化换手；基准 = 观察池全标的等权（分数面板覆盖率不足时输出缺失不推断） | 引入外部指数基准（依赖行情数据范围，本期不做） |
| D9 | CLI 形态 | 两条命令：`factor-combine`（P5A）、`factor-backtest`（P5B，读 latest 分数面板；`--panel` 支持注入供测试） | 单命令全链路（跨包耦合 CLI 编排，拆两条更小可审查，不推荐本轮合并） |

## 5. 任务分解

### P5A 因子组合分数管线（先做，analytics 侧新管线，参照 factor_research 结构）

- **P5A-1** `pipelines/_shared/panel.py`：提取 `assemble_panel` / `load_optional_dataset`
  （自 `factor_research/pipeline.py`，行为不变）；`factor_research` 改经共享模块导入，
  删除私有副本（P4B 既有 17 个测试锁定行为）。
- **P5A-2** `config/analytics/factor_portfolio.yaml` + `pipelines/factor_portfolio/config.py`：
  窗口、`price_col`、`rebalance_days`、`top_n`、`min_valid_factors`、`min_trade_days`、
  `factor_research_dir`（默认 latest）、`factor_whitelist`（空 = 读准入 pass）。
- **P5A-3** `pipelines/factor_portfolio/pipeline.py`：`FactorPortfolioRunResult` +
  `run_factor_portfolio` 编排——数据装配 → `compute_all_factors` →
  读准入报告 JSON（manifest 定位 run 目录，latest 或指定 run；解析失败/无 pass 因子
  fail-closed）→ 截面 z-score + direction 对齐 → 等权合成分数 → 分数面板
  （trade_date × symbol × composite_score）+ 组合说明（因子清单、权重、方向、来源报告）。
- **P5A-4** `pipelines/factor_portfolio/artifacts.py`：RunPaths + `write_artifacts`
  （分数面板 CSV、组合说明 json、manifest + latest），产物 `data/analytics/factor_portfolio/`。
- **P5A-5** 测试：mock 面板手工可算分数（与 `cross_sectional_zscore` 单测对齐）；
  准入过滤边界（pass 过滤 / 白名单覆盖 / 报告缺失 fail-closed）；direction 对齐；
  窗口覆盖不足报错；manifest 落盘。
- **P5A-6** `stock_cli/factor_combine.py` + Makefile `factor-combine` target +
  `analytics-boundaries.md` 说明（`pipelines.factor_portfolio` 2-dot 外部入口）。
- 提交：`feat(analytics): 因子组合分数管线 factor_portfolio（P5A）`

### P5B 策略层回测器（后做，strategy 侧新模块）

- **P5B-1** `stock_strategy/portfolio/backtester.py`：纯函数核心 `run_factor_backtest`——
  输入（分数面板、价格面板、参数）+ 调仓模拟（每 `rebalance_days` 选 top-N 等权，
  close 成交、现金兜底、净值按日复盘）+ 统计（D8 集合，公式与 `primitives` 风格一致、
  小数制）+ 净值序列 DataFrame。缺失分数日沿用上期持仓（不空仓跳变），全期无有效分数
  fail-closed。
- **P5B-2** `stock_strategy/portfolio/report.py`：`build_backtest_report` 渲染
  markdown（净值/统计表/最大回撤区间/换手 + 口径标注：未复权、无成本、无 T+1、样本内、
  观察池幸存者偏差）+ json（全量统计 + nav 序列）。
- **P5B-3** 数据装配入口 `stock_strategy/portfolio/run.py`（或并入 backtester）：
  读 `factor_portfolio` latest 分数面板 + `stock_daily_bar` 价格（`load_dataset_compat`
  经 2-dot 门面/产物读取，不直连 pipelines 实现）、窗口覆盖 fail-closed。
- **P5B-4** 测试：小样本手工可算净值/年化/回撤/Sharpe 边界（公式核对）；
  调仓边界（top-N 截断、等权归一、现金兜底、分数缺失沿用持仓）；
  窗口不足 fail-closed；报告落盘。
- **P5B-5** `stock_strategy/__init__.py` 导出回测器；`stock_cli/factor_backtest.py` +
  Makefile `factor-backtest` target；`analytics-boundaries.md` 补充 strategy 侧消费说明。
- 提交：`feat(strategy): 因子组合分数回测器与报告（P5B）`

## 6. 验收标准

- [x] `run_factor_portfolio` 对 mock 面板输出确定性组合分数面板；分数与
      `cross_sectional_zscore` 单测逐值一致；direction=negative 因子取反后合成。
- [x] 因子池 = 准入报告 pass 因子（latest 或指定 run）；报告缺失/无 pass、
      窗口覆盖不足均 fail-closed；`factor_whitelist` 可显式覆盖。
- [x] `run_factor_backtest` 对 mock 小样本输出可手工复算的净值曲线与
      年化/波动/Sharpe/最大回撤/Calmar 统计（与公式一致）；调仓逻辑覆盖
      top-N 截断、等权、现金兜底、分数缺失沿用持仓。
- [x] 产物 markdown + json + 分数面板 CSV + nav CSV + manifest + latest 落盘
      `data/analytics/factor_portfolio/`（P5A）与 `data/analytics/factor_backtest/`（P5B）；
      `factor-combine` / `factor-backtest` 子命令可运行（mock 数据路径）。
- [x] `factor_research` 行为与产物零变化（共享提取后 17 个既有测试全绿）；
      既有 `stock_strategy` 消费方零改动；`make lint` 全绿（strategy→analytics
      边界检查通过，无 3-dot 违规）。

## 7. 风险与不做什么

- **风险 1 无复权价**（同 P4）：前向收益/净值用未复权 `close`，除权日失真。处置：
  回测报告标注口径；复权价列为后续数据项，不阻塞。
- **风险 2 历史水位不足**：3 年窗口依赖 `stock_daily_bar` 可回溯性；不足 fail-closed，
  不产出空报告。
- **风险 3 样本内过拟合**：准入判定与回测同窗口，且等权合成仅报告统计、不做自动
  决策（P4 风险 4 同款处置）；IC/ICIR 加权列为后续候选。报告标注"样本内、仅研究参考"。
- **风险 4 幸存者偏差**：因子面板/价格来自当前观察池成分，回测含幸存者偏差，报告标注。
- **风险 5 换仓成本被忽略**：无成本/无滑点/无 T+1 约束研究版，换手统计输出供人工评估。
- **不做**：不新增回测数据（不改 stock_data）；不做事件驱动策略引擎；不做多空组合；
  不做 IC 加权；不自动回流准入结论；不改既有 CLI/策略配置 Schema。

## 8. 后续候选项（不在本轮）

- 复权价数据项（`stock_data` 侧），消除前向收益/净值口径风险。
- 事件驱动回测引擎 + `FactorCompositeStrategy`（`BaseStrategy` 化，接入既有策略生命周期）。
- IC/ICIR 加权合成、行业中性化合成（`cross_sectional_zscore(group_by=industry)`）。
- 评估窗 / 回测窗样本外分离；交易成本 / T+1 / 涨跌停建模。
- 准入结论回流：评估通过 → FeatureSpec 版本升级 / direction 修正 / 进入策略候选池。

## 9. 实施记录（实施后回填）

- **P5A `feat(analytics): 因子组合分数管线 factor_portfolio`**（待提交）：
  - `pipelines/_shared/panel.py`：从 `factor_research` 提取 `assemble_panel` /
    `load_optional_dataset` 与基础列常量（行为不变，17 个既有测试锁定）；
  - `pipelines/factor_portfolio/`（config / pipeline / artifacts / backtest_artifacts +
    2-dot 门面）+ `config/analytics/factor_portfolio.yaml`：
    数据装配 → `compute_all_factors` → 准入报告 pass 因子（`factor_whitelist` 覆盖）
    → 按交易日分组的截面 z-score（direction 对齐）等权合成 → 分数面板 CSV +
    组合说明 json + manifest + latest；窗口覆盖不足 / 无 pass 因子 fail-closed；
  - `stock_cli/factor_combine.py` + Makefile `factor-combine` target；
  - 17 个新测试：手工可算 z-score 合成、direction 对齐、min_valid 门控、
    白名单/准入来源边界、端到端落盘。
- **P5B `feat(strategy): 因子组合分数回测器与报告`**（待提交）：
  - `stock_strategy/portfolio/backtester.py`：纯函数 `run_factor_backtest`
    （调仓日 close 成交次日生效、top-N 等权、现金兜底、分数缺失沿用持仓、
    基准等权；日度净值 + 年化/波动/Sharpe/最大回撤/Calmar/期胜率）；
  - `stock_strategy/portfolio/report.py` + `application.py`（读 factor_portfolio
    latest 分数面板与组合说明、DataCatalog 价格、产物发布到
    `data/analytics/factor_backtest/`）；`stock_strategy.portfolio` 包与
    `stock_cli/factor_backtest.py` + Makefile `factor-backtest` target；
  - `analytic-boundaries` 消费说明：strategy 侧经 2-dot 门面
    （`pipelines.factor_portfolio`）读产物，不直连实现模块；
  - 测试：手工算例净值/基准逐值核对、统计公式核对、fail-closed 边界、
    端到端产物落盘。
  - `analytics-boundaries.md` 无需白名单改动：新增面板装配共享模块
    `pipelines._shared.panel` 与 2-dot 消费说明。
