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
