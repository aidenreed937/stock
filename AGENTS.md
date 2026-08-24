# Repository Guidelines

## 适用范围与信息源

- 本文件只保留项目级、跨模块且相对稳定的规则；具体公式、字段、产物 Schema 和 CLI 参数以当前代码、YAML 配置、CLI `--help` 与运行产物 Manifest 为准。
- `.agents/skills/` 负责按任务路由工作流和专题约束，不在本文件复制实现细节。引用仓库文件时优先使用相对路径，避免绑定某台机器的绝对 `file://` 路径。
- 修改前先检查当前工作区状态；未明确要求时不提交、不推送、不覆盖用户已有改动。

## 项目结构

- `src/`：7 个顶级源码包：
  - `stock_core/`：基础数据契约、领域模型、YAML 加载器、全局常量与异常工具库；
  - `stock_data/`：数据源接入、2-Tier ETL、Parquet/DuckDB 存储、审计与质量运维；
  - `stock_reporting/`：研报渲染引擎、报告模板与阈值解读配置；
  - `stock_analytics/`：指标、Mart、市场温度、行业结构与分析产物管线；
  - `stock_strategy/`：策略基类、上下文、信号生成与回测运行器；
  - `stock_cli/`：命令行入口和用户交互编排；
  - `stock/`：向后兼容门面包。
- `tests/unit/`：按源码包组织的单元测试，另含 `tests/unit/scripts/` 的脚本测试；不要求机械地与源码目录完全 1:1。
- `config/`：策略、风险、观察池、分析配置和智能体参考配置；`config/universe/watchlist.yaml` 是核心观察池唯一信任源。
- `data/`：本地 RAW、Curated、Mart、分析产物与缓存；不提交敏感信息、真实 Token 或临时产物。
- `docs/`：架构、CLI、数据存储和开发规范；`.agents/skills/`：任务路由和专题操作指南；`.github/workflows/ci.yml`：CI 门禁。

`config/agent/` 当前是智能体参考配置，不是分析管线的运行时输入：

- `user_persona.yaml` 由 `stock-deep-research` skill 默认参考；
- `soul.md` 是投研表达和求真准则参考，目前没有自动加载链路；
- 若未来要让代码或管线消费这些文件，必须增加明确的 loader、Schema 和测试，不能依赖“约定会自动读取”。

## 环境与沙箱隔离

项目要求 Python 3.12+，使用 `uv` 管理环境和依赖。在沙箱或受限环境下，将缓存和解释器路径约束在项目内：

```bash
export UV_CACHE_DIR=.uv_cache
export UV_PYTHON_INSTALL_DIR=.uv_python
export PRE_COMMIT_HOME="$(pwd)/.pre_commit_cache"
```

所有命令优先通过 `make` 或 `uv run` 执行，禁止直接使用系统全局 `python` 或 `pip`。后台任务应使用合理的等待时间，避免循环轮询状态；未收到完成事件前不要反复查询。

pre-commit 缓存使用项目内的 `.pre_commit_cache/`，该目录已加入 `.gitignore`。直接执行 `git commit` 时，当前 shell 也必须导出 `PRE_COMMIT_HOME`；Makefile 的变量不会回写父 shell 环境。

## 标准开发、分析与数据管道命令

### 1. 代码质量与测试门禁

```bash
make install                         # 同步依赖并安装 pre-commit
make lint                            # Ruff、mypy、类规模与导入边界检查
make format                          # Ruff 自动修复并格式化（会修改文件）
make test                            # 全量 pytest 与覆盖率门禁（最低 75%）
make test TEST_PATH=tests/unit/...   # 受影响范围的定向测试
make check                           # format、lint、Rust 检查与 test 全流程
make run                             # 运行主程序
```

## 领域任务

涉及数据工程、数据查询、市场分析、个股研究、行业研究或指标规范时，先读取对应
`.agents/skills/*/SKILL.md`。Skill 负责用途、工作流和验收方式；不要把领域命令和实现细节复制回本文件。

## 稳定架构约束

1. **事实存储与派生层**：
   - `data/raw/`：API 原始响应分区快照，保留源字段和批次信息；
   - `data/curated/`：标准化黄金事实表（日期类型、主键、单位和血统统一），是下游策略与分析的唯一事实消费层；
   - `data/curated/mart/`：由 Curated 构建的派生 Mart/特征缓存，不替代原始 Curated 事实；
   - `data/analytics/`：分析管线运行目录、Manifest、报告和 `latest` 展示副本。
2. **观察池单一信任源**：`config/universe/watchlist.yaml` 集中管理核心个股、指数和 ETF 的观察范围及基准日；CLI 传入 `SYMBOL=watchlist` 时按配置路由和截断。
3. **数据源与指标细节**：由对应代码、配置和 Skill 维护，不在本文件重复列举。
4. **Ground Truth First**：所有点位、估值和指标必须来自本地 Curated 或已校验的产物；本地缺失必须披露，不得用记忆补造。外部背景必须标注来源与时效。
5. **信息分级**：报告区分已验证事实、机制推断和外部背景；公式或策略口径不确定时先查代码配置、权威依据和测试。

## 编码、测试与提交规范

1. 使用 4 空格缩进；YAML/Markdown 使用 2 空格；LF 换行；Ruff 行宽为 100；类与方法规模遵循 `scripts/lint_class_size.py`。
2. 测试文件命名为 `test_*.py`，函数命名为 `test_<behavior>`；外部数据源必须 mock，不依赖真实 Token 或网络。先跑受影响范围测试，再根据风险决定是否运行全量 `make test`。
3. 生成数据、缓存、日志和验证产物留在被忽略目录，不将敏感信息或临时产物加入 Git。
4. 提交信息遵循 Conventional Commits（`<type>(<scope>): <summary>`）；分支使用 `feat/`、`fix/`、`refactor/`、`docs/` 或 `chore/`。未经明确要求不自动 commit 或 push；提交前运行受影响检查，合并前通过 `make check`。
