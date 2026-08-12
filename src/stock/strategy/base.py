"""策略基础框架抽象基类。"""

from abc import ABC, abstractmethod
from typing import Any

from stock.strategy.context import Context
from stock.strategy.signal import Signal


class BaseStrategy(ABC):
    """所有自定义交易策略必须继承的基类。

    提供标准化生命周期方法，确保无论在回测还是实盘都能无缝运行。
    """

    def __init__(self, context: Context | None = None) -> None:
        """初始化策略，注入全局上下文。

        Args:
            context: 由引擎提供的回测/实盘上下文。若为空则创建默认上下文。
        """
        self.context = context or Context()

    def on_init(self) -> None:  # noqa: B027
        """【生命周期钩子】策略初始化。

        适用于预热指标计算、加载机器学习模型权重等只需要运行一次的操作。
        """
        pass

    @abstractmethod
    def on_bar(self, data: Any) -> list[Signal]:
        """【核心方法】处理到达的新行情数据。

        Args:
            data: 引擎推入的数据，可以是单条记录或包含历史视窗的 DataFrame。

        Returns:
            list[Signal]: 返回要在当前周期末触发的交易信号列表。
        """
        pass
