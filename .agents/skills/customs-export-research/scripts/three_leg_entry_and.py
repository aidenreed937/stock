#!/usr/bin/env python3
"""三腿 AND 入场前置条件筛选（无前视，支持 L2 / L3 粒度）。

规则（三腿 AND，缺一不可）:
  腿1 出口拐点 ±3 月窗口: 行业出口 3MMA yoy 由负转正 → 拐点月 T；
      数据发布滞后 1 个月（GACC 月度 T+20），有效窗口 = T+1 ~ T+3（无前视裁剪）。
  腿2 资金吸筹 20 日 + 突破 60 日高: 主力净流入 20 日累计 > 0 且
      收盘 >= 60 日滚动最高（当日收盘判定，T+1 执行，收益从次日基准算）。
  腿3 财报 TTM 双正: 信号日前最新已披露报告期营收 TTM 增速 >= 0 且
      净利 TTM 增速 >= 0（eff_date 披露日口径，无前视）。

数据:
  腿1: data/analytics/industry/customs_export_prosperity_panel.parquet (l2/l3 层)
  腿2: data/raw/tushare/market=CN/moneyflow (主力资金) + 行业日线
       (L2: industry_l2_panel_daily; L3: sw_daily industry_level=L3)
  腿3: L2: industry_l2_panel_daily (披露日口径); L3: sw_2021_l3_fs_* 重建

用法:
    uv run python scripts/three_leg_entry_and.py                  # L2（默认）
    uv run python scripts/three_leg_entry_and.py --level L3       # L3
    uv run python scripts/three_leg_entry_and.py --asof 2026-07
"""

from __future__ import annotations

import argparse
import glob
from pathlib import Path

import polars as pl

from stock_analytics.marts.shared.industry_structure.financial_ttm_rebuild import (
    expand_financial_with_ttm_rebuild,
)
from stock_data.catalog import DataCatalog
from stock_data.catalog.sw_industry_golden import (
    load_sw_2021_industry_dimension,
    load_sw_2021_industry_members,
)
from stock_data.core.runtime import DataRuntimeContext

DEFAULT_PANEL = Path("data/analytics/industry/customs_export_prosperity_panel.parquet")
DEFAULT_MART = Path("data/curated/mart/industry_l2_panel_daily.parquet")
DEFAULT_OUTPUT = Path("scratch/three_leg_entry_signals.parquet")

# 出口面板多映射行业（801033.SI;801034.SI）跳过
SKIP_L2 = {"801033.SI;801034.SI"}

L3_FS_DATASETS = (
    "sw_2021_l3_fs_non_financial",
    "sw_2021_l3_fs_bank",
    "sw_2021_l3_fs_security",
    "sw_2021_l3_fs_insurance",
)


def build_leg1(panel: pl.DataFrame, level: str) -> pl.DataFrame:
    """腿1: 拐点月 T（3MMA yoy 由负转正）+ 有效窗口 [T+1, T+3]（发布滞后 1 月裁剪）。

    ``level``: "l2" / "l3"，对应面板 granularity 层；返回码为面板 index_code
    （801081.SI / 850xxx.SI），由调用方映射到申万六位 industry_code。
    """
    gran = level.lower()
    sub = panel.filter(
        pl.col("granularity") == gran,
        pl.col("code").is_in(SKIP_L2).not_(),
        pl.col("yoy_growth_3mma").is_not_null(),
    )
    sub = sub.sort(["code", "report_month"])
    sub = sub.with_columns(
        pl.col("yoy_growth_3mma").shift(1).over("code").alias("prev_yoy")
    )
    turning = sub.filter(
        pl.col("prev_yoy").is_not_null() & (pl.col("prev_yoy") < 0) & (pl.col("yoy_growth_3mma") >= 0)
    ).select(
        pl.col("code").alias("industry_index"),
        pl.col("report_month").alias("turning_month"),
        pl.col("yoy_growth_3mma").alias("turning_yoy"),
    )
    # 有效窗口月: T+1(数据发布) ~ T+3(窗口右端)
    w = turning.with_columns(
        pl.col("turning_month").str.to_date("%Y-%m").dt.offset_by("1mo").dt.strftime("%Y-%m").alias("w_start"),
        pl.col("turning_month").str.to_date("%Y-%m").dt.offset_by("3mo").dt.strftime("%Y-%m").alias("w_end"),
    )
    return w.select(["industry_index", "turning_month", "turning_yoy", "w_start", "w_end"])


