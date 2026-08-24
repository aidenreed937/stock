# Stock Finance Project

基于 `uv` 构建的金融/股票数据分析与研究信号系统，提供数据管道、量化分析、报告生成和研究策略信号能力，不执行实盘下单或撮合。

## 核心特性

- **模块化分包架构**: 按职责拆分为 7 个顶级源码包（含向后兼容门面 `stock`），依赖方向受边界检查约束。
- **完整 ETL 数据管道**: 规范分层的 `Fetcher (采集) ➔ Cleaner (清洗) ➔ Normalizer (标准化) ➔ Storage (存储)` 2-Tier 架构。
- **YAML 策略配置驱动**: 基于 `Pydantic` 校验 YAML 强类型配置文件，实现零硬编码解耦。
- **数据分析与研究信号**: 使用 `Polars` 计算技术指标、六维市场温度计与申万行业结构分析，并输出结构化研报。
- **可追溯持久化**: 基于 `DuckDB + Parquet` 实现带数据集身份、版本、血统和原子写入的本地存储（RAW、Curated、Mart 分层）。
- **统一工具链与编码规范**: 基于 `uv` 依赖管理，集成 `Ruff`, `Mypy` (strict), `Pytest` (覆盖率 > 75%)，保障系统长期可维护性。

## 快捷命令指南

### 1. 安装与同步依赖

```bash
make install
```

### 2. 运行主示范程序

```bash
make run
```

### 3. 代码检查与自动化测试

```bash
# 格式化、代码规范检查与单测验证 (提交前执行)
make check
```

## 开发与架构指南

- 想要参与贡献或了解如何扩展策略与指标，请阅读 [贡献指南 (CONTRIBUTING.md)](CONTRIBUTING.md) 和仓库根目录的 `AGENTS.md`。
- 详细的数据架构设计与分层规范说明，请阅读 [系统架构文档 (docs/architecture.md)](docs/architecture.md) 与 [数据存储指南 (docs/data_architecture.md)](docs/data_architecture.md)。
- 命令行 CLI 与历史数据回填指南，请阅读 [CLI 命令行指南 (docs/cli_guide.md)](docs/cli_guide.md)；具体参数以对应命令的 `--help` 为准。

## 模块说明

- `src/stock_core/`: 最底层基础设施与核心契约（零内部业务依赖）
  - `contracts.py`: 标的身份、数据集身份 (`DatasetKey`) 与标准 Schema 契约
  - `models/`: Pydantic 强类型领域模型与 YAML 配置模型
  - `config/`: 环境配置管理 (`settings.py`) 与 YAML 配置加载器 (`loader.py`)
  - `constants.py` & `exceptions.py` & `utils/`: 全局常量、领域异常与 Loguru 结构化日志工具
- `src/stock_data/`: 2-Tier 湖仓数据管道与数据资产管理
  - `fetcher/`: 数据源适配器 (`tushare`, `lixinger`, `yfinance`, `fred`, `alphavantage`)
  - `cleaner/`: 脏数据过滤、价格逻辑校验与去重
  - `normalizer/`: 异构列名别名对齐与统一日期 (`pl.Date`) / 单位标准化
  - `storage/`: DuckDB + RAW / Curated Parquet 分区存储与 SQL 查询引擎
  - `audit/` & `quality/` & `ops/`: 资产主审计、质量隔离门禁与数据迁移运维
- `src/stock_reporting/`: 研报渲染引擎与解读配置（自包含，零依赖 analytics）
  - `engine/`: Jinja2/Polars 研报渲染器与过滤器
  - `templates/`: 市场全景、行业结构、投资简报等模版
  - `interpretation/`: 研报指标阈值配置与状态解读规则库
- `src/stock_analytics/`: 量化投研核心计算
  - `primitives/`: SMA、EMA、RSI、MACD 等纯计算算子
  - `metrics/`: 指标规格、数据集读取与指标引擎
  - `features/`、`marts/`: 可复用特征和领域聚合事实
  - `pipelines/`: 市场温度、行业结构、简报、选股和诊断等分析流水线
- `src/stock_strategy/`: 策略投研与信号
  - `base.py` & `context.py`: 策略基类与上下文抽象
  - `runner.py`: 配置驱动的研究策略运行与信号报告生成
  - `pool/`: 经典策略池实现（如双均线 RSI 策略）
- `src/stock_cli/`: 顶层交互与用户命令行入口
  - `main.py`: 主程序流程示范入口
  - `backfill.py`、`sync.py`、`audit.py`: 数据回填、增量同步和审计 CLI
  - `market_temperature.py`、`multi_date.py`、`quant_brief.py` 等：分析产物 CLI
- `src/stock/`: 向后兼容根入口门面 (`__init__.py`)
