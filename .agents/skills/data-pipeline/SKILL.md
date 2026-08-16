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
   - CLI 的 `ENDPOINT` 应使用项目任务名（如 `index_daily_bar`），不要直接使用上游 API 名（如 TuShare `index_daily`）；API 名只存在于 `TaskSpec.api_name` 路由层。
3. **显式单位标准化 (`UnitNormalizer`)**：
   - 彻底消灭数据源单位歧义（TuShare 成交量“手” $\rightarrow$ “股” $\times 100$；成交额“千元” $\rightarrow$ “元” $\times 1000$；市值“万元” $\rightarrow$ “元” $\times 10000$）。
   - 单位处理遵循 **RAW 保真、Curated 标准单位、分析层无倍率**：RAW 只保存 API 原始字段和原始单位；所有金额、成交量、市值等单位转换只能在 `UnitNormalizer` 所在的 RAW -> Curated 清洗链路执行；Curated 是下游唯一消费契约，分析指标、因子、回测和扫描代码不得再写 `* 10000`、`* 1_000_000` 等数据源倍率。

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
用于回填 A 股行情、指数 K 线、每日估值、复权因子、申万行业行情、成分流水、卖方研报及业绩预告/快报：

```bash
# 1. 回填 12 年 A 股 10 大核心指数 K 线 (底层 TuShare API: index_daily)
make backfill START=2014-08-01 END=2026-08-14 SOURCE=tushare ENDPOINT=index_daily_bar

# 2. 全市场 A 股每日估值指标全量回填 (自动按交易日并发回填，自动单位归一为元)
make backfill START=2013-01-04 END=2026-08-14 SOURCE=tushare ENDPOINT=daily_basic

# 3. 回填申万行业历史成分股流水与分类标准 (零前瞻偏差基石，一次落盘)
make backfill SOURCE=tushare ENDPOINT=index_member,index_classify

# 4. 回填全市场 2020 年至今券商研报卖方盈利预测 (支持行业预期上修比例聚合)
make backfill START=2020-01-01 END=2026-08-14 SOURCE=tushare ENDPOINT=report_rc

# 5. 回填全市场 2020 年至今上市公司业绩预告与业绩快报 (自动启用 VIP 全市场通道，秒级完成)
make backfill START=2020-01-01 END=2026-08-14 SOURCE=tushare ENDPOINT=forecast
make backfill START=2020-01-01 END=2026-08-14 SOURCE=tushare ENDPOINT=express

# 6. 多接口单一 CLI 进程串行安全回填 (复权因子 + 每日估值 + 申万行业 + 场内基金)
make backfill START=2024-01-01 END=2026-08-14 SOURCE=tushare ENDPOINT=adj_factor,daily_basic,sw_daily,fund_daily,fund_adj

# 7. 回填自选池 A 股个股 12 年 K 线 (如贵州茅台 600519.SH)
make backfill START=2014-08-01 END=2026-08-14 SOURCE=tushare SYMBOL=600519.SH
```

#### ② 理杏仁 LiXinger (`SOURCE=lixinger`)
用于回填 9 大核心 A 股指数的 12 年基本面估值、申万 2021 行业成份股图谱、一级/二级行业估值序列及四大专属行业合并财务报表：

> ⚠️ **理杏仁 API 限制**：单次请求时间跨度不能超过 10 年。系统代码中已实现 `timedelta(days=3200)` 自动 9 年时间分片切片，无需人工分段。行业代码已实现动态全谱映射，无硬编码。

```bash
# 1. 回填 9 大核心指数 12 年基本面估值历史 (2014-08-01 ~ 2026-08-14)
make backfill START=2014-08-01 END=2026-08-14 SOURCE=lixinger ENDPOINT=index_fundamental

# 2. 回填申万 2021 行业成分股名册图谱 (797 个一二三级行业成份股)
make backfill SOURCE=lixinger ENDPOINT=sw_2021_constituents

# 3. 回填申万 31 个一级与 134 个二级行业全历史估值序列 (PE-TTM、PB、股息率、总市值等)
make backfill START=2014-08-01 END=2026-08-14 SOURCE=lixinger ENDPOINT=sw_2021_fundamental,sw_2021_l2_fundamental

# 4. 回填申万 31 行业四大专属合并财务报表 (2020 年至今非金融/银行/证券/保险)
make backfill START=2020-01-01 END=2026-08-14 SOURCE=lixinger ENDPOINT=sw_2021_fs_non_financial,sw_2021_fs_bank,sw_2021_fs_security,sw_2021_fs_insurance
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

### 4.2 更新时间窗口就绪诊断与调度保护 (Update Scheduler)
各数据源发布时间窗口不同（如 A 股日 K 为 17:00、估值指标为 18:00、美股历史为次日 06:00）。`DataUpdateScheduler` 在回填与增量时自动作为前置收盘保护锁，防止抓取盘中半条数据或未就绪截面。

运行以下命令可诊断各数据源端点当前的就绪状态：

```bash
uv run python -m stock.data.update_scheduler [--source tushare] [--date YYYY-MM-DD]
```

### 4.3 一键极速增量同步与自动化调度 (Fast Daily Sync)
增量引擎 `DailySyncEngine` 会自动探测本地落盘最新交易日（Watermark），识别时间发布窗口，多端点并发补齐缺口，并在完成后自动运行对账审计。`per_symbol` 任务会按观察池展开标的，并按单标的水位与 `base_date` 规划；执行结果只要出现 `FAILED` 或 `NO_DATA`，CLI 即以失败退出，防止空跑被误判成功。

#### 1. 统一 CLI 与 Makefile 入口
```bash
# 1. 默认一键同步当天所有已就绪端点并对账
make sync

