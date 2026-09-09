#!/usr/bin/env python3
"""出口景气信号择时回测：分批建仓 → 景气松动分批减仓 → 胜率/持有收益。

规则（可解释、无未来函数）：
- **建仓信号**：产品出口 3MMA yoy 连续 entry_confirm 个月 > 0（防抖确认）→
  当月起分 3 批建仓（每景气月 +1/3 至满仓），组合按当月可用公司等权；
- **景气松动/减仓**：满仓后 yoy 连续 exit_confirm 个月环比下降（见顶回落）
  → 减半仓；yoy ≤ 0 → 清仓（“景气度松动，逐步减仓”）；
- 轮收益按当期权重折算；一轮 = 首笔买入月 ~ 清仓月（weight 0→>0 始、>0→0 止）。

统计：交易轮次明细（起止/轮收益/同期沪深300/超额）+ 胜率、平均/中位轮收益、
盈亏比、平均持有月、跑赢基准占比。

用法:
    uv run python scripts/backtest_customs_company_signal.py
    uv run python scripts/backtest_customs_company_signal.py --product solar_cell --symbols 601012.SH 688223.SH
"""

from __future__ import annotations

import argparse
import csv
import glob
import statistics
from datetime import date
from pathlib import Path
from typing import Any, cast

import polars as pl

DEFAULT_YOY = Path("data/analytics/industry/customs_product_volume_price.parquet")
DEFAULT_TRANSFORMER = ["600089.SH", "601179.SH", "002028.SZ", "002270.SZ", "688676.SH", "301291.SZ"]
DEFAULT_BENCH = "000300.SH"
DEFAULT_OUTPUT = Path("data/analytics/industry/customs_signal_backtest.parquet")
DEFAULT_FINA = Path("data/curated/tushare/market=CN/fina_indicator")

# 竞争力分层（§5.4 修订：同产品内部相对比较；产品级低毛利排除为可选开关）
DEFAULT_MAP = Path("config/data/customs/company_exposure_map.csv")
QUALITY_KEEP = {"正常"}  # 保留层（剔除亏损型/低竞争力，可选低毛利产品）
PRODUCT_GP_OK = 15.0  # 产品级中位毛利率门槛（%）
PRODUCT_ROE_OK = 10.0  # 产品级中位 ROE 门槛（%）


