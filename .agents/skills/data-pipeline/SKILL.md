---
name: data-pipeline
description: 涵盖项目全部真实数据源（TuShare、理杏仁 LiXinger、Yahoo Finance yfinance、美联储 FRED）的历史数据回填 (Backfill) 与每日增量采集 (Incremental Ingestion) 操作指南与最佳实践。包含 CLI 快捷命令、配置路由、并发控制、断点续传、数据审计对账与质量校验规则。
---

# 核心数据管道 (Data Pipeline) - 历史回填与增量采集操作指南

本技能提供项目中全部 **4 大真实数据源**（TuShare、理杏仁 LiXinger、Yahoo Finance yfinance、美联储 FRED）的历史数据全量回填（Backfill）与每日增量采集（Incremental Ingestion）的标准操作流程、CLI 命令手册、自动化路由机制与质量审计规范。

---

## 1. 架构与数据源职责分布

项目采用 **2-Tier 离线存储架构**（原始 RAW 响应快照与精炼 Curated Parquet 分层）：

| 数据源 (`data_source`) | 核心职责与涵盖数据 | 默认更新频率 | 限频规则与保护时间 | 离线存储落盘路径 |
| :--- | :--- | :--- | :--- | :--- |
| **`tushare`** | A 股全量行情、指数日线、每日估值 (PE/PB/市值)、复权因子、北向持仓、申万行业、场内基金、宏观经济 | 每日盘后 | 180次/分；北京时间 18:00 后 | `data/curated/tushare/market=CN/` |
| **`lixinger`** | 9 大核心 A 股指数基本面估值、申万 2021 行业成份股图谱、申万 31 行业历史估值序列、公司基本面 | 每日盘后 | 30次/分；单次跨度 $\le 10$ 年 | `data/curated/lixinger/market=CN/` |
| **`yfinance`** | 外盘 9 大核心指数 K 线、美股科技巨头 K 线、8 大全球宏观资产、历史拆股与分红 | 每日/事件 | 40次/分；北京时间次日 06:00 后 | `data/curated/yfinance/market=US\|GLOBAL...` |
| **`fred`** | 美联储官方宏观经济数据（基准利率、CPI、失业率、非农、GDP、美债利差、美联储资产） | 月度/季度/日线 | 120次/分；自然日历匹配 | `data/curated/fred/market=US/` |

---

## 2. 统一观察池与技术路由 (Single Source of Truth)

