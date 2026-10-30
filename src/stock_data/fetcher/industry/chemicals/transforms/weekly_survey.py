"""化工周度调查 RAW/Curated 转换与同周合流引擎。"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl

from stock_data.fetcher.industry.chemicals.schemas import (
    WEEKLY_SURVEY_RAW_SCHEMA,
    WEEKLY_SURVEY_SCHEMA,
)


def build_weekly_survey_raw_frame(df: pl.DataFrame) -> pl.DataFrame:
    """将周报数值保存为源值文本，避免 RAW 层承载数值转换。"""
    if df.is_empty():
        return pl.DataFrame(schema=WEEKLY_SURVEY_RAW_SCHEMA)
    for column in ("raw_content_sha256", "raw_snapshot_path"):
        if column not in df.columns:
            df = df.with_columns(pl.lit("").alias(column))
    if "data_status" not in df.columns:
        df = df.with_columns(pl.lit("actual").alias("data_status"))

    return (
        df.with_columns(
            pl.col("operating_rate_pct").cast(pl.String).alias("operating_rate_pct_raw"),
            pl.col("weekly_output_w_tons").cast(pl.String).alias("weekly_output_w_tons_raw"),
            pl.col("factory_inventory_w_tons")
            .cast(pl.String)
            .alias("factory_inventory_w_tons_raw"),
            pl.col("shipment_rate_pct").cast(pl.String).alias("shipment_rate_pct_raw"),
            pl.col("data_status").cast(pl.String),
        )
        .drop(
            [
                "operating_rate_pct",
                "weekly_output_w_tons",
                "factory_inventory_w_tons",
                "shipment_rate_pct",
            ]
        )
        .select(list(WEEKLY_SURVEY_RAW_SCHEMA))
    )


def coalesce_weekly_survey_frame(df: pl.DataFrame) -> pl.DataFrame:
    """自然周同周合流引擎 (Weekly Coalesce Engine) 与物理守恒补算。

    1. 将同属于一个自然周 (ISO Year, ISO Week) 的不同日期碎片 (如周一库存快讯与周四综合详报) 合流为一个标准基准周;
    2. 对缺失开工率但具有真实产量的记录，结合相邻周期有效样本的有效周产能基准执行物理守恒补算，并打上 imputed 状态标签。
    """
    if df.is_empty():
        return pl.DataFrame(schema=WEEKLY_SURVEY_SCHEMA)

    work_df = df
    if work_df["report_date"].dtype == pl.String:
        work_df = work_df.with_columns(pl.col("report_date").str.to_date(strict=False))
    if work_df["trade_date"].dtype == pl.String:
        work_df = work_df.with_columns(pl.col("trade_date").str.to_date(strict=False))
    if "release_date" in work_df.columns and work_df["release_date"].dtype == pl.String:
        work_df = work_df.with_columns(pl.col("release_date").str.to_date(strict=False))

    # 规范化 symbol 与产品名称
    work_df = work_df.with_columns(
        pl.col("symbol").str.to_uppercase().alias("symbol")
    ).with_columns(
        pl.when(pl.col("symbol") == "TA")
        .then(pl.lit("精对苯二甲酸"))
        .when(pl.col("symbol") == "V")
        .then(pl.lit("聚氯乙烯"))
        .when(pl.col("symbol") == "MEG")
        .then(pl.lit("乙二醇"))
        .when(pl.col("symbol") == "MA")
        .then(pl.lit("甲醇"))
        .when(pl.col("symbol") == "SA")
        .then(pl.lit("纯碱"))
        .when(pl.col("symbol") == "TIO2")
        .then(pl.lit("钛白粉"))
        .when(pl.col("symbol") == "SH")
        .then(pl.lit("烧碱"))
        .when(pl.col("symbol") == "UR")
        .then(pl.lit("尿素"))
        .when(pl.col("symbol") == "EB")
        .then(pl.lit("苯乙烯"))
        .when(pl.col("symbol") == "PP")
        .then(pl.lit("聚丙烯"))
        .when(pl.col("symbol") == "PX")
        .then(pl.lit("对二甲苯"))
        .when(pl.col("symbol") == "R32")
        .then(pl.lit("制冷剂R32"))
        .when(pl.col("symbol") == "MDI")
        .then(pl.lit("聚合MDI"))
        .otherwise(pl.col("product_name"))
        .alias("product_name")
    )

    for num_col in (
        "operating_rate_pct",
        "weekly_output_w_tons",
        "factory_inventory_w_tons",
        "shipment_rate_pct",
    ):
        if num_col in work_df.columns and work_df[num_col].dtype != pl.Float64:
            work_df = work_df.with_columns(pl.col(num_col).cast(pl.Float64, strict=False))

    work_df = work_df.with_columns(
        pl.col("report_date").dt.iso_year().alias("iso_year"),
        pl.col("report_date").dt.week().alias("iso_week"),
        pl.col("report_date").dt.weekday().alias("weekday"),
    )

    coalesced_rows: list[dict[str, Any]] = []
    group_keys = ["product_name", "symbol", "iso_year", "iso_week"]

    for (p_name, sym, _y, _w), group in work_df.group_by(group_keys):
        sorted_by_date = group.sort(
            by=["report_date", "weekday"],
            descending=[True, True],
            nulls_last=True,
        )

        def _get_latest_non_null(col: str, df_source: pl.DataFrame = sorted_by_date) -> Any:
            filtered = df_source.filter(pl.col(col).is_not_null())
            if len(filtered) > 0:
                return filtered[col][0]
            return None

        op_rate = _get_latest_non_null("operating_rate_pct")
        output = _get_latest_non_null("weekly_output_w_tons")
        inv = _get_latest_non_null("factory_inventory_w_tons")
        shipment = _get_latest_non_null("shipment_rate_pct")

        # 基准行锚定：优先周四（weekday == 4），若无周四则取当周最新 report_date 行
        thu_rows = group.filter(pl.col("weekday") == 4)
        if len(thu_rows) > 0:
            anchor = thu_rows.sort(by="report_date", descending=True).row(0, named=True)
            best_report_date = anchor["report_date"]
            best_trade_date = anchor["trade_date"]
        else:
            anchor = sorted_by_date.row(0, named=True)
            best_report_date = anchor["report_date"]
            best_trade_date = anchor["trade_date"]

        max_release = (
            group["release_date"].drop_nulls().max()
            if "release_date" in group.columns and len(group["release_date"].drop_nulls()) > 0
            else None
        )

        coalesced_rows.append(
            {
                "trade_date": best_trade_date,
                "report_date": best_report_date,
                "product_name": p_name,
                "symbol": sym,
                "operating_rate_pct": op_rate,
                "weekly_output_w_tons": output,
                "factory_inventory_w_tons": inv,
                "shipment_rate_pct": shipment,
                "source": anchor.get("source") or "weekly_survey",
                "source_url": anchor.get("source_url") or "",
                "release_date": max_release,
                "data_status": anchor.get("data_status") or "actual",
                "collected_at": anchor.get("collected_at") or "",
            }
        )

    coalesced_df = pl.DataFrame(coalesced_rows, schema=WEEKLY_SURVEY_SCHEMA).sort(
        ["product_name", "report_date"]
    )

    # 物理守恒补算缺失的开工率
    imputed_rows: list[dict[str, Any]] = []
    for row in coalesced_df.iter_rows(named=True):
        if row["operating_rate_pct"] is None and row["weekly_output_w_tons"] is not None:
            cur_date: date = row["report_date"]
            nearby = coalesced_df.filter(
                (pl.col("product_name") == row["product_name"])
                & (pl.col("operating_rate_pct").is_not_null())
                & (pl.col("weekly_output_w_tons").is_not_null())
                & (pl.col("report_date") >= pl.lit(cur_date).dt.offset_by("-60d"))
                & (pl.col("report_date") <= pl.lit(cur_date).dt.offset_by("+60d"))
            )
            if len(nearby) > 0:
                capacities = (
                    nearby["weekly_output_w_tons"] / (nearby["operating_rate_pct"] / 100.0)
                ).to_list()
                capacities.sort()
                med_cap = capacities[len(capacities) // 2]
                if med_cap > 0:
                    imputed_rate = round((row["weekly_output_w_tons"] / med_cap) * 100.0, 2)
                    row["operating_rate_pct"] = imputed_rate
                    row["data_status"] = "imputed"
        imputed_rows.append(row)

    final_df = pl.DataFrame(imputed_rows, schema=WEEKLY_SURVEY_SCHEMA).sort(
        ["product_name", "report_date"]
    )
    return final_df.select(list(WEEKLY_SURVEY_SCHEMA)).cast(pl.Schema(WEEKLY_SURVEY_SCHEMA))


def build_weekly_survey_curated_frame(df: pl.DataFrame) -> pl.DataFrame:
    """从周报 RAW 源值恢复标准化 Curated 表，并执行同周合流与物理补算。"""
    if df.is_empty():
        return pl.DataFrame(schema=WEEKLY_SURVEY_SCHEMA)

    work_df = df
    if "operating_rate_pct_raw" in work_df.columns:
        work_df = work_df.with_columns(
            pl.col("operating_rate_pct_raw")
            .cast(pl.Float64, strict=False)
            .alias("operating_rate_pct"),
            pl.col("weekly_output_w_tons_raw")
            .cast(pl.Float64, strict=False)
            .alias("weekly_output_w_tons"),
            pl.col("factory_inventory_w_tons_raw")
            .cast(pl.Float64, strict=False)
            .alias("factory_inventory_w_tons"),
            pl.col("shipment_rate_pct_raw")
            .cast(pl.Float64, strict=False)
            .alias("shipment_rate_pct"),
        ).drop(
            [
                "operating_rate_pct_raw",
                "weekly_output_w_tons_raw",
                "factory_inventory_w_tons_raw",
                "shipment_rate_pct_raw",
            ]
        )

    if "data_status" not in work_df.columns:
        work_df = work_df.with_columns(pl.lit("actual").alias("data_status"))

    return coalesce_weekly_survey_frame(work_df)


__all__ = [
    "build_weekly_survey_curated_frame",
    "build_weekly_survey_raw_frame",
    "coalesce_weekly_survey_frame",
]