# 2. 补齐指定数据源或指定日期缺口
make sync SOURCE=tushare DATE=YYYY-MM-DD

# 3. 全数据源一键增量并强制覆盖刷新
make sync SOURCE=all FORCE=1
```

#### 2. LiXinger TaskBundle 调度
增量同步支持将相关原子任务按组传入。bundle 只在计划入口展开，展开后每个子任务仍独立探测水位、执行、失败重试、路由、落盘和审计：

```bash
# 行情：股票与指数 K 线
make sync SOURCE=lixinger ENDPOINT=market_bundle

# 行业：申万 2021 成份、估值与四类行业财报
make sync SOURCE=lixinger ENDPOINT=industry_bundle

# 公司：公司基本面、四类财报与质押
make sync SOURCE=lixinger ENDPOINT=company_bundle

# 宏观：国债、利率、有色金属与原油
make sync SOURCE=lixinger ENDPOINT=macro_bundle

# 指数：指数基本面估值
make sync SOURCE=lixinger ENDPOINT=index_bundle
```

当前 bundle 名只用于增量同步调度，不会出现在公开原子 task 列表，也不会合并子任务的数据集或水位。

#### 3. 宿主机标准 Crontab 调度模板 (分时 3 波次)
量化系统采用无状态定时唤起，通过 Crontab 配置 3 波次同步任务：
```crontab
# 波次 1 (工作日 17:15): A 股日 K 与场内 ETF 行情
15 17 * * 1-5 cd /Users/mac/workspace/personal/finance/stock && make sync SOURCE=tushare >> logs/cron_sync.log 2>&1

# 波次 2 (工作日 18:15): A 股每日估值、复权因子、申万行业、资金流、ETF 规模
15 18 * * 1-5 cd /Users/mac/workspace/personal/finance/stock && make sync SOURCE=tushare >> logs/cron_sync.log 2>&1

