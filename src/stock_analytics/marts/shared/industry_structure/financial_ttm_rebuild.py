"""理杏仁行业财务 TTM 同比的差分重建 transform。

背景：理杏仁 ``sw_2021_l2/l3_fs_*`` 的 ``q.ps.{toi,np}.ttm_y2y`` 在 2021-2023 报告期
存在源端缺失（2022 年 L3 缺失率约 70%），而 ``q.ps.{toi,np}.t``（YTD 累计值）基本完整。

本模块实现"从累计值差分重建单季金额 → 4 期滚动和 → 精确 TTM 同比"，并保留
``official / derived / proxy`` 口径标记：

- ``official``：源端 ``ttm_y2y`` 非空，直接使用；
- ``derived``：源端缺失但 ``t`` 可精确重建（与官方对账中位差 0.0pp，L2/L3 均验证）；
- ``proxy``：两者均不可得时，用 ``c_y2y`` 四期滚动均值作为明确标注的代理值。

注意：``t`` 是 YTD 累计而非单季金额，单季 = ``t(i) - t(上一报告期)``（Q1 无前序时
直接取 ``t``）；``unique(keep="last")`` 会打乱行序，必须先排序再做 ``shift/rolling``。
"""

from __future__ import annotations

from typing import Any

import polars as pl

_REPORT_PERIOD_ORDER = {
    "first_quarterly_report": 1,
    "interim_report": 2,
    "third_quarterly_report": 3,
    "annual_report": 4,
}

REVENUE_SOURCE_COL = "revenue_growth_source"
PROFIT_SOURCE_COL = "profit_growth_source"

#: 展开后事实帧的稳定 schema（含口径标记列）
FINANCIAL_TTM_SCHEMA: dict[str, Any] = {
    "eff_date": pl.Date,
    "industry_code": pl.Utf8,
    "revenue_growth_ttm": pl.Float64,
    "profit_growth_ttm": pl.Float64,
    "gross_margin_ttm": pl.Float64,
    REVENUE_SOURCE_COL: pl.Utf8,
    PROFIT_SOURCE_COL: pl.Utf8,
}


def _empty_financial_ttm() -> pl.DataFrame:
    return pl.DataFrame(schema=FINANCIAL_TTM_SCHEMA)


def _rebuild_ttm_from_cumulative(
    frame: pl.DataFrame,
    metric: str,
) -> tuple[pl.Series, pl.Series]:
    """从 YTD 累计值 ``q.ps.<metric>.t`` 重建 TTM 同比。

    返回 ``(重建值, 是否精确重建)``：重建值在无法重建时为 null；
    精确重建标志用于区分 ``derived`` 与 ``proxy``。
    """
    q = pl.col("q")
    t_expr = q.struct.field("ps").struct.field(metric).struct.field("t")
    std_dtype = frame.schema["standardDate"]
    std_expr = (
        pl.col("standardDate").str.strptime(pl.Datetime, "%Y-%m-%dT%H:%M:%S%z").dt.date()
        if std_dtype == pl.Utf8
        else pl.col("standardDate").cast(pl.Date)
    )

    base = frame.with_columns(
        pl.col("symbol").cast(pl.Utf8, strict=False).alias("_sym"),
        std_expr.alias("_std"),
        t_expr.cast(pl.Float64).alias("_t"),
        pl.col("reportType").replace_strict(_REPORT_PERIOD_ORDER, default=None).alias("_period"),
    ).select(["_sym", "_std", "_period", "_t"])
    # 同一 (行业, 报告期) 只保留一条（keep="last" 后会乱序，必须重排序）
    base = base.unique(subset=["_sym", "_std"], keep="last").sort(["_sym", "_std"])

    base = (
        base.with_columns(
            pl.col("_t").shift(1).over("_sym").alias("_t_prev"),
        )
        .with_columns(
            pl.when(pl.col("_period") == 1)
            .then(pl.col("_t"))
            .otherwise(pl.col("_t") - pl.col("_t_prev"))
            .alias("_q_amt"),
        )
        .with_columns(
            pl.col("_q_amt")
            .rolling_sum(window_size=4, min_samples=4)
            .over("_sym")
            .alias("_ttm_amt"),
            pl.col("_q_amt")
            .rolling_sum(window_size=4, min_samples=4)
            .shift(4)
            .over("_sym")
            .alias("_ttm_prev"),
        )
        .with_columns(
            pl.when(pl.col("_ttm_prev").is_not_null() & (pl.col("_ttm_prev") != 0))
            .then((pl.col("_ttm_amt") - pl.col("_ttm_prev")) / pl.col("_ttm_prev").abs())
            .otherwise(None)
            .alias("_rebuilt"),
        )
    )

    rebuilt = base["_rebuilt"]
    # 重建成功 = 有 TTM 分子且分母非零；精确 = 单季金额全部为正（无源端断裂）
    precise = (
        base["_ttm_amt"].is_not_null()
        & base["_ttm_prev"].is_not_null()
        & (base["_ttm_prev"] != 0)
        & (base["_q_amt"] > 0)
    )
    return rebuilt, precise


