# Repository Guidelines

## 项目结构

- `src/`：按职责清晰拆分为 6 个顶级包：
  - `stock_core/`：基础数据契约、领域模型、YAML 加载器、全局常量与异常工具库；
  - `stock_data/`：2-Tier ETL 管道（Fetcher、Cleaner、Normalizer、Parquet/DuckDB Storage）、审计与质量运维；
  - `stock_reporting/`：研报渲染引擎、报告模板与阈值解读配置；
  - `stock_analytics/`：技术指标、六维市场温度计与行业结构分析；
  - `stock_strategy/`：策略基类、上下文、信号生成与回测运行器；
  - `stock_cli/`：顶层用户交互与命令行入口；
  - `stock/`：向后兼容门面包。
- `tests/unit/`：按源码模块组织的单元测试；`tests/integration/`：集成测试目录。
- `config/`：策略、风险和标的池 YAML 配置（其中 `config/universe/watchlist.yaml` 为全系统唯一核心观察池）；`data/`：本地 RAW/Curated 2-Tier 离线 Parquet 数据与缓存，不提交敏感信息或临时产物。
- `docs/`：架构、CLI、数据存储和开发规范；`.agents/skills/data-pipeline/SKILL.md`：核心数据管道与回填实操指南；`.github/workflows/ci.yml`：CI 门禁。

## 环境与沙箱隔离

项目要求 Python 3.12+，使用 `uv` 管理环境和依赖。在沙箱或受限执行环境下，必须将 `uv` 缓存与解释器路径约束在项目内部，避免访问外部目录被拦截：

```bash
export UV_CACHE_DIR=.uv_cache
export UV_PYTHON_INSTALL_DIR=.uv_python
```

所有命令优先通过 `make` 或 `uv run` 执行，禁止直接使用系统全局 `python` 或 `pip`。

- **严禁轮询后台任务状态 (No Polling)**：运行命令时合理设置 `WaitMsBeforeAsync` 优先同步获取输出；若切入后台，严禁循环调用 `manage_task(Action='status')`，必须直接停止调用工具（Yield Turn）等待系统事件自动唤醒。

## 标准开发与数据管道命令

### 1. 代码质量与测试门禁

```bash
make install       # 同步依赖并安装 pre-commit
make lint          # Ruff 检查、mypy 类型检查与类规模约束 (lint_class_size)
make format        # Ruff 自动修复并格式化
make test          # pytest 单元测试 + 覆盖率 (最低 75%)
make check         # format、lint、test 全流程门禁
make run           # 运行主程序 (uv run python -m stock_cli.main)
make scan          # 一键全市场量化全景扫描与体检 (支持 DATE=YYYY-MM-DD FORMAT=markdown OUTPUT=...)
```

### 2. 核心数据管道 CLI (`data-pipeline`)

