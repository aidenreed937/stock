# Git 分支管理与提交规范

本文档定义了本量化交易与分析系统的 Git 分支管理策略与提交规范，适用于个人与独立开发者的高效开发流程。

---

## 1. 核心分支策略

采用 **主干驱动开发 (Trunk-Based Development)** + **短生命周期特性分支** 模式。

### 分支类型

| 分支类型 | 命名规范 | 描述与约束 |
| :--- | :--- | :--- |
| **主干分支** | `main` | 唯一受保护的主分支。代码永远保持可构建、测试全通过（100% 绿色）。禁止直接修改。 |
| **特性分支** | `feat/xxx` | 用于开发新功能或新模块（如 `feat/market-breadth`）。 |
| **修复分支** | `fix/xxx` | 用于修复已发现的 Bug 或类型错误（如 `fix/tushare-token`）。 |
| **重构分支** | `refactor/xxx` | 用于代码抽象优化与结构调整（如 `refactor/duckdb-store`）。 |
| **日常维护** | `chore/xxx` | 用于依赖升级、CI 配置更改或构建脚本调整（如 `chore/deps`）。 |

---

## 2. 规范化提交 (Conventional Commits)

提交信息一律采用 **Conventional Commits** 格式：

```text
<type>(<scope>): <short summary>

[optional body]
```

### Type 类型说明

- **`feat`**: 新功能 (Feature)
- **`fix`**: 修复 Bug
- **`refactor`**: 代码重构（既不加新功能也不修复 Bug）
- **`test`**: 增加或修改单元测试 / 集成测试
- **`docs`**: 文档更新（如修改 README、架构说明等）
- **`style`**: 格式调整（空格、缩进，不影响代码逻辑）
- **`chore`**: 构建工具、依赖库更新或辅助配置修改

### 示例

- `feat(strategy): add MACDCrossStrategy and Signal models`
- `fix(fetcher): resolve tushare pro_api initialization with missing token`
- `refactor(pipeline): implement GenericCleaner for non-kline endpoints`
- `test(analytics): add unit tests for MarketBreadthAnalyzer`

---

## 3. 标准开发与合并流程

### 步骤一：创建特性分支
开发新需求前，确保本地 `main` 处于最新状态，并切出分支：
```bash
git checkout main
git pull
git checkout -b feat/your-feature-name
```

### 步骤二：本地开发与频繁提交
小步快跑，每个逻辑自洽的修改单独提交一次：
```bash
git add .
git commit -m "feat(scope): brief description"
```

### 步骤三：质量门禁验证 (Quality Gate)
在合并前，**必须**运行全量门禁检查，确保格式、类型检查与测试 100% 通过：
```bash
make check
```

### 步骤四：线性 Fast-Forward 合并与清理
验证无误后，将分支合入 `main` 并清理已完成的分支：
```bash
# 切回主干
git checkout main

# 线性 Fast-Forward 合并 (保持线性 Git log)
git merge --ff-only feat/your-feature-name

# 删除本地临时分支
git branch -d feat/your-feature-name
```

---

## 4. 安全红线与禁止事项

1. **禁止破坏性操作**：严禁在 `main` 分支使用 `git push --force`、`git reset --hard` 或 `--no-verify`。
2. **禁止带脏提交**：提交前必须确保不包含敏感信息（如 `.env` 中的 `TUSHARE_TOKEN`）及临时数据文件。
3. **禁止长寿命分支**：特性分支生命周期尽量控制在 1-2 天内，避免累积巨大的 Merge 冲突。
