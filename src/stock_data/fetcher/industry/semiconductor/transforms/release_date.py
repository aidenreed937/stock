"""半导体 RAW 发布日期契约。"""

from __future__ import annotations

import polars as pl


def require_raw_release_dates(
    df: pl.DataFrame, endpoint: str, *, allow_unavailable: bool = False
) -> pl.DataFrame:
    """校验 RAW 发布日期状态，区分源端缺失与真实已报告日期。"""
    if "release_date" not in df.columns:
        raise ValueError(f"半导体 RAW 端点 {endpoint} 缺少 release_date 列")

    if "release_date_status" not in df.columns:
        missing = df.filter(pl.col("release_date").is_null()).height
        if missing:
            raise ValueError(
                f"半导体 RAW 端点 {endpoint} 有 {missing} 行缺少真实 release_date，拒绝落盘"
            )
        return df

    if df["release_date_status"].null_count():
        raise ValueError(f"半导体 RAW 端点 {endpoint} 缺少 release_date_status")

    statuses = set(df["release_date_status"].drop_nulls().cast(pl.String).to_list())
    invalid_statuses = statuses - {"reported", "unavailable"}
    if invalid_statuses:
        raise ValueError(
            f"半导体 RAW 端点 {endpoint} 存在非法 release_date_status: {invalid_statuses}"
        )

    reported_missing = df.filter(
        (pl.col("release_date_status") == "reported") & pl.col("release_date").is_null()
    ).height
    unavailable_with_date = df.filter(
        (pl.col("release_date_status") == "unavailable") & pl.col("release_date").is_not_null()
    ).height
    if reported_missing or unavailable_with_date:
        raise ValueError(f"半导体 RAW 端点 {endpoint} 的 release_date 与状态不一致")
    if "release_date_raw" in df.columns:
        reported_without_raw = df.filter(
            (pl.col("release_date_status") == "reported") & pl.col("release_date_raw").is_null()
        ).height
        if reported_without_raw:
            raise ValueError(f"半导体 RAW 端点 {endpoint} 缺少 release_date_raw")
    if not allow_unavailable:
        missing = df.filter(pl.col("release_date_status") == "unavailable").height
        if missing:
            raise ValueError(
                f"半导体 RAW 端点 {endpoint} 有 {missing} 行缺少真实 release_date，拒绝落盘"
            )
    return df