def _load_moneyflow() -> pl.DataFrame:
    """个股主力资金（日频，全历史）。"""
    parts = sorted(glob.glob("data/raw/tushare/market=CN/moneyflow/year=*/month=*/data.parquet"))
    frames = []
    for p in parts:
        cols = pl.scan_parquet(p).collect_schema().names()
        code_col = "symbol" if "symbol" in cols else "ts_code"
        frames.append(
            pl.read_parquet(p, columns=["trade_date", code_col, "net_mf_amount"]).rename({code_col: "sym"})
        )
    mf = pl.concat(frames).with_columns(
        pl.col("trade_date").cast(pl.String).str.strptime(pl.Date, "%Y%m%d").alias("d"),
        pl.col("sym").str.slice(0, 6).alias("stock6"),
    ).select(["d", "stock6", "net_mf_amount"]).rename({"d": "trade_date"})
    return mf


def _load_industry_price(runtime: DataRuntimeContext, level: str) -> pl.DataFrame:
    """行业指数日线: L2 用 panel_daily（披露日财务同源），L3 用 sw_daily。"""
    if level.upper() == "L2":
        return pl.read_parquet(DEFAULT_MART).select(
            ["industry_code", "trade_date", "close"]
        ).sort(["industry_code", "trade_date"])
    cat_ts = DataCatalog(data_source="tushare", runtime=runtime)
    sd = cat_ts.load_dataset("sw_daily")
    return sd.filter(pl.col("industry_level") == "L3").select(
        ["industry_code", "trade_date", "close"]
    ).sort(["industry_code", "trade_date"])


def build_leg2(runtime: DataRuntimeContext, level: str) -> pl.DataFrame:
    """腿2: 右侧启动信号日（资金吸筹20日 AND 突破60日高），按行业-月去重取首日。"""
    mf = _load_moneyflow()
    cat_ts = DataCatalog(data_source="tushare", runtime=runtime)
    members = load_sw_2021_industry_members(
        cat_ts, current_only=True, level=level.upper(), canonical_only=True,
        columns=("symbol", "industry_code"),
    ).rename({"symbol": "stock6"})
    ind_mf = (
        mf.join(members, on="stock6", how="inner")
        .group_by(["trade_date", "industry_code"])
        .agg(pl.col("net_mf_amount").sum().alias("net_mf"))
        .sort(["industry_code", "trade_date"])
    )

    price = _load_industry_price(runtime, level)
    merged = price.join(ind_mf, on=["industry_code", "trade_date"], how="left").sort(
        ["industry_code", "trade_date"]
    )
    merged = merged.with_columns(
        pl.col("net_mf").fill_null(0.0).rolling_sum(20).over("industry_code").alias("mf20"),
        pl.col("close").rolling_max(60).over("industry_code").alias("high60"),
    )
    merged = merged.with_columns(
        (pl.col("close") >= pl.col("high60")).alias("break60"),
        (pl.col("mf20") > 0).alias("acc20"),
    )
    merged = merged.with_columns(
        (pl.col("break60") & pl.col("acc20")).alias("right_start"),
    )
    sig = merged.filter(pl.col("right_start")).select(["industry_code", "trade_date"])
    # 行业-月去重（取当月首个信号日）
    sig = sig.with_columns(pl.col("trade_date").dt.strftime("%Y-%m").alias("ym")).sort(
        ["industry_code", "trade_date"]
    ).unique(subset=["industry_code", "ym"], keep="first")
    return sig.select(["industry_code", "trade_date", "ym"])


