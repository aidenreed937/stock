# 宏观风控（`macro`）线 SOP 符合性评估

> 本文是**宏观风控专项**文档，评估宏观风控线（双轨制雷达 → 策略验证 → 实盘雏形）
> 对照通用量化研究标准工作流程（`../quantitative_research_workflow.md`）的符合程度，
> 并给出收口建议。
> 只保留宏观业务相关的评估结论与行动项；通用工作流（六阶段 SOP、Checklist、
> Ground Truth First）见通用文档，本文不重复。

---

## 1. 评估范围

对照通用 SOP 六阶段，对当前宏观风控线做逐项评估，基于本次核查时的代码、配置与产物：

- 代码：`src/stock_analytics/pipelines/macro_risk/`（S2 特征）、
  `src/stock_strategy/macro/`（S3 验证 + S4 雏形）、`src/stock_reporting/templates/macro_risk_report.py`
- 配置：`config/analytics/macro_risk.yaml`、`config/strategy/macro_risk.yaml`
- 产物：`data/analytics/macro_risk/`、`data/analytics/macro_strategy/`
- 方法论：`macro-risk-research` Skill（双轨雷达、8 维风控画像、跨周期回测）

---

## 2. 评估结论：**整体符合性好，S2 特征层与 S3 稳定性/样本外已闭环；本轮已补齐 IC 验证、敏感性源码化与 Manifest 回填，剩余开放项以 CLI 统一命令面与历史产物披露为主**

宏观风控线是本仓库按 SOP 落地较完整的一条线：S2 特征层**配置驱动、无前视（PIT/时区对齐完备）、无量纲化走标准 primitives、ArtifactStore+Manifest**；S3 具备**事件状态机回测（带 T+1 + 摩擦 + 死区）、Walk-Forward 样本外、跨范式稳定性审计 + 压力测试 + CI 回归门禁**。

本轮修复后，S3 此前缺失的 **IC 验证**已补齐（新增 `stock_strategy/macro/ic.py`，整体/年度/当前时窗三口径），**敏感性扫描已源码化**（新增 `stock_strategy/macro/sensitivity.py`），S2 的 **Manifest `inputs`/`watermarks` 已回填**。剩余"部分符合"项多为收紧类增量（CLI 统一命令面、历史产物披露、文档分篇归档），不改变主干工程化水准。

---

## 3. 逐项对照通用 SOP

