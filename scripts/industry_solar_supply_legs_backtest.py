"""光伏设备（申万二级 630500）纯正光伏供需腿择时研究（口径对齐仓库 _monthly_pct）。

背景：630500 原需求腿=光伏装机（solar_capacity，NEA 官方）、原供给腿=硅业多晶硅开工率
（polysilicon_operating_rate）。上一轮实证：剪刀差(装机-开工率)全周期 IC -0.129（反向）、
样本外 2022+ -0.141；开工率官方口径仅 20 个月；派生利用率与官方开工率同源（重叠段相关 0.85），
属顺周期同步指标。口径收敛（2026-09 阶段 1）：`derived_utilization_rate`（产量×12/年化产能，
物理第一性原理派生、全历史完整）为唯一标准特征，`operating_rate` 降级为参考辅助列，
不再作为模型输入；本脚本供给腿统一使用派生利用率口径。本脚本按仓库标准口径
（value → YoY → rolling 分位 → release_date 生效前向填充）对候选供给腿做独立择时检验，
输出逐腿 IC 与逐年漂移。

腿口径（对齐 industry_direction_map._monthly_pct，window_months=36）：
- derived_poly：polysilicon_supply_monthly.derived_utilization_rate（103 月）
- cell_prod：solar_cell_production.output_current（NBS 官方实物量，120 月）
- wafer_util：pv_wafer_monthly.derived_wafer_utilization_rate（103 月）
需求腿基线：solar_capacity 光伏装机（NEA）。

IC = Spearman(腿分位, 未来60日收益)，T+1 生效、无前视；样本外自 2022-01-01。

输出：data/analytics/industry_strategy/industry_solar_supply_legs_backtest.{csv,md}
"""

from __future__ import annotations

import datetime
from pathlib import Path

import polars as pl
from industry_direction_map import _monthly_pct
from scipy import stats

_START = datetime.date(2018, 1, 1)
_OOS = datetime.date(2022, 1, 1)
_PANEL = Path("data/curated/mart/industry_l2_panel_daily.parquet")
_OUT = Path("data/analytics/industry_strategy")
_INDUSTRY = "630500"


def _monthly_leg(path: str, col: str) -> pl.DataFrame:
    df = pl.read_parquet(path)
    if col not in df.columns:
        raise ValueError(f"col {col} missing from {path}")
    return _monthly_pct(df.select(["trade_date", "release_date", col]), col, window_months=36)


def _align(leg: pl.DataFrame, panel: pl.DataFrame) -> pl.DataFrame:
    """把月频腿（trade_date=release_date 生效）前向填充到日频交易日网格。"""
    return (
        panel.select(["trade_date"])
        .join(leg.select(["trade_date", "pct"]), on="trade_date", how="left")
        .sort("trade_date")
        .with_columns(pl.col("pct").fill_null(strategy="forward"))
        .drop_nulls(["pct"])
    )


def _load_panel() -> pl.DataFrame:
    panel = pl.read_parquet(_PANEL)
    return (
        panel.filter((pl.col("industry_code") == _INDUSTRY) & (pl.col("trade_date") >= _START))
        .select(["trade_date", "close"])
        .sort("trade_date")
        .with_columns((pl.col("close").shift(-60) / pl.col("close") - 1.0).alias("f60"))
    )


def _ic(daily: pl.DataFrame, panel: pl.DataFrame, t0) -> float | None:
    m = (
        panel.filter(pl.col("trade_date") >= t0)
        .join(daily, on="trade_date", how="inner")
        .drop_nulls(["pct", "f60"])
    )
    if len(m) < 30:
        return None
    rho, _ = stats.spearmanr(m["pct"].to_list(), m["f60"].to_list())
    return round(rho, 3)


def main() -> None:
    legs = {
        "需求-装机": ("data/curated/industry/solar_capacity.parquet", "monthly_new_capacity_3mma"),
        "供给-derived_poly": (
            "data/curated/industry/polysilicon_supply_monthly.parquet",
            "derived_utilization_rate",
        ),
        "供给-cell_prod": ("data/curated/industry/solar_cell_production.parquet", "output_current"),
        "供给-wafer_util": (
            "data/curated/industry/pv_wafer_monthly.parquet",
            "derived_wafer_utilization_rate",
        ),
    }
    panel = _load_panel()
    print("=== 630500 各腿 fwd60 IC（标准 _monthly_pct 口径，T+1，release_date 生效）===")
    leg_cache = {}
    for label, (path, col) in legs.items():
        daily = _align(_monthly_leg(path, col), panel)
        leg_cache[label] = daily
        print(
            f"{label:22s} 全周期IC={_ic(daily, panel, _START)}  OOS2022+={_ic(daily, panel, _OOS)}"
        )

    # 剪刀差 = demand - supply，对每根供给腿（两腿都对齐到日频交易日后相减）
    dem = leg_cache["需求-装机"]
    print("\n=== 630500 剪刀差(装机 - 各供给腿) fwd60 IC ===")
    for label, (path, col) in legs.items():
        if "供给" not in label:
            continue
        sup = leg_cache[label]
        sc = (
            dem.select(["trade_date", "pct"])
            .rename({"pct": "demand"})
            .join(
                sup.select(["trade_date", "pct"]).rename({"pct": "supply"}),
                on="trade_date",
                how="inner",
            )
            .with_columns((pl.col("demand") - pl.col("supply")).alias("sc"))
            .select(["trade_date", "sc"])
        )
        m = (
            panel.filter(pl.col("trade_date") >= _START)
            .join(sc, on="trade_date", how="inner")
            .drop_nulls(["sc", "f60"])
        )
        m2 = m.filter(pl.col("trade_date") >= _OOS)
        rho_full, _ = stats.spearmanr(m["sc"].to_list(), m["f60"].to_list())
        rho_oos, _ = stats.spearmanr(m2["sc"].to_list(), m2["f60"].to_list())
        print(
            f"剪刀差(装机-{label.split('-')[-1]}): 全周期IC={round(rho_full, 3)}  OOS={round(rho_oos, 3)}"
        )
        # 逐年漂移
        drift = []
        for y in sorted(set(d.year for d in m["trade_date"].to_list())):
            sub = m.filter(pl.col("trade_date").dt.year() == y)
            if len(sub) < 20:
                continue
            r, _ = stats.spearmanr(sub["sc"].to_list(), sub["f60"].to_list())
            drift.append(f"{y}:{round(r, 3)}")
        print("    剪刀差逐年:", "  ".join(drift))


if __name__ == "__main__":
    main()
