"""A强机会 105 行（87 家公司）股价强度分析（前复权，方法论 §3 口径）。

计算 1y/3y 前复权收益、52 周位置、相对沪深300 超额（观察点 = 股价数据末
2026-09-07，A 池评级来自 2026-07 快照），并计算信号强度（yoy/暴露度）与
股价强度的 Pearson 相关性与 Spearman 相关性。
"""

from __future__ import annotations

import glob
from datetime import date, timedelta
from pathlib import Path

import polars as pl

SIGNAL = Path("data/analytics/industry/customs_company_h8_signal.parquet")
BAR_ROOT = Path("data/curated/tushare/market=CN/stock_daily_bar")
AF_ROOT = Path("data/curated/tushare/market=CN/adj_factor")
IDX = Path("data/curated/tushare/market=CN/index_daily_bar/data.parquet")
YEARS = ("2023", "2024", "2025", "2026")


def _load_bars(root: Path, columns: list[str]) -> pl.DataFrame:
    files = sorted(
        f for year in YEARS for f in glob.glob(f"{root}/year={year}/**/*.parquet", recursive=True)
    )
    frames = []
    for f in files:
        try:
            frames.append(pl.read_parquet(f, columns=columns))
        except Exception:
            continue
    if not frames:
        raise FileNotFoundError(f"未找到 Parquet: {root}")
    return pl.concat(frames).unique(subset=[columns[0], columns[1]], keep="last")


def _px_at(df: pl.DataFrame, target: date) -> pl.DataFrame:
    """每个 symbol 取 <= target 的最近一个交易日前复权收盘价。"""
    return (
        df.filter(pl.col("trade_date") <= target)
        .sort(["symbol", "trade_date"])
        .group_by("symbol")
        .agg(pl.col("adj_close").last().alias("px"))
    )


def _pearson(x: list[float], y: list[float]) -> float:
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    return cov / (sxx**0.5 * syy**0.5) if sxx and syy else float("nan")


