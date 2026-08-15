"""指标标准长表输出。"""

from datetime import date

import polars as pl


def to_long_format(
    df: pl.DataFrame,
    *,
    trade_date: date,
    entity_col: str,
    metric_cols: tuple[str, ...],
) -> pl.DataFrame:
    """将宽表指标转换为 date/entity/metric/value 标准长表。"""
    if df.is_empty():
        return pl.DataFrame(
            schema={
                "trade_date": pl.Date,
                "entity": pl.String,
                "metric": pl.String,
                "value": pl.Float64,
            }
        )

    return (
        df.select([pl.col(entity_col).alias("entity"), *[pl.col(col) for col in metric_cols]])
        .unpivot(index="entity", variable_name="metric", value_name="value")
        .with_columns(pl.lit(trade_date).alias("trade_date"))
        .select(["trade_date", "entity", "metric", "value"])
    )
