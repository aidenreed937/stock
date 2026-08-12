---
name: data-pipeline
description: 涵盖项目全部真实数据源（TuShare、理杏仁 LiXinger、Yahoo Finance yfinance、美联储 FRED）的历史数据回填 (Backfill) 与每日增量采集 (Incremental Ingestion) 操作指南与最佳实践。包含 CLI 快捷命令、配置路由、并发控制、断点续传、数据审计对账与质量校验规则。
---

# 核心数据管道 (Data Pipeline) - 历史回填与增量采集操作指南

本技能提供项目中全部 **4 大真实数据源**（TuShare、理杏仁 LiXinger、Yahoo Finance yfinance、美联储 FRED）的历史数据全量回填（Backfill）与每日增量采集（Incremental Ingestion）的标准操作流程、CLI 命令手册、自动化路由机制与质量审计规范。

---

## 1. 架构与数据源职责分布

项目采用 **2-Tier 离线存储架构**（原始 Raw 缓存与精炼 Curated Parquet 分层）：

| 数据源 (`data_source`) | 核心职责与涵盖数据 | 默认更新频率 | 限频规则与保护时间 | 离线存储落盘路径 |
| :--- | :--- | :--- | :--- | :--- |
| **`tushare`** | A 股全量元数据、A 股大盘指数 K 线、A 股每日估值、重点观察股 K 线 | 每日盘后 | 180次/分；北京时间 18:00 后 | `data/curated/tushare/market=CN/` |
| **`lixinger`** | 9 大核心 A 股指数基本面估值（等权/市值加权 PE-TTM、PB、股息率、市值） | 每日盘后 | 30次/分；单次跨度 $\le 10$ 年 | `data/curated/lixinger/market=CN/` |
| **`yfinance`** | 外盘 9 大指数 K线、美股 7 巨头 K线、8 大全球宏观资产、分红拆股、企财三表 | 每日/事件/季度 | 40次/分；北京时间次日 06:00 后 | `data/curated/yfinance/market=US\|GLOBAL\|JP\|HK...` |
| **`fred`** | 美联储官方宏观经济数据（基准利率、CPI、失业率、非农、GDP、美债利差、美联储资产） | 月度/季度/日线 | 120次/分；自然日历匹配 | `data/curated/fred/market=US/` |

---

## 2. 历史数据全量回填 (Historical Backfill)

### 2.1 统一 CLI 命令行入口
项目提供了基于 Makefile 的标准 CLI 回填入口：

```bash
make backfill START=YYYY-MM-DD END=YYYY-MM-DD SOURCE=<data_source> [ENDPOINT=<endpoint>] [SYMBOL=<symbol>]
```

---

### 2.2 四大真实数据源回填实操指南

#### ① TuShare (`SOURCE=tushare`)
用于回填 A 股元数据、指数日线 K 线及每日估值数据：

```bash
# 1. 回填 12 年 A 股 10 大核心指数 K 线与每日估值 (000001.SH, 000300.SH, 399006.SZ 等)
make backfill START=2014-08-01 END=2026-08-12 SOURCE=tushare ENDPOINT=index_daily

# 2. 回填 12 年指数每日估值 (PE-TTM, PB, 股息率)
make backfill START=2014-08-01 END=2026-08-12 SOURCE=tushare ENDPOINT=index_dailybasic

# 3. 回填指定 A 股个股 12 年 K 线 (如贵州茅台 600519.SH)
make backfill START=2014-08-01 END=2026-08-12 SOURCE=tushare SYMBOL=600519.SH
```

#### ② 理杏仁 LiXinger (`SOURCE=lixinger`)
用于回填 9 大核心 A 股指数的 12 年基本面估值数据（等权 PE、市值加权 PE 等）：

> ⚠️ **理杏仁 API 限制**：单次请求时间跨度不能超过 10 年。系统代码中已实现 `timedelta(days=3200)` 自动 9 年时间分片切片，无需人工分段。

```bash
# 回填 9 大核心指数 12 年基本面估值历史 (2014-08-01 ~ 2026-08-12)
make backfill START=2014-08-01 END=2026-08-12 SOURCE=lixinger ENDPOINT=index_fundamental
```

#### ③ Yahoo Finance (`SOURCE=yfinance`)
用于回填美股巨头、外盘指数、全球宏观资产及公司行为数据：

