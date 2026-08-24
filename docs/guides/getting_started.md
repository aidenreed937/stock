# 开发者快速上手指南 (Getting Started)

指南涵盖环境搭建、包管理（基于 `uv`）以及日常开发中的代码检验与自动化测试流。

## 一、 环境要求

- **操作系统**: macOS / Linux / Windows
- **Python 版本**: Python >= 3.12
- **包管理器**: `uv` (版本 >= 0.5.0)

---

## 二、 基础开发流 (Workflow)

在沙箱或受限环境下，先将 uv 和 pre-commit 缓存放入项目内的忽略目录：

```bash
export UV_CACHE_DIR=.uv_cache
export UV_PYTHON_INSTALL_DIR=.uv_python
export PRE_COMMIT_HOME="$(pwd)/.pre_commit_cache"
```

### 1. 同步环境与依赖

使用 `uv` 一键拉取并构建隔离虚拟环境 `.venv`：

```bash
uv sync
```

### 2. 运行示范主程序

```bash
uv run python -m stock.main
```

### 3. 代码检查与自动化测试

在提交代码前，请依次执行以下本地验证指令：

```bash
# 1. 静态代码 Lint 与自动格式化修复
uv run ruff check --fix .

# 2. Mypy 严格类型检查
uv run mypy

# 3. 运行 pytest 单元测试套件与覆盖率统计
uv run pytest
```

---

## 三、 依赖安装规范

- **安装生产依赖**:
  ```bash
  uv add <package_name>
  ```
- **安装开发测试依赖**:
  ```bash
  uv add --dev <package_name>
  ```
- **安装 Git Pre-commit 钩子**:
  ```bash
  uv run pre-commit install
  ```

直接执行 `git commit` 前也要保留 `PRE_COMMIT_HOME` 环境变量；否则 pre-commit 会回退到用户目录下的默认缓存路径。
