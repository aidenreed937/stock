"""排雷规则输入与样本池构造纯函数。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from stock_analytics.pipelines.stock_screen.sources import StockScreenSources
    from stock_reporting.interpretation.stock_screen.config import RuleConfig


def build_universe(
    frame: pl.DataFrame,
    symbols: Sequence[str],
    as_of_date: date,
) -> pl.DataFrame:
    """按标的范围与上市/退市状态构造有效样本池。"""
    if frame.is_empty() or "symbol" not in frame.columns:
        return pl.DataFrame(
            schema={
                "symbol": pl.String,
                "name": pl.String,
                "industry": pl.String,
                "list_date": pl.Date,
                "market": pl.String,
            }
        )
    result = frame
    if symbols:
        result = result.filter(pl.col("symbol").is_in(list(symbols)))
    if "list_status" in result.columns:
        result = result.filter(
            pl.col("list_status")
            .cast(pl.String, strict=False)
            .str.to_uppercase()
            .is_in(["L", "上市"])
        )
    if "list_date" in result.columns:
        result = result.filter(pl.col("list_date").is_null() | (pl.col("list_date") <= as_of_date))
    if "delist_date" in result.columns:
        result = result.filter(
            pl.col("delist_date").is_null() | (pl.col("delist_date") > as_of_date)
        )
    if "industry" not in result.columns:
        result = result.with_columns(
            pl.col("industry_name").cast(pl.String, strict=False).alias("industry")
            if "industry_name" in result.columns
            else pl.lit(None, dtype=pl.String).alias("industry")
        )
    return result.unique(subset=["symbol"], keep="last")


def rule_input(
    rule: RuleConfig,
    sources: StockScreenSources,
    universe: pl.DataFrame,
    as_of_date: date,
    rule_datasets: dict[str, str],
) -> pl.DataFrame:
    """根据规则需求裁剪和构造输入数据帧。"""
    if rule.rule_id in {"st_marked", "too_new_listing"}:
        return universe
    if rule.rule_id == "suspended":
        return suspension_input(sources, as_of_date)
    if rule.rule_id == "receivables_revenue_distortion":
        bs = sources.get("balancesheet")
        inc = sources.get("income")
        if bs.is_empty() or inc.is_empty():
            return pl.DataFrame()
        join_cols = [
            c for c in ("symbol", "end_date", "ann_date") if c in bs.columns and c in inc.columns
        ]
        if not join_cols:
            return pl.DataFrame()
        inc_cols = [c for c in ("revenue", "total_revenue") if c in inc.columns]
        if not inc_cols:
            return pl.DataFrame()
        return bs.join(inc.select([*join_cols, *inc_cols]), on=join_cols, how="inner")
    dataset = rule_datasets.get(rule.rule_id)
    frame = sources.get(dataset or "")
    if dataset in {"daily_basic", "stock_daily_bar"}:
        return at_as_of(frame, "trade_date", as_of_date)
    return frame


def suspension_input(sources: StockScreenSources, as_of_date: date) -> pl.DataFrame:
    """构造停牌规则输入的行情与停牌记录。"""
    frames: list[pl.DataFrame] = []
    bars = sources.get("stock_daily_bar")
    if not bars.is_empty():
        frames.append(
            bars.select([column for column in ("symbol", "trade_date") if column in bars.columns])
        )
    suspensions = sources.get("suspend_d")
    if not suspensions.is_empty():
        selected = suspensions
        if "suspend_date" not in selected.columns and "trade_date" in selected.columns:
            selected = selected.with_columns(pl.col("trade_date").alias("suspend_date"))
        selected = selected.select(
            [
                column
                for column in ("symbol", "trade_date", "suspend_date", "suspend_type")
                if column in selected.columns
            ]
        )
        frames.append(selected)
    if not frames:
        return pl.DataFrame()
    combined = pl.concat(frames, how="diagonal_relaxed")
    if "trade_date" in combined.columns:
        combined = combined.filter(
            pl.col("trade_date").is_null() | (pl.col("trade_date") <= as_of_date)
        )
    if "suspend_date" in combined.columns:
        combined = combined.filter(
            pl.col("suspend_date").is_null() | (pl.col("suspend_date") <= as_of_date)
        )
    return combined


def at_as_of(frame: pl.DataFrame, date_column: str, as_of_date: date) -> pl.DataFrame:
    """过滤指定日期列等于基准日的行。"""
    if frame.is_empty() or date_column not in frame.columns:
        return pl.DataFrame()
    return frame.filter(pl.col(date_column) == as_of_date)


__all__ = ["at_as_of", "build_universe", "rule_input", "suspension_input"]
