---
name: market-aggregate-monitor
description: 面向本仓库 A 股全市场聚合监控的执行、解读与扩展指南。用户要求运行或修改全市场聚合、MarketAggregateFetcher、MarketAggregateMonitor、market_aggregate.yaml、市场广度、涨跌家数、全市场成交额或市场聚合报告时使用。指导通过本地 stock_basic 股票全集和腾讯批量快照生成配置驱动快照、缓存、质量报告和市场温度式产物，并严格区分全市场摘要与腾讯核心观察池逐标的实时监控。
---

# A 股全市场聚合监控

## 适用范围

本 Skill 服务于全市场级摘要监控：读取本地 `stock_basic` 股票全集，通过腾讯批量快照获取实时字段，在内存中聚合市场广度、涨跌分布、成交额和市值，再生成可追溯的报告产物。它不输出全市场逐标的明细，也不替代腾讯核心观察池实时监控。

当用户说“全市场聚合”“市场温度计”“市场广度”“涨跌家数”“全市场成交额”“聚合快照质量”“MarketAggregateFetcher”或要求运行/扩展 `make market-aggregate` 时触发本 Skill。

## 标准入口

默认使用仓库根目录的 Makefile；需要直接调用 Python 时保留项目的 `uv` 环境变量约束。

```bash
make market-aggregate
make market-aggregate FORMAT=markdown
make market-aggregate WATCH=1 INTERVAL=60
make market-aggregate RECORD=1
make market-aggregate CONFIG=config/analytics/market_aggregate.yaml
```

常用覆盖参数：`OUTPUT_ROOT`、`RAW_ROOT`、`NO_LATEST`、`BATCH_SIZE`、`STRONG_MOVE_PCT`。运行失败时先查看命令错误和质量产物，不要用模型记忆补写市场数值。

## 配置和代码路由

先读取 `config/analytics/market_aggregate.yaml`，再按任务加载对应入口：

| 任务 | 入口 |
| --- | --- |
| 腾讯批量抓取与聚合 | `src/stock_data/fetcher/realtime/market_aggregate.py`、`src/stock_data/fetcher/realtime/tencent.py` |
| 缓存、网络失败回退、RAW 协调 | `src/stock_analytics/realtime/market_aggregate_monitor.py`、`src/stock_analytics/realtime/cache.py` |
| 配置驱动产物管线 | `src/stock_analytics/pipelines/market_aggregate/pipeline.py`、`artifacts.py` |
| 配置模型 | `src/stock_reporting/interpretation/market_aggregate/config.py` |
| Markdown/JSON/质量报告 | `src/stock_reporting/templates/market_aggregate.py`、`src/stock_reporting/templates/aggregate/` |
| CLI | `src/stock_cli/market_aggregate.py` |

修改共享接口或核心聚合逻辑前，先阅读调用方和对应单测；不要把聚合通道接入核心观察池的逐标的报告。

## 指标口径和边界

当前快照可提供：

- 覆盖数、返回数、覆盖率和 `valid` / `partial` 状态；
- 上涨、下跌、平盘数量与占比，涨跌比；
- 配置阈值以上的强势上涨/下跌数量与占比；
- 涨跌幅 P25、中位数、P75，成交额加权涨跌幅；
- 全市场成交额、总市值、流通市值、流通市值换手率；
- 成交额前 5% 标的集中度。

必须在报告中保留覆盖率和新鲜度。`strong_move_pct` 只是涨跌幅阈值，不能称为涨停/跌停；不能从此摘要推导全市场 MA20/MA60 比例、行业轮动、涨跌停事件或逐标的实时明细。金额内部统一为元，展示为亿元时只做除以 `1e8` 的展示换算。

## 缓存、质量和存储

默认配置为：30 秒内 `fresh`，30 至 300 秒 `stale`，超过 300 秒 `expired`。`MarketAggregateMonitor` 在抓取失败时仅回退到同一协调器已有的当天快照；报告必须显式展示 `freshness`、`age_seconds`、`status` 和 `coverage_ratio`。`stale` 或 `expired` 不能被描述成实时数据。

聚合结果默认写入 `data/analytics/market_aggregate/`：

```text
runs/as_of=YYYY-MM-DD/run_*/
  manifest.json snapshot.json facts.parquet
  report.md report.json human_report.md
  quality_report.md quality_report.json
latest/
```

`RECORD=1` 时才将一行聚合快照追加到 `data/raw/realtime/market_aggregate/tencent/`（按日期/小时分区）；该 RAW 留档不写入 Curated，也不是逐标的历史资产。覆盖率分母是本地 `stock_basic` 过滤出的沪深在市股票数；质量阈值默认是覆盖率 `0.95`，低于阈值必须按质量异常处理。

### 短期趋势与盘中可比性

当前管线会在实时聚合摘要之外生成短期趋势：

- 当前行来自腾讯盘中 `MarketAggregateSnapshot`；历史行从本地 `stock_daily_bar` 聚合涨跌/成交额，
  并从 `daily_basic` 补充总市值、流通市值和流通市值换手率；默认取前 4 个完整交易日，配置位于
  `market_aggregate.trend`；
- 趋势状态为 `available`、`partial` 或 `unavailable`，历史不足或未提供本地 `DataCatalog` 时
  只降级趋势，不伪造当前快照；
- 结果写入运行目录的 `trend.parquet`，报告 JSON/Markdown 同时展示 `history_average`、
  `current_vs_history_average` 和 `latest_vs_previous`；
- 上涨/下跌占比、强势家数、涨跌幅中位数和成交额加权涨跌幅可用于结构方向比较；盘中快照与完整
  日线之间的成交额、流通市值换手率明确标记为
  `not_comparable_intraday_vs_full_day`，不能据此直接推断全天成交额或换手率。

因此，趋势段落应先说明当前快照的 `quote_date`、历史日期和 `freshness`，再解释方向；若
`coverage_ratio` 不达标或快照来自缓存，趋势只能作为部分覆盖观察。

## 修改和验证工作流

1. 先确认需求是运行、改 YAML、改模板还是改抓取/聚合逻辑，并保持全市场摘要范围不变。
2. 改配置时优先修改 `config/analytics/market_aggregate.yaml`，不要把指标顺序、标签或限制硬编码进模板。
3. 改抓取器时保持分批、重试、超时和部分覆盖状态；外部腾讯请求必须 mock，本地 `stock_basic` 缺失时不得降级到核心观察池。
4. 改缓存或产物时同步检查质量报告、`latest/` 和 RAW 留档边界。
5. 至少运行受影响测试；全市场聚合相关测试可用：

   ```bash
   UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run pytest --no-cov -q tests/unit/stock_analytics/realtime/test_market_aggregate.py tests/unit/stock_analytics/pipelines/market_aggregate
   ```

6. 交付前运行 `git diff --check`；若改动涉及 Python，再运行 `UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run ruff check .`，并如实报告网络、Token 或本地数据缺失。

## 结果解读规则

报告首先判断数据质量，再描述市场状态：

- `coverage_ratio` 达标且 `fresh`：可以称为当前聚合快照；
- `partial`、低覆盖率或 `stale`：使用“部分覆盖/缓存观察”，同时列出限制；
- `expired` 或无快照：不得输出确定性的市场结论，应说明数据不可用；
- 任何没有快照支撑的政策、新闻、行业轮动或技术指标结论，都不能写入报告。
