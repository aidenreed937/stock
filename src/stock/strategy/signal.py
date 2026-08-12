"""交易信号模型，作为策略层与执行层之间的通信载体。"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import IntEnum


class SignalDirection(IntEnum):
    """交易信号方向枚举。"""

    BUY = 1
    SELL = -1
    CLOSE = 0


@dataclass
class Signal:
    """策略层输出的标准交易信号对象。

    使用 target_weight 作为核心驱动指标，便于复利计算与资金分配。
    """

    symbol: str
    direction: SignalDirection
    target_weight: float | None = None
    reason: str = ""
    timestamp: date | datetime | None = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        """校验目标仓位百分比。"""
        if self.target_weight is not None and not (0.0 <= self.target_weight <= 1.0):
            raise ValueError(f"target_weight 必须在 0.0 到 1.0 之间，当前: {self.target_weight}")
