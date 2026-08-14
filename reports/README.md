# Reports 投研与量化报告中心

本目录统一归档与管理量化系统的各类分析、体检、审计与回测报告。

## 目录结构

- `reports/scan/`：每日/定期 A 股宏观、中观行业与微观博弈全景体检报告（由 `make scan` 自动生成）
- `reports/audit/`：本地 Parquet 数据资产物理盘点与 RAW/Curated 对账审计报告（由 `make audit` 生成）
- `reports/backtest/`：策略回测、绩效评估与夏普/回撤归因分析报告
- `reports/research/`：量化投研、因子有效性与行业特征专题研究报告

## 命名规范

- 扫描体检报告：`reports/scan/market_scan_YYYYMMDD.md`
- 审计报告：`reports/audit/audit_YYYYMMDD.md`
- 策略回测报告：`reports/backtest/<strategy_name>_YYYYMMDD.md`
