# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

基于 `uv` 的 A 股金融/股票数据分析与研究信号项目。核心能力：多数据源 ETL 数据管道、本地列式数据仓库（DuckDB + Parquet）、量化技术指标分析（Polars）、全市场扫描体检报告与数据质量审计。**不含**回测、撮合或实盘执行。

## 常用命令

依赖管理用 `uv`（禁用 npm/yarn）；日常操作大多封装在 `Makefile` 中：

```bash
# 安装依赖 + pre-commit 钩子
uv sync && uv run pre-commit install --hook-type pre-commit --hook-type commit-msg

# 提交前全量检查（format + lint + test）
make check

# 单独跑 lint（ruff + mypy strict + 类大小检查）
make lint
# 格式化
make format
# 全量测试
make test

# 运行单个测试文件 / 单个用例
uv run pytest tests/unit/data/test_backfill.py
uv run pytest tests/unit/data/test_backfill.py -k "断点续传"
```

注意 `make lint` 还会运行 `scripts/lint_class_size.py`（类行数与方法数上限门禁），并非只有 ruff/mypy。

### 环境与沙箱隔离

项目要求 Python 3.12+，用 `uv` 管理。在沙箱或受限执行环境下，必须把 `uv` 缓存与解释器路径约束在项目内部（避免访问外部目录被拦截）；所有命令优先走 `make` / `uv run`，**禁止直接用系统全局 `python` / `pip`**：

```bash
export UV_CACHE_DIR=.uv_cache
export UV_PYTHON_INSTALL_DIR=.uv_python
```

（Makefile 的部分 target 已内联这两个变量。）

- **严禁轮询后台任务状态 (No Polling)**：运行命令时合理设置超时优先同步获取输出；若命令切入后台，严禁循环查询状态死等，直接结束当轮调用等待系统事件自动唤醒。

### 业务命令（多用带参数的 make target）

```bash
# 3 层市场体检扫描（宏观/中观/微观），产物落 reports/scan/{YYYY-MM-DD}/
make scan DATE=2026-08-12 FORMAT=console

# 历史数据回填（tushare，断点续传）
make backfill START=2026-08-01 END=2026-08-12 ENDPOINT=daily

# 全局数据源连通性探测 / 离线质量校验
make probe
make validate ENDPOINT=stock_daily_bar

# 全库物理存储审计 / 统一审计 CLI
make master-audit
make audit TYPE=master DOMAIN=valuation FREQ=daily

# 生成股票 Filtered Universe / 基于 Universe 回填理杏仁基本面 / 迁移/规约数据
make filter-universe
make backfill-fundamental
make migrate-data APPLY=1
```

完整的 Python 模块 CLI 用法见 [docs/cli_guide.md](docs/cli_guide.md)。

## 数据源与配置

四种数据源在 `src/stock_data/fetcher/` 下：`tushare`（A 股行情/财务/资金流）、`lixinger`（理杏仁估值/财务，key 带 `source_unit`）、`yfinance` 与 `fred`（宏观指数）。通过 `--data-source` / `settings.data_source_mode` 选择，Lixinger 的路径与单位语义与 TuShare 不同。

- 环境配置/敏感 Token 走 `pydantic-settings` + `.env`（TuShare/Lixinger Token 不进 Git）。
- 业务与策略参数由 `config/*.yaml` 经 Pydantic 强类型校验加载，**零硬编码**。新增指标/策略应遵循 YAML 驱动。
- 全局常量（默认指标周期、交易所开市首日、接口起始日校准）集中在 `src/stock_core/constants.py`。
- **统一观察池单一信任源**：`config/universe/watchlist.yaml` 是全系统唯一核心自选池（A 股个股、宽基/核心指数基准日、旗舰 ETF 上市基准日、全球外盘与宏观资产）。CLI 传 `SYMBOL=watchlist` 时自动路由并对齐各标的 `base_date`，不要绕开该配置硬编码标的清单。

## 核心架构（只读前必读）

系统拆分为 **6 个顶级业务包**，严格遵循单向依赖图谱 (DAG)：
`stock_core ◄── {stock_data, stock_reporting} ◄── stock_analytics ◄── stock_strategy ◄── stock_cli`

