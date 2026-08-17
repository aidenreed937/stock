# Stock Finance Project Scaffold

基于 `uv` 构建的金融/股票数据分析与研究信号脚手架。当前不包含回测、撮合或实盘执行能力。

## 核心特性

- **模块化分包架构**: 按照职责清晰拆分为 6 个顶级包（`stock_core`, `stock_data`, `stock_reporting`, `stock_analytics`, `stock_strategy`, `stock_cli`），单向无环依赖（DAG）。
- **完整 ETL 数据管道**: 规范分层的 `Fetcher (采集) ➔ Cleaner (清洗) ➔ Normalizer (标准化) ➔ Storage (存储)` 2-Tier 架构。
- **YAML 策略配置驱动**: 基于 `Pydantic` 校验 YAML 强类型配置文件，实现零硬编码解耦。
- **数据分析与研究信号**: 使用 `Polars` 计算技术指标、六维市场温度计与申万行业结构分析，并输出结构化研报。
- **极速持久化**: 基于 `DuckDB + Parquet` 实现带数据集身份、版本和原子写入的本地行情列式存储（RAW 与 Curated 分层）。
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

- 想要参与贡献或了解如何扩展策略与指标，请阅读 [贡献指南 (CONTRIBUTING.md)](CONTRIBUTING.md)。
- 详细的数据架构设计与分层规范说明，请阅读 [系统架构文档 (docs/architecture.md)](docs/architecture.md) 与 [数据存储指南 (docs/data_architecture.md)](docs/data_architecture.md)。
- 命令行 CLI 与历史数据回填指南，请阅读 [CLI 命令行指南 (docs/cli_guide.md)](docs/cli_guide.md)。

## 模块说明 (6 大顶级包)

- `src/stock_core/`: 最底层基础设施与核心契约（零内部业务依赖）
  - `contracts.py`: 标的身份、数据集身份 (`DatasetKey`) 与标准 Schema 契约
  - `models/`: Pydantic 强类型领域模型与 YAML 配置模型
  - `config/`: 环境配置管理 (`settings.py`) 与 YAML 配置加载器 (`loader.py`)
  - `constants.py` & `exceptions.py` & `utils/`: 全局常量、领域异常与 Loguru 结构化日志工具
- `src/stock_data/`: 2-Tier 湖仓数据管道与数据资产管理
  - `fetcher/`: 4 大数据源适配器 (`tushare`, `lixinger`, `yfinance`, `fred`)
  - `cleaner/`: 脏数据过滤、价格逻辑校验与去重
  - `normalizer/`: 异构列名别名对齐与统一日期 (`pl.Date`) / 单位标准化
  - `storage/`: DuckDB + RAW / Curated Parquet 分区存储与 SQL 查询引擎
  - `audit/` & `quality/` & `ops/`: 资产主审计、质量隔离门禁与数据迁移运维
- `src/stock_reporting/`: 研报渲染引擎与解读配置（自包含，零依赖 analytics）
  - `engine/`: Jinja2/Polars 研报渲染器与过滤器
  - `templates/`: 市场全景、行业结构、投资简报等模版
  - `interpretation/`: 研报指标阈值配置与状态解读规则库
- `src/stock_analytics/`: 量化投研核心计算
  - `primitives/`: SMA、EMA、RSI、MACD 等技术指标底层计算
  - `metrics/`: 六维市场温度计计算与量化分位数模型
  - `industry/`: 申万行业分类与结构分析
  - `pipelines/`: 宏观、中观与微观统一分析流水线
- `src/stock_strategy/`: 策略投研与信号
  - `base.py` & `context.py`: 策略基类与上下文抽象
  - `runner.py`: 配置驱动的研究策略运行与信号报告生成
  - `pool/`: 经典策略池实现（如双均线 RSI 策略）
- `src/stock_cli/`: 顶层交互与用户命令行入口
  - `main.py`: 主程序流程演示入口
  - `backfill.py` & `sync.py` & `audit.py`: 历史回填、增量同步与数据审计 CLI
  - `market_temperature.py` & `features.py`: 市场全景扫描与特征生成 CLI
- `src/stock/`: 向后兼容根入口门面 (`__init__.py`)
