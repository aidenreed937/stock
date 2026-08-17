"""策略层专属异常定义。"""

from stock_core.exceptions import StockError


class StrategyError(StockError):
    """策略执行与风控计算相关异常"""

    pass
