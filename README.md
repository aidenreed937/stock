# Stock Finance Project Scaffold

基于 `uv` 构建的高能金融/股票数据分析与策略开发脚手架。

## 核心特性

- **数据分析引擎**: 使用 `Polars` 进行高效向量化计算（SMA, EMA, RSI）。
- **极速持久化**: 基于 `DuckDB + Parquet` 实现本地行情列式存储与 SQL 快速查询。
- **结构化校验**: 基于 `Pydantic` 校验行情数据（OHLCV 逻辑与约束）。
- **统一工具链**: 基于 `uv` 进行环境与依赖管理，集成 `Ruff`, `Mypy`, `Pytest`。

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

## 开发指南

想要参与贡献或了解如何扩展策略与指标，请阅读 [贡献指南 (CONTRIBUTING.md)](CONTRIBUTING.md)。

## 模块说明

- `src/stock/config`: 环境配置与路径管理 (`pydantic-settings`)
- `src/stock/data/fetcher`: 行情数据抓取抽象层及模拟数据源
- `src/stock/data/storage`: DuckDB + Parquet 本地极速存储层
- `src/stock/models`: Pydantic 数据结构定义与校验规则
- `src/stock/analytics`: 技术指标（移动平均线、RSI）计算逻辑
- `src/stock/utils`: Loguru 结构化日志工具