```bash
# 1. 一键全量回填观察池（美股 7 巨头 + 外盘 9 大核心指数 12 年 K 线）
make backfill START=2014-08-01 END=2026-08-12 SOURCE=yfinance

# 2. 回填 8 大全球宏观资产 12 年历史 (美债10年/3月、美元指数、离岸人民币、黄金、原油、铜、VIX)
make backfill START=2014-08-01 END=2026-08-12 SOURCE=yfinance ENDPOINT=macro_indicators

# 3. 回填指定美股 (如 NVDA) 12 年历史 K 线
make backfill START=2014-08-01 END=2026-08-12 SOURCE=yfinance SYMBOL=NVDA

# 4. 回填美股历史拆股 (splits) 与派息 (dividends) 记录
make backfill SOURCE=yfinance ENDPOINT=splits SYMBOL=NVDA
make backfill SOURCE=yfinance ENDPOINT=dividends SYMBOL=AAPL
```

#### ④ 美联储 FRED (`SOURCE=fred`)
用于回填美联储官方 7 大核心宏观经济指标（美联储利率、CPI、失业率、非农、GDP、美债 10Y-2Y 利差、美联储总资产）：

```bash
# 1. 一键全量回填 FRED 7 大核心宏观指标 12 年历史
make backfill START=2014-08-01 END=2026-08-12 SOURCE=fred

# 2. 回填指定的单个宏观指标 (如美联储有效利率 FEDFUNDS)
make backfill SOURCE=fred SYMBOL=FEDFUNDS START=2014-08-01 END=2026-08-12
```

---

## 3. 每日增量采集与定时调度 (Incremental Ingestion)

### 3.1 每日盘后全增量同步命令
每日收盘后，运行以下命令即可实现全数据源自动增量补全（断点自动续传）：

```bash
make run
```
或针对当天日期进行增量回填：
```bash
make backfill START=$(date +%Y-%m-%d) END=$(date +%Y-%m-%d) SOURCE=tushare
make backfill START=$(date +%Y-%m-%d) END=$(date +%Y-%m-%d) SOURCE=yfinance
```

### 3.2 自动化增量调度服务 (Scheduler)
启动后台驻留增量调度器（包含数据源收盘保护锁，防止抓取盘中半条 K 线）：

```bash
uv run python -m stock.data.update_scheduler
```

---

## 4. 数据审计、校验与对账规范

在完成回填或增量采集后，必须执行质量验证门禁：

### 4.1 数据质量校验 (Quality Gate)
检查是否存在非法负价格、最高价低于最低价、缺失必需列等问题：

```bash
make validate
```

### 4.2 数据源健康探测 (Source Probe)
测试各大数据源 API 连通性、Token 有效性与配额：

```bash
make probe
```

### 4.3 跨数据源估值百分位对账 (Cross-Source Audit)
对比 TuShare vs 理杏仁关于相同指数（如沪深 300、创业板指）的 10 年 PE-TTM 分位对齐度：

```bash
make audit
```

### 4.4 物理落盘全库审计脚本
运行 Polars 脚本物理扫描全库 300+ 个 Parquet 文件，输出全量存储清单：

```bash
uv run python -c "
import polars as pl
from pathlib import Path

files = list(Path('data/curated').rglob('*.parquet'))
records = []
for f in files:
    try:
        df = pl.read_parquet(f)
        src = f.parts[2] if len(f.parts) > 2 else 'unknown'
        dataset = f.parts[4] if len(f.parts) > 4 else f.stem
        records.append({
            'source': src,
            'dataset': dataset,
            'rows': len(df),
            'symbols': df['symbol'].n_unique() if 'symbol' in df.columns else 1,
            'min_date': str(df['trade_date'].min())[:10] if 'trade_date' in df.columns else 'N/A',
            'max_date': str(df['trade_date'].max())[:10] if 'trade_date' in df.columns else 'N/A',
        })
    except Exception:
        pass

df_rec = pl.DataFrame(records)
print(df_rec.group_by(['source', 'dataset']).agg(
    pl.col('symbols').max().alias('标的数'),
    pl.col('rows').sum().alias('总记录行数'),
    pl.col('min_date').min().alias('最早交易日'),
    pl.col('max_date').max().alias('最新交易日'),
).sort(['source', 'dataset']))
"
```

---

## 5. 故障排查与开发者最佳实践

1. **沙箱环境变量配置**：
   在限制沙箱环境下，为防止 `uv` 访问外部系统路径被拦截，须设置：
   ```bash
   export UV_CACHE_DIR=.uv_cache
   export UV_PYTHON_INSTALL_DIR=.uv_python
   ```
2. **频率限制自动休眠**：
   每个数据源均在 `config/data.yaml` 中配置了极速流与安全 Rate Limits（如 `yfinance` 40次/分，理杏仁 30次/分）。若触发限频，系统会自动休眠 60 秒并自动重试，无需人工干预。
3. **单标的 1 次全量请求优化**：
   按标的采集（如 `history` / `global_index_daily` / `fred`）时，系统自动切换为整段范围单次请求模式，规避切分为 145 个月度小批次导致的频次卡顿。
