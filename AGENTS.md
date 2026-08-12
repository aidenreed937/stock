# Repository Guidelines

## 项目结构

- `src/stock/`：核心 Python 包，按职责划分为 `data`（Fetcher、Cleaner、Normalizer、Storage ETL 链路）、`analytics`（技术指标与市场分析）、`strategy`（策略与信号）、`models`、`config` 和 `utils`。
- `tests/unit/`：按源码模块组织的单元测试；`tests/integration/`：集成测试目录。
- `config/`：策略、风险和标的池 YAML 配置；`data/`：本地 RAW/Curated 数据与缓存，不提交敏感信息或临时产物。
- `docs/`：架构、CLI、数据存储和开发规范；`.github/workflows/ci.yml`：CI 门禁。

## 开发命令

项目要求 Python 3.12+，使用 `uv` 管理环境和依赖：

```bash
make install       # 同步依赖并安装 pre-commit
make run           # 运行 uv run python -m stock.main
make test          # pytest + 覆盖率，最低 75%
make lint          # Ruff 检查与 mypy src 严格类型检查
make format        # Ruff 自动修复并格式化
make check         # format、lint、test 全流程；可能修改格式
make backfill START=2026-08-01 END=2026-08-12
```

### 沙箱隔离与 uv 缓存配置

`uv` 默认会从系统用户全局路径（如 `~/.local/share/uv/`）调用 Python 解释器和依赖缓存。在沙箱限制环境下，访问工作区以外的路径会导致文件系统拦截（`sandbox blocked open`）。

为避免触发外部沙箱权限申请，可将 `uv` 缓存与 Python 安装路径约束在项目工作区内部：

```bash
export UV_CACHE_DIR=.uv_cache
export UV_PYTHON_INSTALL_DIR=.uv_python
```


## 编码规范

使用 4 空格缩进，YAML/Markdown 使用 2 空格；文件采用 LF 并保留末尾换行。Ruff 行宽为 100，遵循 `pyproject.toml` 中的 lint 规则；公共 API 和核心逻辑使用 Google 风格 docstring，函数、方法和变量使用 `snake_case`，类使用 `PascalCase`。业务代码应保持明确类型注解，避免 `print`，使用项目日志工具。

## 测试要求

测试文件命名为 `test_*.py`，测试函数命名为 `test_<behavior>`。新增或修改策略、指标、数据管道时，在对应的 `tests/unit/` 子目录补充测试；外部数据源应使用 mock，不依赖真实 Token 或网络。提交前运行 `uv run pytest tests/unit/<path>` 做局部验证，并确保完整 `uv run pytest` 的覆盖率不低于 75%。

## 提交与 PR

提交遵循 Conventional Commits：`<type>(<scope>): <summary>`，例如 `feat(strategy): add MACD signal` 或 `fix(fetcher): handle missing token`。分支使用 `feat/`、`fix/`、`refactor/`、`docs/` 或 `chore/` 前缀。PR 应说明变更目的、影响模块和验证命令；涉及配置、数据格式或 CLI 行为时说明兼容性影响。合并前必须通过 `make check`，并确认没有提交 `.env`、Token、凭据或本地数据文件。
