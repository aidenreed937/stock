"""复算 20 日 / 60 日前向胜率矩阵 (Cycle Win-Rate Matrix)。

从本地黄金产物复算 `references/cycle_windows_matrix.md` 第一节的胜率矩阵：
对每个满足信号情景的交易日，统计其后 20 / 60 个交易日中证全指 (000985) 与
创业板指 (399006) 的前向收益胜率与均值，保证统计数字可复现、可对账。

用法:
    uv run python .agents/skills/macro-risk-research/scripts/compute_cycle_winrate_matrix.py

数据依赖:
    - data/analytics/macro_risk/latest/risk_factors.parquet (信号情景)
    - data/curated/lixinger/market=CN/index_daily_bar/**/*.parquet (指数日线)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import polars as pl

# 信号情景定义: (名称, 过滤表达式, 列名) —— 表达式作用于 risk_factors 的列
SCENARIOS: list[tuple[str, str]] = [
    ("全样本基准", "1 == 1"),
    ("狂热区 (Overheat > 65)", "overheat_index > 65"),
    ("恐慌区 (Panic > 65)", "panic_index > 65"),
    ("国家队托底 (ETF >= 90)", "etf_flow_ratio_score >= 90"),
    ("极度冰点 (Panic > 75)", "panic_index > 75"),
]

WINDOWS = (20, 60)


def _forward_returns(index_close: pl.DataFrame) -> pl.DataFrame:
    """为每个交易日计算其后 N 交易日前向收益。

    返回: trade_date / fwd20 / fwd60 (t 日收盘到其后第 20/60 个交易日收盘的收益%)。
    """
    frame = index_close.sort("trade_date")
    out = frame.select("trade_date")
    for w in WINDOWS:
        # 未来第 w 个交易日的收盘价 (按行索引平移)
        shifted = frame.with_columns(pl.col("close").shift(-w).alias("fwd_close"))
        fwd = (
            frame.join(shifted.select(["trade_date", "fwd_close"]), on="trade_date", how="left")
            .with_columns(((pl.col("fwd_close") / pl.col("close") - 1.0) * 100.0).alias(f"fwd{w}"))
            .select(["trade_date", f"fwd{w}"])
        )
        out = out.join(fwd, on="trade_date", how="left")
    return out


def _win_stats(frame: pl.DataFrame, col: str) -> tuple[int, float, float]:
    """返回 (样本数, 胜率%, 均收益%)。"""
    sub = frame.filter(pl.col(col).is_not_null())
    n = len(sub)
    if n == 0:
        return 0, 0.0, 0.0
    win_rate = (sub.filter(pl.col(col) > 0).height / n) * 100.0
    mean_ret = float(sub[col].mean())
    return n, win_rate, mean_ret


def main() -> None:
    parser = argparse.ArgumentParser(description="复算 20/60 日前向胜率矩阵")
    parser.add_argument(
        "--risk-root",
        type=str,
        default="data/analytics/macro_risk",
        help="宏观风险产物根目录 (默认: data/analytics/macro_risk)",
    )
    args = parser.parse_args()

    risk_root = Path(args.risk_root)
    risk_df = pl.read_parquet(risk_root / "latest" / "risk_factors.parquet").with_columns(
        pl.col("trade_date").cast(pl.Date)
    )

    con = duckdb.connect()
    index_df = (
        pl.from_pandas(
            con.execute(
                '''
                SELECT trade_date, symbol, close
                FROM "data/curated/lixinger/market=CN/index_daily_bar/**/*.parquet"
                WHERE symbol IN ('000985', '399006')
                '''
            ).df()
        )
        .with_columns(pl.col("trade_date").cast(pl.Date))
        .sort(["symbol", "trade_date"])
    )

    full_ret = _forward_returns(index_df.filter(pl.col("symbol") == "000985"))
    chi_ret = _forward_returns(index_df.filter(pl.col("symbol") == "399006"))

    merged = (
        risk_df.select(["trade_date", "panic_index", "overheat_index", "etf_flow_ratio_score"])
        .join(full_ret, on="trade_date", how="left", suffix="_full")
        .join(chi_ret, on="trade_date", how="left", suffix="_chi")
    )

    latest = risk_df["trade_date"].max()
    print(f"=== 20/60 日前向胜率矩阵复算 (样本区间 {risk_df['trade_date'].min()} ~ {latest}, "
          f"共 {len(risk_df)} 个因子日) ===")
    print(f"{'信号情景':<32}{'样本':>6} | {'全指20D胜率':>12} {'均收益':>8} | "
          f"{'全指60D胜率':>12} {'均收益':>8} | {'创业20D胜率':>12} {'均收益':>8} | "
          f"{'创业60D胜率':>12} {'均收益':>8}")
    print("-" * 150)

    for name, cond in SCENARIOS:
        sub = merged.filter(pl.sql_expr(cond))
        n20, wr20f, mr20f = _win_stats(sub, "fwd20")
        _, wr60f, mr60f = _win_stats(sub, "fwd60")
        _, wr20c, mr20c = _win_stats(sub, "fwd20_chi")
        _, wr60c, mr60c = _win_stats(sub, "fwd60_chi")
        print(
            f"{name:<32}{n20:>6} | {wr20f:>10.1f}% {mr20f:>+7.2f}% | "
            f"{wr60f:>10.1f}% {mr60f:>+7.2f}% | {wr20c:>10.1f}% {mr20c:>+7.2f}% | "
            f"{wr60c:>10.1f}% {mr60c:>+7.2f}%"
        )


if __name__ == "__main__":
    main()
