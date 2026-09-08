#!/usr/bin/env python3
"""公司级三层信号合成：出口前瞻 × 资金确认 × 财报真扩张。

把出口景气研究链升级为可交易信号（2026-09，配合
docs/research/customs_export_forward/METHODOLOGY_COMPANY_FINAL.md §3 股价验证）：
- **腿1 出口前瞻**：公司段级出口 3MMA yoy + 驱动质量 + 拐点/二阶导
  （来自 build_customs_company_exposure.py 的公司观察表）；
- **腿2 资金确认**：个股双资金信号——主力净流入（tushare moneyflow，近 20
  交易日累计/成交额强度）+ 两融杠杆（margin_detail 融资余额近 20 日变化率）；
- **腿3 财报真扩张**：最新报告期营收/净利 yoy（fina_indicator）——后视验证
  是否真扩张（避免在景气顶接盘）。

评级（三腿同向最强，背离最危险）：
- A 强机会：出口强正 + 资金正 + 财报双正（三腿共振）；
- B 确认中：出口正 + 资金正（财报未双正/未披露）；
- C 兑现中：出口正 + 财报双正（资金未确认，需查价格是否已透支）；
- D 前瞻观察：仅出口正（等资金与财报）；
- 顶背离 ⚠：出口见顶/双弱/量增速回落 且 资金负 且 财报仍正——最危险组合，
  出口已弱、资金在撤、财报滞后为正，减仓/回避。

用法:
    uv run python scripts/build_customs_company_signal.py
    uv run python scripts/build_customs_company_signal.py --output-csv scratch/company_signal_latest.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

DEFAULT_COMPANY = Path("data/analytics/industry/customs_company_exposure_latest.csv")
DEFAULT_OUTPUT_PQ = Path("data/analytics/industry/customs_company_signal.parquet")
DEFAULT_OUTPUT_CSV = Path("data/analytics/industry/customs_company_signal_latest.csv")
DEFAULT_MONEYFLOW = Path("data/curated/tushare/market=CN/moneyflow")
DEFAULT_MARGIN = Path("data/curated/tushare/market=CN/margin_detail")
DEFAULT_FINA = Path("data/curated/tushare/market=CN/fina_indicator")
FUND_WINDOW = 20  # 资金腿近 N 交易日
MARGIN_CHG_TH = 2.0  # 融资余额 20 日变化率阈值（%）


def export_leg_state(
    yoy: float | None, drive: str | None, turn: str | None, second: str | None
) -> tuple[str, str]:
    """腿1 出口前瞻状态 → (state, evidence)。"""
    if yoy is None:
        return "未知", "出口 yoy NaN"
    strong = yoy >= 0.3 and drive in ("量价齐升", "量驱动")
    if strong:
        state = "强正"
    elif yoy > 0:
        state = "正"
    elif yoy > -0.1:
        state = "弱"
    else:
        state = "负"
    flags = [f"yoy {yoy * 100:+.0f}%", drive or "-"]
    if turn == "启动拐点":
        flags.append("启动")
    if turn == "见顶拐点" or second == "量增速回落":
        flags.append("见顶/回落")
    return state, " ".join(flags)


def fund_leg_state(strength: float | None, margin_chg: float | None) -> tuple[str, str]:
    """腿2 资金状态：主力净流入强度 + 融资余额变化率 → (state, evidence)。

    主力与两融任一确认即"正"（杠杆确认滞后于主力但佐证趋势）；双负才"负"。
    """
    ev = []
    if strength is not None:
        ev.append(f"主力 {strength:+.2f}%")
    if margin_chg is not None:
        ev.append(f"融资 {margin_chg:+.1f}%")
    if not ev:
        return "未知", "无资金数据"
    if strength is None:
        strength = 0.0
    if margin_chg is None:
        margin_chg = 0.0
    if strength > 0.5 or margin_chg > MARGIN_CHG_TH:
        return "正", " ".join(ev)
    if strength < -0.5 and margin_chg < -MARGIN_CHG_TH:
        return "负", " ".join(ev)
    return "平", " ".join(ev)


def fin_leg_state(or_yoy: float | None, np_yoy: float | None) -> tuple[str, str]:
    """腿3 财报真扩张：最新期营收/净利 yoy → (state, evidence)。"""
    if or_yoy is None or np_yoy is None:
        return "未知", "财报数据缺失"
    if or_yoy > 0 and np_yoy > 0:
        return "真扩张", f"营收 {or_yoy:+.0f}% 净利 {np_yoy:+.0f}%"
    if or_yoy > 0:
        return "增收不增利", f"营收 {or_yoy:+.0f}% 净利 {np_yoy:+.0f}%"
    return "未兑现", f"营收 {or_yoy:+.0f}% 净利 {np_yoy:+.0f}%"


def rate(f1: str, f2: str, f3: str, turn: str | None, second: str | None) -> tuple[str, str]:
    """三层信号评级 → (rating, risk_flag)。"""
    peak_risk = (turn == "见顶拐点") or (second == "量增速回落") or (f1 == "负")
    if peak_risk and f2 == "负" and f3 == "真扩张":
        return "回避", "顶背离⚠"
    if f1 in ("强正", "正") and f2 == "正" and f3 == "真扩张":
        return "A强机会", ""
    if f1 in ("强正", "正") and f2 == "正":
        return "B确认中", ""
    if f1 in ("强正", "正") and f3 == "真扩张":
        return "C兑现中", ""
    if f1 in ("强正", "正"):
        return "D前瞻观察", ""
    return "观望", ""


def load_moneyflow_strength(dir_path: Path, symbols: list[str]) -> pl.DataFrame:
    """近 FUND_WINDOW 交易日主力净流入累计 / 成交额累计 → 资金强度(%)。"""
    frames = []
    for f in sorted(dir_path.glob("**/*.parquet")):
        try:
            frames.append(
                pl.read_parquet(f).select(
                    [
                        "symbol",
                        "trade_date",
                        "net_mf_amount",
                        "buy_elg_amount",
                        "buy_lg_amount",
                        "buy_md_amount",
                        "buy_sm_amount",
                    ]
                )
            )
        except Exception:
            continue
    if not frames:
        return pl.DataFrame(schema={"symbol": pl.String, "fund_strength_20d": pl.Float64})
    mf = pl.concat(frames).unique().filter(pl.col("symbol").is_in(symbols))
    mf = mf.with_columns(
        (
            pl.col("buy_elg_amount")
            + pl.col("buy_lg_amount")
            + pl.col("buy_md_amount")
            + pl.col("buy_sm_amount")
        ).alias("turnover")
    ).sort("trade_date")
    # 每 symbol 最近 FUND_WINDOW 个交易日
    mf = (
        mf.group_by("symbol")
        .tail(FUND_WINDOW)
        .group_by("symbol")
        .agg(
            pl.col("net_mf_amount").sum().alias("net"),
            pl.col("turnover").sum().alias("turn"),
        )
        .with_columns(
            pl.when(pl.col("turn") > 0)
            .then(pl.col("net") / pl.col("turn") * 100)
            .otherwise(None)
            .alias("fund_strength_20d")
        )
        .select(["symbol", "fund_strength_20d"])
    )
    return mf


def load_margin_change(dir_path: Path, symbols: list[str]) -> pl.DataFrame:
    """近 FUND_WINDOW 交易日融资余额变化率（margin_detail.rzye 首尾）→ (%)."""
    frames = []
    for f in sorted(dir_path.glob("**/*.parquet")):
        try:
            frames.append(pl.read_parquet(f).select(["symbol", "trade_date", "rzye"]))
        except Exception:
            continue
    if not frames:
        return pl.DataFrame(schema={"symbol": pl.String, "margin_chg_20d": pl.Float64})
    md = pl.concat(frames).unique().filter(pl.col("symbol").is_in(symbols)).sort("trade_date")
    md = md.group_by("symbol").tail(FUND_WINDOW)
    # 每 symbol 窗口内首尾融资余额 → 变化率
    out = (
        md.group_by("symbol")
        .agg(
            pl.col("rzye").first().alias("rz0"),
            pl.col("rzye").last().alias("rz1"),
        )
        .with_columns(
            pl.when(pl.col("rz0") > 0)
            .then((pl.col("rz1") / pl.col("rz0") - 1) * 100)
            .otherwise(None)
            .alias("margin_chg_20d")
        )
        .select(["symbol", "margin_chg_20d"])
    )
    return out


def load_fina_latest(dir_path: Path, symbols: list[str]) -> pl.DataFrame:
    """每公司最新报告期 or_yoy / netprofit_yoy（fina_indicator 指标口径）。"""
    frames = []
    for f in sorted(dir_path.glob("**/*.parquet")):
        try:
            frames.append(
                pl.read_parquet(f).select(["symbol", "end_date", "or_yoy", "netprofit_yoy"])
            )
        except Exception:
            continue
    if not frames:
        return pl.DataFrame(
            schema={"symbol": pl.String, "or_yoy": pl.Float64, "netprofit_yoy": pl.Float64}
        )
    fi = pl.concat(frames).unique().filter(pl.col("symbol").is_in(symbols))
    latest = fi.sort("end_date").group_by("symbol").agg(pl.col("end_date").last().alias("last_d"))
    out = (
        fi.join(latest, on="symbol")
        .filter(pl.col("end_date") == pl.col("last_d"))
        .select(["symbol", "or_yoy", "netprofit_yoy"])
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", default=str(DEFAULT_COMPANY), help="公司观察表 CSV")
    parser.add_argument("--output-pq", default=str(DEFAULT_OUTPUT_PQ), help="信号 parquet")
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV), help="信号 CSV")
    parser.add_argument("--moneyflow", type=Path, default=DEFAULT_MONEYFLOW)
    parser.add_argument("--margin", type=Path, default=DEFAULT_MARGIN)
    parser.add_argument("--fina", type=Path, default=DEFAULT_FINA)
    args = parser.parse_args()

    comp = pl.read_csv(args.company)
    symbols = comp["stock_code"].unique().to_list()
    fund = load_moneyflow_strength(args.moneyflow, symbols)
    margin = load_margin_change(args.margin, symbols)
    fina = load_fina_latest(args.fina, symbols)

    out = (
        comp.join(fund, left_on="stock_code", right_on="symbol", how="left")
        .join(margin, left_on="stock_code", right_on="symbol", how="left")
        .join(fina, left_on="stock_code", right_on="symbol", how="left")
    )
    # 三腿状态（用 map_rows 避免逐行 python 循环）
    out = out.with_columns(
        pl.struct(["value_yoy_3mma", "驱动类型", "拐点", "二阶导"])
        .map_elements(
            lambda r: export_leg_state(r["value_yoy_3mma"], r["驱动类型"], r["拐点"], r["二阶导"])[
                0
            ],
            return_dtype=pl.String,
        )
        .alias("f1_state"),
        pl.struct(["fund_strength_20d", "margin_chg_20d"])
        .map_elements(
            lambda r: fund_leg_state(r["fund_strength_20d"], r["margin_chg_20d"])[0],
            return_dtype=pl.String,
        )
        .alias("f2_state"),
        pl.struct(["or_yoy", "netprofit_yoy"])
        .map_elements(
            lambda r: fin_leg_state(r["or_yoy"], r["netprofit_yoy"])[0],
            return_dtype=pl.String,
        )
        .alias("f3_state"),
    )
    out = out.with_columns(
        pl.struct(["f1_state", "f2_state", "f3_state", "拐点", "二阶导"])
        .map_elements(
            lambda r: rate(r["f1_state"], r["f2_state"], r["f3_state"], r["拐点"], r["二阶导"])[0],
            return_dtype=pl.String,
        )
        .alias("rating"),
        pl.struct(["f1_state", "f2_state", "f3_state", "拐点", "二阶导"])
        .map_elements(
            lambda r: rate(r["f1_state"], r["f2_state"], r["f3_state"], r["拐点"], r["二阶导"])[1],
            return_dtype=pl.String,
        )
        .alias("risk_flag"),
    )
    out = out.sort(["rating", "company_name", "product_key", "bind_segment"])
    out.write_parquet(Path(args.output_pq))
    out.write_csv(Path(args.output_csv))

    print(
        f"信号行: {out.height}  公司: {out['company_name'].n_unique()}  产品: {out['product_key'].n_unique()}"
    )
    print("评级分布:")
    print(
        out.group_by("rating").len().sort("len", descending=True).to_pandas().to_string(index=False)
    )
    n_risk = out.filter(pl.col("risk_flag") != "").height
    print(f"顶背离/回避标记: {n_risk} 行")
    print(f"已写出: {Path(args.output_pq)} / {Path(args.output_csv)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
