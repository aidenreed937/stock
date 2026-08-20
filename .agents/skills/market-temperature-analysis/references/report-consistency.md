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

- 三类产物文件是否齐全。
- `market_temperature`、`industry_structure`、`investor_brief` 基准日是否一致。
- `investor_brief` 引用的上游 `run_id` 是否真实存在。
- Markdown 核心数字是否来自 `scores.json`。
- 简报行业是否来自 `industry_panel.parquet`。
- 候选行业是否误包含高拥挤或景气承压标签。
- 风险行业是否有拥挤依据。
- 报告是否出现无源叙事短语。

## 使用要求

跨周期研究、案例复盘和对外输出前必须先跑一致性校验。校验失败时，不继续输出投资判断，只报告失败项和需要修复的产物。

产物选择以 `manifest.json` 的 `as_of_date` 为准，不以目录修改时间或 `latest/` 名称推断观测日期。无 `DATE` 运行投资者简报时，系统会在市场温度和行业结构的 `runs/as_of=*` 中选择共同的最新观测日期，再读取该日期下最新运行。

批量生成多个交易日时，任务按日期串行执行并统一不刷新 `latest/`，避免日期任务覆盖共享目录；简报必须按 `DATE` 绑定同日的市场温度和行业结构运行。全部日期完成后再执行区间校验，并由单个收口任务发布选定日期的 `latest/`。同一交易日不要重复启动同一类产物，当前 `run_id` 只有秒级时间精度，可能发生目录冲突。

可直接使用 skill 内快捷脚本执行上述流程：

```bash
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python \
  uv run python .agents/skills/market-temperature-analysis/scripts/build_multi_date_artifacts.py \
  --start YYYY-MM-DD --end YYYY-MM-DD
```
