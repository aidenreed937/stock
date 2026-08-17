"""数据清洗器抽象基类定义。"""

from abc import ABC, abstractmethod

import polars as pl


class BaseDataCleaner(ABC):
    """行情数据清洗抽象基类。"""

    @abstractmethod
    def clean(self, df: pl.DataFrame) -> pl.DataFrame:
        """对传入的数据帧执行清洗、去重与合法性过滤。

        Args:
            df: 待清洗的原始 Polars DataFrame。

        Returns:
            pl.DataFrame: 清洗完成后的 Polars DataFrame。
        """
        pass
