# 报告一致性校验

## 目的

校验报告是否可追溯到本地事实、配置规则和上游产物，防止 Markdown 叙述和 JSON/Parquet 事实不一致。

## 命令

```bash
make report-consistency
make report-consistency DATE=YYYY-MM-DD
make report-consistency START=YYYY-MM-DD END=YYYY-MM-DD OUTPUT=data/analytics/report_consistency.json
```

## 校验范围

- 四类产物文件是否齐全；历史旧日期缺少 `quant_brief` 时保留兼容性告警。
- `market_temperature`、`industry_structure`、`investor_brief`、`quant_brief` 基准日是否一致。
- 两类简报引用的上游 `run_id` 是否真实存在。
- Markdown 核心数字是否来自 `scores.json`。
- 简报行业是否来自 `industry_panel.parquet`。
- 候选行业是否误包含高拥挤或景气承压标签。
- 风险行业是否有拥挤依据。
- 报告是否出现无源叙事短语。
- 市场温度 manifest 的 `source_cutoffs.external_market` 是否存在且与事实使用日期一致。
- `scores.json` 与报告中的 `external_risk`、`drivers`、情绪子组和资金 20 日累计事实是否串线。
- `quant_brief` 的综合温度、风险等级、温度变化、Top5% 成交占比和行业行是否与上游事实一致。

## 使用要求

跨周期研究、案例复盘和对外输出前必须先跑一致性校验。校验失败时，不继续输出投资判断，只报告失败项和需要修复的产物。

产物选择以 `manifest.json` 的 `as_of_date` 为准，不以目录修改时间或 `latest/` 名称推断观测日期。无 `DATE` 运行投资者简报或量化投研简报时，系统会在市场温度和行业结构的 `runs/as_of=*` 中选择共同的最新观测日期，再读取该日期下最新运行。

批量生成多个交易日时，任务按日期串行执行并统一不刷新 `latest/`，避免日期任务覆盖共享目录；两类简报必须按 `DATE` 绑定同日的市场温度和行业结构运行。全部日期完成后再执行区间校验，并由单个收口任务发布选定日期的四类 `latest/`。同一交易日不要重复启动同一类产物，当前 `run_id` 只有秒级时间精度，可能发生目录冲突。

一致性校验通过不代表指标质量自动合格；仍需阅读各运行目录的 `quality_report.md/json`，特别是
资金 `metric_date` 滞后、外盘 cutoff、行业 `trend_diagnostics` 和情绪主温度降级状态。

可直接使用 skill 内快捷脚本执行上述流程。日常刷新优先使用 `--last-n N` 或日期区间；如需同步新数据，使用 `--refresh-mart` 增量刷新。不要使用 `OVERWRITE=1`，除非任务明确要求重建并已准备备份/恢复方案：

```bash
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python \
  uv run python .agents/skills/market-temperature-analysis/scripts/build_multi_date_artifacts.py \
  --last-n N --refresh-mart
```

脚本会在增量刷新前后检查 `market_daily` 的历史起点；历史范围被截短时立即停止，不生成或发布后续产物。
