"""用法 A 原型：中期顶背离慢速减仓闸门 (Slow Top-Divergence Gate) 回测验证。

背景（方法论 §7.4 / §5.3）：
- `copper_gold_score` (60D IC -0.33) 与 `cb_price_score` (60D IC -0.209) 是最强、
  最稳（年度符号稳定）的两个单因子，但属「慢变量」：信号集中在 60D，5/20D 弱；
- 直接混入 overheat_index（服务 20D 短期防守）已被证伪（§5.3 回测全面劣化）；
- 独立合成慢速闸门：当二者高分位（中期顶背离）时，对权益仓位施加额外封顶，
  余量转固收——落点正是它们最强的 60D 窗口，且不污染短线指数。

策略语义：
- 基底 = v5_rebalance_etf（V5 权益状态机 × 常数权益封顶 0.7 + 固收补足）；
- 叠加 = 慢速闸门：dim_slow = mean(copper_gold_score, cb_price_score)；
  当 dim_slow 滚动分位 > 慢速顶背离阈值（默认 80 分位，250 日滚动）时，
  权益封顶从 0.7 降至 gate_cap（默认 0.45），其余转固收；
- 缺口/降位后信号回落（< 60 分位）恢复 0.7。

评估口径（与 `stock_cli/macro_strategy.py` 一致）：
- 全周期 CAGR / 年化波动 / 夏普（无风险 1.5%）/ 最大回撤；
- 与基底 v5_rebalance_etf 对比；另附 6 大宏观范式分段对比。

用法:
    uv run python scripts/macro_slow_top_divergence_proto.py [--gate-threshold 80] [--gate-cap 0.45]
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
from math import sqrt
from pathlib import Path

import polars as pl

from stock_data.catalog import DataCatalog
from stock_strategy.base import BaseStrategy
from stock_strategy.context import Context
from stock_strategy.macro.assembly import assemble_macro_panel, load_price_panel
from stock_strategy.macro.runner import MacroRiskRunner
from stock_strategy.pool.macro_rotation_v5_rebalance import MacroRotationV5RebalanceStrategy
from stock_strategy.signal import Signal, SignalDirection

RISK_ROOT = Path("data/analytics/macro_risk")
CONFIG_PATH = Path("config/strategy/macro_risk.yaml")

# 6 大宏观范式窗口（与 winrate 矩阵 / IC 复审同口径）
REGIMES: list[tuple[str, str, str | None]] = [
    ("范式一：杠杆牛熊", "2015-01-05", "2015-12-31"),
    ("范式二：供给侧蓝筹", "2016-01-04", "2017-12-29"),
    ("范式三：去杠杆慢熊", "2018-01-02", "2018-12-28"),
    ("范式四：公募抱团牛", "2019-01-02", "2021-02-18"),
    ("范式五：存量红利防守", "2021-02-19", "2024-01-31"),
    ("范式六：政策新质牛", "2024-02-01", None),
]


def _coerce_ts(value: object) -> date | datetime | None:
    if isinstance(value, date | datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


class MacroSlowGateStrategy(MacroRotationV5RebalanceStrategy):
    """V5-rebalance + 中期顶背离慢速减仓闸门。"""

    def __init__(
        self,
        context: Context | None = None,
        ma_window: int = 20,
        symbols: tuple[str, ...] | list[str] | None = None,
        initial_weights: dict[str, float] | None = None,
        benchmark_symbol: str | None = None,
        equity_cap: float = 0.7,
        panic_threshold: float = 75.0,
        panic_entry_threshold: float = 65.0,
        overheat_threshold: float = 65.0,
        smart_filter_threshold: float = 40.0,
        bias_threshold: float = 0.15,
        gate_threshold: float = 80.0,
        gate_cap: float = 0.45,
        gate_off_threshold: float = 60.0,
        gate_lookback: int = 250,
    ) -> None:
        super().__init__(
            context=context,
            ma_window=ma_window,
            symbols=symbols,
            initial_weights=initial_weights,
            benchmark_symbol=benchmark_symbol,
            equity_cap=equity_cap,
            panic_threshold=panic_threshold,
            panic_entry_threshold=panic_entry_threshold,
            overheat_threshold=overheat_threshold,
            smart_filter_threshold=smart_filter_threshold,
            bias_threshold=bias_threshold,
        )
        self.gate_threshold = float(gate_threshold)
        self.gate_cap = float(gate_cap)
        self.gate_off_threshold = float(gate_off_threshold)
        self.gate_lookback = int(gate_lookback)

    def _slow_gate_active(self, history: pl.DataFrame) -> bool:
        """慢速顶背离闸门：dim_slow 滚动分位 > 阈值时激活（< off 阈值解除）。"""
        if len(history) < self.gate_lookback:
            return False
        cols = [c for c in ("copper_gold_score", "cb_price_score") if c in history.columns]
        if len(cols) < 2:
            return False
        sub = history[cols].drop_nulls()
        if len(sub) < self.gate_lookback:
            return False
        dim_slow = sub.mean_horizontal()  # 每行 = mean(copper, cb)
        full = dim_slow.to_list()
        recent = full[-self.gate_lookback :]
        # 滚动分位：当前值在近 250 日窗口内的百分位
        cur = full[-1]
        pct = sum(v <= cur for v in recent) / len(recent) * 100.0
        return pct >= self.gate_threshold

    def on_bar(self, data: pl.DataFrame) -> list[Signal]:
        if data.is_empty() or len(data) < self.ma_window:
            return []
        # 让 V5 处理权益腿
        equity_signals = self._v5.on_bar(data)
        eq_target = self._v5.weights
        eq_total = sum(eq_target.values())

        gate_on = self._slow_gate_active(data)
        cap = self.gate_cap if gate_on else self.equity_cap
        scaled_eq_total = eq_total * cap
        fixed_w = 1.0 - scaled_eq_total

        target = {sym: w * cap for sym, w in eq_target.items()}
        target[self.fixed_symbol] = fixed_w

        v5_reason = equity_signals[0].reason if equity_signals else "持有"
        gate_txt = f"慢速顶背离闸门ON(封顶{cap:.0%})" if gate_on else f"慢速闸门OFF(封顶{cap:.0%})"
        reason = f"{v5_reason} → {gate_txt} (权益{scaled_eq_total:.0%}/固收{fixed_w:.0%})"
        latest = data.tail(1).to_dicts()[0]
        timestamp = _coerce_ts(latest.get("trade_date"))

        signals: list[Signal] = []
        for sym, tgt_w in target.items():
            curr_w = self.weights.get(sym, 0.0)
            if abs(tgt_w - curr_w) < 1e-9:
                continue
            direction = (
                SignalDirection.CLOSE
                if tgt_w == 0.0
                else (SignalDirection.BUY if tgt_w > curr_w else SignalDirection.SELL)
            )
            signals.append(
                Signal(
                    symbol=sym,
                    direction=direction,
                    target_weight=tgt_w,
                    reason=reason,
                    timestamp=timestamp,
                )
            )
            self.weights[sym] = tgt_w
        return signals


def _summarize_nav(nav: list[float]) -> dict[str, float | None]:
    n_days = max(len(nav) - 1, 0)
    total_return = nav[-1] - 1.0
    annual = nav[-1] ** (252 / n_days) - 1.0 if n_days > 0 else None
    daily = [nav[i] / nav[i - 1] - 1.0 for i in range(1, len(nav))]
    vol: float | None = None
    if len(daily) > 1:
        mean = sum(daily) / len(daily)
        variance = sum((d - mean) ** 2 for d in daily) / (len(daily) - 1)
        vol = sqrt(variance) * sqrt(252)
    sharpe = (annual - 0.015) / vol if annual is not None and vol and vol > 0 else None
    peak = nav[0]
    max_dd = 0.0
    for value in nav:
        peak = max(peak, value)
        max_dd = max(max_dd, 1.0 - value / peak)
    return {
        "total_return": total_return,
        "annual_return": annual,
        "annual_volatility": vol,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
    }


def _fmt(val: float | None, digits: int = 2) -> str:
    if val is None:
        return "N/A"
    if digits == 2:
        return f"{val:,.2f}"
    return f"{val:,.{digits}f}"


def _run_backtest(
    strategy: BaseStrategy,
    name: str,
    panel: pl.DataFrame,
    price_panel: pl.DataFrame,
) -> tuple[list[float], list[date]]:
    # 提取策略标的（V5-rebalance 用 defensive/growth/fixed 三腿）
    syms = [
        getattr(strategy, "sym_defensive", "510880.SH"),
        getattr(strategy, "sym_growth", "159915.SZ"),
        getattr(strategy, "fixed_symbol", "511010.SH"),
    ]
    runner = MacroRiskRunner(
        strategy=strategy,
        symbols=syms,
        initial_weights=dict(getattr(strategy, "initial_weights", {})),
        strategy_name=name,
    )
    result = runner.backtest(panel, price_panel)
    # backtest 返回 trade_date / nav 两列
    nav = result["nav"].to_list() if "nav" in result.columns else []
    dates = result["trade_date"].to_list() if "trade_date" in result.columns else []
    # 首行建仓归一为 1.0，纳入净值序列
    if nav and nav[0] != 1.0:
        nav = [1.0] + nav
        dates = [panel["trade_date"].min()] + dates
    return nav, dates


def main() -> None:
    parser = argparse.ArgumentParser(description="中期顶背离慢速减仓闸门原型回测")
    parser.add_argument(
        "--gate-threshold", type=float, default=80.0, help="慢速闸门激活分位 (默认 80)"
    )
    parser.add_argument("--gate-cap", type=float, default=0.45, help="慢速闸门权益封顶 (默认 0.45)")
    parser.add_argument("--gate-off", type=float, default=60.0, help="慢速闸门解除分位 (默认 60)")
    parser.add_argument("--gate-lookback", type=int, default=250, help="滚动分位窗口 (默认 250)")
    args = parser.parse_args()

    catalog = DataCatalog(data_source="tushare")
    # 组装面板（含需要的中期因子列）
    panel = assemble_macro_panel(
        catalog=catalog,
        benchmark_symbol="000985.CSI",
        risk_root=RISK_ROOT,
        extra_factor_cols=[
            "copper_gold_score",
            "cb_price_score",
            "smart_money_pct",
            "dim_cross_asset",
        ],
    )
    price_panel = load_price_panel(
        catalog=catalog,
        symbols=["510880.SH", "159915.SZ", "511010.SH", "000985.CSI"],
        start_date=panel["trade_date"].min(),
        end_date=panel["trade_date"].max(),
    )

    # 基底 = v5_rebalance_etf 常量封顶 0.7
    base_equity_cap = 0.7
    symbols = ["510880.SH", "159915.SZ", "511010.SH"]
    base = MacroRotationV5RebalanceStrategy(
        ma_window=20,
        symbols=symbols,
        benchmark_symbol="000985.CSI",
        equity_cap=base_equity_cap,
    )
    gate = MacroSlowGateStrategy(
        ma_window=20,
        symbols=symbols,
        benchmark_symbol="000985.CSI",
        equity_cap=base_equity_cap,
        gate_threshold=args.gate_threshold,
        gate_cap=args.gate_cap,
        gate_off_threshold=args.gate_off,
        gate_lookback=args.gate_lookback,
    )

    base_nav, base_dates = _run_backtest(base, "base", panel, price_panel)
    gate_nav, gate_dates = _run_backtest(gate, "slowgate", panel, price_panel)

    base_stats = _summarize_nav(base_nav)
    gate_stats = _summarize_nav(gate_nav)

    print("=" * 90)
    print("中期顶背离慢速减仓闸门原型回测 (全周期)")
    print(
        f"闸门参数: 激活分位>{args.gate_threshold} 权益封顶{args.gate_cap:.0%} 解除<{args.gate_off} 滚动{args.gate_lookback}日"
    )
    print("=" * 90)
    hdr = f"{'策略':<36}{'CAGR':>8}{'波动':>8}{'夏普':>8}{'最大回撤':>10}"
    print(hdr)
    print("-" * 90)
    for name, s in (
        ("基底 v5_rebalance(0.7)", base_stats),
        (f"慢速闸门(th{args.gate_threshold:.0f}/cap{args.gate_cap:.0%})", gate_stats),
    ):
        print(
            f"{name:<36}{s['annual_return'] * 100:>7.2f}% {s['annual_volatility'] * 100:>7.2f}% "
            f"{s['sharpe']:>8.2f} {s['max_drawdown'] * 100:>9.2f}%"
        )

    # 分段对比
    print("\n=== 6 大宏观范式分段 CAGR / 最大回撤 ===")
    for r_name, start_d, end_d in REGIMES:
        s_d = date.fromisoformat(start_d)
        e_d = date.fromisoformat(end_d) if end_d else max(panel["trade_date"])
        idx_b = [i for i, d in enumerate(base_dates) if s_d <= d <= e_d]
        idx_g = [i for i, d in enumerate(gate_dates) if s_d <= d <= e_d]
        if not idx_b or not idx_g:
            continue
        bs = _summarize_nav([base_nav[i] for i in idx_b])
        gs = _summarize_nav([gate_nav[i] for i in idx_g])
        print(
            f"{r_name:<14} 基底 CAGR {bs['annual_return'] * 100:6.2f}% DD {bs['max_drawdown'] * 100:6.2f}% | "
            f"慢速门 CAGR {gs['annual_return'] * 100:6.2f}% DD {gs['max_drawdown'] * 100:6.2f}% | "
            f"ΔCAGR {((gs['annual_return'] or 0) - (bs['annual_return'] or 0)) * 100:+6.2f}pp"
        )


if __name__ == "__main__":
    main()
