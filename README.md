# Stock Finance Project Scaffold

基于 `uv` 构建的金融/股票数据分析与研究信号脚手架。当前不包含回测、撮合或实盘执行能力。

## 核心特性

- **完整 ETL 数据管道**: 规范分层的 `Fetcher (采集) ➔ Cleaner (清洗) ➔ Normalizer (标准化) ➔ Storage (存储)` 架构。
- **YAML 策略配置驱动**: 基于 `Pydantic` 校验 YAML 强类型配置文件，实现零硬编码解耦。
- **数据分析与研究信号**: 使用 `Polars` 计算 SMA、EMA、RSI、MACD，并输出配置驱动的结构化信号报告。
- **极速持久化**: 基于 `DuckDB + Parquet` 实现带数据集身份、版本和原子写入的本地行情列式存储。
- **结构化校验**: 基于 `Pydantic` 校验行情数据（OHLCV 逻辑与约束）。
- **统一工具链与编码规范**: 基于 `uv` 依赖管理，集成 `Ruff`, `Mypy` (strict), `Pytest`, `.editorconfig` 及 Git Pre-commit 拦截。

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
# 格式化、代码规范检查与单测验证 (建议在提交前执行)
make check
```

## 开发与架构指南

- 想要参与贡献或了解如何扩展策略与指标，请阅读 [贡献指南 (CONTRIBUTING.md)](CONTRIBUTING.md)。
- 详细的数据架构设计与分层规范说明，请阅读 [系统架构文档 (docs/architecture.md)](docs/architecture.md) 与 [数据存储指南 (docs/data_architecture.md)](docs/data_architecture.md)。
- 命令行 CLI 与历史数据回填指南，请阅读 [CLI 命令行指南 (docs/cli_guide.md)](docs/cli_guide.md)。

## 模块说明

- `docs/architecture.md`: 系统架构设计、模块分层与 5 大数据流动原则说明文档
- `docs/data_architecture.md`: RAW + Curated 两层数据存储、时间分区归档规范与并发限频指南
- `docs/cli_guide.md`: CLI 命令行使用指南与历史数据回填参数说明
- `config/`: YAML 策略与业务配置文件目录
- `src/stock/config`: 环境配置管理 (`settings.py`) 与 YAML 配置加载器 (`loader.py`)
- `src/stock/constants.py`: 全局常量定义（默认指标周期、存储目录常量等）
- `src/stock/data/fetcher`: 行情数据抓取抽象层及数据源实现
  - `src/stock/data/fetcher/tushare`: TuShare 接口管理注册表、Token 客户端与请求切片器
- `src/stock/data/cleaner`: 脏数据过滤、价格逻辑校验与去重模块
- `src/stock/data/normalizer`: 异构列名别名对齐与数据类型标准化模块
- `src/stock/data/storage`: DuckDB + Parquet 本地极速存储层
- `src/stock/data/pipeline.py`: ETL 流水线管道编排核心
- `src/stock/data/contracts.py`: 标的身份、数据集身份与日线 Schema 契约
- `src/stock/models`: Pydantic 行情与策略配置结构模型
- `src/stock/analytics`: 技术指标（移动平均线、RSI、MACD）计算逻辑
- `src/stock/strategy/runner.py`: 配置驱动的研究策略运行与信号报告
- `src/stock/utils`: Loguru 结构化日志工具
