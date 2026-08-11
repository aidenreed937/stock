"""数据标准化器抽象基类定义。"""

from abc import ABC, abstractmethod

import polars as pl


class BaseDataNormalizer(ABC):
    """行情数据标准化抽象基类。"""

    @abstractmethod
    def normalize(self, df: pl.DataFrame) -> pl.DataFrame:
        """对清洗后的数据执行字段别名对齐、数据类型转换与列排序等标准化操作。

        Args:
            df: 清洗后的 Polars DataFrame。

        Returns:
            pl.DataFrame: 标准化转换后的统一 Schema 数据帧。
        """
        pass
