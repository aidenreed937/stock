# 五大数据源历史全量回填实操指南 (Backfill Recipes)

统一 CLI 回填命令规范：
```bash
make backfill START=YYYY-MM-DD END=YYYY-MM-DD SOURCE=<data_source> [ENDPOINT=<endpoint>] [SYMBOL=<symbol>] [FORCE_REFRESH=1]
```

---

## 1. TuShare (`SOURCE=tushare`)

* **数据特性**：A 股全市场行情、指数、估值、复权因子、北向、申万行业、场内基金与宏观。
* **限频规则**：180 次/分；北京时间 18:00 后收盘数据就绪。

```bash
# 1. 回填 12 年 A 股 10 大核心指数 K 线 (底层 API: index_daily)
make backfill START=2014-08-01 END=2026-08-14 SOURCE=tushare ENDPOINT=index_daily_bar

# 2. 全市场 A 股每日估值指标全量回填 (自动按交易日并发，自动单位归一为元)
make backfill START=2013-01-04 END=2026-08-14 SOURCE=tushare ENDPOINT=daily_basic

# 3. 回填申万行业历史成分股流水与分类标准 (一次落盘)
make backfill SOURCE=tushare ENDPOINT=index_member,index_classify

# 4. 回填全市场 2020 年至今券商研报一致预期盈利预测
make backfill START=2020-01-01 END=2026-08-14 SOURCE=tushare ENDPOINT=report_rc

# 5. 回填 2020 年至今上市公司业绩预告与业绩快报 (自动启用全市场通道)
make backfill START=2020-01-01 END=2026-08-14 SOURCE=tushare ENDPOINT=forecast,express

# 6. 回填 26 只核心 ETF 全历史行情、复权与份额
make backfill START=2005-01-01 END=2026-08-14 SOURCE=tushare ENDPOINT=fund_daily,etf_share_size,fund_adj SYMBOL=watchlist FORCE_REFRESH=1

# 7. 回填可转债、公司行为事件
make backfill START=YYYY-MM-DD END=YYYY-MM-DD SOURCE=tushare ENDPOINT=cb_basic,cb_daily,stk_holdertrade,repurchase,block_trade

# 8. 回填期权静态合约与日行情（用于 PCR/成交观察及结算价波动率代理）
make backfill START=YYYY-MM-DD END=YYYY-MM-DD SOURCE=tushare ENDPOINT=opt_basic,opt_daily

# 9. 回填全市场前十大流通股东 (按自然季度报告期自动批量并发调度)
make backfill START=2020-01-01 END=2026-08-14 SOURCE=tushare ENDPOINT=top10_floatholders
```

---

## 2. 理杏仁 LiXinger (`SOURCE=lixinger`)

* **数据特性**：指数基本面估值、申万 2021 行业图谱与估值、行业四大财报、国债收益率与社融。
* **限频与限制**：30 次/分；单次请求跨度 $\le 10$ 年（系统内部已内建 9 年时间分片自动切片）。

```bash
# 1. 回填 9 大核心指数 12 年基本面估值 (2014-08-01 ~ 2026-08-14)
make backfill START=2014-08-01 END=2026-08-14 SOURCE=lixinger ENDPOINT=index_fundamental

# 2. 回填申万 2021 行业成份股名册图谱 (797 个一二三级行业成份股)
make backfill SOURCE=lixinger ENDPOINT=sw_2021_constituents

# 3. 回填申万 31 个一级与 162 个二级行业全历史估值序列
make backfill START=2014-08-01 END=2026-08-14 SOURCE=lixinger ENDPOINT=sw_2021_fundamental,sw_2021_l2_fundamental

# 4. 回填申万行业四大专属合并财务报表 (2020 年至今非金融/银行/证券/保险)
make backfill START=2020-01-01 END=2026-08-14 SOURCE=lixinger ENDPOINT=sw_2021_fs_non_financial,sw_2021_fs_bank,sw_2021_fs_security,sw_2021_fs_insurance
```

---

## 3. Yahoo Finance (`SOURCE=yfinance`)

* **数据特性**：外盘 9 大核心指数、美股科技巨头、7 大全球宏观资产（美债、美元指数、黄金、原油、铜、VIX）。
* **限频与限制**：40 次/分；北京时间次日 06:00 后就绪。

```bash
# 1. 一键全量回填观察池（美股科技巨头 + 外盘 9 大核心指数 12 年 K 线）
make backfill START=2014-08-01 END=2026-08-12 SOURCE=yfinance

# 2. 回填 7 大全球宏观资产 12 年历史
make backfill START=2014-08-01 END=2026-08-12 SOURCE=yfinance ENDPOINT=macro_indicators

# 3. 回填美股历史拆股 (splits) 与派息 (dividends)
make backfill SOURCE=yfinance ENDPOINT=splits SYMBOL=NVDA
make backfill SOURCE=yfinance ENDPOINT=dividends SYMBOL=AAPL
```

---

## 4. 美联储 FRED (`SOURCE=fred`)

* **数据特性**：美联储官方宏观序列（基准利率 FEDFUNDS、CPIAUCSL、失业率 UNRATE、非农 PAYEMS、GDP、美债利差 T10Y2Y、美联储资产 WALCL）。
* **限频与日历**：120 次/分；自然日历匹配。

```bash
# 1. 一键全量回填 FRED 7 大核心宏观指标 12 年历史
make backfill START=2014-08-01 END=2026-08-12 SOURCE=fred

# 2. 回填指定的单个宏观指标
make backfill SOURCE=fred SYMBOL=FEDFUNDS START=2014-08-01 END=2026-08-12
```

---

## 5. Alpha Vantage (`SOURCE=alphavantage`)

* **数据特性**：USD/CNH 外汇日线（补齐 Yahoo `CNH=X` 缺口）。
* **限频与模式**：免费版 5 次/分；强制单线程。

```bash
export ALPHA_VANTAGE_API_KEY='你的真实API_KEY'
make backfill START=2014-08-01 END=2026-08-14 SOURCE=alphavantage ENDPOINT=fx_daily SYMBOL='CNH=X' FORCE_REFRESH=1
```

## 6. 回填后的真实数据验收

回填完成后按以下顺序验收；`backfill-accept` 只读检查 RAW 与 Curated 的范围、主键和可解释缺口，不替代质量门禁：

```bash
make backfill-accept ENDPOINT=stock_daily_bar SOURCE=tushare START=YYYY-MM-DD END=YYYY-MM-DD
make features-build TARGET=domain_marts START=YYYY-MM-DD END=YYYY-MM-DD
make validate
make master-audit
make audit TYPE=all
make features-build TARGET=all START=YYYY-MM-DD END=YYYY-MM-DD
make scan DATE=YYYY-MM-DD FORMAT=markdown
```

领域 Mart 的输入数据集缺失时，构建器应保持稳定 Schema 并输出空结果；验收报告必须区分“上游无数据”“质量隔离”“合法主键去重”和“未解释丢失”。
