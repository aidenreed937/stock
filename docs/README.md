# Stock 项目文档中心

欢迎来到 `stock` 金融/股票项目文档中心。本文档库采用模块化结构组织，便于团队协作与长远演进。

## 📚 文档目录导航

### 1. 🏛️ 架构设计 (`docs/architecture/`)
- [系统架构目录与总览 (Architecture Index)](file:///Users/mac/workspace/personal/finance/stock/docs/architecture/README.md) — 2-Tier ETL 湖仓一体架构导航与核心设计理念
- [核心数据流水线与 6 大类 (Data Pipeline & Core Classes)](file:///Users/mac/workspace/personal/finance/stock/docs/architecture/data_pipeline.md) — 数据从采集到落盘的 2-Tier ETL 生命周期与 6 大核心类职责详解
- [系统模块总览 (Overview)](file:///Users/mac/workspace/personal/finance/stock/docs/architecture/overview.md) — 整体分层架构、依赖倒置原则与模块边界

### 2. 📏 规范与质量控制 (`docs/standards/`)
- [代码编写规范 (Coding Guidelines)](file:///Users/mac/workspace/personal/finance/stock/docs/standards/coding_guidelines.md) — 命名规范、Python 3.12 强类型约束与领域异常定义
- [质量防护与工具门禁 (Quality Gates)](file:///Users/mac/workspace/personal/finance/stock/docs/standards/quality_gates.md) — Ruff 超严格规则矩阵、Mypy 严格模式、Pre-commit 与测试门禁

### 3. 🚀 开发者指南 (`docs/guides/`)
- [快速上手指南 (Getting Started)](file:///Users/mac/workspace/personal/finance/stock/docs/guides/getting_started.md) — 基于 `uv` 的环境搭建、本地运行、测试与 Lint 常用指令
- [数据接口注册完整开发规范与 Checklist](file:///Users/mac/workspace/personal/finance/stock/docs/guides/endpoint_registration_guide.md) — 新增数据源/端点的 5 步标准注册流程与防漏防错清单
- [多品类市场数据摄取与调度规则手册 (Market Data Ingestion Rules)](file:///Users/mac/workspace/personal/finance/stock/docs/guides/market_data_ingestion_rules.md) — 股票/指数/ETF/行业摄取范式、全市场截面 vs 观察池范围抓取及 DuckDB 架构规范

### 4. 🔬 投研框架与数据底座 (`docs/research/` & `docs/`)
- [A股量化研究与实盘交易框架 (Research Framework)](file:///Users/mac/workspace/personal/finance/stock/docs/research/a_share_quant_framework.md) — 宏观β四象限、行业轮动、多因子选股与实盘执行闭环
- [量化系统数据底座与 PIT 设计规范 (Data Foundation Spec)](file:///Users/mac/workspace/personal/finance/stock/docs/data_foundation_spec.md) — PIT 无未来函数财报切片、复权引擎分离与日历对齐

---

## 📈 文档演进规范

在为本项目新增功能模块或调整架构时，请遵循以下文档更新规则：
1. **新建架构/方案设计**: 在 `docs/architecture/` 下新增独立 `.md` 文件，并在本 `README.md` 中补充索引。
2. **规则/工具链变更**: 修改 `docs/standards/quality_gates.md` 与对应的 `pyproject.toml` 配置。
3. **保持图表规范**: 所有 Mermaid 架构图的节点标签文本必须使用双引号包裹，确保渲染正常。
