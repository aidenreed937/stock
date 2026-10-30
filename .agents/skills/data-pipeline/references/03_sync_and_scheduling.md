# 每日增量采集与定时调度指南 (Incremental Ingestion & Scheduling)

`DailySyncEngine` 提供基于水位自动嗅探（Watermark Sniffing）、发布窗口保护（Wave Routing）与多端点并发补齐的一站式增量更新服务。`SOURCE=all` 覆盖 TuShare、LiXinger、FRED、Alpha Vantage 和 Industry，永久排除 yfinance；yfinance 仍可显式单独同步。跨源并发度按 `source_workers` 配置控制。

---

## 1. 增量同步 CLI 指令规范

```bash
# 1. 默认一键同步当天所有已就绪端点并执行自动对账
make sync

# 2. 仅同步指定数据源或指定日期
make sync SOURCE=tushare DATE=YYYY-MM-DD
make sync SOURCE=lixinger
make sync SOURCE=yfinance

# 3. 强制覆盖刷新 (日常同步源，不含 yfinance)
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
make sync SOURCE=lixinger ENDPOINT=industry_bundle  # 申万 2021 成份与估值
make sync SOURCE=lixinger ENDPOINT=industry_financial_bundle  # 申万季度合并财报（报告期批量请求）
make sync SOURCE=lixinger ENDPOINT=company_bundle   # 公司基本面、财报与股权质押
make sync SOURCE=lixinger ENDPOINT=macro_daily_bundle,macro_monthly_bundle  # 国债、利率、投资者与宏观序列
make sync SOURCE=lixinger ENDPOINT=index_fundamental                     # 指数基本面估值（原子任务）
# 个股风险接口按需执行，默认仅使用 LiXinger 观察池
make sync SOURCE=lixinger ENDPOINT=regulatory_measures
make sync SOURCE=lixinger ENDPOINT=exchange_inquiry
make sync SOURCE=lixinger ENDPOINT=unlock_summary
```

LiXinger 不再注册历史别名 `macro_bundle` 和 `index_bundle`。宏观数据使用 `macro_daily_bundle`、`macro_monthly_bundle`，指数基本面直接使用原子任务 `index_fundamental`，并维护独立水位和失败状态。申万季度合并财报使用独立的 `industry_financial_bundle`，不再混入 `industry_bundle`。监管措施、交易所问询和限售解禁任务为显式任务，不进入未指定端点的默认同步；监管措施和问询函仅按观察池股票执行。

---

## 3. 水位、发布时间窗口与 RAW 缓存

未指定 `ENDPOINT` 时，`make sync SOURCE=lixinger` 会通过 `public_tasks.py` / `task_catalog.py` 展开默认公开原子任务；高消耗风险任务虽已注册，但被标记为显式任务，不会自动展开。指定风险端点或 bundle 时才执行，并独立计算 Curated 水位、增量区间和失败状态。

单任务的计划状态遵循以下语义：

| 计划状态 | 判定 | 上游 HTTP 请求 |
| :--- | :--- | :---: |
| `UP_TO_DATE` | 普通任务的 Curated 水位已覆盖目标日/期间 | 否 |
| `SKIPPED` | 发布时间窗口未到、交易日历不可用或任务被配置停用 | 否 |
| `PENDING` | 水位存在缺口、首次同步尚无水位，或事件任务到了滚动刷新窗口 | 普通任务先查 RAW 缓存；事件刷新任务绕过 RAW |

### 显式目标日、自动回退与同步后验收

`DATE` 的语义取决于是否显式传入：

- `make sync SOURCE=tushare DATE=2026-09-04` 表示只请求 `2026-09-04`。如果该日尚未过发布时间窗口，会得到 `SKIPPED`，不会自动改为请求 `2026-09-03`；
- 日常定时任务应省略 `DATE`，例如 `make sync SOURCE=tushare`，让调度器按交易日历和端点发布时间自动选择最近已就绪交易日；
- 运行日为 `2026-09-04` 但需补齐前一交易日时，应明确使用 `make sync SOURCE=tushare DATE=2026-09-03`；
- 可先用 `UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_data.pipeline.scheduler --source tushare --date 2026-09-04` 查看端点就绪状态。

同步命令正常退出只表示没有 `FAILED` 任务，不等于目标日已落盘。同步后必须核对任务状态和关键数据集的实际最新水位，并将其记录为下游的 `effective_as_of`。只有关键输入达到该有效基准日，才执行 `make features-build TARGET=domain_marts` 或宏观风险管线；否则应先补数，或在报告中明确使用的实际基准日。

待执行任务默认启用 RAW 缓存；缓存覆盖目标日期和标的时直接复用，跳过网络请求。TuShare `stk_holdertrade`、`repurchase`、`block_trade`、`share_float` 在发布窗口后每天刷新，分别最多回看 31/31/5/31 天，并按本地业务水位收窄日常请求区间；`FORCE=1` 仍可关闭普通任务 RAW 缓存并绕过发布时间窗口。