def load_quality_layers(
    fina_root: Path | str = DEFAULT_FINA,
    map_path: Path | str = DEFAULT_MAP,
    product_gate: bool = False,
) -> dict[str, dict[str, str]]:
    """构建 产品 → {公司 → 竞争力分层}（§5.4 修订：同产品内部相对比较）。

    口径：最近一期年报（end_date 为最新 12-31）的 netprofit_margin / grossprofit_margin /
    roe（单期值）。分层规则：
      - 亏损型（公司级）：netprofit_margin < 0（绝对硬事实，跨产品统一剔除）；
      - 低竞争力（公司级）：同产品内 netprofit_margin 与 grossprofit_margin **均低于同产品
        中位数**（bottom-left 象限，相对同产品竞争组），且非亏损型；
      - 低毛利产品（产品级，product_gate=True 才启用）：产品中位 grossprofit_margin <15%
        且中位 roe <10%（价格战/产能过剩环节），整产品剔除——仅静态组合下行保护用，
        择时回测默认关闭（择时已由 yoy≤0 清仓做下行保护，产品级排除会误伤上行赢家）；
      - 正常：其余（保留）。
    无财务数据或单公司产品（无法相对比较）→ 仅套用亏损型绝对标记，其余归"正常"。

    Returns:
        {product_key: {stock_code: 分层名}}，分层 ∈ {低毛利产品, 亏损型, 低竞争力, 正常}。
    """
    frames = []
    for f in sorted(glob.glob(str(Path(fina_root) / "year=*" / "month=*" / "data.parquet"))):
        try:
            frames.append(
                pl.read_parquet(f).select(
                    ["symbol", "end_date", "netprofit_margin", "grossprofit_margin", "roe"]
                )
            )
        except Exception:
            continue
    if not frames:
        return {}
    fin = pl.concat(frames).filter(
        (pl.col("end_date").dt.month() == 12)
        & pl.col("netprofit_margin").is_not_null()
        & pl.col("grossprofit_margin").is_not_null()
        & pl.col("roe").is_not_null()
    )
    latest = fin.group_by("symbol").agg(pl.col("end_date").max())
    fin = fin.join(latest, on=["symbol", "end_date"], how="inner")
    agg = fin.group_by("symbol").agg(
        pl.col("netprofit_margin").mean().alias("np"),
        pl.col("grossprofit_margin").mean().alias("gp"),
        pl.col("roe").mean().alias("roe"),
    )
    per_sym = {r["symbol"]: (r["np"], r["gp"], r["roe"]) for r in agg.iter_rows(named=True)}

    # 产品 → 公司集合（暴露度映射）
    product_syms: dict[str, set[str]] = {}
    with Path(map_path).open("r", encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            product_syms.setdefault(r["product_key"], set()).add(r["stock_code"])

    quality: dict[str, dict[str, str]] = {}
    for product, syms in product_syms.items():
        rows = {s: per_sym[s] for s in syms if s in per_sym}
        med_np = statistics.median(v[0] for v in rows.values()) if len(rows) >= 2 else None
        med_gp = statistics.median(v[1] for v in rows.values()) if len(rows) >= 2 else None
        med_roe = statistics.median(v[2] for v in rows.values()) if len(rows) >= 2 else None
        # 产品级（可选）：中位毛利率低 且 中位 ROE 低 = 价格战/产能过剩环节，整产品剔除
        if (
            product_gate
            and med_gp is not None
            and med_roe is not None
            and med_gp < PRODUCT_GP_OK
            and med_roe < PRODUCT_ROE_OK
        ):
            quality[product] = {s: "低毛利产品" for s in syms}
            continue
        q: dict[str, str] = {}
        for s in syms:
            v = rows.get(s)
            if v is None:
                q[s] = "正常"  # 无财报覆盖不误杀
                continue
            np, gp, _roe = v
            if np < 0:
                q[s] = "亏损型"
            elif med_np is not None and np < med_np and gp < med_gp:
                q[s] = "低竞争力"
            else:
                q[s] = "正常"
        quality[product] = q
    return quality


def filter_quality_for_product(
    product: str, symbols: list[str], quality: dict[str, dict[str, str]]
) -> list[str]:
    """按竞争力分层过滤公司池（剔除低毛利产品/亏损型/低竞争力，保留正常）。"""
    q = quality.get(product, {})
    return [s for s in symbols if q.get(s, "正常") in QUALITY_KEEP]


BUILD_LOTS = 3  # 建仓批数


def build_weight_plan(
    vals: list[float | None],
    entry_confirm: int = 2,
    exit_confirm: int = 2,
    drives: list[str | None] | None = None,
    quality_gate: bool = False,
) -> list[float]:
    """状态机权重计划：0 → 1/3 → 2/3 → 1（建仓）→ 0.5（见顶减半）→ 0（清仓）。

    离场只看金额 yoy（≤0 清仓、见顶回落减半）；quality_gate=True 时**入场**还需
    驱动类型为量价齐升/量驱动（量拐质量门，只入门、不管出——正交验证见 19 号文档：
    量确认用在离场会导致 whipsaw）。
    """
    allowed = {"量价齐升", "量驱动"}
    n = len(vals)
    w = [0.0] * n
    pos = 0.0
    up_streak = 0
    drop_streak = 0
    lot = 1.0 / BUILD_LOTS
    for i in range(n):
        y = vals[i]
        d = drives[i] if drives else None
        # 离场：金额 yoy≤0 清仓（不因驱动类型清仓）
        if y is None or y <= 0:
            pos = 0.0
            up_streak = 0
            drop_streak = 0
            w[i] = 0.0
            continue
        # 入场确认：金额>0 已保证；quality_gate 要求量价齐升/量驱动
        entry_ok = d in allowed if quality_gate else True
        up_streak = up_streak + 1 if entry_ok else 0
        prev = vals[i - 1] if i > 0 else None
        new_drop = prev is not None and y < prev
        drop_streak = drop_streak + 1 if new_drop else 0
        if pos == 0.0:
            if up_streak >= entry_confirm:
                pos = lot  # 信号确认，开始建仓
        elif pos < 1.0:
            pos = min(pos + lot, 1.0)  # 逐步建仓至满仓
        elif drop_streak >= exit_confirm:
            pos = 0.5  # 见顶回落 → 减半
        w[i] = pos
    return w


def load_monthly_ret(pattern: str, want: list[str] | None, use_adj: bool = True) -> pl.DataFrame:
    """前复权月收益（数据起点起，GACC 口径 2019-01）：日线 × 复权因子 → 月末价 → pct_change。

    use_adj=False 用于指数（无股票复权因子，直接收盘价）。
    """
    frames = []
    for f in sorted(glob.glob(pattern, recursive=True)):
        try:
            frames.append(pl.read_parquet(f).select(["symbol", "trade_date", "close"]))
        except Exception:
            continue
    bars = pl.concat(frames).unique()
    adjf = None
    if use_adj:
        try:
            adjf = pl.concat(
                [
                    pl.read_parquet(f).select(["symbol", "trade_date", "adj_factor"])
                    for f in sorted(
                        glob.glob(
                            "data/curated/tushare/market=CN/adj_factor/year=2*/**/*.parquet",
                            recursive=True,
                        )
                    )
                ]
            ).unique()
        except Exception:
            pass
    if adjf is not None:
        px = bars.join(adjf, on=["symbol", "trade_date"], how="left")
    else:
        px = bars.with_columns(pl.lit(1.0).alias("adj_factor"))
    px = (
        px.with_columns((pl.col("close") * pl.col("adj_factor")).alias("px"))
        .filter(pl.col("px").is_not_null(), pl.col("trade_date") >= pl.lit(date(2016, 1, 1)))
        .sort(["symbol", "trade_date"])  # 月末价取每月最后交易日：group_by 前必须按日排序
        .with_columns(pl.col("trade_date").dt.strftime("%Y-%m").alias("month"))
        .group_by(["symbol", "month"])
        .agg(pl.col("px").last())
    )
    out = (
        px.sort(["symbol", "month"])
        .with_columns(pl.col("px").pct_change().over("symbol").alias("ret"))
        .drop_nulls("ret")
    )
    if want:
        out = out.filter(pl.col("symbol").is_in(want))
    return out.select(["symbol", "month", "ret"])


def split_trades(
    months: list[str], weights: list[float], port: pl.DataFrame
) -> list[dict[str, Any]]:
    """按权重计划切分交易轮次，逐月按当期权重折算组合与基准收益。"""
    wmap = dict(zip(months, weights))
    prov = port.with_columns(
        pl.col("month").map_elements(lambda m: wmap.get(m, 0.0), return_dtype=pl.Float64).alias("w")
    ).sort("month")
    trades: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for r in prov.iter_rows(named=True):
        m, w, cr, br = r["month"], r["w"], r["combo_ret"], r["bench_ret"]
        if w > 0 and cur is None:
            cur = {"start": m, "trade_ret": 1.0, "bench_ret": 1.0, "n_months": 0}
        if w == 0 and cur is not None:
            cur["end"] = m
            trades.append(cur)
            cur = None
            continue
        if cur is not None:
            cur["n_months"] += 1
            if cr is not None:
                cur["trade_ret"] *= 1 + w * cr
            if br is not None:
                cur["bench_ret"] *= 1 + br
            if w == 1.0 or w == 0.5:
                pass  # 权重已在乘法中体现
    return trades


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yoy", default=str(DEFAULT_YOY), help="商品量价拐点面板 parquet")
    parser.add_argument("--product", default="transformer", help="产品键")
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_TRANSFORMER, help="受益公司代码")
    parser.add_argument("--bench", default=DEFAULT_BENCH, help="基准指数代码")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="回测结果 parquet")
    parser.add_argument("--entry-confirm", type=int, default=2, help="建仓确认月数")
    parser.add_argument("--exit-confirm", type=int, default=2, help="见顶减仓确认月数")
    parser.add_argument(
        "--quality-gate", action="store_true", help="入场要求量价齐升/量驱动（质量过滤）"
    )
    parser.add_argument(
        "--quality-filter",
        action="store_true",
        help="按竞争力分层过滤公司池（§5.4：剔除亏损型 + 净利率/毛利率均低于同产品中位数的低竞争力）",
    )
    parser.add_argument(
        "--product-gate",
        action="store_true",
        help="叠加产品级低毛利排除（中位毛利率<15% 且 ROE<10% 整产品剔除，仅静态组合下行保护）",
    )
    args = parser.parse_args()

    symbols = args.symbols
    if args.quality_filter:
        quality = load_quality_layers(
            fina_root=DEFAULT_FINA, map_path=DEFAULT_MAP, product_gate=args.product_gate
        )
        symbols = filter_quality_for_product(args.product, symbols, quality)
        print(
            f"[quality-filter] 公司池 {len(args.symbols)} → {len(symbols)} 家"
            f"（剔除: {sorted(set(args.symbols) - set(symbols))}）"
        )

    # 1) 产品出口 yoy（units 段全月序）+ 驱动类型（质量过滤用）
    pv = pl.read_parquet(args.yoy)
    ser = (
        pv.filter((pl.col("product_key") == args.product) & (pl.col("unit_segment") == "units"))
        .select(["report_month", "value_yoy_3mma", "驱动类型"])
        .sort("report_month")
    )
    months = ser["report_month"].to_list()
    vals: list[float | None] = ser["value_yoy_3mma"].to_list()
    drives: list[str | None] = ser["驱动类型"].to_list()
    weights = build_weight_plan(
        vals, args.entry_confirm, args.exit_confirm, drives, args.quality_gate
    )

    # 2) 公司月收益与基准
    retdf = load_monthly_ret(
        "data/curated/tushare/market=CN/stock_daily_bar/year=2*/**/*.parquet", symbols
    )
    benchdf = (
        load_monthly_ret(
            "data/curated/tushare/market=CN/index_daily/year=2*/**/*.parquet",
            [args.bench],
            use_adj=False,
        )
        .rename({"ret": "bench_ret"})
        .drop("symbol")
    )
    port = (
        retdf.join(benchdf, on="month", how="inner")
        .group_by("month")
        .agg(pl.col("ret").mean().alias("combo_ret"), pl.col("bench_ret").first())
        .sort("month")
    )
    trades = split_trades(months, weights, port)
    if not trades:
        print("[FAIL] 信号未触发任何交易轮次")
        return 1

    tdf = pl.DataFrame(
        [
            {
                "start": t["start"],
                "end": t["end"],
                "n_months": t["n_months"],
                "trade_ret": t["trade_ret"] - 1,
                "bench_ret": t["bench_ret"] - 1,
                "excess": (t["trade_ret"] - 1) - (t["bench_ret"] - 1),
                "win": (t["trade_ret"] - 1) > 0,
                "beat_bench": (t["trade_ret"] - 1) > (t["bench_ret"] - 1),
            }
            for t in trades
        ]
    )
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    tdf.write_parquet(args.output)

    n = tdf.height
    wins = tdf.filter(pl.col("win")).height
    beats = tdf.filter(pl.col("beat_bench")).height
    mean_pos = cast("float", tdf.filter(pl.col("trade_ret") > 0)["trade_ret"].mean())
    mean_neg = cast("float", tdf.filter(pl.col("trade_ret") <= 0)["trade_ret"].mean())
    pl_ratio = mean_pos / abs(mean_neg) if mean_neg != 0 else float("nan")
    avg_ret = cast("float", tdf["trade_ret"].mean())
    avg_excess = cast("float", tdf["excess"].mean())
    avg_hold = cast("float", tdf["n_months"].mean())
    print(
        f"\n=== {args.product} 信号择时回测（确认 {args.entry_confirm} 月建仓 / 见顶 {args.exit_confirm} 月减仓）==="
    )
    print(
        tdf.select(
            ["start", "end", "n_months", "trade_ret", "bench_ret", "excess", "win", "beat_bench"]
        )
        .to_pandas()
        .to_string(index=False)
    )
    print(f"\n交易轮次: {n}")
    print(f"胜率: {wins}/{n} = {wins / n * 100:.0f}%    平均轮收益: {avg_ret * 100:+.1f}%")
    print(
        f"跑赢沪深300: {beats}/{n} = {beats / n * 100:.0f}%    平均超额: {avg_excess * 100:+.1f}pp"
    )
    print(f"盈亏比: {pl_ratio:.2f}    平均持有: {avg_hold:.1f} 个月")
    print(f"已写出: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
