"""策略运行时上下文，隔离策略与真实账户/回测引擎的交互。"""

from dataclasses import dataclass
from datetime import date  # noqa: TC003


@dataclass
class Position:
    """单个标的持仓明细。"""

    symbol: str
    volume: float
    avg_cost: float
    last_price: float | None = None

    @property
    def market_value(self) -> float:
        """当前市值"""
        if self.last_price is not None:
            return self.volume * self.last_price
        return self.volume * self.avg_cost

    @property
    def unrealized_pnl(self) -> float:
        """未实现盈亏"""
        if self.last_price is not None:
            return (self.last_price - self.avg_cost) * self.volume
        return 0.0


class Context:
    """提供策略可读取的当前账户状态与系统时间。

    本对象应为只读，策略不直接修改它。执行引擎会在成交后更新该 Context。
    """

    def __init__(self, initial_cash: float = 100000.0) -> None:
        """初始化策略上下文。

        Args:
            initial_cash: 初始可用资金，默认 100000.0。
        """
        self.current_date: date | None = None
        self.cash: float = initial_cash
        self.positions: dict[str, Position] = {}

    @property
    def total_value(self) -> float:
        """计算当前账户总净值（现金 + 所有持仓市值）。"""
        pos_value = sum(pos.market_value for pos in self.positions.values())
        return self.cash + pos_value