# 波次 3 (周二至周六 09:15): 美股外盘收盘行情、全球宏观、A 股融资融券
15 09 * * 2-6 cd /Users/mac/workspace/personal/finance/stock && make sync SOURCE=all >> logs/cron_sync.log 2>&1
```

---

## 5. 数据质量校验、离线运维与统一审计

### 5.1 数据质量门禁 (Quality Gate & Quarantine)
清洗阶段会将可归因异常记录写入 `data/quarantine/`；存储与读取阶段对来源、日期、标的交集和 `schema_version="v2"` 执行 fail-closed 校验：

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
4. **Curated schema 演进（所有数据源通用）**：
   TuShare、LiXinger、Yahoo Finance、FRED 的 Curated 写入都会经过统一 Parquet 写入器。凡是已有 `data.parquet` 非空，后续新增或删除业务列，都可能触发 schema 校验。扩展宽表字段时，除源端 registry/default fields 外，必须同步清洗规则、单位/标准化、审计字段、写入器 schema 兼容和单测。若回填已成功拉取并清洗，但提交时报：
   ```text
   Curated 文件 [...] schema 不匹配: 已有列 [...]，新数据列 [...]
   ```
   这是旧 Parquet schema 与新业务列集合不一致，不是 API 拉取失败。优先在 `src/stock/data/storage/partition_writer.py` 为该数据集的**已知合法新增列**做受控对齐，或执行显式迁移；不要删除现有 Parquet 后重跑。若差异来自历史残留的冗余身份列（例如全市场单行时间序列历史上带有固定 `symbol`，新数据按真实主键只保留 `trade_date`），优先在 `src/stock/data/storage/compat.py` 的 `StorageCompat.post_process_dataset()` 为该数据集做确定性后处理，不要把冗余列加入写入器通用白名单。修复后可直接重跑同一条 `make backfill ... FORCE_REFRESH=1`。案例：`index_fundamental` 新增 `pe_ttm.mcw/pb.mcw/ps_ttm.mcw/dyr.mcw` 时，需要允许这些已知估值列从旧 schema 平滑补空合并；`moneyflow_hsgt` 历史 Curated 带 dummy `symbol` 而新数据不带时，应在 `StorageCompat.post_process_dataset("moneyflow_hsgt", ...)` 统一删除冗余 `symbol`。
5. **单位口径修复与新增接口防遗漏**：
   - 新增或修复 endpoint 时，先核验上游真实单位，再同步更新 Provider registry 的字段单位声明与 `src/stock/data/normalizer/unit_normalizer.py` 的显式倍率规则。
   - RAW 不做乘法，不为分析便利改历史原值；已有错误 Curated 必须从 RAW 全历史重放，只重建 Curated。
   - Curated 金额字段统一为元，成交量统一为股/份，市值统一为元；`market`、`currency`、`exchange` 等 metadata 必须在入库后满足数据集契约。
   - 分析层只做聚合、比值、窗口统计和业务语义计算，不得根据数据源字段名补乘或补除倍率。若发现分析层出现 `* 10000`、`* 1_000_000` 等源口径修正，优先回到入库清洗层修复。
   - 回填验收除行数、主键、日期外，必须抽样验证 RAW 原值到 Curated 标准单位的倍率是否正确。例如 `moneyflow` 为 TuShare “万元”乘 `10000`，`moneyflow_hsgt` 为 TuShare “百万元”乘 `1_000_000`，`stock_daily_bar.amount` 为“千元”乘 `1000`。
6. **LiXinger 403 权限/次数异常**：
   若返回 `403` 且消息包含 `Exceed maximum access time, please purchase Open API.`，按理杏仁开放平台权限或访问次数耗尽处理。最多在用户明确要求时重试一次；若仍为 403，不要循环重试，直接报告需要恢复 API 权限/额度。
7. **字段扩展回填后的落盘核验**：
   回填成功后，用本地 Curated Parquet 核验行数、日期范围和新增字段非空数，避免只看到命令成功但字段为空：
   ```bash
   UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -c 'import polars as pl; p="data/curated/<source>/market=<market>/<dataset>/data.parquet"; df=pl.read_parquet(p); cols=["<new_col_1>","<new_col_2>"]; d=next((c for c in ["trade_date","date","end_date"] if c in df.columns), None); print("rows", len(df)); print("date_range", (df[d].min(), df[d].max()) if d else None); print("columns", [c for c in cols if c in df.columns]); print("non_null", {c: df[c].drop_nulls().len() for c in cols if c in df.columns})'
   ```

---

## 7. 新数据接口注册标准流水线 (New Endpoint Registration Checklist)

当系统需要引入新接口（如宏观指标、期货指数、财务报表等）时，必须严格遵守 5 步注册流水线，防止路由或策略漏配：

详细开发指南参考：[`docs/guides/endpoint_registration_guide.md`](file:///Users/mac/workspace/personal/finance/stock/docs/guides/endpoint_registration_guide.md)

1. **步骤 1：Fetcher 接口元数据定义**
   在对应 Provider 的 `endpoints/` 或 `registry.py` 中实例化 `EndpointMeta`（定义 `primary_keys`、`date_columns`、`required_columns`；**切勿混入 `fetch_mode`**）。
2. **步骤 2：质量与单位 Profile 绑定**
   在 Provider 的 `_PROFILES` 字典中为新端点指定必需列、单位映射（如 `CNY100m`、`percent`）和质检 Profile；凡存在上游非标准单位的数值字段，必须同步在 `UnitNormalizer` 中声明 RAW -> Curated 倍率，禁止把倍率修正留给分析层。
3. **步骤 3：任务路由与分区分流 (`TaskRegistry`)**
   在 [`src/stock/data/task_registry.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock/data/task_registry.py) 中用 `TaskSpec` 明确 `task_name`、`api_name`、`dataset`、`fetch_mode`、`partitioned`、`is_single_sync` 与 `required_pool`。公开 CLI 示例必须使用 `task_name`；`_ALIASES` 仅用于兼容历史 API 名或外部路径。
4. **步骤 4：观察池与单次同步策略 (`BackfillPlanner`)**
   在 [`src/stock/data/planner.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock/data/planner.py) 中确认新端点是否需要 watchlist 展开、是否按 `base_date` 截断，以及 `per_symbol + is_single_sync` 是否应由 `_should_expand_single_sync()` 拆成多个原子任务。
5. **步骤 5：自动化门禁验证**
   执行 `uv run pytest tests/unit/data/ --no-cov` 与 `make lint` 确保 100% 通过；涉及单位规则时，还必须从 RAW 重放 Curated 并核验主键、行数、日期范围、字段类型、metadata 与样例倍率。