def build_leg3(runtime: DataRuntimeContext, level: str) -> pl.DataFrame:
    """腿3: 每日财报 TTM 双正状态（已披露口径）。

    L2 直接取 panel_daily 自带列（mart 已按 eff_date 前向填充，无前视）；
    L3 从理杏仁 L3 财务表经 ``expand_financial_with_ttm_rebuild`` 重建
    （eff_date 披露日），再按行业 join_asof 前向填充到日频。
    """
    if level.upper() == "L2":
        panel = pl.read_parquet(DEFAULT_MART)
        return panel.select(
            ["industry_code", "trade_date", "revenue_growth_ttm", "profit_growth_ttm"]
        ).with_columns(
            (
                pl.col("revenue_growth_ttm").is_not_null()
                & (pl.col("revenue_growth_ttm") >= 0)
                & pl.col("profit_growth_ttm").is_not_null()
                & (pl.col("profit_growth_ttm") >= 0)
            ).alias("leg3_ok")
        )

    cat_lx = DataCatalog(data_source="lixinger", runtime=runtime)
    parts = []
    for ds in L3_FS_DATASETS:
        fr = cat_lx.load_dataset(ds, columns=["reportDate", "symbol", "reportType", "standardDate", "q"])
        if not fr.is_empty():
            parts.append(expand_financial_with_ttm_rebuild(fr))
    fs = pl.concat(parts).select(
        ["industry_code", "eff_date", "revenue_growth_ttm", "profit_growth_ttm"]
    ).with_columns(
        (
            pl.col("revenue_growth_ttm").is_not_null()
            & (pl.col("revenue_growth_ttm") >= 0)
            & pl.col("profit_growth_ttm").is_not_null()
            & (pl.col("profit_growth_ttm") >= 0)
        ).alias("leg3_ok")
    ).drop_nulls(subset=["eff_date"]).sort(["industry_code", "eff_date"])
    # 按行业前向填充到日频（每个行业取 eff_date <= trade_date 的最新一期）
    price = _load_industry_price(runtime, "L3")
    out = price.join(
        fs.select(["industry_code", "eff_date", "leg3_ok"]),
        on="industry_code",
        how="left",
    ).sort(["industry_code", "trade_date", "eff_date"])
    out = out.filter(pl.col("eff_date") <= pl.col("trade_date"))
    out = out.sort(["industry_code", "trade_date", "eff_date"]).group_by(
        ["industry_code", "trade_date"]
    ).tail(1)
    return out.select(["industry_code", "trade_date", "leg3_ok"])


