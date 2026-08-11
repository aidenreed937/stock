# Stock 项目文档中心

欢迎来到 `stock` 金融/股票项目文档中心。本文档库采用模块化结构组织，便于团队协作与长远演进。

## 📚 文档目录导航

### 1. 🏛️ 架构设计 (`docs/architecture/`)
- [系统架构总览 (Overview)](file:///Users/mac/workspace/personal/finance/stock/docs/architecture/overview.md) — 整体分层架构、依赖倒置原则与模块边界
- [数据处理流水线 (Data Pipeline)](file:///Users/mac/workspace/personal/finance/stock/docs/architecture/data_pipeline.md) — 数据抓取、校验、Parquet 列式存储与 DuckDB SQL 检索契约

### 2. 📏 规范与质量控制 (`docs/standards/`)
- [代码编写规范 (Coding Guidelines)](file:///Users/mac/workspace/personal/finance/stock/docs/standards/coding_guidelines.md) — 命名规范、Python 3.12 强类型约束与领域异常定义
- [质量防护与工具门禁 (Quality Gates)](file:///Users/mac/workspace/personal/finance/stock/docs/standards/quality_gates.md) — Ruff 超严格规则矩阵、Mypy 严格模式、Pre-commit 与测试门禁

### 3. 🚀 开发者指南 (`docs/guides/`)
- [快速上手指南 (Getting Started)](file:///Users/mac/workspace/personal/finance/stock/docs/guides/getting_started.md) — 基于 `uv` 的环境搭建、本地运行、测试与 Lint 常用指令

---

## 📈 文档演进规范

在为本项目新增功能模块或调整架构时，请遵循以下文档更新规则：
1. **新建架构/方案设计**: 在 `docs/architecture/` 下新增独立 `.md` 文件，并在本 `README.md` 中补充索引。
2. **规则/工具链变更**: 修改 `docs/standards/quality_gates.md` 与对应的 `pyproject.toml` 配置。
3. **保持图表规范**: 所有 Mermaid 架构图的节点标签文本必须使用双引号包裹，确保渲染正常。
