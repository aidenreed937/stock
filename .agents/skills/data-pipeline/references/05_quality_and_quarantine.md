# 数据质量门禁与异常隔离区机制 (Quality Gate & Quarantine)

在 2-Tier ETL 流水线中，质量管理遵循 **“零静默丢弃、严格物理断言、异常透明隔离”** 原则。本专题指导大模型理解质量门禁规则与隔离区排查方法。

---

## 1. 全库数据质量门禁 (`QualityGate`)

* **源码位置**：[`src/stock_data/governance/quality/gate.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock_data/governance/quality/gate.py)
* **执行命令**：`make validate`

### ① K 线数据 (Bar Data) 物理有效性断言
对 `stock_daily_bar`、`index_daily_bar`、`fund_daily` 等行情数据集执行如下断言：
1. **必需列检查**：`symbol`, `trade_date`, `open`, `high`, `low`, `close`, `volume`, `amount` 必须全部存在且无全列空值；
2. **OHLC 几何逻辑**：
   * $\text{high} \ge \max(\text{open}, \text{close})$
   * $\text{low} \le \min(\text{open}, \text{close})$
   * $\text{high} \ge \text{low}$
3. **量价非负性**：$\text{amount} \ge 0$, $\text{volume} \ge 0$。

### ② 两融数据 (Margin Data) 质量与覆盖断言
* **数值质量**（[`src/stock_data/governance/quality/margin_quality.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock_data/governance/quality/margin_quality.py)）：
  * 融资余额 (`rzye`)、融券余量 (`rqyl`) $\ge 0$；
  * 买入额与偿还额的时序逻辑与极值波动跳变预警。
* **交易所覆盖完整性**（[`src/stock_data/governance/quality/margin_coverage.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock_data/governance/quality/margin_coverage.py)）：
  * 动态依据交易所历史真实上线基准日进行截面完整性检查：
    * **SSE (上交所)**: 2010-03-31 至今
    * **SZSE (深交所)**: 2010-03-31 至今
    * **BSE (北交所)**: 2023-02-13 至今
  * 早于上线日的交易所不要求记录，上线日之后若缺失对应交易所则断言失败。

---

## 2. 异常数据隔离区 (`QuarantineStore`)

* **源码位置**：[`src/stock_data/governance/quality/quarantine.py`](file:///Users/mac/workspace/personal/finance/stock/src/stock_data/governance/quality/quarantine.py)
* **物理落盘路径**：`data/quarantine/`

### ① 为什么使用隔离区（拒绝静默丢弃）
在 Stage 2 清洗阶段（`CleanerStage`），当遇到无法通过清洗规则的脏数据（如早于上市日期的假数据、OHLC 逻辑违背记录等），**严禁直接在内存中 `.drop()` 静默丢弃**。
必须调用 `QuarantineStore.write()` 将脏数据持久化至隔离区，以确保：
1. **审计可追溯**：清洗链路应记录主键去重、质量隔离和范围裁剪等处理结果；不能仅用 Curated 行数与 RAW 行数相等作为质量结论；
2. **归因排查**：发生数据缺口时，结合 Quarantine、回填验收和审计明细，区分规则拦截、合法去重、领域聚合以及上游源头未提供。

### ② 隔离区 Parquet 结构与元数据
写入隔离区的记录会在原始字段基础上追加以下审计列：
* `__quarantine_reason`：被隔离的具体原因（例如 `listing_date_violation`, `invalid_ohlc`）；
* `__quarantine_endpoint`：触发隔离的项目任务名；
* `__quarantine_source`：数据源标识（如 `tushare`）；
* `__quarantine_timestamp`：隔离发生时的 UTC 时间戳。

---

## 3. 隔离区排查与诊断实操

当发现 Curated 数据存在缺口但 API 回填成功时，运行以下单行命令排查是否落入隔离区：

```bash
UV_CACHE_DIR=.uv_cache UV_PYTHON_INSTALL_DIR=.uv_python uv run python -c '
import polars as pl
from pathlib import Path

q_root = Path("data/quarantine")
if q_root.exists():
    files = list(q_root.rglob("*.parquet"))
    print(f"隔离区文件数: {len(files)}")
    for f in files[:5]:
        df = pl.read_parquet(f)
        print(f"--- 文件: {f.name} (行数: {len(df)}) ---")
        if "__quarantine_reason" in df.columns:
            print("原因分布:", df["__quarantine_reason"].value_counts().to_dicts())
else:
    print("当前无隔离区数据 (数据质量完好)")
'
```