def expand_financial_with_ttm_rebuild(frame: pl.DataFrame) -> pl.DataFrame:
    """展开理杏仁 L2/L3 财务嵌套字段，缺失 ``ttm_y2y`` 时差分重建并标注口径。

    ``frame`` 需含 ``reportDate`` / ``symbol`` / ``reportType`` / ``standardDate``
    与嵌套 ``q`` 结构（``q.ps.{toi,np}.{t,ttm_y2y,c_y2y}``、
    ``q.ps.gp_m.ttm`` 可选——银行/证券/保险无毛利率字段 → null）。

    输出列见 :data:`FINANCIAL_TTM_SCHEMA`：``eff_date`` / ``industry_code`` /
    ``revenue_growth_ttm`` / ``profit_growth_ttm`` / ``gross_margin_ttm`` /
    ``revenue_growth_source`` / ``profit_growth_source``（official/derived/proxy）。
    """
    if frame.is_empty():
        return _empty_financial_ttm()

    q = pl.col("q")
    q_fields = getattr(frame.schema["q"], "fields", [])
    ps_dtype = next((f.dtype for f in q_fields if f.name == "ps"), None)
    ps_fields = getattr(ps_dtype, "fields", []) if ps_dtype is not None else []
    has_gp = any(f.name == "gp_m" for f in ps_fields)

    out = frame.select(
        [
            pl.col("reportDate").alias("eff_date"),
            pl.col("symbol").cast(pl.Utf8, strict=False).alias("industry_code"),
            q.struct.field("ps").struct.field("toi").struct.field("ttm_y2y").alias("_rev_official"),
            q.struct.field("ps").struct.field("np").struct.field("ttm_y2y").alias("_prof_official"),
            q.struct.field("ps").struct.field("toi").struct.field("c_y2y").alias("_rev_c"),
            q.struct.field("ps").struct.field("np").struct.field("c_y2y").alias("_prof_c"),
            (
                q.struct.field("ps")
                .struct.field("gp_m")
                .struct.field("ttm")
                .alias("gross_margin_ttm")
                if has_gp
                else pl.lit(None, dtype=pl.Float64).alias("gross_margin_ttm")
            ),
        ]
    )

    rev_rebuilt, rev_precise = _rebuild_ttm_from_cumulative(frame, "toi")
    prof_rebuilt, prof_precise = _rebuild_ttm_from_cumulative(frame, "np")
    out = out.with_columns(
        rev_rebuilt.alias("_rev_derived"),
        prof_rebuilt.alias("_prof_derived"),
        rev_precise.alias("_rev_precise"),
        prof_precise.alias("_prof_precise"),
    )

    # official 优先 → derived（t 重建）→ proxy（c_y2y 四期滚动均值，明确标注）
    out = out.with_columns(
        pl.coalesce(
            pl.col("_rev_official"),
            pl.when(pl.col("_rev_derived").is_not_null()).then(pl.col("_rev_derived")),
            pl.col("_rev_c").rolling_mean(window_size=4, min_samples=4).over("industry_code"),
        ).alias("revenue_growth_ttm"),
        pl.coalesce(
            pl.col("_prof_official"),
            pl.when(pl.col("_prof_derived").is_not_null()).then(pl.col("_prof_derived")),
            pl.col("_prof_c").rolling_mean(window_size=4, min_samples=4).over("industry_code"),
        ).alias("profit_growth_ttm"),
        pl.when(pl.col("_rev_official").is_not_null())
        .then(pl.lit("official"))
        .when(pl.col("_rev_derived").is_not_null())
        .then(pl.lit("derived"))
        .otherwise(pl.lit("proxy"))
        .alias(REVENUE_SOURCE_COL),
        pl.when(pl.col("_prof_official").is_not_null())
        .then(pl.lit("official"))
        .when(pl.col("_prof_derived").is_not_null())
        .then(pl.lit("derived"))
        .otherwise(pl.lit("proxy"))
        .alias(PROFIT_SOURCE_COL),
    )

    return out.select(list(FINANCIAL_TTM_SCHEMA)).sort(["industry_code", "eff_date"])
