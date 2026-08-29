# 宏观风控研报交付结构说明 (Delivery Template)

> **文档定位**：本文档仅说明交付研报的**章节结构**（供 agent 组装输出时参考）。
> 报告中出现的全部数字（分位、胜率、净值、绩效指标、调仓信号）一律取自工程产物：
> - 宏观风控雷达与维度分位：`data/analytics/macro_risk/latest/report.md`（工程模板 `stock_reporting/templates/macro_risk_report.py` 渲染）与 `risk_factors.parquet`；
> - 多策略回测对账：`data/analytics/macro_strategy/multi_strategy_comparison.md`（工程模板 `macro_strategy_comparison.py` 渲染）；
> - 20/60 日胜率与范式特征：`cycle_windows_matrix.md` / `macro_regimes_playbook.md`（引用前用复算脚本核对）；
> 禁止在 SKILL 或本文档内另存快照数字。

## 建议章节结构

1. **宏观周期综合定位**：一句话定性当前状态（如：局部过热 / 极度冰点 / 震荡磨底 / 哑铃平衡）。
2. **双轨风控雷达与多维穿透**：狂热/恐慌指数 + 维度分位表（因子字段、当前历史分位、风险等级），数据取自 `macro_risk/latest/report.md`。
3. **20 日 vs 60 日周期推演与前向胜率**：结合当前 Overheat/Panic，参照 `cycle_windows_matrix.md` 最新矩阵评估短线节奏与季度赔率。
4. **跨周期 6 大宏观范式映射**：明确当前环境最贴近历史哪一阶段，说明相似点与结构差异（参照 `macro_regimes_playbook.md`）。
5. **宏观多策略回测对账与状态机指引**：
   - 绩效对账直接引用 `macro_strategy/multi_strategy_comparison.md` 产物（理论版 / ETF 实盘版两组表格）；
   - 当前调仓信号与目标配置按 `stock_cli.macro_strategy_live` 巡检结果描述，触发阈值以 `config/strategy/macro_risk.yaml` 为准；
   - 附资金曲线图 `multi_strategy_comparison.png`。
6. **风控纪律与触发条件**：按当前状态机结论描述，不另述实现细节。
