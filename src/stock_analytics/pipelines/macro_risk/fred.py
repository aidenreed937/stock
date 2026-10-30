"""宏观风控使用的 FRED DFF 日频序列与水位工具。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_analytics.primitives import add_dff_availability_date, calculate_dff_change_6m

_DEFAULT_CURATED_ROOT = Path("data/curated/fred/market=US")
_CANDIDATE_DATASETS = ("dff", "macro_indicators")


def _to_date(val: Any) -> date | None:
    return val if isinstance(val, date) else None


@dataclass(frozen=True, slots=True)
class DFFSeries:
    """标准化后的 DFF 序列及其实际来源。"""

    frame: pl.DataFrame
    latest_observation_date: date | None
    source_dataset: str | None
    source_path: Path | None


@dataclass(frozen=True, slots=True)
class DFFSnapshot:
    """截至指定 A 股市场日期可见的 DFF 六个月变化与观测水位。"""

    change_6m: float | None
    observation_date: date | None
    source_dataset: str | None


@dataclass(frozen=True, slots=True)
class FedFundsSeries:
    """兼容历史脚本的月频 FEDFUNDS 序列。生产因子已迁移至 DFF。"""

    frame: pl.DataFrame
    latest_observation_date: date | None
    source_dataset: str | None
    source_path: Path | None


@dataclass(frozen=True, slots=True)
class FedFundsSnapshot:
    """兼容旧报告调用方的月频 FEDFUNDS 快照。"""

    change_6m: float | None
    observation_date: date | None
    source_dataset: str | None


def _empty_series_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": pl.Series([], dtype=pl.Date),
            "value": pl.Series([], dtype=pl.Float64),
        }
    )


def _read_candidate(path: Path) -> pl.DataFrame:
    try:
        frame = pl.read_parquet(path)
    except Exception:
        return _empty_series_frame()

    if "symbol" not in frame.columns or "value" not in frame.columns:
        return _empty_series_frame()
    date_column = "trade_date" if "trade_date" in frame.columns else "observation_date"
    if date_column not in frame.columns:
        return _empty_series_frame()

    return (
        frame.filter(pl.col("symbol").cast(pl.String, strict=False) == "DFF")
        .select(
            pl.col(date_column).cast(pl.Date, strict=False).alias("trade_date"),
            pl.col("value").cast(pl.Float64, strict=False).alias("value"),
        )
        .drop_nulls()
        .unique(subset=["trade_date"], keep="last")
        .sort("trade_date")
    )


def load_dff_series(
    curated_root: Path | str = _DEFAULT_CURATED_ROOT,
) -> DFFSeries:
    """读取 DFF，兼容独立表与聚合 FRED 表两种落盘位置。

    ``dff`` 是首选标准表；若其观测水位低于聚合表，则选择水位更高的候选，
    防止标准表尚未同步时静默回退到更旧数据。相同水位时优先 ``dff``。
    """
    root = Path(curated_root)
    candidates: list[tuple[int, str, Path, pl.DataFrame]] = []
    for priority, dataset in enumerate(_CANDIDATE_DATASETS):
        path = root / dataset / "data.parquet"
        frame = _read_candidate(path)
        if not frame.is_empty():
            candidates.append((priority, dataset, path, frame))

    if not candidates:
        return DFFSeries(_empty_series_frame(), None, None, None)

    _, dataset, path, frame = max(
        candidates,
        key=lambda item: (_to_date(item[3]["trade_date"].max()) or date.min, -item[0]),
    )
    return DFFSeries(frame, _to_date(frame["trade_date"].max()), dataset, path)


def load_dff_snapshot(
    target_date: date | None,
    curated_root: Path | str = _DEFAULT_CURATED_ROOT,
) -> DFFSnapshot:
    """返回目标 A 股交易日可见的 DFF 六个月变化及其原始观测日期。"""
    series = load_dff_series(curated_root)
    if series.frame.is_empty():
        return DFFSnapshot(None, None, None)

    visible = add_dff_availability_date(series.frame)
    if target_date is not None:
        visible = visible.filter(pl.col("available_date") <= target_date)
    observation_date = _to_date(visible["trade_date"].max()) if not visible.is_empty() else None

    changes = calculate_dff_change_6m(series.frame)
    if target_date is not None:
        changes = changes.filter(pl.col("trade_date") <= target_date)
    if changes.is_empty():
        return DFFSnapshot(None, observation_date, series.source_dataset)

    latest = changes.tail(1)
    value = latest["ffr_chg_6m"][0]
    change_observation_date = _to_date(latest["observation_date"][0])
    return DFFSnapshot(
        float(value) if value is not None else None,
        change_observation_date,
        series.source_dataset,
    )


def load_fedfunds_series(
    curated_root: Path | str = _DEFAULT_CURATED_ROOT,
) -> FedFundsSeries:
    """兼容读取旧 FEDFUNDS 数据，不供生产宏观因子使用。"""
    root = Path(curated_root)
    candidates: list[tuple[int, str, Path, pl.DataFrame]] = []
    for priority, dataset in enumerate(("fedfunds", "macro_indicators")):
        path = root / dataset / "data.parquet"
        try:
            frame = pl.read_parquet(path)
        except Exception:
            continue
        date_column = "trade_date" if "trade_date" in frame.columns else "observation_date"
        if not {"symbol", "value", date_column}.issubset(frame.columns):
            continue
        frame = (
            frame.filter(pl.col("symbol").cast(pl.String, strict=False) == "FEDFUNDS")
            .select(
                pl.col(date_column).cast(pl.Date, strict=False).alias("trade_date"),
                pl.col("value").cast(pl.Float64, strict=False),
            )
            .drop_nulls()
            .unique(subset=["trade_date"], keep="last")
            .sort("trade_date")
        )
        if not frame.is_empty():
            candidates.append((priority, dataset, path, frame))
    if not candidates:
        return FedFundsSeries(_empty_series_frame(), None, None, None)
    _, dataset, path, frame = max(
        candidates,
        key=lambda item: (_to_date(item[3]["trade_date"].max()) or date.min, -item[0]),
    )
    return FedFundsSeries(frame, _to_date(frame["trade_date"].max()), dataset, path)


def build_fedfunds_change_6m(frame: pl.DataFrame) -> pl.DataFrame:
    """兼容历史月频 FEDFUNDS diff(6) 口径，不供生产因子使用。"""
    if frame.is_empty() or not {"trade_date", "value"}.issubset(frame.columns):
        return pl.DataFrame(schema={"trade_date": pl.Date, "ffr_chg_6m": pl.Float64})
    return (
        frame.select(
            pl.col("trade_date").cast(pl.Date, strict=False),
            pl.col("value").cast(pl.Float64, strict=False),
        )
        .drop_nulls()
        .sort("trade_date")
        .with_columns(pl.col("value").diff(6).alias("ffr_chg_6m"))
        .select(["trade_date", "ffr_chg_6m"])
        .drop_nulls()
    )


def load_fedfunds_snapshot(
    target_date: date | None,
    curated_root: Path | str = _DEFAULT_CURATED_ROOT,
) -> FedFundsSnapshot:
    """兼容旧报告读取月频 FEDFUNDS 快照，不供生产宏观因子使用。"""
    series = load_fedfunds_series(curated_root)
    visible = series.frame
    if target_date is not None:
        visible = visible.filter(pl.col("trade_date") <= target_date)
    observation_date = _to_date(visible["trade_date"].max()) if not visible.is_empty() else None
    changes = build_fedfunds_change_6m(series.frame)
    if target_date is not None:
        changes = changes.filter(pl.col("trade_date") <= target_date)
    if changes.is_empty():
        return FedFundsSnapshot(None, observation_date, series.source_dataset)
    value = changes.tail(1)["ffr_chg_6m"][0]
    return FedFundsSnapshot(
        float(value) if value is not None else None,
        observation_date,
        series.source_dataset,
    )


__all__ = [
    "DFFSeries",
    "DFFSnapshot",
    "FedFundsSeries",
    "FedFundsSnapshot",
    "build_fedfunds_change_6m",
    "load_dff_series",
    "load_dff_snapshot",
    "load_fedfunds_series",
    "load_fedfunds_snapshot",
]
