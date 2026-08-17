# 每日增量采集与定时调度指南 (Incremental Ingestion & Scheduling)

`DailySyncEngine` 提供基于水位自动嗅探（Watermark Sniffing）、发布窗口保护（Wave Routing）与多端点并发补齐的一站式增量更新服务。

---

## 1. 增量同步 CLI 指令规范

```bash
# 1. 默认一键同步当天所有已就绪端点并执行自动对账
make sync

# 2. 仅同步指定数据源或指定日期
make sync SOURCE=tushare DATE=YYYY-MM-DD
make sync SOURCE=yfinance

# 3. 强制覆盖刷新 (全数据源)
make sync SOURCE=all FORCE=1

# 4. Alpha Vantage 单并发增量 (限频保护)
make sync SOURCE=alphavantage ENDPOINT=fx_daily WORKERS=1
```

---

## 2. 理杏仁 TaskBundle 组合调度

增量同步支持将相关原子任务按业务组传入（自动展开为独立水位探测和独立审计）：

```bash
make sync SOURCE=lixinger ENDPOINT=market_bundle    # 股票与指数 K 线
make sync SOURCE=lixinger ENDPOINT=industry_bundle  # 申万 2021 成份、估值与四类行业财报
make sync SOURCE=lixinger ENDPOINT=company_bundle   # 公司基本面、财报与股权质押
make sync SOURCE=lixinger ENDPOINT=macro_bundle     # 国债、利率、有色金属、M1/M2 与社融
make sync SOURCE=lixinger ENDPOINT=index_bundle     # 指数基本面估值
```

---

## 3. 发布时间窗口诊断 (Update Scheduler)

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

## 4. 生产宿主机 Crontab 3 波次调度模板

```crontab
# 波次 1 (工作日 17:15): A 股日 K 与场内 ETF 行情
15 17 * * 1-5 cd /Users/mac/workspace/personal/finance/stock && make sync SOURCE=tushare >> logs/cron_sync.log 2>&1

# 波次 2 (工作日 18:15): A 股每日估值、复权因子、申万行业、资金流、ETF 规模
15 18 * * 1-5 cd /Users/mac/workspace/personal/finance/stock && make sync SOURCE=tushare >> logs/cron_sync.log 2>&1

# 波次 3 (周二至周六 09:15): 美股外盘收盘行情、全球宏观、A 股融资融券
15 09 * * 2-6 cd /Users/mac/workspace/personal/finance/stock && make sync SOURCE=all >> logs/cron_sync.log 2>&1
```
