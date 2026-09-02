"""半导体深研线：供需剪刀差与结构性确认腿的腿部构建。

对齐 ``scripts/industry_direction_map.py`` 已实证的半导体腿部实现，工程化为
配置驱动、经 ``DataCatalog`` 读产业数据源、按 release_date 生效（无前视）。

核心腿部：
- demand 腿 = 台积电月营收(领先) + SIA 全球销售额(同步) 均值合成；剔 SOX 市价。
- supply 腿 = SEAJ 日本制设备出货 3MMA（领先 1-2 年产能释放）。
- 剪刀差 = demand - supply。
结构性腿（leg_type 独立分组，不入剪刀差）：
- ai_capex = 北美四大云厂商 CapEx 季度同比 -> 12 季滚动分位。
- storage  = DXI 存储指数月度同比 -> 36 月滚动分位。
全部产 0-100 滚动分位、日频前向填充。

术语约定：本模块产出的都是**特征（feature / 候选因子）**——回测的输入；
**不是已验证的有效因子**。因子有效性由 stock_strategy 验证层确认。
"""

from __future__ import annotations

import logging

import polars as pl

from stock_analytics.pipelines.semiconductor.config import (
    MonthlySource,
    QuarterlySource,
    SemiconductorLegsConfig,
)
from stock_data.catalog import DataCatalog
from stock_data.core.runtime import DataRuntimeContext

logger = logging.getLogger(__name__)


def _rolling_pct(series: pl.Series, window: int = 756) -> pl.Series:
    """滚动历史分位 (0-100)：每个时点在过去 window 天/期内的分位。"""
    s = series.fill_nan(0.0).fill_null(0.0)
    return (
        s.to_frame("v")
        .select(
            pl.col("v").rolling_map(
                lambda x: float((x <= x[-1]).mean()) * 100.0 if len(x) > 0 else 50.0,
                window_size=window,
                min_samples=1,
            )
        )["v"]
        .fill_nan(50.0)
        .fill_null(50.0)
    )


def _effective_col(df: pl.DataFrame) -> str:
    """生效列：优先 release_date（消除前视），否则 trade_date。"""
    return "release_date" if "release_date" in df.columns else "trade_date"


def _forward_to_daily(
    effective_scores: pl.DataFrame,
    calendar: pl.DataFrame,
) -> pl.DataFrame:
    """把 (生效日, pct) 对齐到日频日历并前向填充，返回 (trade_date, direction_score)。"""
    return (
        calendar.join(effective_scores, on="trade_date", how="left")
        .sort("trade_date")
        .with_columns(pl.col("pct").fill_null(strategy="forward").alias("direction_score"))
        .select(["trade_date", "direction_score"])
        .drop_nulls()
    )


def _load_source(cat: DataCatalog, source: str, column: str) -> pl.DataFrame | None:
    """加载产业数据源；缺失/异常返回 None（调用方容忍空腿）。"""
    try:
        df = cat.load_dataset(source)
    except Exception as exc:
        logger.warning("半导体腿部数据源 %s 加载失败，腿为空: %s", source, exc)
        return None
    if df.is_empty() or column not in df.columns:
        return None
    return df


def build_monthly_leg(
    source: MonthlySource,
    calendar: pl.DataFrame,
    cat: DataCatalog,
) -> pl.DataFrame:
    """月频源 → YoY → 滚动分位 → 日频前向填充 0-100 腿。

    返回帧 ``(trade_date, direction_score)``；数据源缺失时返回空帧。
    """
    df = _load_source(cat, source.source, source.column)
    if df is None:
        return _empty_leg()

    eff = _effective_col(df)
    extra = [eff] if eff != "trade_date" else []
    out = (
        df.select(["trade_date", *extra, source.column])
        .sort("trade_date")
        .with_columns(pl.col(source.column).pct_change(12).alias("yoy"))
        .drop_nulls()
    )
    pct = _rolling_pct(out["yoy"].cast(pl.Float64), window=source.window_months)
    monthly = out.with_columns(pct.alias("pct")).select([eff, "pct"]).rename({eff: "trade_date"})
    return _forward_to_daily(monthly, calendar)


def build_quarterly_leg(
    source: QuarterlySource,
    calendar: pl.DataFrame,
    cat: DataCatalog,
) -> pl.DataFrame:
    df = _load_source(cat, source.source, source.column)
    if df is None:
        return _empty_leg()
    eff = _effective_col(df)
    extra = [eff] if eff != "trade_date" else []
    if "yoy_growth" in df.columns and df["yoy_growth"].is_not_null().any():
        out = (
            df.select(["trade_date", *extra, "yoy_growth"])
            .rename({"yoy_growth": "yoy"})
            .drop_nulls()
            .sort("trade_date")
        )
    else:
        out = (
            df.select(["trade_date", *extra, source.column])
            .sort("trade_date")
            .with_columns(pl.col(source.column).pct_change(4).alias("yoy"))
            .drop_nulls()
        )
    pct = _rolling_pct(out["yoy"].cast(pl.Float64), window=source.window_quarters)
    quarterly = out.with_columns(pct.alias("pct")).select([eff, "pct"]).rename({eff: "trade_date"})
    return _forward_to_daily(quarterly, calendar)


def _empty_leg() -> pl.DataFrame:
    return pl.DataFrame(schema={"trade_date": pl.Date, "direction_score": pl.Float64})


