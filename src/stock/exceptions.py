class StockError(Exception):
    """金融项目异常基类"""

    pass


class DataError(StockError):
    """数据处理相关异常基类"""

    pass


class DataFetchError(DataError):
    """外部数据源抓取/请求失败异常"""

    pass


class DataValidationError(DataError):
    """行情数据校验或 Schema 不匹配异常"""

    pass


class StorageError(DataError):
    """DuckDB / Parquet 存储与读写失败异常"""

    pass


class StrategyError(StockError):
    """策略执行与风控计算相关异常"""

    pass
