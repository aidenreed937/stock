"""RAW 缓存读写共享字段规则。"""

from datetime import date

import polars as pl

from stock.core.contracts import DatasetKey

RAW_DATE_COLUMNS = ("trade_date", "date", "end_date", "month", "quarter")
RAW_RANGE_DATE_COLUMNS = ("trade_date", "date", "end_date")
RAW_SYMBOL_COLUMNS = ("symbol", "ts_code", "stockCode", "code")
RAW_PRIMARY_KEY_FALLBACK_COLUMNS = ("symbol", "stockCode", "ts_code", "code", "trade_date", "date")
RAW_ARTIFACT_SUFFIXES = (".bak.parquet", ".tmp.parquet")


def first_existing_column(frame: pl.DataFrame, candidates: tuple[str, ...]) -> str | None:
    """按候选顺序返回 DataFrame 中存在的第一列。"""
    return next((column for column in candidates if column in frame.columns), None)


def normalize_raw_date_series(series: pl.Series) -> pl.Series:
    """将源端日期文本归一为纯数字字符串，用于分区和范围判断。"""
    return (
        series.cast(pl.Utf8, strict=False)
        .str.replace(r"\.0+$", "")
        .str.replace_all(r"[^\d]", "")
    )


def month_key_for(key: DatasetKey, month_start: date) -> DatasetKey:
    """按月份生成与原始请求等价的 RAW 分区 key。"""
    return DatasetKey(
        provider=key.provider,
        dataset=key.dataset,
        endpoint=key.endpoint,
        start_date=month_start,
        end_date=date(month_start.year, month_start.month, 28),
        instrument=key.instrument,
        adjustment=key.adjustment,
        schema_version=key.schema_version,
    )