def build_demand_leg(
    config: SemiconductorLegsConfig,
    calendar: pl.DataFrame,
    cat: DataCatalog,
) -> pl.DataFrame:
    """需求腿：多个需求源各自 YoY 滚动分位后均值合成（剔除 SOX 市价）。"""
    if config.scissors is None or not config.scissors.demand_sources:
        return _empty_leg()
    legs = []
    for msrc in config.scissors.demand_sources:
        leg = build_monthly_leg(msrc, calendar, cat)
        if not leg.is_empty():
            legs.append(leg)
    if not legs:
        return _empty_leg()
    merged = legs[0].rename({"direction_score": "_leg0"})
    for idx, leg in enumerate(legs[1:], start=1):
        merged = merged.join(
            leg.rename({"direction_score": f"_leg{idx}"}), on="trade_date", how="left"
        )
    leg_cols = [f"_leg{i}" for i in range(len(legs))]
    return (
        merged.sort("trade_date")
        .with_columns([pl.col(c).fill_null(strategy="forward") for c in leg_cols])
        .drop_nulls(subset=leg_cols)
        .with_columns(pl.mean_horizontal(leg_cols).alias("direction_score"))
        .select(["trade_date", "direction_score"])
        .drop_nulls()
    )


def build_supply_leg(
    config: SemiconductorLegsConfig,
    calendar: pl.DataFrame,
    cat: DataCatalog,
) -> pl.DataFrame:
    """供给腿：SEAJ 设备出货（领先 1-2 年产能释放）。"""
    if config.scissors is None:
        return _empty_leg()
    return build_monthly_leg(config.scissors.supply, calendar, cat)


def build_structural_legs(
    config: SemiconductorLegsConfig,
    calendar: pl.DataFrame,
    cat: DataCatalog,
) -> dict[str, pl.DataFrame]:
    """结构性确认腿（ai_capex / storage），leg_type 独立分组、不入剪刀差。

    对配置声明的每条腿始终返回键（空数据时返回空帧），保证下游 schema 稳定。
    """
    out: dict[str, pl.DataFrame] = {}
    if config.structural is None:
        return out
    ai_capex = build_quarterly_leg(config.structural.ai_capex, calendar, cat)
    out["ai_capex"] = ai_capex
    storage = build_monthly_leg(config.structural.storage, calendar, cat)
    out["storage"] = storage
    return out


def build_semiconductor_legs_panel(
    config: SemiconductorLegsConfig,
    calendar: pl.DataFrame,
    cat: DataCatalog,
) -> pl.DataFrame:
    """组装半导体/计算机设备腿部面板（长表，行业维度扩展）。

    输出列：trade_date, industry_code, demand_score, supply_score, scissors_score,
    以及结构性腿列（ai_capex_score / storage_score，可空）。
    剪刀差 demand/supply 按 neutral_score 中性回退；结构性腿缺数据时为空。
    """
    demand = build_demand_leg(config, calendar, cat)
    supply = build_supply_leg(config, calendar, cat)
    structural = build_structural_legs(config, calendar, cat)
    neutral = config.neutral_score

    combined = calendar.select("trade_date")

    def attach_leg(
        frame: pl.DataFrame,
        leg: pl.DataFrame,
        col: str,
        *,
        do_neutral: bool,
    ) -> pl.DataFrame:
        if leg.is_empty():
            return frame.with_columns(pl.lit(None, dtype=pl.Float64).alias(col))
        out = frame.join(
            leg.rename({"direction_score": col}), on="trade_date", how="left", coalesce=True
        )
        filled = pl.col(col).fill_null(strategy="forward")
        if do_neutral:
            return out.with_columns(filled.fill_null(neutral).alias(col))
        return out.with_columns(filled.alias(col))

    combined = attach_leg(combined, demand, "demand_score", do_neutral=True)
    combined = attach_leg(combined, supply, "supply_score", do_neutral=True)
    combined = combined.with_columns(
        (pl.col("demand_score") - pl.col("supply_score")).alias("scissors_score")
    )

    struct_cols: list[str] = []
    for key, leg in structural.items():
        score_col = f"{key}_score"
        combined = attach_leg(combined, leg, score_col, do_neutral=False)
        struct_cols.append(score_col)

    base_cols = ["trade_date", "demand_score", "supply_score", "scissors_score"]

    rows: list[pl.DataFrame] = []
    for code in config.industry_codes:
        rows.append(
            combined.select([*base_cols, *struct_cols]).with_columns(
                pl.lit(code).alias("industry_code")
            )
        )
    if not rows:
        return pl.DataFrame(
            schema={
                "trade_date": pl.Date,
                "industry_code": pl.Utf8,
                "demand_score": pl.Float64,
                "supply_score": pl.Float64,
                "scissors_score": pl.Float64,
                **{f"{k}_score": pl.Float64 for k in structural},
            }
        )
    return pl.concat(rows).select(["trade_date", "industry_code", *base_cols[1:], *struct_cols])


def load_calendar(runtime: DataRuntimeContext, calendar_mart: str) -> pl.DataFrame:
    """从 Curated Mart 加载日频交易日历（仅取 trade_date）。"""
    path = runtime.data_root / "curated" / "mart" / f"{calendar_mart}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"缺少交易日历 Mart: {path}")
    return pl.read_parquet(path).select("trade_date").sort("trade_date")


__all__ = [
    "build_demand_leg",
    "build_monthly_leg",
    "build_semiconductor_legs_panel",
    "build_structural_legs",
    "build_supply_leg",
    "load_calendar",
]