| SOP 落点 | 宏观现状 | 结论 |
| :-- | :-- | :-- |
| **S0 立题** | `macro-risk-research` Skill 定义双轨雷达（overheat/panic）、8 维风控画像、6 大宏观范式；机制假说与口径在 Skill 与代码注释中明确定位 | ✅ 符合 |
| S0 术语分层 | 特征（`stock_analytics.pipelines.macro_risk` 产出 0-100 分位 score）vs 有效因子（`stock_strategy/macro` 验证）区分清晰，`ic.py` 模块注释显式声明"本层是验证层，不产生新特征" | ✅ 符合 |
| S0 参数进配置 | `config/analytics/macro_risk.yaml`（factor/window/direction/维度/指数）与 `config/strategy/macro_risk.yaml`（策略 thresholds/friction/regimes/stress_tests/ic/sensitivity）；阈值无代码硬编码散落 | ✅ 符合 |
| **S1 数据** | 数据经 `data_fetchers.py` 注册表提取 Curated/Mart；两融/ETF/复合资金流按发布时滞平移至下一交易日（`_shift_to_next_trading_day`），VIX 时区平移一天，无前视 | ✅ 符合 |
| S1 质量/测试 | 有 `test_macro_risk_pipeline.py`（含 fund_issuance 不前向延续的守卫测试）、`test_macro_risk_capital_flow.py`；外部源可 mock | ✅ 符合 |
| **S2 特征** | `pipelines/macro_risk/`（config/pipeline/data_fetchers/corporate_fetchers/artifacts），config 驱动、0-100 滚动历史分位、release_date 前向填充、无量纲化走 `rolling_percentile` primitives | ✅ 符合 |
| S2 产物/Manifest | `data/analytics/macro_risk/latest/` 有 `manifest.json`（provenance: git_commit/config_sha256 + `data_completeness` + `summary`）+ 面板 parquet；**本轮已回填 `inputs`（13 个因子数据源）与 `watermarks`（13 条水位）** | ✅ 符合（本轮收口） |
| **S3 验证** | 事件状态机回测 `MacroRiskRunner`（T+1 生效 + 佣金/滑点 + 调仓死区 + ETF 复权）；Walk-Forward 滚动 3Y-IS→1Y-OOS + WFE 评级；`run_full_stability_audit` 跨 6 大范式 + 4 大极端危机压力测试 + 252D/756D 滚动胜率 + 双引擎熊市识别；`assert_stability_guardrails` CI 回归门禁 | ✅ 符合 |
| S3 IC 验证 | **本轮新增** `stock_strategy/macro/ic.py`：整体 + 年度 + 当前时窗三口径时序 Rank IC（复用 `stock_analytics.primitives.factor_evaluation`），产物落 `data/analytics/macro_strategy/ic/` | ✅ 符合（本轮收口） |
| S3 敏感性扫描 | **本轮新增** `stock_strategy/macro/sensitivity.py`：overheat 阈值 × ma 窗口网格扫描，产物落 `data/analytics/macro_strategy/robustness/overheat_sweep.csv`，取代原未跟踪临时脚本 | ✅ 符合（本轮收口） |
| **S4 组合/实盘** | 策略标的/基准由 `config/strategy/macro_risk.yaml` 集中管理；防守门（smart_filter/bias_threshold/equity_cap）；T+1 执行纪律在 `MacroRiskRunner` 落地；14:50 盘尾报单在 `live.py` + `macro-risk-research` Skill | ✅ 符合（经由 Skill 与 runner） |
| **S5 报告/归档** | `render_macro_risk_report` 产出 `report.md`（信息分级 + 来源标注）；宏观日报在 `macro-risk-research` Skill；**本轮新增** `docs/research/macro/sop_gap_assessment.md` | ✅ 符合（本轮收口） |
| **统一 CLI 入口** | `src/stock_cli/` 中宏观命令面（macro-*）是否完整覆盖新 IC/敏感性入口待核验；若以就地调用为主则同半导体一样属"部分符合" | ⚠️ 待核验 |
| **数据来源披露** | `config/analytics/macro_risk.yaml` 的 factor 注释（如 smart_money 口径）与 `ic_report.md` 覆盖区间已披露来源口径，但未形成对标光伏 `02_data_availability.md` 的统一"来源/时效/代理口径"表头声明 | ⚠️ 部分符合 |
| **文档分篇归档** | 宏观有 `docs/research/macro_*.md`（极值形态/范式切换/里程碑）散篇，未在 `docs/research/macro/` 下沉淀 `NN_*.md` 分篇体系 | ⚠️ 部分符合 |

---

## 4. 建议的符合性收口（按优先级）

1. **补统一 CLI 入口（P1）**：把新增的 IC 验证（`build_ic_report`）与敏感性扫描
   （`run_sensitivity_sweep`）接到 `src/stock_cli/` 的宏观命令面，提供 `--as-of` /
   `--latest` / `--dry-run` 统一研究命令，使 IC/敏感性可一键复现，不再依赖就地脚本。
2. **补数据来源披露（P1）**：仿照光伏 `docs/research/photovoltaic/02_data_availability.md`，
   为宏观因子数据源生成一份统一的"数据源/时效/代理口径/缺口"声明，满足
   Ground Truth First 与信息分级（特别标注估值冷启动、海外 VIX/铜金比时区平移等口径）。
3. **补研究分篇归档（P1）**：在 `docs/research/macro/` 下沉淀 `NN_*.md` 分篇
   （数据可得性 → 特征 → IC/回测/稳定性 → 结论），对齐光伏分篇结构。
4. **历史敏感性产物清理（P2）**：`data/analytics/macro_strategy/robustness/_overheat_mech.py`
   临时脚本已由 `sensitivity.py` 取代，确认无引用后可清理（当前为 git 忽略目录，不提交）。

> 说明：以上"部分符合"项多为**有据可依的增量收口**，不改变宏观风控线当前已具备的
> 完整性与工程化水准；在按第 4 节的 P1（CLI 入口 + 数据披露 + 分篇归档）补齐前，
> 宏观线可视为"符合 SOP"但"CLI 统一命令面 + 统一披露 + 分篇归档待补全"。

---

## 5. 本文与通用 SOP 的关系

- 通用工作流（六阶段、Checklist、Ground Truth First、门禁）见
  `../quantitative_research_workflow.md`。
- 本文是 `通用 SOP × 宏观风控专题规则` 落地后的**符合性自我审计**，随宏观研究演进持续跟踪。
- 新业务线的符合性评估，另立 `docs/research/<business>/sop_gap_assessment.md`，
  不并入通用文件。