数据管道回填与审计优先参考 [`.agents/skills/data-pipeline/SKILL.md`](file:///Users/mac/workspace/personal/finance/stock/.agents/skills/data-pipeline/SKILL.md)，标准 CLI 指令统一由 `Makefile` 封装：

```bash
# 1. 历史数据全量回填 (统一 Makefile 入口)
make backfill START=YYYY-MM-DD END=YYYY-MM-DD SOURCE=<data_source> [ENDPOINT=<endpoint>] [SYMBOL=<symbol>] [FORCE_REFRESH=1]

# 示例：回填 26 只自选 ETF 全历史行情与规模 (自动按上市基日截断)
make backfill START=2005-01-01 END=2026-08-14 SOURCE=tushare ENDPOINT=fund_daily,etf_share_size,fund_adj SYMBOL=watchlist FORCE_REFRESH=1

# 示例：回填 12 年 A 股 10 大核心指数 K 线（项目任务名，底层 API 为 index_daily）
make backfill START=2014-08-01 END=2026-08-12 SOURCE=tushare ENDPOINT=index_daily_bar

# 示例：回填理杏仁 9 大核心指数 12 年基本面估值
make backfill START=2014-08-01 END=2026-08-12 SOURCE=lixinger ENDPOINT=index_fundamental

# 示例：回填 yfinance 观察池美股巨头与外盘指数 12 年 K 线
make backfill START=2014-08-01 END=2026-08-12 SOURCE=yfinance

# 示例：回填 FRED 7 大核心宏观指标 12 年历史
make backfill START=2014-08-01 END=2026-08-12 SOURCE=fred

# 2. 数据资产主审计与多维对账
make master-audit                     # 全库 Parquet 物理主审计盘点
make audit TYPE=master                # 资产盘点 (同 master-audit)
make audit TYPE=reconciliation        # RAW vs Curated 双向物理对账
make audit TYPE=valuation             # 估值指标专项对账 (daily_basic 对齐率)
make audit TYPE=factor                # 技术因子专项对账 (复权因子与行业行情)
make audit TYPE=all                   # 全套系联动审计

# 3. 运维、质量门禁与探针
make probe                            # 4 大数据源连通性与时延健康探测
make validate                         # 离线数据质量规则校验与隔离
make baseline                         # 生成不可变数据资产基线清单
make migrate-data [APPLY=1]           # 存量 Parquet 离线去重与 Schema 迁移
```

## 核心架构与数据流契约

1. **2-Tier 存储架构**：
   - `data/raw/`：API 原始响应分区快照，按批次追加，保留原始字段。
   - `data/curated/`：标准化黄金表（`pl.Date` 类型统一、主键去重、单位标准化），为下游策略回测与因子计算的**唯一消费事实标准**。
2. **统一观察池单一信任源**：
   - [`config/universe/watchlist.yaml`](file:///Users/mac/workspace/personal/finance/stock/config/universe/watchlist.yaml) 集中管理 A 股核心个股、10 大指数基准日与 26 只核心 ETF 上市基准日。
   - CLI 传入 `SYMBOL=watchlist` 时自动路由并对齐各标的的 `base_date`。
3. **数据源职责分工**：
   - `tushare`：A 股全量行情、每日估值、复权因子、北向持仓、申万行情、场内基金/ETF。
   - `lixinger`：指数基本面估值、申万 2021 行业成份股图谱、31 行业估值序列及中债官方国债收益率与基准利率。
   - `yfinance`：外盘 9 大核心指数、美股科技巨头 K 线、8 大全球宏观资产。
   - `fred`：美联储官方宏观指标（基准利率、CPI、非农、失业率、GDP、利差等）。
4. **量化投研与分析准则 (Ground Truth First)**：
   - 严格遵循**本地真实数据第一**，所有点位、估值与指标必须通过代码查询本地 Curated 黄金表输出，严禁凭模型记忆虚构；
   - 严格执行**三层信息分级透明化**（已验证事实 / 机制推断 / 外部背景）与**防过拟合审查**；
   - **严禁无源叙事污染**：本地库无政策或新闻数据表，严禁将外部记忆中的“政策刺激/救市会议”伪装为数据事实写入结论或表格，详见 [`.agents/skills/data-catalog/references/data_query_caveats.md`](file:///Users/mac/workspace/personal/finance/stock/.agents/skills/data-catalog/references/data_query_caveats.md)。

## 编码与测试规范

1. **编码格式**：使用 4 空格缩进，YAML/Markdown 使用 2 空格；LF 换行。Ruff 行宽为 100；类与方法控制规模，遵循 `scripts/lint_class_size.py` 存量基线。
2. **测试要求**：测试文件命名为 `test_*.py`，函数为 `test_<behavior>`。外部数据源必须使用 mock，不依赖真实 Token 或网络。单测运行 `uv run pytest tests/unit/<path>` 做局部验证，完整 `make test` 覆盖率不得低于 75%。
3. **提交与 PR 规范**：遵循 Conventional Commits（`<type>(<scope>): <summary>`）。分支使用 `feat/`、`fix/`、`refactor/`、`docs/` 或 `chore/`。合并前必须通过 `make check`。
