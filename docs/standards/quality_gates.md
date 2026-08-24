# 质量防护与工具门禁 (Quality Gates & Tool Rules)

为了保持项目长期演进过程中代码风格零偏移、质量与稳定性极高，项目引入了四重防护隔离墙。

## 一、 检查作用域与排除原则 (Scope & Exclusion Rules)

为防止工具扫描安装在 `.venv` 或 `site-packages` 中的第三方依赖库代码，所有分析与约束规则**严格限定在本项目自身的代码范围**内：

- **受约束的目标目录**: `src/` (核心业务逻辑) 和 `tests/` (自动化测试)
- **硬性排除的目录**: `.venv/`, `venv/`, `data/`, `build/`, `dist/`, `notebooks/`, `*.egg-info`
- **第三方包忽略机制**:
  - `mypy` 配置 `files = ["src"]` 并开启 `ignore_missing_imports = true`，避免外部第三方包缺少存根引发报错。
  - `ruff` 配置 `exclude` 列表与 `src = ["src", "tests"]`。

---

## 二、 Ruff 防膨胀与质量规则阵列

在 `pyproject.toml` 的 `[tool.ruff]` 中配置了以下硬性规则：

| 规则代码 | 约束项 | 阈值限制 | 作用描述 |
| :--- | :--- | :--- | :--- |
| `C901` | mccabe 圈复杂度 | `max-complexity = 10` | 防止嵌套过深的条件逻辑 |
| `PLR0913` | 方法入参数量上限 | `max-args = 5` | 促使将复杂入参重构为 Pydantic/dataclass 参数对象 |
| `PLR0912` | 方法分支控制上限 | `max-branches = 12` | 促使拆分冗长 if-else 逻辑 |
| `PLR0915` | 方法内部语句数上限| `max-statements = 50` | 防止单个函数/方法膨胀 |
| `PLR0904` | 类中公共方法数上限| `max-public-methods = 15`| 防止出现 God Class 类膨胀 |
| `T20` | 禁用 print | 必须使用 `logger` | 确保生成标准日志 |
| `S` | 静态安全扫描 | 识别硬编码密钥与风险代码 | 保障安全性 |

---

## 三、 Mypy 严格模式与测试覆盖率门禁

1. **Mypy 严格模式**: 开启 `strict = true`，不支持任何隐式 `Any` 或遗漏函数类型提示。
2. **测试门禁**: 配置 `pytest-cov --cov-fail-under=75`，任何单元测试覆盖率低于 75% 的提交均会被 CI/CD 中断。
3. **Pre-commit 本地硬拦截**: 通过 `.pre-commit-config.yaml` 确保只有符合上述规则的代码才能成功执行 `git commit`；缓存通过 `PRE_COMMIT_HOME` 定位到项目内的 `.pre_commit_cache/`，避免沙箱访问 `~/.cache/pre-commit`。
