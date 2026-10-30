"""用法 A 慢速顶背离闸门：Walk-Forward 样本外验证（基底 vs 闸门）。

目的：验证全样本 in-sample 扫参得到的改善（cap30/th75: 夏普 0.85、范式五 DD-6.6pp）
在**未见过的未来时段**（OOS）是否依然成立，排除纯 in-sample 过拟合。

口径（与 `macro_strategy/walk_forward.py` 一致）：
- 滚动 3 年样本内 (IS) -> 1 年样本外 (OOS)，步进 1Y；
- 参数固定为 in-sample 最优候选 cap30/th75，不在每切片重调（同一规则测 OOS，标准协议）；
- 每切片分别在完整面板上回测（保证 250 日闸门 lookback 有历史），再截取 IS/OOS 区间算指标；
- 指标：CAGR% / 最大回撤% / 夏普，用 `compute_slice_metrics` 同口径。

用法:
    uv run python scripts/macro_slow_gate_walkforward.py [--gate-cap 0.30] [--gate-threshold 75]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

from stock_data.catalog import DataCatalog
from stock_strategy.macro.assembly import assemble_macro_panel, load_price_panel
from stock_strategy.macro.audit_calc import compute_slice_metrics
from stock_strategy.macro.runner import MacroRiskRunner

RISK_ROOT = Path("data/analytics/macro_risk")
TRAIN_YEARS = 3
TEST_YEARS = 1


def _run_strategy(
    symbols: list[str],
    eq_cap: float,
    gate_args: dict | None,
    panel: pl.DataFrame,
    price_panel: pl.DataFrame,
) -> pl.DataFrame:
    """实例化基底或慢速闸门策略并回测，返回 trade_date/nav。"""
    from stock_strategy.pool.macro_rotation_v5_rebalance import (
        MacroRotationV5RebalanceStrategy,
    )

    if gate_args is None:
        strat = MacroRotationV5RebalanceStrategy(
            ma_window=20, symbols=symbols, benchmark_symbol="000985.CSI", equity_cap=eq_cap
        )
    else:
        from stock_strategy.pool.macro_slow_top_divergence import (
            MacroSlowTopDivergenceStrategy,
        )

        strat = MacroSlowTopDivergenceStrategy(
            ma_window=20,
            symbols=symbols,
            benchmark_symbol="000985.CSI",
            equity_cap=eq_cap,
            **gate_args,
        )
    runner = MacroRiskRunner(
        strategy=strat,
        symbols=symbols,
        initial_weights=dict(strat.initial_weights),
        strategy_name="wfv",
    )
    return runner.backtest(panel, price_panel)


def _metrics(sub: pl.DataFrame) -> dict[str, float]:
    if sub.is_empty() or len(sub) < 2:
        return {"cagr": 0.0, "mdd": 0.0, "sharpe": 0.0}
    m = compute_slice_metrics(sub, ["nav"]).get("nav", {})
    return {
        "cagr": m.get("annualized_return", 0.0) * 100.0,
        "mdd": m.get("max_drawdown", 0.0) * 100.0,
        "sharpe": m.get("sharpe", 0.0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="慢速闸门 Walk-Forward 样本外验证")
    parser.add_argument("--gate-cap", type=float, default=0.30)
    parser.add_argument("--gate-threshold", type=float, default=80.0)
    parser.add_argument("--gate-off", type=float, default=60.0)
    args = parser.parse_args()

    catalog = DataCatalog(data_source="tushare")
    panel = assemble_macro_panel(
        catalog=catalog,
        benchmark_symbol="000985.CSI",
        risk_root=RISK_ROOT,
        extra_factor_cols=["copper_gold_score", "cb_price_score", "smart_money_pct"],
    ).with_columns(pl.col("trade_date").cast(pl.Date))
    symbols = ["510880.SH", "159915.SZ", "511010.SH"]
    price_panel = load_price_panel(
        catalog=catalog,
        symbols=symbols + ["000985.CSI"],
        start_date=panel["trade_date"].min(),
        end_date=panel["trade_date"].max(),
    )

    gate_args = {
        "gate_threshold": args.gate_threshold,
        "gate_cap": args.gate_cap,
        "gate_off_threshold": args.gate_off,
    }

    base_nav = _run_strategy(symbols, 0.7, None, panel, price_panel)
    gate_nav = _run_strategy(symbols, 0.7, gate_args, panel, price_panel)

    dates = sorted(panel["trade_date"].unique().to_list())
    total = len(dates)
    train = TRAIN_YEARS * 252
    step = TEST_YEARS * 252
    slice_idx = 1
    start = 0

    print("=" * 100)
    print(
        f"慢速闸门 Walk-Forward 样本外验证 (IS {TRAIN_YEARS}Y → OOS {TEST_YEARS}Y, 参数 cap{args.gate_cap:.0%}/th{args.gate_threshold:.0f})"
    )
    print("=" * 100)
    hdr = (
        f"{'切片':<5}{'OOS区间':<22}{'基底SR':>7}{'闸门SR':>7}{'SRΔ':>7} | "
        f"{'基底DD':>8}{'闸门DD':>8}{'DDΔpp':>8} | {'基底CAGR':>9}{'闸门CAGR':>9}{'CAGRΔ':>8}"
    )
    print(hdr)
    print("-" * 100)

    oos_rows = []
    while start + train < total:
        oos_start_i = start + train
        oos_end_i = min(start + train + step - 1, total - 1)
        oos_start_d = dates[oos_start_i]
        oos_end_d = dates[oos_end_i]

        b_sub = base_nav.filter(
            (pl.col("trade_date") >= oos_start_d) & (pl.col("trade_date") <= oos_end_d)
        )
        g_sub = gate_nav.filter(
            (pl.col("trade_date") >= oos_start_d) & (pl.col("trade_date") <= oos_end_d)
        )
        if b_sub.is_empty() or g_sub.is_empty():
            start += step
            slice_idx += 1
            continue
        bm = _metrics(b_sub)
        gm = _metrics(g_sub)
        oos_rows.append((slice_idx, oos_start_d, oos_end_d, bm, gm))
        print(
            f"{slice_idx:<5}{(str(oos_start_d) + '~' + str(oos_end_d)):<22}{bm['sharpe']:>7.2f}{gm['sharpe']:>7.2f}"
            f"{(gm['sharpe'] - bm['sharpe']):>+7.2f} | "
            f"{bm['mdd']:>7.2f}%{gm['mdd']:>7.2f}%{(gm['mdd'] - bm['mdd']):>+8.2f} | "
            f"{bm['cagr']:>8.2f}%{gm['cagr']:>8.2f}%{(gm['cagr'] - bm['cagr']):>+8.2f}"
        )
        start += step
        slice_idx += 1

    if not oos_rows:
        print("无可评估 OOS 切片")
        return

    # 汇总：闸门 OOS 战胜基底的切片占比
    n = len(oos_rows)
    sr_win = sum(1 for _, _, _, b, g in oos_rows if g["sharpe"] > b["sharpe"])
    dd_win = sum(1 for _, _, _, b, g in oos_rows if g["mdd"] < b["mdd"])
    cagr_win = sum(1 for _, _, _, b, g in oos_rows if g["cagr"] > b["cagr"])

    print("-" * 100)
    print(f"OOS 切片数: {n}")
    print(f"闸门 OOS 夏普 > 基底: {sr_win}/{n} ({sr_win / n * 100:.0f}%)")
    print(f"闸门 OOS 回撤 < 基底: {dd_win}/{n} ({dd_win / n * 100:.0f}%)")
    print(f"闸门 OOS CAGR > 基底: {cagr_win}/{n} ({cagr_win / n * 100:.0f}%)")

    # 拼接全 OOS 净值 vs 基底，算整体
    b_stitch = _stitch(base_nav, oos_rows, "base")
    g_stitch = _stitch(gate_nav, oos_rows, "gate")
    print("\n=== 拼接连串 OOS 净值 全区间 ===")
    print(
        f"基底: CAGR {_metrics(b_stitch)['cagr']:.2f}%  MDD {_metrics(b_stitch)['mdd']:.2f}%  SR {_metrics(b_stitch)['sharpe']:.2f}"
    )
    print(
        f"闸门: CAGR {_metrics(g_stitch)['cagr']:.2f}%  MDD {_metrics(g_stitch)['mdd']:.2f}%  SR {_metrics(g_stitch)['sharpe']:.2f}"
    )
    print(
        f"Δ: CAGR {_metrics(g_stitch)['cagr'] - _metrics(b_stitch)['cagr']:+.2f}pp  "
        f"MDD {_metrics(g_stitch)['mdd'] - _metrics(b_stitch)['mdd']:+.2f}pp  "
        f"SR {_metrics(g_stitch)['sharpe'] - _metrics(b_stitch)['sharpe']:+.2f}"
    )


def _stitch(nav_df: pl.DataFrame, oos_rows: list, tag: str) -> pl.DataFrame:
    segs = []
    for _, s, e, _, _ in oos_rows:
        sub = (
            nav_df.filter((pl.col("trade_date") >= s) & (pl.col("trade_date") <= e))
            .select(["trade_date", "nav"])
            .sort("trade_date")
        )
        if sub.is_empty():
            continue
        segs.append(sub)
    if not segs:
        return nav_df.head(2)
    out = pl.concat(segs).unique(subset=["trade_date"], keep="last").sort("trade_date")
    return out


if __name__ == "__main__":
    main()
