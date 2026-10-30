"""严格事件研究：评级日（信号月）→ 未来 12 个月收益/胜率（H8 动态链路）。

逐月重建三层信号（无前视）：
- f1 出口腿：公司×产品面板（``customs_company_h8_product_panel.parquet``）
  当月 3MMA yoy / 驱动 / 拐点 / 二阶导 → ``export_leg_state``；
- f2 资金腿：截至信号月末的 20 交易日主力净流入强度 + 融资余额变化率；
- f3 财报腿：截至信号月末**已披露**（``ann_date <= 月末``）的最新报告期
  or_yoy / netprofit_yoy（严格 PIT，不用"最新一期"这种前视口径）；
- 评级复用 ``signal.rate``（A/B/C/D/回避/观望）。

前视消除（METHODOLOGY §6 / release_calendar）：
- 信号月 M 的数据发布时间 = ``release_date_for(M)``；可交易起始月 =
  ``effective_month(M)``（发布月的下一个月）；
- 买入价 = effective 月第一个交易日前复权收盘价；卖出价 = 12 个月后的
  前复权收盘价（无足够未来数据则剔除该样本）；
- 基准 = 沪深300 同期收益（同样 effective 月首日至 +12 月）。

产出（stdout 表格 + parquet）：
- 按月评级池：样本数 / 胜率 / 平均收益 / 平均超额 / 中位收益；
- 汇总：全池 + A/B/C/D/回避 各自 1y 胜率与超额。

用法:
    uv run python scripts/backtest_customs_company_h8_event.py
    uv run python scripts/backtest_customs_company_h8_event.py --min-signal 2021-06
"""

from __future__ import annotations

import argparse
import glob
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

import polars as pl

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from stock_analytics.pipelines.customs_company.signal import (  # noqa: E402
    export_leg_state,
    fin_leg_state,
    fund_leg_state,
    rate,
)
from stock_data.fetcher.industry.customs.release_calendar import effective_month  # noqa: E402

PANEL = Path("data/analytics/industry/customs_company_h8_product_panel.parquet")
BAR_ROOT = Path("data/curated/tushare/market=CN/stock_daily_bar")
AF_ROOT = Path("data/curated/tushare/market=CN/adj_factor")
IDX = Path("data/curated/tushare/market=CN/index_daily_bar/data.parquet")
MF_ROOT = Path("data/curated/tushare/market=CN/moneyflow")
MG_ROOT = Path("data/curated/tushare/market=CN/margin_detail")
FINA_ROOT = Path("data/curated/tushare/market=CN/fina_indicator")
DEFAULT_OUTPUT = Path("data/analytics/industry/customs_company_h8_event_backtest.parquet")
HOLD_MONTHS = 12


def _glob_years(root: Path, columns: list[str]) -> pl.DataFrame:
    files = sorted(glob.glob(f"{root}/**/*.parquet", recursive=True))
    frames = []
    for f in files:
        try:
            frames.append(pl.read_parquet(f, columns=columns))
        except Exception:
            continue
    if not frames:
        raise FileNotFoundError(f"未找到 Parquet: {root}")
    return pl.concat(frames)


def _px_matrix() -> tuple[pl.DataFrame, pl.DataFrame]:
    """全市场前复权收盘价长表（symbol × trade_date → adj_close）+ 沪深300。"""
    bar = _glob_years(BAR_ROOT, ["symbol", "trade_date", "close"])
    af = _glob_years(AF_ROOT, ["symbol", "trade_date", "adj_factor"])
    latest_af = (
        af.sort("trade_date").group_by("symbol").agg(pl.col("adj_factor").last().alias("af_latest"))
    )
    px = (
        bar.join(af, on=["symbol", "trade_date"], how="inner")
        .join(latest_af, on="symbol", how="left")
        .with_columns(
            (pl.col("close") * pl.col("adj_factor") / pl.col("af_latest")).alias("adj_close")
        )
        .select(["symbol", "trade_date", "adj_close"])
        .sort(["symbol", "trade_date"])
    )
    idx = pl.read_parquet(IDX, columns=["symbol", "trade_date", "close"]).filter(
        pl.col("symbol") == "000300.SH"
    )
    return px, idx


