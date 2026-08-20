"""按数据任务契约裁剪 Fetcher 返回的业务日期范围。"""

from datetime import date

import polars as pl

from stock_core.utils.logger import logger
from stock_data.core.task_registry import is_task_partitioned, resolve_task
from stock_data.storage.raw_schema import normalize_raw_date_series


def _quarter_key(value: date) -> int:
    """将日期转换为可比较的自然季度序号。"""
    return value.year * 4 + (value.month - 1) // 3 + 1


def clip_endpoint_date_range(
    frame: pl.DataFrame,
    start_date: date,
    end_date: date,
    endpoint: str,
    data_source: str,
) -> pl.DataFrame:
    """按接口业务日期裁剪记录；TuShare 季度财报按报告期季度裁剪。"""
    task_fetch_mode = ""
    task_frequency = ""
    try:
        task = resolve_task(data_source, endpoint)
        task_fetch_mode = task.fetch_mode
        task_frequency = task.frequency
        if not is_task_partitioned(data_source, task.dataset) or task.frequency in (
            "static",
            "event",
        ):
            return frame
    except Exception:
        pass

    quarterly_report = (
        data_source == "tushare"
        and task_fetch_mode == "per_period"
        and task_frequency == "quarterly"
        and "end_date" in frame.columns
    )
    date_col = (
        "end_date"
        if quarterly_report
        else next(
            (
                c
                for c in (
                    "trade_date",
                    "date",
                    "report_date",
                    "ann_date",
                    "end_date",
                    "month",
                    "quarter",
                )
                if c in frame.columns
            ),
            "",
        )
    )
    if not date_col or frame.is_empty():
        return frame

    if date_col == "quarter":
        start_val = _quarter_key(start_date)
        end_val = _quarter_key(end_date)
        q_str = pl.col(date_col).cast(pl.Utf8, strict=False).str.to_uppercase()
        yr_expr = q_str.str.extract(r"(\d{4})").cast(pl.Int32, strict=False)
        q_expr = q_str.str.extract(r"Q(\d)").cast(pl.Int32, strict=False)
        q_val = yr_expr * 4 + q_expr
        clipped = frame.filter(q_val.is_between(start_val, end_val))
    elif quarterly_report:
        start_val = _quarter_key(start_date)
        end_val = _quarter_key(end_date)
        compact_date = normalize_raw_date_series(pl.col(date_col)).str.slice(0, 8)
        yr_expr = compact_date.str.slice(0, 4).cast(pl.Int32, strict=False)
        month_expr = compact_date.str.slice(4, 2).cast(pl.Int32, strict=False)
        q_expr = (
            pl.when(month_expr <= 3)
            .then(1)
            .when(month_expr <= 6)
            .then(2)
            .when(month_expr <= 9)
            .then(3)
            .when(month_expr <= 12)
            .then(4)
            .otherwise(None)
        )
        q_val = yr_expr * 4 + q_expr
        clipped = frame.filter(q_val.is_between(start_val, end_val))
    elif date_col == "month":
        start_val = start_date.year * 100 + start_date.month
        end_val = end_date.year * 100 + end_date.month
        norm_expr = (
            pl.col(date_col)
            .cast(pl.Utf8, strict=False)
            .str.replace_all("-", "")
            .str.slice(0, 6)
            .cast(pl.Int32, strict=False)
        )
        clipped = frame.filter(norm_expr.is_between(start_val, end_val))
    else:
        start_val = int(start_date.strftime("%Y%m%d"))
        end_val = int(end_date.strftime("%Y%m%d"))
        norm_expr = (
            pl.col(date_col)
            .cast(pl.Utf8, strict=False)
            .str.replace_all("-", "")
            .str.slice(0, 8)
            .cast(pl.Int32, strict=False)
        )
        clipped = frame.filter(norm_expr.is_between(start_val, end_val))

    if len(clipped) != len(frame):
        logger.warning(
            f"接口 [{endpoint}] 丢弃源端请求范围外记录 {len(frame) - len(clipped)} 行 "
            f"(请求范围 {start_date} ~ {end_date}, 日期列 {date_col})"
        )
    return clipped
