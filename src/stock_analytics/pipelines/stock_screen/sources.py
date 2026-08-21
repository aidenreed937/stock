"""个股排雷数据源加载与基准日对齐。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from stock_analytics.catalog_compat import load_dataset_compat
from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog
from stock_reporting.interpretation.stock_screen.config import StockScreenConfig

_DATASET_COLUMNS: dict[str, tuple[str, ...]] = {
    "stock_basic": (
        "symbol",
        "ts_code",
        "name",
        "list_date",
        "delist_date",
        "list_status",
        "market",
    ),
    "stock_daily_bar": ("symbol", "trade_date", "amount", "close"),
    "daily_basic": (
        "symbol",
        "trade_date",
        "close",
        "pe",
        "pb",
        "total_mv",
        "circ_mv",
        "turnover_rate",
    ),
    "income": ("symbol", "ts_code", "ann_date", "end_date", "n_income"),
    "fina_indicator": ("symbol", "ts_code", "ann_date", "end_date", "netprofit_yoy", "roe"),
    "balancesheet": (
        "symbol",
        "ts_code",
        "ann_date",
        "end_date",
        "total_hldr_eqy_exc_min_int",
        "goodwill",
    ),
    "forecast": (
        "symbol",
        "ts_code",
        "ann_date",
        "end_date",
        "p_change_min",
        "p_change_max",
    ),
    "stk_holdertrade": (
        "symbol",
        "ts_code",
        "ann_date",
        "begin_date",
        "close_date",
        "in_de",
        "change_vol",
    ),
    "hk_hold": ("symbol", "ts_code", "trade_date", "vol", "sharehold", "hold_vol", "ratio"),
    "limit_list_d": ("symbol", "ts_code", "trade_date", "limit", "limit_type", "pct_chg"),
    "suspend_d": ("symbol", "ts_code", "trade_date", "suspend_date", "suspend_type"),
    "regulatory_measures": (
        "symbol",
        "stockCode",
        "date",
        "type",
        "displayTypeText",
        "linkText",
        "linkUrl",
        "linkType",
        "referent",
    ),
    "exchange_inquiry": (
        "symbol",
        "stockCode",
        "date",
        "type",
        "displayTypeText",
        "linkText",
        "linkUrl",
        "linkType",
    ),
    "unlock_summary": (
        "symbol",
        "stockCode",
        "last_data_date",
        "srl_last",
        "srl_cap_r_last",
        "elr_s_y1",
        "elr_s_cap_r_y1",
        "elr_mc_y1",
    ),
    "index_member": ("index_code", "con_code", "in_date", "out_date"),
    "index_classify": ("index_code", "industry_name", "level", "src", "is_pub"),
    "index_daily_bar": ("symbol", "trade_date", "close"),
    "cashflow": ("symbol", "ts_code", "ann_date", "end_date", "n_cashflow_act"),
}

_EVENT_DATASETS = frozenset({"forecast", "stk_holdertrade", "hk_hold", "limit_list_d", "suspend_d"})


@dataclass(frozen=True, slots=True)
class StockScreenSources:
    """一次排雷运行加载的数据帧与可用性信息。"""

    frames: Mapping[str, pl.DataFrame]
    available: Mapping[str, bool]
    data_gaps: tuple[dict[str, str], ...]

    def get(self, dataset: str) -> pl.DataFrame:
        """返回数据集；缺失时返回空数据帧。"""
        return self.frames.get(dataset, pl.DataFrame())


def build_industry_map(
    sources: StockScreenSources,
    as_of_date: date,
) -> pl.DataFrame:
    """按基准日构建 申万 L1/L2 行业归属表。

    以 index_member 的活跃成员（in_date<=as_of<out_date）为基准，
    通过 index_classify 关联行业名，返回 symbol/l1_name/l2_name。
    """
    members = sources.get("index_member")
    classify = sources.get("index_classify")
    if members.is_empty() or classify.is_empty():
        return pl.DataFrame()
    required = {"index_code", "con_code", "in_date", "out_date"}
    if not required.issubset(set(members.columns)):
        return pl.DataFrame()
    if "index_code" not in classify.columns or "industry_name" not in classify.columns:
        return pl.DataFrame()

    l1 = (
        classify.filter(pl.col("level") == "L1")
        .pipe(_prefer_sw2021)
        .select("index_code", pl.col("industry_name").alias("l1_name"))
    )
    l2 = (
        classify.filter(pl.col("level") == "L2")
        .pipe(_prefer_sw2021)
        .select("index_code", pl.col("industry_name").alias("l2_name"))
    )
    active = members.filter(
        (pl.col("in_date") <= pl.lit(as_of_date))
        & (pl.col("out_date").is_null() | (pl.col("out_date") > pl.lit(as_of_date)))
    ).select("con_code", "index_code")

    result = (
        active.join(l2, on="index_code", how="inner")
        .select("con_code", "l2_name")
        .rename({"con_code": "symbol"})
        .unique(subset=["symbol"], keep="first")
    )
    l1_map = (
        active.join(l1, on="index_code", how="inner")
        .select("con_code", "l1_name")
        .rename({"con_code": "symbol"})
        .filter(pl.col("l1_name").is_not_null())
        .unique(subset=["symbol"], keep="first")
    )
    result = result.join(l1_map, on="symbol", how="left")
    return result.with_columns(pl.col("symbol").cast(pl.String))


def _prefer_sw2021(frame: pl.DataFrame) -> pl.DataFrame:
    """同一 index_code 存在 SW2014/SW2021 两套记录时优先保留 SW2021。"""
    if "src" not in frame.columns:
        return frame.unique(subset=["index_code"], keep="first")
    return (
        frame.with_columns(
            pl.when(pl.col("src") == "SW2021").then(0).otherwise(1).alias("_src_rank")
        )
        .sort("_src_rank")
        .unique(subset=["index_code"], keep="first")
        .drop("_src_rank")
    )


def resolve_as_of_date(
    target_date: date | None = None,
    *,
    storage_dir: Path | str | None = None,
    catalog: Any | None = None,
) -> date:
    """解析全市场日频数据共同可用的基准日。"""
    if target_date is not None:
        return target_date
    active_catalog = catalog or DataCatalog(data_source="tushare", storage_dir=storage_dir)
    latest_dates: list[date] = []
    for dataset in ("stock_daily_bar", "daily_basic"):
        try:
            values = active_catalog.latest_trade_dates(dataset=dataset, n=1)
        except TypeError:
            values = active_catalog.latest_trade_dates(dataset, n=1)
        except Exception as exc:
            logger.debug(f"读取 {dataset} 最新交易日失败: {exc}")
            values = []
        latest_dates.extend(value for value in values if isinstance(value, date))
    if latest_dates:
        return min(latest_dates)

    frame = load_dataset(
        active_catalog,
        "stock_daily_bar",
        columns=("symbol", "trade_date"),
    )
    normalized = _normalize_frame(frame)
    if "trade_date" in normalized.columns and not normalized.is_empty():
        latest = normalized.get_column("trade_date").max()
        if isinstance(latest, date):
            return latest
    raise ValueError("本地没有可用的 stock_daily_bar/daily_basic 交易日，无法解析 as_of")


def load_stock_screen_sources(
    config: StockScreenConfig,
    as_of_date: date,
    *,
    storage_dir: Path | str | None = None,
    catalogs: Mapping[str, Any] | None = None,
) -> StockScreenSources:
    """按配置加载排雷数据，并将日期裁剪到基准日。"""
    frames: dict[str, pl.DataFrame] = {}
    available: dict[str, bool] = {}
    gaps: list[dict[str, str]] = []
    catalog_cache: dict[str, Any] = dict(catalogs or {})
    for item in config.datasets:
        if not item.enabled:
            gaps.append(_gap(item.data_source, item.dataset, "disabled", item.note))
            continue
        if item.dataset in frames:
            continue
        try:
            active_catalog = catalog_cache.get(item.data_source)
            if active_catalog is None:
                active_catalog = DataCatalog(data_source=item.data_source, storage_dir=storage_dir)
                catalog_cache[item.data_source] = active_catalog
            frame = _load_configured_dataset(
                active_catalog,
                item.dataset,
                as_of_date,
                symbols=list(config.symbols) or None,
                static=item.static,
            )
        except Exception as exc:
            frame = pl.DataFrame()
            gaps.append(_gap(item.data_source, item.dataset, "unavailable", str(exc)))
        normalized = _normalize_frame(frame)
        if not item.static:
            normalized = _clip_as_of(normalized, as_of_date)
        frames[item.dataset] = normalized
        available[item.dataset] = not normalized.is_empty()
        if normalized.is_empty() and not any(gap["dataset"] == item.dataset for gap in gaps):
            gaps.append(_gap(item.data_source, item.dataset, "missing", item.note))

    return StockScreenSources(frames=frames, available=available, data_gaps=tuple(gaps))


def load_dataset(
    catalog: Any,
    dataset: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    symbols: list[str] | None = None,
    columns: Sequence[str] | None = None,
) -> pl.DataFrame:
    """从 DataCatalog 读取指定数据集；目录异常时返回空帧。"""
    try:
        return load_dataset_compat(
            catalog,
            dataset,
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
            columns=columns,
        )
    except Exception as exc:
        logger.debug(f"加载排雷数据集 {dataset} 失败: {exc}")
        return pl.DataFrame()


def _load_configured_dataset(
    catalog: Any,
    dataset: str,
    as_of_date: date,
    *,
    symbols: list[str] | None,
    static: bool,
) -> pl.DataFrame:
    start_date = None if static else as_of_date - timedelta(days=730)
    return load_dataset(
        catalog,
        dataset,
        start_date=start_date,
        end_date=None if static else as_of_date,
        symbols=symbols,
        columns=_DATASET_COLUMNS.get(dataset),
    )


def _normalize_frame(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty():
        return frame
    normalized = frame
    if "symbol" not in normalized.columns:
        for candidate in ("ts_code", "stockCode", "code"):
            if candidate in normalized.columns:
                normalized = normalized.rename({candidate: "symbol"})
                break
    if "symbol" in normalized.columns:
        normalized = normalized.with_columns(pl.col("symbol").cast(pl.String, strict=False))
    for column in (
        "trade_date",
        "ann_date",
        "end_date",
        "begin_date",
        "close_date",
        "suspend_date",
        "list_date",
        "delist_date",
    ):
        if column in normalized.columns:
            normalized = normalized.with_columns(_date_expr(column))
    return normalized


def _date_expr(column: str) -> pl.Expr:
    return pl.col(column).map_elements(_parse_date, return_dtype=pl.Date).alias(column)


def _parse_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip().replace("-", "")[:8]
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def _clip_as_of(frame: pl.DataFrame, as_of_date: date) -> pl.DataFrame:
    if frame.is_empty():
        return frame
    date_column = next(
        (
            column
            for column in ("trade_date", "ann_date", "end_date", "suspend_date")
            if column in frame.columns
        ),
        None,
    )
    if date_column is None:
        return frame
    return frame.filter(pl.col(date_column) <= pl.lit(as_of_date))


def _gap(data_source: str, dataset: str, status: str, note: str) -> dict[str, str]:
    return {
        "data_source": data_source,
        "dataset": dataset,
        "status": status,
        "note": note or f"{data_source}.{dataset} 不可用",
    }


__all__ = [
    "StockScreenSources",
    "build_industry_map",
    "load_dataset",
    "load_stock_screen_sources",
    "resolve_as_of_date",
]
