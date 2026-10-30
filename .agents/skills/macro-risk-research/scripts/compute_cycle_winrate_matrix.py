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
from datetime import date
from pathlib import Path

import duckdb
import polars as pl

# 信号情景定义: (名称, 过滤表达式) —— 表达式作用于 risk_factors 的列。
# 「连续维持 N 天」列由 stock_analytics.primitives.macro.consecutive_days 预计算
# (smart_money_pct_consec / insider_net_score_consec)，仅当信号连续达标才累加，回落即清零。
SCENARIOS: list[tuple[str, str]] = [
    ("全样本基准", "1 == 1"),
    ("狂热区 (Overheat > 65)", "overheat_index > 65"),
    ("恐慌区 (Panic > 65)", "panic_index > 65"),
    ("极度冰点 (Panic > 75)", "panic_index > 75"),
    # 52 周新低占比分位 (newlow252_ratio_score, raw 方向: 高分位 = 恐慌端出清广度大)；
    # 该因子只登记为独立观测、不进 panic_index，此处用于判定是否值得升级为信号。
    ("52周新低出清高位 (NewLow252 >= 80)", "newlow252_ratio_score >= 80"),
    ("52周新低出清极值 (NewLow252 >= 90)", "newlow252_ratio_score >= 90"),
    ("聪明钱逆势接货 (SmartMoney >= 80)", "smart_money_pct >= 80"),
    # 方向口径：insider_net 因子配置为 direction=rev（score = 100 - 分位），
    # 因此 insider_net_score 高分位 = 内部人净增持极弱/净卖出，而非「增持潮」。
    ("内部人净增持极弱 (Insider >= 80, rev 口径)", "insider_net_score >= 80"),
    ("真黄金坑 (Panic>65 & SmartMoney>=80)", "panic_index > 65 and smart_money_pct >= 80"),
    ("聪明钱连续维持>=3D", "smart_money_pct_consec >= 3"),
    ("聪明钱连续维持>=5D", "smart_money_pct_consec >= 5"),
    ("内部人净增持持续弱 >=3D", "insider_net_score_consec >= 3"),
    ("内部人净增持持续弱 >=5D", "insider_net_score_consec >= 5"),
]

MACRO_REGIMES: list[tuple[str, str, str]] = [
    ("范式一：杠杆牛熊", "2015-01-05", "2015-12-31"),
    ("范式二：供给侧蓝筹", "2016-01-04", "2017-12-29"),
    ("范式三：去杠杆慢熊", "2018-01-02", "2018-12-28"),
    ("范式四：公募抱团牛", "2019-01-02", "2021-02-18"),
    ("范式五：存量红利防守", "2021-02-19", "2024-01-31"),
    # 末段以哨兵 "" 表示「右移到最新数据日」，避免硬编码结束日期导致
    # 新增交易日落入任何范式窗口之外（见 main 中 _resolve_regimes）。
    ("范式六：政策新质牛", "2024-02-01", ""),
]

WINDOWS = (20, 60)


def _resolve_regimes(risk_df: pl.DataFrame) -> list[tuple[str, str, str]]:
    """把 MACRO_REGIMES 中哨兵结束日期 "" 解析为风险因子最新交易日。

    避免硬编码范式窗口末段导致新增样本落入任何范式之外。
    """
    latest = risk_df["trade_date"].max()
    latest_str = latest.strftime("%Y-%m-%d") if isinstance(latest, date) else str(latest)
    return [
        (name, start_d, end_d if end_d else latest_str) for name, start_d, end_d in MACRO_REGIMES
    ]


def _build_consecutive_cols(frame: pl.DataFrame) -> pl.DataFrame:
    """为内部人增持 / 聪明钱分位构造「连续维持 N 天」列。

    复用系统级原语 ``stock_analytics.primitives.macro.consecutive_days`` 与
    ``config/analytics/macro_risk.yaml`` / ``ic`` 审计同口径（减少配方漂移）：
    信号连续达标即累加，回落或数据缺失即清零。直接在原帧上追加列，不复制。
    """
    from stock_analytics.primitives.macro import consecutive_days

    out = frame
    for col, threshold in (("smart_money_pct", 80.0), ("insider_net_score", 80.0)):
        if col in out.columns:
            out = consecutive_days(out.sort("trade_date"), col, threshold)
    return out


