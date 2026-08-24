# 代码编写规范 (Coding Guidelines)

本文档定义了本项目团队统一遵循的编码格式、命名约定、类型注解及异常处理规范。

## 一、 命名规范

- **模块/文件名**: 全小写 + 下划线（snake_case），例如 `duckdb_store.py`。
- **类名**: 大驼峰（PascalCase），例如 `DuckDBMarketStore`, `TuShareDataFetcher`。
- **函数/变量/属性**: 小写 + 下划线（snake_case），例如 `fetch_daily_bars_df`。
- **常量**: 全大写 + 下划线（UPPER_SNAKE_CASE），例如 `DEFAULT_TIMEOUT_SECONDS = 30`。

---

## 二、 类型标注规范 (Strict Typing)

1. **100% 类型覆盖**: 所有函数的入参和返回值必须显式标注类型（Mypy Strict 模式要求）。
2. **使用现代 Python 3.12+ 联合类型**:
   - 使用 `int | None` 替代 `Optional[int]`。
   - 使用 `list[str]`, `dict[str, Any]` 替代 `typing.List`, `typing.Dict`。
3. **不可变数据优先**: 传递批量行情数据时优先使用不可变数据结构或 `polars.DataFrame`。

---

## 三、 异常处理规范

1. **严禁静默吞隐异常**: 严禁写裸露的 `except: pass` 或捕获 `Exception` 后无任何日志记录。
2. **领域异常层级**: 所有业务异常必须继承自基础类 `StockError` ([src/stock_core/exceptions.py](../../src/stock_core/exceptions.py))：
   ```text
   StockError (基类)
   ├── DataError
   │   ├── DataFetchError      # 外部数据抓取失败/超时
   │   ├── DataValidationError # Pydantic 或数据校验失败
   │   └── StorageError        # DuckDB / Parquet 读写失败
   └── StrategyError           # 策略或风控计算异常
   ```

---

## 四、 注释与 Docstring 规范

- 函数与类统一使用 **Google Docstring** 格式。
- 说明参数含义、返回值类型及可能的异常抛出。
