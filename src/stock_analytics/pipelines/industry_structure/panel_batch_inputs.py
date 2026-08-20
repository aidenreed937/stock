"""行业结构面板批次输入的预处理与缓存。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from stock_analytics.pipelines.industry_structure.industry_mapping import (
    _is_current_industry_date,
    _stock_industry_map_from_lixinger_constituents,
    load_industry_l1_maps,
    prepare_stock_industry_members,
    stock_industry_map_from_prepared_members,
)
from stock_analytics.pipelines.industry_structure.panel_metrics_batch import (
    fundamental_panel_batch,
    valuation_panel_batch,
)
from stock_analytics.pipelines.industry_structure.panel_sources import (
    date_column_expr,
    load_dataset,
    load_moneyflow_base_frame,
    load_stock_amount_frame,
    optional_numeric_expr,
    optional_text_expr,
)

if TYPE_CHECKING:
    from stock_core.contracts import MarketDataCatalog
    from stock_reporting.interpretation.industry_structure.config import IndustryStructureConfig


@dataclass(slots=True)
class IndustryPanelBatchInputs:
    """行业面板批次内预处理的按日输入。"""

    cat_ts: MarketDataCatalog
    cat_lx: MarketDataCatalog
    config: IndustryStructureConfig
    forecast_by_date: dict[date, pl.DataFrame]
    express_by_date: dict[date, pl.DataFrame]
    report_revision_by_date: dict[date, pl.DataFrame]
    moneyflow_by_date: dict[date, pl.DataFrame]
    stock_amount_by_date: dict[date, pl.DataFrame]
    valuation_by_date: dict[date, pl.DataFrame]
    fundamental_by_date: dict[date, pl.DataFrame]
    stock_industry_members: pl.DataFrame
    index_to_l1: dict[str, str]
    industry_to_l1: dict[str, str]
    _stock_maps: dict[date, pl.DataFrame] = field(default_factory=dict)
    _current_lixinger_map: pl.DataFrame | None = None

    @classmethod
    def prepare(
        cls,
        cat_ts: MarketDataCatalog,
        cat_lx: MarketDataCatalog,
        config: IndustryStructureConfig,
        *,
        target_dates: tuple[date, ...],
        moneyflow_start_date: date,
        end_date: date,
    ) -> IndustryPanelBatchInputs:
        """一次读取并预处理批次内会反复使用的事件与资金流输入。"""
        index_to_l1, industry_to_l1 = load_industry_l1_maps(cat_ts, config)
        stock_industry_members = prepare_stock_industry_members(cat_ts, index_to_l1)
        forecast = _prepare_forecast_frame(
            load_dataset(
                cat_ts,
                "forecast",
                columns=[
                    "symbol",
                    "ann_date",
                    "end_date",
                    "type",
                    "p_change_min",
                    "p_change_max",
                ],
            )
        )
        express = _prepare_express_frame(
            load_dataset(
                cat_ts,
                "express",
                columns=[
                    "symbol",
                    "ann_date",
                    "end_date",
                    "n_income",
                    "prior_period_net_profit",
                    "diluted_roe",
                ],
            )
        )
        report_revision = _prepare_report_revision_frame(
            load_dataset(
                cat_ts,
                "report_rc",
                columns=["symbol", "report_date", "org_name", "quarter", "np"],
            )
        )
        moneyflow = load_moneyflow_base_frame(cat_ts, moneyflow_start_date, end_date)
        stock_amount = load_stock_amount_frame(cat_ts, moneyflow_start_date, end_date)
        return cls(
            cat_ts=cat_ts,
            cat_lx=cat_lx,
            config=config,
            forecast_by_date=_partition_by_date(forecast, "ann_date"),
            express_by_date=_partition_by_date(express, "ann_date"),
            report_revision_by_date=_partition_by_date(report_revision, "report_date"),
            moneyflow_by_date=_partition_by_date(moneyflow, "trade_date"),
            stock_amount_by_date=_partition_by_date(stock_amount, "trade_date"),
            stock_industry_members=stock_industry_members,
            index_to_l1=index_to_l1,
            industry_to_l1=industry_to_l1,
            valuation_by_date=valuation_panel_batch(
                cat_lx,
                target_dates,
                industry_to_l1,
                classification_catalog=cat_ts,
            ),
            fundamental_by_date=fundamental_panel_batch(
                cat_lx,
                target_dates,
                industry_to_l1,
            ),
        )

    def stock_map(self, as_of_date: date) -> pl.DataFrame:
        """按批次复用已归一成分记录，仅按基准日切片。"""
        if as_of_date not in self._stock_maps:
            frames: list[pl.DataFrame] = []
            ts_map = stock_industry_map_from_prepared_members(
                self.stock_industry_members, as_of_date
            )
            if not ts_map.is_empty():
                frames.append(ts_map.with_columns(pl.lit(0).alias("_source_priority")))
            if _is_current_industry_date(self.cat_ts, as_of_date):
                if self._current_lixinger_map is None:
                    self._current_lixinger_map = _stock_industry_map_from_lixinger_constituents(
                        self.cat_lx, self.industry_to_l1
                    )
                if not self._current_lixinger_map.is_empty():
                    frames.append(
                        self._current_lixinger_map.with_columns(pl.lit(1).alias("_source_priority"))
                    )
            if not frames:
                self._stock_maps[as_of_date] = pl.DataFrame(
                    schema={"stock_key": pl.Utf8, "industry_code": pl.Utf8}
                )
            else:
                self._stock_maps[as_of_date] = (
                    pl.concat(frames, how="vertical_relaxed")
                    .drop_nulls(subset=["stock_key", "industry_code"])
                    .sort(["stock_key", "_source_priority", "industry_code"])
                    .unique(subset=["stock_key"], keep="first", maintain_order=True)
                    .select("stock_key", "industry_code")
                )
        return self._stock_maps[as_of_date]


def _prepare_forecast_frame(raw: pl.DataFrame) -> pl.DataFrame:
    """一次完成业绩预告的日期、数值和正向标签归一。"""
    if raw.is_empty() or not {"symbol", "ann_date"}.issubset(raw.columns):
        return pl.DataFrame()
    base = raw.select(
        pl.col("symbol").cast(pl.String).str.slice(0, 6).alias("stock_key"),
        date_column_expr(raw, "ann_date", "ann_date"),
        date_column_expr(raw, "end_date", "end_date"),
        optional_text_expr(raw, ("type",), "type"),
        optional_numeric_expr(raw, ("p_change_min",), "p_change_min"),
        optional_numeric_expr(raw, ("p_change_max",), "p_change_max"),
    ).drop_nulls(subset=["stock_key", "ann_date"])
    return _prepare_forecast_values(base)


def _prepare_forecast_values(frame: pl.DataFrame) -> pl.DataFrame:
    positive_labels = ("预增", "略增", "续盈", "扭亏")
    return frame.with_columns(
        _midpoint_expr("p_change_min", "p_change_max").alias("_p_change_mid")
    ).with_columns(
        pl.when(pl.col("_p_change_mid").is_not_null())
        .then((pl.col("_p_change_mid") > 0).cast(pl.Int64))
        .otherwise(pl.col("type").is_in(positive_labels).cast(pl.Int64))
        .alias("_positive")
    )


def _prepare_express_frame(raw: pl.DataFrame) -> pl.DataFrame:
    """一次完成业绩快报的日期与利润增速归一。"""
    if raw.is_empty() or not {"symbol", "ann_date"}.issubset(raw.columns):
        return pl.DataFrame()
    base = raw.select(
        pl.col("symbol").cast(pl.String).str.slice(0, 6).alias("stock_key"),
        date_column_expr(raw, "ann_date", "ann_date"),
        date_column_expr(raw, "end_date", "end_date"),
        optional_numeric_expr(raw, ("n_income",), "n_income"),
        optional_numeric_expr(raw, ("prior_period_net_profit",), "_prior_net_profit"),
        optional_numeric_expr(raw, ("diluted_roe",), "diluted_roe"),
    ).drop_nulls(subset=["stock_key", "ann_date"])
    return _prepare_express_values(base)


def _prepare_express_values(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        pl.when(pl.col("n_income").is_not_null() & (pl.col("_prior_net_profit") > 0))
        .then((pl.col("n_income") / pl.col("_prior_net_profit") - 1.0) * 100.0)
        .otherwise(None)
        .alias("_profit_growth")
    )


def _prepare_report_revision_frame(raw: pl.DataFrame) -> pl.DataFrame:
    """一次完成研报修订序列的日期解析和前值计算。"""
    required = {"symbol", "report_date", "org_name", "quarter", "np"}
    if raw.is_empty() or not required.issubset(raw.columns):
        return pl.DataFrame()
    base = raw.select(
        pl.col("symbol").cast(pl.String).str.slice(0, 6).alias("stock_key"),
        date_column_expr(raw, "report_date", "report_date"),
        pl.col("org_name").cast(pl.String).alias("org_name"),
        pl.col("quarter").cast(pl.String).alias("quarter"),
        pl.col("np").cast(pl.Float64, strict=False).alias("np"),
    ).drop_nulls(subset=["stock_key", "report_date", "org_name", "quarter", "np"])
    if base.is_empty():
        return base
    return base.sort(["stock_key", "org_name", "quarter", "report_date"]).with_columns(
        pl.col("np").shift(1).over(["stock_key", "org_name", "quarter"]).alias("_prev_np")
    )


def _partition_by_date(frame: pl.DataFrame, date_column: str) -> dict[date, pl.DataFrame]:
    """将批次输入按业务日期分片，避免每个基准日扫描全表。"""
    if frame.is_empty() or date_column not in frame.columns:
        return {}
    partitions: dict[date, pl.DataFrame] = {}
    for raw_key, partition in frame.partition_by(date_column, as_dict=True).items():
        key = raw_key[0] if isinstance(raw_key, tuple) else raw_key
        if isinstance(key, date):
            partitions[key] = partition
    return partitions


def _concat_date_partitions(
    partitions: dict[date, pl.DataFrame],
    start_date: date,
    end_date: date,
) -> pl.DataFrame:
    """拼接指定日期窗口的已预处理输入。"""
    frames = [frame for value, frame in partitions.items() if start_date <= value <= end_date]
    return pl.concat(frames, how="vertical_relaxed") if frames else pl.DataFrame()


def _filter_target_period_if_available(
    frame: pl.DataFrame,
    period_column: str,
    target_period: date,
) -> pl.DataFrame:
    if frame.is_empty() or period_column not in frame.columns:
        return frame
    target_rows = frame.filter(pl.col(period_column) == target_period)
    return target_rows if not target_rows.is_empty() else frame


def _latest_completed_report_period(as_of_date: date) -> date:
    year = as_of_date.year
    if as_of_date.month >= 10:
        return date(year, 9, 30)
    if as_of_date.month >= 7:
        return date(year, 6, 30)
    if as_of_date.month >= 4:
        return date(year, 3, 31)
    return date(year - 1, 12, 31)


def _midpoint_expr(left: str, right: str) -> pl.Expr:
    return (
        pl.when(pl.col(left).is_not_null() & pl.col(right).is_not_null())
        .then((pl.col(left) + pl.col(right)) / 2.0)
        .otherwise(pl.coalesce(pl.col(left), pl.col(right)))
    )