数据单向流动：`Fetcher ➔ Cleaner ➔ Normalizer ➔ Storage ➔ Analytics ➔ Strategy ➔ Reporting`，禁止跨层反向依赖；OHLCV 只读不可变；全程 Polars/Arrow 零拷贝；Cleaner/Normalizer 为纯无状态函数便于测试。

### 双层存储（关键约定）

- **RAW 层** `data/raw/{data_source}/{endpoint}/year=YYYY/month=MM/`：原汁原味 API 响应，Hive 式时间分区，防重复请求 + 支持离线重洗。
- **Curated 层** `data/curated/{data_source}/market={market}/{dataset}/`：统一规范 Schema，注入 `data_source` / `updated_at` 血统，供分析引擎直接读。`CatalogDataset`（`src/stock_data/catalog.py`）是统一读取 Curated 数据的入口，非 RAW。
- 两地物理文件 1-to-1 镜像。涉及列名/单位归一化改动的风险点常在此：Schema 校验是 fail-closed（来源/schema 不一致即拒绝写入，不做隐式列合并）。

### 分析与研报层（物化解耦）

- **分析计算层 (`src/stock_analytics/`)**：
  - `primitives/indicators.py`：SMA/EMA/RSI/MACD 技术指标。
  - `metrics/`：六维市场温度计与量化分位数模型。
  - `pipelines/`：宏观、中观与微观统一分析流水线。
- **研报渲染层 (`src/stock_reporting/`)**：
  - `templates/`：全景体检、行业结构、投资简报等报告模板。
  - `interpretation/`：指标阈值、区间评级配置与解读规则库（自包含，零依赖 analytics）。
  - 报告物化解耦：计算与渲染分离，产物按日落 `reports/scan/{YYYY-MM-DD}/`。

### 审计体系

`src/stock_data/audit/`：物理存储主审计、统一审计 CLI、回填验收（fail-closed）、以及 `benchmarks/`（申万2021一级行业代码、交易日历等官方基准数据）。领域驱动与时态统一的事实基准对账是本仓库的重要质量防线，改动审计逻辑时注意基准数据权威性与 RAW/Curated 口径区分。

### 领域 Universe 与运维

`src/stock_data/domain/`：基于流动性规则的股票品域筛选（`rules/`）；`ops/`：探针、迁移、repair/repartition 运维脚本；`quality/`：门禁与隔离（quarantine）。

## 量化投研准则（Ground Truth First）

- **本地真实数据第一**：所有点位、估值与指标必须通过代码查询本地 Curated 黄金表输出，严禁凭模型记忆虚构数值。
- **严禁无源叙事污染**：本地库无政策/新闻数据表，严禁把外部记忆中"政策刺激/救市会议"等叙事伪装成数据事实写入结论或表格（详见 `.agents/skills/data-catalog/references/data_query_caveats.md`）。
- **三层信息分级透明化**：区分已验证事实 / 机制推断 / 外部背景，并做防过拟合审查。

数据管道与回填实操另见 `.agents/skills/data-pipeline/SKILL.md`。

## 约定与规范

- **语言**：代码注释、docstring、日志、commit message 默认中文；docstring 用 Google 风格。
- **质量门禁**：ruff（line-length 100、含 pydocstyle/复杂度/参数个数约束）+ mypy strict + 类大小检查 + Conventional Commits（pre-commit 拦截，GitHub Actions 兜底）。新增分析/策略逻辑强制要求配套单测；测试访问**外部数据源必须 mock**（不依赖真实 Token/网络），全量 `make test` 覆盖率 ≥75%。测试文件命名 `test_*.py`、函数 `test_<behavior>`。
- **Commit/Branch**：Conventional Commits（`feat/fix/docs/chore/...`），分支 `feat/xxx` 等。
- **新增数据源/指标流程**：Fetcher 继承基础接口，输入输出定义 Pydantic Model，核心逻辑带 Google 风格 docstring，并配套单测。见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 技能

`tushare-data` skill（`.agents/skills/tushare-data/SKILL.md`）面向 A 股数据研究场景，可复用其数据获取/清洗思路。