def _month_end(month: str) -> date:
    year, mon = int(month[:4]), int(month[5:7])
    if mon == 12:
        return date(year, 12, 31)
    nxt = date(year, mon + 1, 1)
    return date(nxt.year, nxt.month, 1) - timedelta(days=1)


def _build_f2(
    panel_symbols: list[str], month: str, mf: pl.DataFrame, mg: pl.DataFrame
) -> pl.DataFrame:
    """截至信号月末的 20 交易日主力强度 + 融资变化率（全市场数据按 symbol 过滤）。"""
    end = _month_end(month)
    mf_s = mf.filter((pl.col("symbol").is_in(panel_symbols)) & (pl.col("trade_date") <= end)).sort(
        ["symbol", "trade_date"]
    )
    strength = (
        mf_s.group_by("symbol")
        .tail(20)
        .with_columns(
            (
                pl.col("buy_elg_amount")
                + pl.col("buy_lg_amount")
                + pl.col("buy_md_amount")
                + pl.col("buy_sm_amount")
            ).alias("turnover")
        )
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
    mg_s = mg.filter((pl.col("symbol").is_in(panel_symbols)) & (pl.col("trade_date") <= end)).sort(
        ["symbol", "trade_date"]
    )
    margin = (
        mg_s.group_by("symbol")
        .tail(20)
        .group_by("symbol")
        .agg(pl.col("rzye").first().alias("rz0"), pl.col("rzye").last().alias("rz1"))
        .with_columns(
            pl.when(pl.col("rz0") > 0)
            .then((pl.col("rz1") / pl.col("rz0") - 1) * 100)
            .otherwise(None)
            .alias("margin_chg_20d")
        )
        .select(["symbol", "margin_chg_20d"])
    )
    return strength.join(margin, on="symbol", how="full")


def _build_f3(panel_symbols: list[str], month: str, fina: pl.DataFrame) -> pl.DataFrame:
    """截至信号月末已披露（ann_date <= 月末）的最新报告期 or_yoy / netprofit_yoy。"""
    end = _month_end(month)
    fi = fina.filter(
        (pl.col("symbol").is_in(panel_symbols))
        & (pl.col("ann_date").is_not_null())
        & (pl.col("ann_date") <= end)
        & (pl.col("end_date").is_not_null())
    ).sort(["symbol", "end_date"])
    latest = fi.group_by("symbol").agg(pl.col("end_date").last().alias("last_d"))
    out = (
        fi.join(latest, on="symbol", how="inner")
        .filter(pl.col("end_date") == pl.col("last_d"))
        .select(["symbol", "or_yoy", "netprofit_yoy"])
        .unique(subset=["symbol"])
    )
    return out


def _month_shift(month: str, delta: int) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    total = year * 12 + (mon - 1) + delta
    return f"{total // 12:04d}-{(total % 12) + 1:02d}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-signal", default="2020-06", help="最早信号月（留足 3MMA yoy 与 12 个月未来）"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    panel = pl.read_parquet(PANEL)
    px, idx = _px_matrix()
    mf = _glob_years(
        MF_ROOT,
        [
            "symbol",
            "trade_date",
            "net_mf_amount",
            "buy_elg_amount",
            "buy_lg_amount",
            "buy_md_amount",
            "buy_sm_amount",
        ],
    )
    mg = _glob_years(MG_ROOT, ["symbol", "trade_date", "rzye"])
    fina = _glob_years(FINA_ROOT, ["symbol", "end_date", "ann_date", "or_yoy", "netprofit_yoy"])
    sb = pl.read_parquet(
        "data/curated/tushare/market=CN/stock_basic/data.parquet",
        columns=["symbol", "list_date"],
    ).with_columns(pl.col("list_date").cast(pl.Date, strict=False))
    # 防御性点-in-time：剔除信号月早于上市日的未来公司（面板若已按上市日构建则无副作用）
    panel = (
        panel.join(sb, on="symbol", how="left")
        .filter(
            pl.col("list_date").is_not_null()
            & (pl.col("report_month").str.to_date("%Y-%m") >= pl.col("list_date"))
        )
        .drop("list_date")
    )
    print(
        f"px: {px.height} 行 | mf: {mf.height} | mg: {mg.height} | fina: {fina.height} | "
        f"fina 最新 ann_date: {fina['ann_date'].max()!s}"
    )

    idx_by_date = (
        idx.sort(["trade_date"])
        .with_columns(pl.col("close").alias("idx_close"))
        .select(["trade_date", "idx_close"])
    )

    # 信号月序列：面板月序（去重排序）
    months = sorted(panel["report_month"].unique().to_list())
    months = [m for m in months if m >= args.min_signal]
    panel_symbols = sorted(panel["symbol"].unique().to_list())

    records: list[dict[str, object]] = []
    for month in months:
        eff = effective_month(month)
        px_max = px["trade_date"].max()
        px_max_s = px_max.isoformat() if isinstance(px_max, date) else str(px_max)
        if eff > px_max_s[:7]:
            break  # 信号已无足够未来数据
        # 该信号月的公司×产品候选（f1 出口腿）
        sub = panel.filter(pl.col("report_month") == month).select(
            [
                "symbol",
                "company_name",
                "product_key",
                "product_exposure",
                "value_yoy_3mma",
                "volume_yoy_3mma",
                "price_yoy_3mma",
                "驱动类型",
                "拐点",
                "二阶导",
            ]
        )
        if sub.is_empty():
            continue
        f2 = _build_f2(panel_symbols, month, mf, mg)
        f3 = _build_f3(panel_symbols, month, fina)

        rows = sub.join(f2, on="symbol", how="left").join(f3, on="symbol", how="left")
        for r in rows.iter_rows(named=True):
            f1_state, _ = export_leg_state(
                r["value_yoy_3mma"], r["驱动类型"], r["拐点"], r["二阶导"]
            )
            f2_state, _ = fund_leg_state(r["fund_strength_20d"], r["margin_chg_20d"])
            f3_state, _ = fin_leg_state(r["or_yoy"], r["netprofit_yoy"])
            rating, risk = rate(f1_state, f2_state, f3_state, r["拐点"], r["二阶导"])
            records.append(
                {
                    "signal_month": month,
                    "effective_month": eff,
                    "symbol": r["symbol"],
                    "company_name": r["company_name"],
                    "product_key": r["product_key"],
                    "exposure": r["product_exposure"],
                    "f1_state": f1_state,
                    "f2_state": f2_state,
                    "f3_state": f3_state,
                    "rating": rating,
                    "risk_flag": risk,
                }
            )

    signals = pl.DataFrame(records)
    print(f"逐月信号重建完成: {signals.height} 行, 信号月 {signals['signal_month'].n_unique()} 个")
    if signals.is_empty():
        return

    # ---- 收益对齐：effective 月首日买入，+HOLD_MONTHS 月后卖出（前复权）----
    # 每个信号自身附加卖出月（= effective 月 + HOLD_MONTHS），避免跨信号错配
    signals = signals.with_columns(
        pl.col("effective_month")
        .map_elements(lambda m: _month_shift(str(m), HOLD_MONTHS), return_dtype=pl.String)
        .alias("sell_month")
    )

    def _px_first_of_month(month_keys: pl.DataFrame) -> pl.DataFrame:
        """按 (symbol, month) 取该月首个交易日前复权收盘价（month_keys: symbol+month 列）。"""
        px_m = px.with_columns(pl.col("trade_date").dt.strftime("%Y-%m").alias("tm"))
        return (
            px_m.join(
                month_keys, left_on=["symbol", "tm"], right_on=["symbol", "month"], how="inner"
            )
            .sort(["symbol", "tm", "trade_date"])
            .group_by(["symbol", "tm"])
            .agg(pl.col("adj_close").first().alias("px"))
            .rename({"tm": "month"})
        )

    buy_map = _px_first_of_month(
        signals.select(["symbol", "effective_month"]).rename({"effective_month": "month"})
    ).rename({"px": "buy_px"})
    signals = signals.join(
        buy_map, left_on=["symbol", "effective_month"], right_on=["symbol", "month"], how="inner"
    )

    sell_map = _px_first_of_month(
        signals.select(["symbol", "sell_month"]).rename({"sell_month": "month"})
    ).rename({"px": "sell_px"})
    signals = signals.join(
        sell_map, left_on=["symbol", "sell_month"], right_on=["symbol", "month"], how="inner"
    )

    # 基准沪深300：effective 月首日 → +HOLD_MONTHS 月首日
    bench_map = (
        idx_by_date.with_columns(pl.col("trade_date").dt.strftime("%Y-%m").alias("tm"))
        .join(
            signals.select(["effective_month"]).unique(),
            left_on="tm",
            right_on="effective_month",
            how="inner",
        )
        .sort(["tm", "trade_date"])
        .group_by("tm")
        .agg(pl.col("idx_close").first().alias("bench_buy"))
        .rename({"tm": "effective_month"})
    )
    bench_sell = (
        idx_by_date.with_columns(pl.col("trade_date").dt.strftime("%Y-%m").alias("tm"))
        .join(
            signals.select(["sell_month"]).unique(),
            left_on="tm",
            right_on="sell_month",
            how="inner",
        )
        .sort(["tm", "trade_date"])
        .group_by("tm")
        .agg(pl.col("idx_close").first().alias("bench_sell"))
        .rename({"tm": "sell_month"})
    )
    signals = (
        signals.join(bench_map, on="effective_month", how="left")
        .join(bench_sell, on="sell_month", how="left")
        .with_columns(
            (pl.col("sell_px") / pl.col("buy_px") - 1).alias("ret_12m"),
            (pl.col("bench_sell") / pl.col("bench_buy") - 1).alias("bench_12m"),
        )
        .with_columns((pl.col("ret_12m") - pl.col("bench_12m")).alias("excess_12m"))
    )

    out = signals.drop_nulls(["ret_12m", "bench_12m"])
    print(f"收益对齐样本: {out.height} 行（剔除无 12 个月未来数据样本）")

    # ---- 统计：按评级池 ----
    stats = []
    for rating in ["A强机会", "B确认中", "C兑现中", "D前瞻观察", "回避", "观望"]:
        sub = out.filter(pl.col("rating") == rating)
        if sub.is_empty():
            continue
        rets = sub["ret_12m"].to_list()
        excess = sub["excess_12m"].to_list()
        wins = sum(1 for r in rets if r > 0)
        stats.append(
            {
                "rating": rating,
                "n": len(rets),
                "win_rate_12m": wins / len(rets),
                "mean_ret_12m": statistics.mean(rets),
                "median_ret_12m": statistics.median(rets),
                "mean_excess_12m": statistics.mean(excess),
                "excess_win_rate": sum(1 for e in excess if e > 0) / len(excess),
            }
        )
    print("\n=== 1y 持有统计（按评级池）===")
    print(
        pl.DataFrame(stats)
        .with_columns(
            pl.col("win_rate_12m")
            .map_elements(lambda v: f"{v:.1%}", return_dtype=pl.String)
            .alias("胜率"),
            pl.col("mean_ret_12m")
            .map_elements(lambda v: f"{v:+.1%}", return_dtype=pl.String)
            .alias("均收益"),
            pl.col("mean_excess_12m")
            .map_elements(lambda v: f"{v:+.1%}", return_dtype=pl.String)
            .alias("均超额"),
            pl.col("excess_win_rate")
            .map_elements(lambda v: f"{v:.1%}", return_dtype=pl.String)
            .alias("跑赢基准率"),
        )
        .select(["rating", "n", "胜率", "均收益", "均超额", "跑赢基准率"])
    )

    # 按月（A 池）
    monthly = (
        out.filter(pl.col("rating") == "A强机会")
        .group_by("signal_month")
        .agg(
            pl.col("symbol").count().alias("n"),
            pl.col("ret_12m").mean().alias("mean_ret"),
            pl.col("excess_12m").mean().alias("mean_excess"),
            (pl.col("ret_12m") > 0).mean().alias("win_rate"),
        )
        .sort("signal_month")
    )
    print("\n=== A 池按月样本量 ===")
    print(
        monthly.filter(pl.col("n") >= 1)
        .select(["signal_month", "n", "win_rate", "mean_ret", "mean_excess"])
        .tail(15)
    )

    out.select(
        [
            "signal_month",
            "effective_month",
            "symbol",
            "company_name",
            "product_key",
            "rating",
            "risk_flag",
            "f1_state",
            "f2_state",
            "f3_state",
            "ret_12m",
            "bench_12m",
            "excess_12m",
        ]
    ).write_parquet(args.output)
    print(f"\n明细已落盘: {args.output}")


if __name__ == "__main__":
    main()