1. **统一自选池单一信任源**：
   - 位于 [`config/universe/watchlist.yaml`](file:///Users/mac/workspace/personal/finance/stock/config/universe/watchlist.yaml)，集中维护 A 股核心标的、10 大 A 股指数（内置官方成立基准日 `base_date`）、全球大盘指数、美股资产与 FRED 宏观序列。
2. **零配置任务自发现 (`TaskRegistry`)**：
   - 由 [`src/stock/data/task_registry.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock/data/task_registry.py) 集中管理任务技术属性（采集模式 `fetch_mode`、是否深层分区 `partitioned`、质检配置 `quality_profile`）。未显式指定 `ENDPOINT` 时，CLI 会自动自发现可用任务执行批量回填。
3. **显式单位标准化 (`UnitNormalizer`)**：
   - 彻底消灭数据源单位歧义（TuShare 成交量“手” $\rightarrow$ “股” $\times 100$；成交额“千元” $\rightarrow$ “元” $\times 1000$；市值“万元” $\rightarrow$ “元” $\times 10000$）。

---

## 3. 历史数据全量回填 (Historical Backfill)

### 3.1 统一 CLI 命令行入口
项目提供了基于 Makefile 的标准 CLI 回填入口：

```bash
make backfill START=YYYY-MM-DD END=YYYY-MM-DD SOURCE=<data_source> [ENDPOINT=<endpoint>] [SYMBOL=<symbol>]
```

---

### 3.2 四大真实数据源回填实操指南

#### ① TuShare (`SOURCE=tushare`)
用于回填 A 股行情、指数 K 线、每日估值、复权因子、申万行业行情及场内基金：

```bash
# 1. 回填 12 年 A 股 10 大核心指数 K 线 (000001.SH, 000300.SH, 399006.SZ 等)
make backfill START=2014-08-01 END=2026-08-12 SOURCE=tushare ENDPOINT=index_daily

# 2. 全市场 A 股每日估值指标全量回填 (自动按交易日并发回填，自动单位归一为元)
make backfill START=2013-01-04 END=2026-08-12 SOURCE=tushare ENDPOINT=daily_basic

# 3. 多接口单一 CLI 进程串行安全回填 (复权因子 + 每日估值 + 申万行业 + 场内基金)
make backfill START=2024-01-01 END=2026-08-12 SOURCE=tushare ENDPOINT=adj_factor,daily_basic,sw_daily,fund_daily,fund_adj

# 4. 回填自选池 A 股个股 12 年 K 线 (如贵州茅台 600519.SH)
make backfill START=2014-08-01 END=2026-08-12 SOURCE=tushare SYMBOL=600519.SH
```

#### ② 理杏仁 LiXinger (`SOURCE=lixinger`)
用于回填 9 大核心 A 股指数的 12 年基本面估值数据、申万 2021 行业成份股图谱及申万 31 个行业历史估值序列：

> ⚠️ **理杏仁 API 限制**：单次请求时间跨度不能超过 10 年。系统代码中已实现 `timedelta(days=3200)` 自动 9 年时间分片切片，无需人工分段。成份股图谱 (`sw_2021_constituents`) 自动采取单次全量超高速获取。

```bash
# 1. 回填 9 大核心指数 12 年基本面估值历史 (2014-08-01 ~ 2026-08-12)
make backfill START=2014-08-01 END=2026-08-12 SOURCE=lixinger ENDPOINT=index_fundamental

# 2. 回填申万 2021 行业成分股名册图谱 (797 个一二三级行业成份股)
make backfill SOURCE=lixinger ENDPOINT=sw_2021_constituents

# 3. 回填申万 31 个一级行业全历史基本面估值序列 (PE-TTM、PB、股息率、总市值等)
make backfill START=2014-08-01 END=2026-08-12 SOURCE=lixinger ENDPOINT=sw_2021_fundamental
```

#### ③ Yahoo Finance (`SOURCE=yfinance`)
用于回填美股巨头、外盘指数、全球宏观资产及公司行为数据：

```bash
# 1. 一键全量回填观察池（美股科技巨头 + 外盘 9 大核心指数 12 年 K 线）
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

## 4. 每日增量采集与定时调度 (Incremental Ingestion)

### 4.1 每日盘后全增量同步命令
每日收盘后，运行以下命令即可实现全数据源自动增量补全（断点自动续传）：

```bash
make run
```
或针对指定日期进行增量回填：
```bash
make backfill START=$(date +%Y-%m-%d) END=$(date +%Y-%m-%d) SOURCE=tushare
make backfill START=$(date +%Y-%m-%d) END=$(date +%Y-%m-%d) SOURCE=yfinance
```

### 4.2 自动化增量调度服务 (Scheduler)
启动后台驻留增量调度器（包含数据源收盘保护锁，防止抓取盘中半条 K 线）：

```bash
uv run python -m stock.data.update_scheduler
```

---

## 5. 数据质量校验、离线运维与统一审计

### 5.1 数据质量门禁 (Quality Gate & Quarantine)
在写入 Curated 时强阻断非法数据，将异常数据隔离记录到 `data/quarantine/`：

```bash
make validate
```

### 5.2 离线运维与数据源健康探测 (Data Ops)
测试各大数据源 API 连通性、Token 有效性与配额，或执行存量数据去重与 Schema 迁移：

```bash
# 1. 全数据源连通性与时延探针检测
make probe

# 2. 存量 Parquet 离线去重、Schema 升级与血统修补 (默认只读预览，加 APPLY=1 真实应用)
make migrate-data
make migrate-data APPLY=1
```

### 5.3 统一数据审计与对账 CLI (Audit CLI)
使用统一的 [`src/stock/cli/audit.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock/cli/audit.py) 入口调度多维度审计：

```bash
# 1. 全库主数据资产盘点审计 (物理扫描所有 Parquet 统计标的、记录数与日期覆盖)
make master-audit
# 或
make audit TYPE=master

# 2. RAW vs Curated 1-to-1 物理对账 (行数、成交量、金额精确对齐)
make audit TYPE=reconciliation

# 3. 估值指标专项对账 (daily_basic 与 stock_daily_bar 股票对齐率)
make audit TYPE=valuation

# 4. 技术因子专项对账 (adj_factor 复权因子与行业日线)
make audit TYPE=factor

# 5. 全套系联动审计
make audit TYPE=all
```

---

## 6. 故障排查与开发者最佳实践

1. **沙箱环境变量配置**：
   在限制沙箱环境下，为防止 `uv` 访问外部系统路径被拦截，须设置：
   ```bash
   export UV_CACHE_DIR=.uv_cache
   export UV_PYTHON_INSTALL_DIR=.uv_python
   ```
2. **频率限制自动休眠**：
   每个数据源均在 `config/data.yaml` 中配置了极速流与安全 Rate Limits（如 `yfinance` 40次/分，理杏仁 30次/分）。若触发限频，系统会自动休眠 60 秒并自动重试，无需人工干预。
3. **微攒批写入 (Micro-batching)**：
   全市场批量回填（如 `daily_basic`）使用 `DuckDBMarketStore.enable_batch_mode()`，在内存中按月分区分批聚合写入，消除磁盘 I/O 写放大，回填数千个交易日稳定高效。

---

## 7. 新数据接口注册标准流水线 (New Endpoint Registration Checklist)

当系统需要引入新接口（如宏观指标、期货指数、财务报表等）时，必须严格遵守 5 步注册流水线，防止路由或策略漏配：

详细开发指南参考：[`docs/guides/endpoint_registration_guide.md`](file:///Users/mac/workspace/personal/finance/stock/docs/guides/endpoint_registration_guide.md)

1. **步骤 1：Fetcher 接口元数据定义**
   在对应 Provider 的 `endpoints/` 或 `registry.py` 中实例化 `EndpointMeta`（定义 `primary_keys`、`date_columns`、`required_columns`；**切勿混入 `fetch_mode`**）。
2. **步骤 2：质量与单位 Profile 绑定**
   在 Provider 的 `_PROFILES` 字典中为新端点指定必需列、单位映射（如 `CNY100m`、`percent`）和质检 Profile。
3. **步骤 3：任务路由与分区分流 (`TaskRegistry`)**
   在 [`src/stock/data/task_registry.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock/data/task_registry.py) 中，将单表数据集加入 `non_part_datasets`，将个股遍历任务加入 `PER_SYMBOL_DATASETS`，并注册任务别名。
4. **步骤 4：调度规划器策略归类 (`BackfillPlanner`)**
   在 [`src/stock/data/planner.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock/data/planner.py) 中，将单表同步任务加入 `MARKET_SINGLE_SYNC_ENDPOINTS`，需遍历股票池的任务加入 `TUSHARE_STOCK_POOL_ENDPOINTS`。
5. **步骤 5：自动化门禁验证**
   执行 `uv run pytest tests/unit/data/ --no-cov` 与 `make lint` 确保 100% 通过。