日频任务通常从 Curated 水位次日开始，月频/季频任务推进到下一业务期间。历史兼容表的 `date`/`Date` 会在 Curated 加载时归一为 `trade_date`，水位扫描按 `TaskSpec.date_columns` 兼容这些别名；看到摘要 `N/A` 时，应使用 `DataCatalog.latest_trade_dates()` 或 `get_latest_trade_date()` 复核，不能仅凭摘要判定缺数。事件型、静态型任务不保证有统一日度水位。

### 季度财报与前十大流通股东全市场任务

TuShare `income`、`fina_indicator`、`balancesheet`、`cashflow` 及 `top10_floatholders` 属于
`fetch_mode=per_period` 的全市场批量任务。`financial_statement_bundle` 展开后仍逐个原子任务维护
水位与失败状态：

- 目标日期解析为目标日前最近已完成季度末，不能按交易日逐日推进；
- `top10_floatholders` 具有**双模采集特性**：回填多季度历史时走 `period` 全市场季度并发通道；日度常规增量（`make sync DATE=YYYY-MM-DD`）时自动按当日公告日期（`ann_date`）单次秒级拉取当天新披露公司；
- 报告期水位等于当前目标期末时，计划仍可标记为“待刷新报告期”，同步会刷新 RAW，吸收后续重述；
- 这些任务自动读取 Curated `stock_basic` 股票池，禁止退化成核心 `watchlist`；
- 公开 CLI 只传 `income` 等项目任务名，不传 `income_vip` 等底层内部 API 名；
- 回填/同步返回后由业务日期裁剪器按 `end_date` 季度裁剪，验收按源端注册复合主键检查重复和缺口。

若财报或股东数据水位不动但希望确认源端修订，应查看计划中的 `refresh_raw_cache`/报告期刷新状态以及 RAW
写入时间，不要盲目把日频 `FORCE=1` 规则套到报告期任务上。

## 4. LiXinger 特殊边界

* `national_debt`、`interest_rates`、`non-ferrous-metals` 和 `crude-oil` 的日期范围接口存在边界开区间差异，Fetcher 会将请求范围前后各扩展一天，再在本地裁剪。
* `pledge_info` 对无质押数据的标的可能缺少 `last_data_date`；当前按可空日期字段处理，属于有效的无数据响应，不应直接判定任务失败。
* 强制刷新只能绕过本地 RAW 缓存，不能改变上游发布水位。若强制刷新成功但 `pledge_info` 的源端 `last_data_date` 仍较旧，应按源端发布滞后排查，并分别核对 RAW、Curated 和上游响应日期。
* 申万季度财报任务使用已完成季度末作为报告期水位；历史回填按季度末拆分原子任务，单报告期通过 `date + stockCodes` 批量请求，行业代码按每批最多 100 个拆分。理杏仁已经返回行业内公司合并结果，Fetcher 不做本地公司级聚合。
* 当前申万行业目录将 `security` / `insurance` 的可用根节点挂在二级；一级财报任务在缺少一级节点时会自动选择对应根代码 `490100` / `490200`，二级财报任务仍按二级明细代码请求。若根代码也缺失，才报告目录映射错误，不应把该失败归因于限流。

## 5. 发布时间窗口诊断 (Update Scheduler)

各数据源与端点的更新时间不同：
* **A 股日 K / ETF**: 北京时间 17:00 后就绪；
* **A 股每日估值 / 行业 / 资金流**: 北京时间 18:00 后就绪；
* **美股外盘 / 全球宏观**: 北京时间次日 06:00 后就绪；
* **宏观经济 (CPI/GDP/社融)**: 月度自然日更新。

诊断各端点当前就绪状态：
```bash
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -m stock_data.pipeline.scheduler [--source tushare] [--date YYYY-MM-DD]
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

# 波次 4 (周二至周六 12:15): FRED VIX 收盘序列延迟发布复查
15 12 * * 2-6 cd /Users/mac/workspace/personal/finance/stock && make sync SOURCE=fred ENDPOINT=VIXCLS >> logs/cron_sync.log 2>&1
```

> FRED `VIXCLS` 按 T+1、23:00 `America/New_York` 判断发布就绪；12:15 `Asia/Shanghai` 的复查波次覆盖夏令时和冬令时。FRED 对不同页面/CSV 的更新可能有短暂时差，CBOE 只承诺每日更新，不保证固定发布时间。

> `SOURCE=all` 不会触发 yfinance。Yahoo Finance 任务仅在需要时显式运行，例如
> `make sync SOURCE=yfinance ENDPOINT=stock_daily_bar,index_daily_bar`。
