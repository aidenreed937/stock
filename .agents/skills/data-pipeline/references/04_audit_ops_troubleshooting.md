# 数据审计、离线治理与故障排查手册 (Audit, Ops & Troubleshooting)

---

## 1. 统一数据审计与对账 CLI (Audit CLI)

```bash
# 1. 全库主数据资产物理盘点 (扫描所有 Parquet 统计标的、总行数与起止覆盖)
make master-audit
# 或
make audit TYPE=master

# 2. RAW vs Curated 1-to-1 物理对账 (确保清洗过程零丢行、成交额一致)
make audit TYPE=reconciliation

# 3. 估值指标专项对账 (daily_basic 每日估值对齐率)
make audit TYPE=valuation

# 4. 技术因子专项对账 (adj_factor 复权因子与行业日线)
make audit TYPE=factor

# 5. 全套系联动主审计
make audit TYPE=all
```

---

## 2. 离线治理与探针工具 (Data Ops)

> [!CAUTION]
> **高危操作安全红线（必须人工授权审查）**：
> 凡涉及直接修改/删除磁盘数据的操作（带 `APPLY=1`），**严禁大模型擅自自动执行**！
> 1. **默认只读预览 (Dry-Run)**：必须先执行不带 `APPLY=1` 的预览命令，向用户汇报拟处理的文件清单、影响记录数与预估效果；
> 2. **人工授权确认**：必须向用户明确陈述变更意图，获得用户明确确认（Review & Approval）后，方可执行 `APPLY=1`。

```bash
# 1. 全数据源连通性与时延探针检测 (只读安全)
make probe

# 2. 数据质量规则与隔离区校验 (只读安全)
make validate

# 3. 存量 Parquet 离线去重、Schema 升级与血统修补
make migrate-data           # [只读安全] 默认 Dry-run 预览变更计划
make migrate-data APPLY=1   # [高危写操作] 必须先做 Dry-run 并经用户明确授权

# 4. 清理过期临时与备份 Parquet 文件
make cleanup-data                           # [只读安全] 默认 Dry-run 预览待删文件
make cleanup-data APPLY=1 OLDER_THAN_DAYS=7 # [高危物理删除] 必须经用户明确授权
```

---

## 3. 常见故障与开发者排错指南

### ① Curated Schema 演进不匹配报错
**现象**：回填拉取清洗成功，但在写入 Parquet 时报错：
```text
Curated 文件 [...] schema 不匹配: 已有列 [...]，新数据列 [...]
```
**原因与解法**：
* 这是旧 Parquet 宽表与新增合法业务列集合不一致，**切勿删除已有 Parquet 后重跑**；
* 优先在 [`src/stock_data/storage/partition_writer.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock_data/storage/partition_writer.py) 为该数据集的已知合法新增列做受控对齐；
* 若历史残留冗余 dummy 列，在 [`src/stock_data/storage/compat.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock_data/storage/compat.py) 的 `StorageCompat.post_process_dataset()` 中做确定性后处理删除；
* 修复后直接重跑 `make backfill ... FORCE_REFRESH=1`。

### ② 单位口径与数值倍率原则
* **RAW 保真**：RAW 只保留上游原始数值和单位，不做任何乘除；
* **Curated 标准单位**：Curated 层金额统一为**元**、成交量统一为**股/份**、市值统一为**元**；
* **倍率规则位置**：所有倍率规则必须在 [`src/stock_data/pipeline/normalizer/unit_normalizer.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock_data/pipeline/normalizer/unit_normalizer.py) 中显式定义；
* **分析层无倍率**：分析层代码严禁根据数据源编写 `* 10000` 或 `* 1_000_000`。

### ③ 理杏仁 403 权限/额度耗尽
* 若返回 `403` 且提示 `Exceed maximum access time, please purchase Open API.`，按开放平台次数耗尽处理，**严禁死循环重试**，直接提示用户恢复 API 额度。

### ④ 落盘结果核验脚本
回填或同步后，快速验证本地 Parquet 行数与列非空：
```bash
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -c '
import polars as pl
p = "data/curated/tushare/market=CN/stock_daily_bar/year=2026/month=08/data.parquet"
df = pl.read_parquet(p)
print("Rows:", len(df), "Cols:", df.columns[:5], "Date Range:", df["trade_date"].min(), "->", df["trade_date"].max())
'
```
