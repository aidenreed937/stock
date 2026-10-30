"""公司级三层信号合成：出口前瞻 × 资金确认 × 财报真扩张 → A/B/C/D/回避 评级。

评级口径（METHODOLOGY_COMPANY_FINAL §5 唯一口径）：
- A 强机会：出口强正 + 资金正 + 财报双正（三腿共振）；
- B 确认中：出口正 + 资金正（财报未双正/未披露）；
- C 兑现中：出口正 + 财报双正（资金未确认，需查价格是否已透支）；
- D 前瞻观察：仅出口正（等资金与财报）；
- 回避·顶背离⚠：出口见顶/双弱/量增速回落 且 资金负 且 财报仍正——最危险组合。

产物路径与既有脚本契约一致：``customs_company_signal.parquet`` / ``_latest.csv``。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import polars as pl

from stock_analytics.pipelines.customs_company.config import (
    SIGNAL_LATEST_FILE,
    SIGNAL_PANEL_FILE,
)


def _drop_excluded_products(
    company_latest: pl.DataFrame, exclude_products: Sequence[str]
) -> pl.DataFrame:
    """剔除快周期商品（§8.1 排除清单）行，仅保留观察表供研究。"""
    if not exclude_products:
        return company_latest
    return company_latest.filter(~pl.col("product_key").is_in(exclude_products))


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


def fund_leg_state(
    strength: float | None, margin_chg: float | None, *, margin_chg_th: float = 2.0
) -> tuple[str, str]:
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
    if strength > 0.5 or margin_chg > margin_chg_th:
        return "正", " ".join(ev)
    if strength < -0.5 and margin_chg < -margin_chg_th:
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


def load_moneyflow_strength(
    dir_path: Path, symbols: list[str], *, fund_window: int = 20
) -> pl.DataFrame:
    """近 fund_window 交易日主力净流入累计 / 成交额累计 → 资金强度(%)。"""
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
    mf = (
        mf.group_by("symbol")
        .tail(fund_window)
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


def load_margin_change(
    dir_path: Path, symbols: list[str], *, fund_window: int = 20
) -> pl.DataFrame:
    """近 fund_window 交易日融资余额变化率（margin_detail.rzye 首尾）→ (%)."""
    frames = []
    for f in sorted(dir_path.glob("**/*.parquet")):
        try:
            frames.append(pl.read_parquet(f).select(["symbol", "trade_date", "rzye"]))
        except Exception:
            continue
    if not frames:
        return pl.DataFrame(schema={"symbol": pl.String, "margin_chg_20d": pl.Float64})
    md = pl.concat(frames).unique().filter(pl.col("symbol").is_in(symbols)).sort("trade_date")
    md = md.group_by("symbol").tail(fund_window)
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


def load_quality_layers(company_frame: pl.DataFrame, dir_path: Path | str) -> pl.DataFrame:
    """同产品内竞争力分层（§5.4 修订）：company_frame 追加 quality_layer 列。

    - 亏损型：netprofit_margin < 0（绝对硬事实，跨产品剔除）；
    - 低竞争力：同产品内 netprofit_margin 与 grossprofit_margin **均低于同产品中位数**；
    - 正常：其余（含无财报覆盖/单公司产品，不误杀）。
    company_frame 需含 stock_code + product_key；dir_path 为 fina_indicator 目录。
    不依赖已删除的 company_exposure_map.csv，产品→公司映射取自 company_frame 本身。
    """
    base = company_frame.with_columns(pl.lit("正常").alias("quality_layer"))
    frames = []
    for f in sorted(Path(dir_path).glob("**/*.parquet")):
        try:
            frames.append(
                pl.read_parquet(f).select(
                    ["symbol", "end_date", "netprofit_margin", "grossprofit_margin"]
                )
            )
        except Exception:
            continue
    if not frames:
        return base
    fin = pl.concat(frames).filter(
        (pl.col("end_date").dt.month() == 12)
        & pl.col("netprofit_margin").is_not_null()
        & pl.col("grossprofit_margin").is_not_null()
    )
    if fin.is_empty():
        return base
    latest = fin.group_by("symbol").agg(pl.col("end_date").max())
    fin = (
        fin.join(latest, on=["symbol", "end_date"], how="inner")
        .group_by("symbol")
        .agg(
            pl.col("netprofit_margin").mean().alias("np"),
            pl.col("grossprofit_margin").mean().alias("gp"),
        )
        .rename({"symbol": "stock_code"})
    )
    joined = company_frame.join(fin, on="stock_code", how="left")
    med = joined.group_by("product_key").agg(
        pl.col("np").median().alias("med_np"),
        pl.col("gp").median().alias("med_gp"),
    )
    joined = joined.join(med, on="product_key", how="left")
    return joined.with_columns(
        pl.when(pl.col("np") < 0)
        .then(pl.lit("亏损型"))
        .when((pl.col("np") < pl.col("med_np")) & (pl.col("gp") < pl.col("med_gp")))
        .then(pl.lit("低竞争力"))
        .otherwise(pl.lit("正常"))
        .alias("quality_layer")
    )


def build_company_signal(
    company_latest: pl.DataFrame,
    *,
    moneyflow_path: Path | str,
    margin_path: Path | str,
    fina_path: Path | str,
    fund_window: int = 20,
    margin_chg_th: float = 2.0,
    exclude_products: Sequence[str] = (),
) -> pl.DataFrame:
    """合成公司三层信号（出口×资金×财报 → rating/risk_flag）。

    Args:
        company_latest: 公司×产品观察表的最新快照。
        moneyflow_path: 主力资金目录（tushare moneyflow）。
        margin_path: 两融目录（margin_detail）。
        fina_path: 财报指标目录（fina_indicator）。
        fund_window: 资金腿近 N 交易日。
        margin_chg_th: 融资余额变化率阈值。
        exclude_products: 快周期商品产品 key 列表（METHODOLOGY_COMPANY_FINAL §8.1），
            这些产品不产生交易信号，仅保留在观察表。

    Returns:
        信号面板（company 快照 + f1/f2/f3_state + rating/risk_flag）。
    """
    company_latest = _drop_excluded_products(company_latest, exclude_products)
    symbols = company_latest["stock_code"].unique().to_list()
    fund = load_moneyflow_strength(Path(moneyflow_path), symbols, fund_window=fund_window)
    margin = load_margin_change(Path(margin_path), symbols, fund_window=fund_window)
    fina = load_fina_latest(Path(fina_path), symbols)

    out = (
        company_latest.join(fund, left_on="stock_code", right_on="symbol", how="left")
        .join(margin, left_on="stock_code", right_on="symbol", how="left")
        .join(fina, left_on="stock_code", right_on="symbol", how="left")
    )
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
            lambda r: fund_leg_state(
                r["fund_strength_20d"], r["margin_chg_20d"], margin_chg_th=margin_chg_th
            )[0],
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
    return out.sort(["rating", "company_name", "product_key", "bind_segment"])


def save_company_signal(signal: pl.DataFrame, output_dir: Path | str) -> tuple[Path, Path]:
    """落盘公司信号（parquet + 最新 CSV，保持既有契约路径）。"""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    pq = root / SIGNAL_PANEL_FILE
    csv = root / SIGNAL_LATEST_FILE
    signal.write_parquet(pq)
    signal.write_csv(csv, include_header=True)
    return pq, csv


__all__ = [
    "build_company_signal",
    "export_leg_state",
    "fin_leg_state",
    "fund_leg_state",
    "load_fina_latest",
    "load_margin_change",
    "load_moneyflow_strength",
    "load_quality_layers",
    "rate",
    "save_company_signal",
]