def _market_median(px: pl.DataFrame) -> pl.DataFrame:
    """市场同期行业中位（超额基准）。"""
    return px.group_by("trade_date").agg(
        pl.col("fwd120").median().alias("mkt_fwd120"),
        pl.col("fwd60").median().alias("mkt_fwd60"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="三腿 AND 入场前置条件筛选（无前视）")
    parser.add_argument("--level", default="L2", choices=["L2", "L3"], help="行业粒度")
    parser.add_argument("--asof", default=None, help="截至报告月（YYYY-MM），默认数据末月")
    args = parser.parse_args()

    runtime = DataRuntimeContext.from_root("data")
    panel = pl.read_parquet(DEFAULT_PANEL)
    gran = args.level.lower()

    # ---- 腿1: 出口拐点窗口 ----
    leg1 = build_leg1(panel, args.level)
    # 行业映射: 面板 index_code (801081.SI / 850xxx.SI) -> 申万内部六位 industry_code
    rt_dim = DataCatalog(data_source="tushare", runtime=runtime)
    dim = load_sw_2021_industry_dimension(rt_dim).filter(
        pl.col("classification") == "SW2021"
    ).select(
        pl.col("index_code").alias("industry_index"),
        pl.col("industry_code"),
    ).unique(subset=["industry_index"])
    leg1 = leg1.join(dim, on="industry_index", how="left")

    # ---- 腿2: 右侧启动信号（日频 → 月度首日）----
    leg2 = build_leg2(runtime, args.level)

    # ---- 腿3: 财报 TTM 双正（披露日口径）----
    leg3 = build_leg3(runtime, args.level)

    # ---- 三腿 AND ----
    sig = leg2.join(leg3.select(["industry_code", "trade_date", "leg3_ok"]),
                    on=["industry_code", "trade_date"], how="left")
    # 行业映射: 六位 industry_code -> 面板 index_code（取出口面板覆盖的行业）
    code_map = leg1.select(["industry_code", "industry_index"]).unique(subset=["industry_code"])
    # 信号月出口 yoy（对应粒度面板，用于假拐点过滤）
    sig = sig.join(code_map, on="industry_code", how="left")
    sig = sig.join(
        panel.filter(pl.col("granularity") == gran).select(
            ["code", "report_month", "yoy_growth_3mma"]
        ),
        left_on=["industry_index", "ym"], right_on=["code", "report_month"], how="left",
    ).rename({"yoy_growth_3mma": "sig_yoy"})
    # 腿1: 信号月落在任一拐点有效窗口 [T+1, T+3]
    # 且信号月 yoy 仍 >= 0（拐点后若再次转负=假拐点，窗口内信号剔除；
    # 例: 机床工具 2026-02 拐点后 03 月起转负，05 月信号不应算 leg1）
    covered = leg1.select(["industry_code", "w_start", "w_end"])
    sig = sig.join(covered, on="industry_code", how="left").with_columns(
        ((pl.col("ym") >= pl.col("w_start")) & (pl.col("ym") <= pl.col("w_end"))).alias("leg1_win")
    )
    sig = sig.group_by(["industry_code", "trade_date", "ym", "leg3_ok", "sig_yoy"]).agg(
        pl.col("leg1_win").any().alias("leg1_win")
    )
    sig = sig.with_columns(
        (pl.col("leg1_win") & (pl.col("sig_yoy").fill_null(-1.0) >= 0)).alias("leg1_ok")
    )
    sig = sig.with_columns((pl.col("leg1_ok") & pl.col("leg3_ok")).alias("three_leg"))

    # ---- 当前时点（asof 月，含发布滞后后的最近 3 月窗口扫描）----
    asof = args.asof or panel.filter(pl.col("granularity") == gran)["report_month"].max()
    from datetime import date

    asof_date = date(int(asof[:4]), int(asof[5:]), 1)
    win_months = []
    y, m = asof_date.year, asof_date.month
    for _ in range(3):
        win_months.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    cur = sig.filter(
        pl.col("ym").is_in(win_months),
        pl.col("three_leg"),
    ).unique(subset=["industry_code", "ym"])
    # 行业名称映射: 六位 industry_code -> 面板 index_code -> 名称
    code_map = leg1.select(["industry_code", "industry_index"]).unique(subset=["industry_code"])
    cur = cur.join(code_map, on="industry_code", how="left")
    cur = cur.join(
        panel.filter(pl.col("granularity") == gran).select(
            ["code", "name"]
        ).unique(subset=["code"]),
        left_on=["industry_index"], right_on=["code"], how="left",
    ).select(["industry_code", "name", "ym", "sig_yoy"])
    print(f"== {asof} 三腿 AND 共振行业（{args.level} 粒度，入场前置条件满足）: {cur.height} 个 ==")
    print(cur.to_pandas().to_string(index=False))

    # ---- 2020 后样本验证（无前视收益: 信号次日基准）----
    print(f"\n== 2020 后三腿共振事件收益（{args.level}，无前视: 次日基准）==")
    px = _load_industry_price(runtime, args.level)
    px = px.with_columns(
        pl.col("close").shift(-1).over("industry_code").alias("base"),
        pl.col("close").shift(-61).over("industry_code").alias("c60"),
        pl.col("close").shift(-121).over("industry_code").alias("c120"),
    )
    px = px.with_columns(
        (pl.col("c60") / pl.col("base") - 1).alias("fwd60"),
        (pl.col("c120") / pl.col("base") - 1).alias("fwd120"),
    )
    ev = sig.filter(pl.col("three_leg"), pl.col("ym") >= "2020-01").join(
        px.select(["industry_code", "trade_date", "fwd60", "fwd120"]),
        on=["industry_code", "trade_date"], how="left",
    )
    market_med = _market_median(px)
    ev = ev.join(market_med, on="trade_date", how="left").with_columns(
        (pl.col("fwd120") - pl.col("mkt_fwd120")).alias("excess120"),
        (pl.col("fwd60") - pl.col("mkt_fwd60")).alias("excess60"),
    )
    f60 = ev["fwd60"].drop_nulls()
    f120 = ev["fwd120"].drop_nulls()
    e120 = ev["excess120"].drop_nulls()
    print(f"样本: {ev.height} 事件 (月度去重)")
    if f60.len():
        print(f"后60日  中位 {f60.median():+.4f} | >0 {((f60 > 0).mean() * 100):.1f}%")
    if f120.len():
        print(f"后120日 中位 {f120.median():+.4f} | >0 {((f120 > 0).mean() * 100):.1f}%")
    if e120.len():
        print(f"超额120日 中位 {e120.median():+.4f} | >0 {((e120 > 0).mean() * 100):.1f}%")

    out = Path(str(DEFAULT_OUTPUT).replace(".parquet", f"_{args.level.lower()}.parquet"))
    sig.write_parquet(out)
    print(f"\n信号明细已写出: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
