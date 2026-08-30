"""申万二级行业基本面面板 Mart（量价齐升供需层接入）。

按 `.agents/skills/industry-trend-tracking` 的因子定义，把理杏仁 L2 财务黄金表
``sw_2021_l2_fs_*``（25 报告期营收/净利 TTM 同比、毛利率）合并进 ``industry_l2_daily``
（行情/估值/动量），输出三级行业基本面面板：

- ``revenue_growth_ttm`` / ``profit_growth_ttm`` / ``gross_margin_ttm``：L2 财务事实；
- ``supply_demand_score``：量价齐升质量分（双正→双增速分位；供给收缩→20；双负→10）；
- ``bargaining_score``：议价权分（量价齐升门内→(净利−营收)增速分位；门外→30）；
- ``crowding_score``：拥挤度（成交额截面分位，缺失用中性 50）；
- ``direction_score``：全球方向（数据缺口，中性 50）。

报告期滞后：财务行以 ``reportDate``（发布日）为可用起点，日频面板按发布日生效，
避免前视偏差。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl

INDUSTRY_L2_PANEL_MART_NAME = "industry_l2_panel_daily"

# 面板输出 schema（按此顺序落盘）
INDUSTRY_L2_PANEL_SCHEMA: dict[str, Any] = {
    "trade_date": pl.Date,
    "industry_code": pl.Utf8,
    "industry_name": pl.Utf8,
    "parent_l1_code": pl.Utf8,
    "parent_l1_name": pl.Utf8,
    "close": pl.Float64,
    "amount_yi": pl.Float64,
    "return_20d": pl.Float64,
    "return_60d": pl.Float64,
    "pe_ttm_ew_percentile_5y": pl.Float64,
    "pb_ew_percentile_5y": pl.Float64,
    "revenue_growth_ttm": pl.Float64,
    "profit_growth_ttm": pl.Float64,
    "gross_margin_ttm": pl.Float64,
    "supply_demand_score": pl.Float64,
    "bargaining_score": pl.Float64,
    "crowding_score": pl.Float64,
    "direction_score": pl.Float64,
}

# 量价齐升质量分参数（对齐 config/analytics/industry_trend_tracking.yaml）
_SUPPLY_CONTRACT_PENALTY = 20.0  # 供给收缩（营收负、净利正）：假繁荣
_DOUBLE_NEGATIVE_PENALTY = 10.0  # 双负（营收负、净利负）
_BARGAINING_NEUTRAL = 30.0  # 量价齐升门外的议价权中性分
_DIRECTION_NEUTRAL = 50.0  # 全球方向数据缺口中性分


def empty_industry_l2_panel() -> pl.DataFrame:
    """返回稳定 schema 的空申万二级行业基本面面板。"""
    return pl.DataFrame(schema=INDUSTRY_L2_PANEL_SCHEMA)


def _cs_percentile(col: str) -> pl.Expr:
    """横截面百分位: (rank - 1) / (count - 1) * 100，空值取中性 50。"""
    return (
        (
            (pl.col(col).rank(method="average").over("trade_date") - 1.0)
            / (pl.col(col).count().over("trade_date") - 1.0)
            * 100.0
        )
        .fill_nan(50.0)
        .fill_null(50.0)
    )


def expand_l2_financial(frame: pl.DataFrame) -> pl.DataFrame:
    """把理杏仁 L2 财务嵌套字段展开为营收/净利 TTM 同比与毛利率事实列。

    ``frame`` 需要含 ``reportDate`` / ``symbol`` 与嵌套 ``q`` 结构：
    ``q.ps.toi.ttm_y2y``（营收同比）、``q.ps.np.ttm_y2y``（净利同比）、
    ``q.ps.gp_m.ttm``（毛利率，仅非金融源；银行/证券/保险无此字段 → null）。
    输出列：``eff_date``（发布日）/ ``industry_code`` / 三个事实列。
    """
    if frame.is_empty():
        return pl.DataFrame(
            schema={
                "eff_date": pl.Date,
                "industry_code": pl.Utf8,
                "revenue_growth_ttm": pl.Float64,
                "profit_growth_ttm": pl.Float64,
                "gross_margin_ttm": pl.Float64,
            }
        )
    q = pl.col("q")
    # gp_m 仅在非金融源存在：从 schema 探测 ps 子结构是否含 gp_m 字段
    q_fields = getattr(frame.schema["q"], "fields", [])  # Struct dtype 才含 fields
    ps_dtype = next((f.dtype for f in q_fields if f.name == "ps"), None)
    ps_fields = getattr(ps_dtype, "fields", []) if ps_dtype is not None else []
    has_gp = any(f.name == "gp_m" for f in ps_fields)
    select_cols = [
        pl.col("reportDate").alias("eff_date"),
        pl.col("symbol").cast(pl.Utf8, strict=False).alias("industry_code"),
        q.struct.field("ps")
        .struct.field("toi")
        .struct.field("ttm_y2y")
        .alias("revenue_growth_ttm"),
        q.struct.field("ps").struct.field("np").struct.field("ttm_y2y").alias("profit_growth_ttm"),
    ]
    if has_gp:
        select_cols.append(
            q.struct.field("ps").struct.field("gp_m").struct.field("ttm").alias("gross_margin_ttm")
        )
    else:
        select_cols.append(pl.lit(None, dtype=pl.Float64).alias("gross_margin_ttm"))
    return (
        frame.select(select_cols)
        .drop_nulls(subset=["revenue_growth_ttm", "profit_growth_ttm"])
        .sort(["industry_code", "eff_date"])
    )


def build_industry_l2_panel_frame(
    l2_daily: pl.DataFrame,
    l2_financial: pl.DataFrame,
    *,
    direction_map: pl.DataFrame | None = None,
    percentile_cutoff: date | None = None,
) -> pl.DataFrame:
    """合并二级行业行情与 L2 财务黄金表，输出基本面面板。

    ``l2_daily`` 为 ``industry_l2_daily`` Mart（含 ``trade_date``/``industry_code``/
    ``industry_name``/``parent_l1_code``/``parent_l1_name``/``close``/``amount_yi``/
    ``return_20d``/``return_60d``/``pe_ttm_ew_percentile_5y``/``pb_ew_percentile_5y``）；
    ``l2_financial`` 为 :func:`expand_l2_financial` 展开后的事实帧（``eff_date``/
    ``industry_code``/``revenue_growth_ttm``/``profit_growth_ttm``/``gross_margin_ttm``）。
    ``direction_map`` 为二级行业方向分长表（``trade_date``/``industry_code``/
    ``direction_score``，来自 ``global_resonance_l2_map.parquet``），缺失回退中性 50；
    为 None 时方向层保持中性。
    ``percentile_cutoff`` 传入时仅输出该日期及之后行（增量构建语义）。
    """
    if l2_daily.is_empty():
        return empty_industry_l2_panel()

    base = l2_daily.select(
        [
            "trade_date",
            "industry_code",
            "industry_name",
            "parent_l1_code",
            "parent_l1_name",
            "close",
            "amount_yi",
            "return_20d",
            "return_60d",
            "pe_ttm_ew_percentile_5y",
            "pb_ew_percentile_5y",
        ]
    ).sort(["trade_date", "industry_code"])

    # 方向层：global_resonance_l2_map（理杏仁码）替换中性 50，缺失回退中性
    if direction_map is not None and not direction_map.is_empty():
        base = base.join(
            direction_map.select(["trade_date", "industry_code", "direction_score"]),
            on=["trade_date", "industry_code"],
            how="left",
        ).with_columns(
            pl.col("direction_score").fill_null(_DIRECTION_NEUTRAL).alias("direction_score")
        )
    else:
        base = base.with_columns(
            pl.lit(_DIRECTION_NEUTRAL, dtype=pl.Float64).alias("direction_score")
        )

    if l2_financial.is_empty():
        # 无财务数据：供需/议价权中性，仅输出行情/动量/拥挤度
        return base.with_columns(
            [
                pl.lit(None, dtype=pl.Float64).alias("revenue_growth_ttm"),
                pl.lit(None, dtype=pl.Float64).alias("profit_growth_ttm"),
                pl.lit(None, dtype=pl.Float64).alias("gross_margin_ttm"),
                pl.lit(_DIRECTION_NEUTRAL, dtype=pl.Float64).alias("supply_demand_score"),
                pl.lit(_BARGAINING_NEUTRAL, dtype=pl.Float64).alias("bargaining_score"),
                _cs_percentile("amount_yi").alias("crowding_score"),
            ]
        ).select(list(INDUSTRY_L2_PANEL_SCHEMA))

    # l2_financial 为已展开事实帧（eff_date/industry_code/三个财务列）
    fin = l2_financial

    # 报告期滞后：每日取「已发布的最新报告期」（交易日 >= 发布日，按行业分组）
    daily_dates = base.select("trade_date").unique().sort("trade_date")
    fin_parts: list[pl.DataFrame] = []
    for code in fin["industry_code"].unique().to_list():
        fin_code = fin.filter(pl.col("industry_code") == code)
        if fin_code.is_empty():
            continue
        fin_parts.append(
            daily_dates.join_asof(
                fin_code,
                left_on="trade_date",
                right_on="eff_date",
                strategy="backward",
            ).filter(pl.col("revenue_growth_ttm").is_not_null())
        )
    if not fin_parts:
        return empty_industry_l2_panel()
    fin_daily = pl.concat(fin_parts).select(
        [
            "trade_date",
            "industry_code",
            "revenue_growth_ttm",
            "profit_growth_ttm",
            "gross_margin_ttm",
        ]
    )

    joined = base.join(fin_daily, on=["trade_date", "industry_code"], how="left")

    # 0. 中间列：营收/净利增速（空值视为 0）、量价齐升门、毛利率扩张代理
    rev = pl.col("revenue_growth_ttm").fill_null(0.0)
    prof = pl.col("profit_growth_ttm").fill_null(0.0)
    base2 = joined.with_columns(
        [
            rev.alias("_rev"),
            prof.alias("_prof"),
            (rev + prof).alias("_rev_plus_prof"),
            (prof - rev).alias("_margin_expand"),
            ((rev > 0.0) & (prof > 0.0)).alias("_quality"),
        ]
    )

    # 1. 供需层：量价齐升（营收 + 净利双正）才是真需求驱动
    supply_demand = (
        pl.when(pl.col("_quality"))
        .then(_cs_percentile("_rev_plus_prof"))
        .when(pl.col("_prof") > 0.0)  # 供给收缩（营收负、净利正）：假繁荣，惩罚
        .then(pl.lit(_SUPPLY_CONTRACT_PENALTY))
        .otherwise(pl.lit(_DOUBLE_NEGATIVE_PENALTY))  # 双负
    )
    # 2. 议价权：量价齐升门内的毛利率扩张（净利增速 > 营收增速）
    bargaining = (
        pl.when(pl.col("_quality"))
        .then(_cs_percentile("_margin_expand"))
        .otherwise(pl.lit(_BARGAINING_NEUTRAL))
    )

    result = base2.with_columns(
        [
            supply_demand.clip(0.0, 100.0).alias("supply_demand_score"),
            bargaining.clip(0.0, 100.0).alias("bargaining_score"),
            _cs_percentile("amount_yi").alias("crowding_score"),
        ]
    ).drop(["_rev", "_prof", "_rev_plus_prof", "_margin_expand", "_quality"])

    result = result.select(list(INDUSTRY_L2_PANEL_SCHEMA)).sort(["trade_date", "industry_code"])
    if percentile_cutoff is not None:
        result = result.filter(pl.col("trade_date") >= percentile_cutoff)
    return result


__all__ = [
    "INDUSTRY_L2_PANEL_MART_NAME",
    "build_industry_l2_panel_frame",
    "empty_industry_l2_panel",
    "expand_l2_financial",
]
