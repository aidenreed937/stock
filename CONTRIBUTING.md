# 贡献指南 (Contributing)

感谢你考虑为本项目做出贡献！

## 代码规范与工具

本项目强制使用以下工具链来保证代码质量，所有提交必须通过这些检查：

- **环境管理**: `uv` (Fast Python Package Installer and Resolver)
- **代码格式化与 Linter**: `ruff`
- **静态类型检查**: `mypy` (Strict 模式 + Pydantic 插件)
- **单元测试**: `pytest`

### 安装开发依赖

克隆项目后，使用 `uv` 同步依赖，并安装 `pre-commit` 钩子：

```bash
# 同步环境与依赖
uv sync

# 安装 git pre-commit 与 commit-msg hooks
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
```

## 常用开发命令

我们提供了一个 `Makefile` 来简化日常命令。如果你安装了 `make`，可以直接使用：

- `make lint`: 运行 Ruff 代码规范检查与 Mypy 静态类型检查。
- `make format`: 使用 Ruff 自动格式化代码并修复部分常见问题。
- `make test`: 运行单元测试并生成覆盖率报告。
- `make check`: 运行所有检查（lint + test），推荐在提交前执行。

（如果没有 `make`，可查看 `Makefile` 内对应的 `uv run ...` 原始命令执行）。

## 提交规范 (Commit Convention)

我们推崇 [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) 规范。

常见的 type 包括：
- `feat`: 新增特性或指标
- `fix`: 修复 bug
- `docs`: 文档变更
- `style`: 代码格式（不影响代码运行的变动，注意非代码逻辑）
- `refactor`: 重构（既不是新增功能，也不是修改 bug 的代码变动）
- `perf`: 性能优化
- `test`: 增加测试
- `chore`: 构建过程或辅助工具的变动

**分支命名建议**：
`feat/xxx`, `fix/xxx`, `docs/xxx` 等。

## 新增数据抓取源或策略指标

1. **抽象实现**：所有的 Fetcher 都应该继承基础接口。
2. **校验与类型**：涉及到数据结构的输入输出，必须定义 `Pydantic` Model 并在方法签名上增加明确的类型注解。
3. **Docstring**：核心分析逻辑和对外的函数/类，强制要求遵循 Google 风格的 Docstring，描述参数与返回值。
4. **单测覆盖**：新增的策略指标（如 `src/stock/analytics` 下的新文件）必须要有一套对应的单测来验证逻辑正确性，保证代码覆盖率。

提交 PR（Pull Request）前，请确保本地 `make check` 通过，GitHub Actions 也会在你提交后自动进行拦截检查。
