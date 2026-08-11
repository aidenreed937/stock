# 数据处理流水线与存储契约 (Data Pipeline & Storage)

针对金融数据**强时序性**、**数据量大**及**外部接口变动频繁**的特点，本项目建立了标准的四阶段数据处理流水线。

## 一、 数据流转步骤

```text
[1. Fetch (抓取)] ──> [2. Validate (校验)] ──> [3. Cache (存储)] ──> [4. Compute (计算)]
```

### 1. Fetch (数据抓取)
- **适配器抽象**: `BaseDataFetcher` 统一定义 `fetch_daily_bars` 与 `fetch_daily_bars_df` 接口。
- **扩展策略**: 当对接 AkShare、TuShare 或 Yahoo Finance 时，只需继承 `BaseDataFetcher` 并在子类中封装具体的网络请求。

### 2. Validate (数据校验)
- **模型校验**: 使用 Pydantic 模型 `DailyBar` 对从外部 API 获取的原始 JSON/Dictionary 数据进行类型转换与逻辑约束。
- **业务规约**: 触发如“最高价不能低于开盘价/最低价”、“开盘价/收盘价必须大于 0”等物理约束检查。

### 3. Cache & Storage (存储与检索)
- **Parquet 列式存储**: 经过校验的数据通过 Polars 直接落盘为二进制 `.parquet` 文件，体积小且加载极快。
- **DuckDB 极速 SQL 查询**: 内存中挂载 DuckDB 引擎，可通过 SQL 语句直接跨 Parquet 文件检索，例如：
  ```sql
  SELECT * FROM 'data/parquet/daily_600000_SH.parquet' WHERE close >= 98.0 ORDER BY trade_date ASC;
  ```

### 4. Compute (向量化计算)
- 基于 Polars 的高效算子进行多维技术指标计算（如 SMA、EMA、RSI），避免传统 Python 显式 `for` 循环带来的性能瓶颈。
