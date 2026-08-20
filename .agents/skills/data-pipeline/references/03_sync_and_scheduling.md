# 每日增量采集与定时调度指南 (Incremental Ingestion & Scheduling)

`DailySyncEngine` 提供基于水位自动嗅探（Watermark Sniffing）、发布窗口保护（Wave Routing）与多端点并发补齐的一站式增量更新服务。`SOURCE=all` 目前由 CLI 按数据源顺序循环，跨数据源并不并行；单个数据源内部才按配置使用线程池。

---

## 1. 增量同步 CLI 指令规范

```bash
# 1. 默认一键同步当天所有已就绪端点并执行自动对账
make sync

# 2. 仅同步指定数据源或指定日期
make sync SOURCE=tushare DATE=YYYY-MM-DD
make sync SOURCE=lixinger
make sync SOURCE=yfinance

# 3. 强制覆盖刷新 (全数据源)
make sync SOURCE=all FORCE=1

# 4. 强制刷新 LiXinger，绕过发布时间窗口、水位与 RAW 缓存
make sync SOURCE=lixinger FORCE=1

# 5. Alpha Vantage 单并发增量 (限频保护)
make sync SOURCE=alphavantage ENDPOINT=fx_daily WORKERS=1
```

---

## 2. 理杏仁 TaskBundle 组合调度

增量同步支持将相关原子任务按业务组传入（自动展开为独立水位探测和独立审计）：

```bash
make sync SOURCE=lixinger ENDPOINT=market_bundle    # 股票与指数 K 线
make sync SOURCE=lixinger ENDPOINT=industry_bundle  # 申万 2021 成份、估值与四类行业财报
make sync SOURCE=lixinger ENDPOINT=company_bundle   # 公司基本面、财报与股权质押
make sync SOURCE=lixinger ENDPOINT=macro_daily_bundle,macro_monthly_bundle  # 国债、利率、投资者与宏观序列
make sync SOURCE=lixinger ENDPOINT=index_fundamental                     # 指数基本面估值（原子任务）
```

LiXinger 不再注册历史别名 `macro_bundle` 和 `index_bundle`。宏观数据使用 `macro_daily_bundle`、`macro_monthly_bundle`，指数基本面直接使用原子任务 `index_fundamental`，并维护独立水位和失败状态。

---

## 3. 水位、发布时间窗口与 RAW 缓存

未指定 `ENDPOINT` 时，`make sync SOURCE=lixinger` 会从任务注册表展开全部公开原子任务；指定 bundle 时先展开并去重。每个原子任务独立计算 Curated 水位、增量区间和失败状态。

单任务的计划状态遵循以下语义：

| 计划状态 | 判定 | 上游 HTTP 请求 |
| :--- | :--- | :---: |
| `UP_TO_DATE` | Curated 水位已覆盖目标日/期间 | 否 |
| `SKIPPED` | 发布时间窗口未到、交易日历不可用或任务被配置停用 | 否 |
| `PENDING` | 水位存在缺口，或首次同步尚无水位 | 先查 RAW 缓存 |

待执行任务默认启用 RAW 缓存；缓存覆盖目标日期和标的时直接复用，跳过网络请求。`FORCE=1` 才会关闭 RAW 缓存，并允许绕过发布时间窗口和已最新水位，用于核验上游响应或强制刷新。

日频任务通常从 Curated 水位次日开始，月频/季频任务推进到下一业务期间。历史兼容表的 `date`/`Date` 会在 Curated 加载时归一为 `trade_date`，水位扫描按任务注册的 `date_columns` 兼容这些别名；看到摘要 `N/A` 时，应使用 `DataCatalog.latest_trade_dates()` 或 `get_latest_trade_date()` 复核，不能仅凭摘要判定缺数。事件型、静态型任务不保证有统一日度水位。

## 4. LiXinger 特殊边界

* `national_debt`、`interest_rates`、`non-ferrous-metals` 和 `crude-oil` 的日期范围接口存在边界开区间差异，Fetcher 会将请求范围前后各扩展一天，再在本地裁剪。
* `pledge_info` 对无质押数据的标的可能缺少 `last_data_date`；当前按可空日期字段处理，属于有效的无数据响应，不应直接判定任务失败。
* 强制刷新只能绕过本地 RAW 缓存，不能改变上游发布水位。若强制刷新成功但 `pledge_info` 的源端 `last_data_date` 仍较旧，应按源端发布滞后排查，并分别核对 RAW、Curated 和上游响应日期。

## 5. 发布时间窗口诊断 (Update Scheduler)

各数据源与端点的更新时间不同：
* **A 股日 K / ETF**: 北京时间 17:00 后就绪；
* **A 股每日估值 / 行业 / 资金流**: 北京时间 18:00 后就绪；
* **美股外盘 / 全球宏观**: 北京时间次日 06:00 后就绪；
* **宏观经济 (CPI/GDP/社融)**: 月度自然日更新。

诊断各端点当前就绪状态：
```bash
uv run python -m stock_data.pipeline.scheduler [--source tushare] [--date YYYY-MM-DD]
```

---

## 6. 生产宿主机 Crontab 3 波次调度模板

```crontab
# 波次 1 (工作日 17:15): A 股日 K 与场内 ETF 行情
15 17 * * 1-5 cd /Users/mac/workspace/personal/finance/stock && make sync SOURCE=tushare >> logs/cron_sync.log 2>&1

# 波次 2 (工作日 18:15): A 股每日估值、复权因子、申万行业、资金流、ETF 规模
15 18 * * 1-5 cd /Users/mac/workspace/personal/finance/stock && make sync SOURCE=tushare >> logs/cron_sync.log 2>&1

# 波次 3 (周二至周六 09:15): 美股外盘收盘行情、全球宏观、A 股融资融券
15 09 * * 2-6 cd /Users/mac/workspace/personal/finance/stock && make sync SOURCE=all >> logs/cron_sync.log 2>&1
```
