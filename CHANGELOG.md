# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- 初始化金融分析脚手架，集成 `uv`, `polars`, `duckdb`, `pydantic`。
- 新增 **RAW + Curated 进阶两层存储架构** (`data/raw/` 时间分区归档层与 `data/curated/` 精炼层)。
- 新增基于 **Hive 风格的时间分区（Time Partitioning）原始数据存储引擎 (`RawDataStorage`)**，支持 `year=YYYY/month=MM/` 自动目录索引、网络请求离线缓存命中与本地回放。
- 新增数据血统元数据追踪（注入 `data_source` 与 `updated_at` 时间戳）。
- 新增 **TuShare 接口管理与采集基础设施** (`client.py` 鉴权与滑动窗口限频、`registry.py` 接口元数据注册表、`slicer.py` 多代码线程池并发切片合并器)。
- 新增规范分层的 **ETL 数据管道架构**（`Cleaner` 脏数据清洗、`Normalizer` 字段标准化、`Pipeline` 数据流编排）。
- 新增 **YAML 策略配置驱动架构** (`Pydantic` 校验 Schema + `loader.py` 加载器)，支持基于 `config/strategy_example.yaml` 灵活驱动应用逻辑。
- 新增 `src/stock/constants.py` 领域常量定义，全面消除魔数与硬编码。
- 增加 `.editorconfig` 跨编辑器格式规范控制。
- 增加 `.pre-commit-config.yaml` 自动拦截钩子与 `Makefile` 常用命令。
- 增加 GitHub Actions CI 自动化构建流水线。
- 编写与更新设计文档（`README.md`, `CONTRIBUTING.md`, `docs/architecture.md`）。
