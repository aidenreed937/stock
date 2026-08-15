"""指标输入数据 Schema 校验。"""

import polars as pl


def require_columns(df: pl.DataFrame, columns: tuple[str, ...], dataset: str) -> None:
    """检查指标输入数据是否包含必需字段。"""
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"{dataset} 缺少字段: {', '.join(missing)}")