def _forward_returns(index_close: pl.DataFrame) -> pl.DataFrame:
    """为每个交易日计算其后 N 交易日前向收益。

    返回: trade_date / fwd20 / fwd60 (t 日收盘到其后第 20/60 个交易日收盘的收益%)。
    """
    frame = index_close.sort("trade_date")
    out = frame.select("trade_date")
    for w in WINDOWS:
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
    values = sub[col].to_list()
    mean_ret = float(sum(values) / len(values)) if values else 0.0
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
                """
                SELECT trade_date, symbol, close
                FROM "data/curated/lixinger/market=CN/index_daily_bar/**/*.parquet"
                WHERE symbol IN ('000985', '399006')
                """
            ).df()
        )
        .with_columns(pl.col("trade_date").cast(pl.Date))
        .sort(["symbol", "trade_date"])
    )

    full_ret = _forward_returns(index_df.filter(pl.col("symbol") == "000985"))
    chi_ret = _forward_returns(index_df.filter(pl.col("symbol") == "399006"))

    risk_cols = ["trade_date", "panic_index", "overheat_index"]
    for opt_col in (
        "smart_money_pct",
        "insider_net_score",
        "repurchase_score",
        "newlow252_ratio_score",
    ):
        if opt_col in risk_df.columns:
            risk_cols.append(opt_col)

    merged = (
        risk_df.select(risk_cols)
        .join(full_ret, on="trade_date", how="left", suffix="_full")
        .join(chi_ret, on="trade_date", how="left", suffix="_chi")
    )

    # 预计算「连续维持 N 天」确认强度列（复用系统级原语，与 ic 审计同口径）
    merged = _build_consecutive_cols(merged)

    latest = risk_df["trade_date"].max()
    latest_str = latest.strftime("%Y-%m-%d") if isinstance(latest, date) else str(latest)
    d_min = risk_df["trade_date"].min()
    min_str = d_min.strftime("%Y-%m-%d") if isinstance(d_min, date) else str(d_min)
    print(
        f"=== 20/60 日前向胜率矩阵全样本复算 (样本区间 {min_str} ~ {latest_str}, "
        f"共 {len(risk_df)} 个因子日) ==="
    )
    print(
        f"{'信号情景':<36}{'样本':>6} | {'全指20D胜率':>12} {'均收益':>8} | "
        f"{'全指60D胜率':>12} {'均收益':>8} | {'创业20D胜率':>12} {'均收益':>8} | "
        f"{'创业60D胜率':>12} {'均收益':>8}"
    )
    print("-" * 155)

    for name, cond in SCENARIOS:
        try:
            sub = merged.filter(pl.sql_expr(cond))
        except Exception as exc:  # 缺列/表达式错误必须显式暴露，静默跳行会让矩阵少行却被误读
            print(f"{name:<36}{'跳过':>6} (表达式无法执行: {exc})")
            continue
        n20, wr20f, mr20f = _win_stats(sub, "fwd20")
        _, wr60f, mr60f = _win_stats(sub, "fwd60")
        _, wr20c, mr20c = _win_stats(sub, "fwd20_chi")
        _, wr60c, mr60c = _win_stats(sub, "fwd60_chi")
        print(
            f"{name:<36}{n20:>6} | {wr20f:>10.1f}% {mr20f:>+7.2f}% | "
            f"{wr60f:>10.1f}% {mr60f:>+7.2f}% | {wr20c:>10.1f}% {mr20c:>+7.2f}% | "
            f"{wr60c:>10.1f}% {mr60c:>+7.2f}%"
        )

    print("\n" + "=" * 155)
    print("=== 6 大宏观范式分段前向胜率对账矩阵 ===")
    print(
        f"{'宏观范式':<24}{'起止区间':<25}{'样本':>6} | {'全指20D胜率':>12} {'均收益':>8} | "
        f"{'全指60D胜率':>12} {'均收益':>8} | {'创业20D胜率':>12} {'均收益':>8} | "
        f"{'创业60D胜率':>12} {'均收益':>8}"
    )
    print("-" * 155)

    regimes = _resolve_regimes(risk_df)
    for r_name, start_d, end_d in regimes:
        sub = merged.filter(
            (pl.col("trade_date") >= pl.lit(start_d).str.to_date())
            & (pl.col("trade_date") <= pl.lit(end_d).str.to_date())
        )
        date_range_str = f"{start_d}~{end_d}"
        n20, wr20f, mr20f = _win_stats(sub, "fwd20")
        _, wr60f, mr60f = _win_stats(sub, "fwd60")
        _, wr20c, mr20c = _win_stats(sub, "fwd20_chi")
        _, wr60c, mr60c = _win_stats(sub, "fwd60_chi")
        print(
            f"{r_name:<24}{date_range_str:<25}{n20:>6} | {wr20f:>10.1f}% {mr20f:>+7.2f}% | "
            f"{wr60f:>10.1f}% {mr60f:>+7.2f}% | {wr20c:>10.1f}% {mr20c:>+7.2f}% | "
            f"{wr60c:>10.1f}% {mr60c:>+7.2f}%"
        )


if __name__ == "__main__":
    main()