def _spearman(x: list[float], y: list[float]) -> float:
    def _rank(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        ranks = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        return ranks

    rx, ry = _rank(x), _rank(y)
    return _pearson(rx, ry)


def main() -> None:
    s = pl.read_parquet(SIGNAL)

    bar = _load_bars(BAR_ROOT, ["symbol", "trade_date", "close"])
    af = _load_bars(AF_ROOT, ["symbol", "trade_date", "adj_factor"])
    print(f"bar rows: {bar.height} | adj rows: {af.height}")

    latest_af = (
        af.sort("trade_date").group_by("symbol").agg(pl.col("adj_factor").last().alias("af_latest"))
    )
    px = (
        bar.join(af, on=["symbol", "trade_date"], how="inner")
        .join(latest_af, on="symbol", how="left")
        .with_columns(
            (pl.col("close") * pl.col("adj_factor") / pl.col("af_latest")).alias("adj_close")
        )
        .sort(["symbol", "trade_date"])
    )
    d_min = px["trade_date"].min()
    d_max = px["trade_date"].max()
    d_min_s = d_min.isoformat() if isinstance(d_min, date) else str(d_min)
    d_max_s = d_max.isoformat() if isinstance(d_max, date) else str(d_max)
    print(f"px rows: {px.height} | dates: {d_min_s} → {d_max_s}")

    idx = pl.read_parquet(IDX, columns=["symbol", "trade_date", "close"]).filter(
        pl.col("symbol") == "000300.SH"
    )
    end = px["trade_date"].max()
    if not isinstance(end, date):
        raise ValueError(f"无法解析交易日末: {end!s}")

    # 52 周窗口起点（约 365 天前）+ 3 年前窗口起点
    y1_target: date = end - timedelta(days=365)
    y3_target: date = end - timedelta(days=365 * 3)
    y1_win: date = end - timedelta(days=400)
    print(
        f"窗口: end={end.isoformat()}, y1_target={y1_target.isoformat()}, "
        f"y3_target={y3_target.isoformat()}"
    )

    y1 = _px_at(px, y1_target).rename({"px": "px_y1"})
    y3 = _px_at(px, y3_target).rename({"px": "px_y3"})
    end_px = (
        px.sort("trade_date").group_by("symbol").agg(pl.col("adj_close").last().alias("px_end"))
    )
    win = (
        px.filter(pl.col("trade_date") > y1_win)
        .group_by("symbol")
        .agg(pl.col("adj_close").max().alias("hi"), pl.col("adj_close").min().alias("lo"))
    )
    stats = (
        end_px.join(y1, on="symbol", how="left")
        .join(y3, on="symbol", how="left")
        .join(win, on="symbol", how="left")
        .with_columns(
            (pl.col("px_end") / pl.col("px_y1") - 1).alias("ret_1y"),
            (pl.col("px_end") / pl.col("px_y3") - 1).alias("ret_3y"),
            ((pl.col("px_end") - pl.col("lo")) / (pl.col("hi") - pl.col("lo"))).alias("pos_52w"),
        )
    )

    i_end = idx["close"].tail(1).item()
    i_y1 = idx.filter(pl.col("trade_date") <= y1_target)["close"].tail(1).item()
    i_y3 = idx.filter(pl.col("trade_date") <= y3_target)["close"].tail(1).item()
    bench_1y, bench_3y = i_end / i_y1 - 1, i_end / i_y3 - 1
    print(f"沪深300: 1y {bench_1y:+.1%} | 3y {bench_3y:+.1%}")

    a_pool = s.filter(pl.col("rating") == "A强机会").unique(subset=["stock_code", "product_key"])
    m = a_pool.join(stats, left_on="stock_code", right_on="symbol", how="left").with_columns(
        (pl.col("ret_1y") - bench_1y).alias("excess_1y"),
        (pl.col("ret_1y") * pl.col("exposure")).alias("ret_x_exp"),
    )
    print(f"\nA 池: {m.height} 行 / {m['stock_code'].n_unique()} 家公司")
    print("\nA 池股价强度描述统计:")
    print(m.select(["ret_1y", "ret_3y", "excess_1y", "pos_52w"]).describe())
    print("\nA 池前 15（按 1y 收益）:")
    print(
        m.sort("ret_1y", descending=True)
        .select(
            [
                "company_name",
                "stock_code",
                "product_key",
                "exposure",
                "value_yoy_3mma",
                "驱动类型",
                "ret_1y",
                "ret_3y",
                "excess_1y",
                "pos_52w",
            ]
        )
        .head(15)
    )

    print("\n相关性（A 池去空，NaN 按缺失处理）:")
    num_cols = ["value_yoy_3mma", "exposure", "ret_x_exp", "ret_1y", "ret_3y"]
    clean = m.with_columns([pl.col(c).fill_nan(None) for c in num_cols]).drop_nulls(num_cols)
    for col in ["value_yoy_3mma", "exposure"]:
        for tgt in ["ret_1y", "ret_3y"]:
            rows = clean.select([col, tgt]).drop_nulls().iter_rows()
            points = list(rows)
            x, y = [r[0] for r in points], [r[1] for r in points]
            if len(x) < 5:
                continue
            print(
                f"  A池 {col} × {tgt}: pearson={_pearson(x, y):+.3f} spearman={_spearman(x, y):+.3f} (n={len(x)})"
            )
    # ret_x_exp 与 ret_1y 是机械相关（构造上含自身），仅标注不解读
    print("  （注: ret_x_exp = ret_1y × exposure 与 ret_1y 的相关为机械相关，不作信号解读）")

    # 全评级池股价强度对比（去重公司×产品）
    sig_all = (
        s.select(["stock_code", "rating"])
        .unique(subset=["stock_code", "rating"])
        .join(stats, left_on="stock_code", right_on="symbol", how="left")
        .with_columns((pl.col("ret_1y") - bench_1y).alias("excess_1y"))
    )
    print("\n各评级池股价强度对比（公司级去重）:")
    comp = (
        sig_all.group_by("rating")
        .agg(
            pl.col("stock_code").n_unique().alias("n_companies"),
            pl.col("ret_1y").median().alias("ret_1y_med"),
            pl.col("ret_3y").median().alias("ret_3y_med"),
            pl.col("excess_1y").median().alias("excess_1y_med"),
            pl.col("pos_52w").median().alias("pos_52w_med"),
        )
        .sort("excess_1y_med", descending=True)
    )
    print(comp)


if __name__ == "__main__":
    main()
