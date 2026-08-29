"""宏观风控多策略 Walk-Forward 滚动前向样本外检验引擎。

通过滚动训练窗口（In-Sample）与滑动样本外（Out-of-Sample）窗口，检验策略在
未见过的真实未来时段中的鲁棒性与参数稳定性，计算 Walk-Forward 效率比 (WFE)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import polars as pl

from stock_core.utils.logger import logger
from stock_strategy.macro.audit_calc import compute_slice_metrics
from stock_strategy.macro.report import _runner_for


@dataclass(frozen=True)
class WalkForwardSlice:
    """单个 Walk-Forward 滚动切片结果。"""

    slice_index: int
    is_start: date
    is_end: date
    oos_start: date
    oos_end: date
    is_trading_days: int
    oos_trading_days: int
    is_cagr: float
    is_max_dd: float
    is_sharpe: float
    oos_cagr: float
    oos_max_dd: float
    oos_sharpe: float
    wfe_ratio: float  # oos_cagr / max(is_cagr, 0.01)


@dataclass(frozen=True)
class WalkForwardResult:
    """策略 Walk-Forward 全周期滚动样本外检验结果。"""

    strategy_name: str
    slices: list[WalkForwardSlice]
    stitched_oos_nav: pl.DataFrame  # trade_date, nav
    full_oos_cagr: float
    full_oos_max_dd: float
    full_oos_sharpe: float
    avg_wfe: float


def _extract_metric(slice_df: pl.DataFrame, col: str = "nav") -> tuple[float, float, float]:
    """返回 (cagr%, max_dd%, sharpe)。"""
    metrics = compute_slice_metrics(slice_df, [col]).get(col, {})
    cagr_pct = metrics.get("annualized_return", 0.0) * 100.0
    max_dd_pct = metrics.get("max_drawdown", 0.0) * 100.0
    sharpe = metrics.get("sharpe", 0.0)
    return cagr_pct, max_dd_pct, sharpe


def run_walk_forward_analysis(
    *,
    strategy_name: str,
    strategy_spec: dict[str, Any],
    macro_panel: pl.DataFrame,
    price_panel: pl.DataFrame,
    train_years: int = 3,
    test_years: int = 1,
) -> WalkForwardResult | None:
    """对指定策略执行 Walk-Forward 滚动切片样本外检验。"""
    if macro_panel.is_empty() or "trade_date" not in macro_panel.columns:
        return None

    dates = sorted(macro_panel["trade_date"].unique().to_list())
    total_days = len(dates)
    train_step = train_years * 252
    test_step = test_years * 252

    if total_days < train_step + test_step:
        logger.warning(
            "数据样本不足以执行 Walk-Forward (总交易日 %d, 所需 %d)",
            total_days,
            train_step + test_step,
        )
        return None

    slices: list[WalkForwardSlice] = []
    oos_nav_segments: list[pl.DataFrame] = []

    slice_idx = 1
    start_pos = 0

    while start_pos + train_step < total_days:
        is_start_d = dates[start_pos]
        is_end_d = dates[start_pos + train_step - 1]
        oos_start_idx = start_pos + train_step
        oos_end_idx = min(start_pos + train_step + test_step - 1, total_days - 1)
        oos_start_d = dates[oos_start_idx]
        oos_end_d = dates[oos_end_idx]

        # 运行完整区间并计算 IS 与 OOS 指标
        runner, _ = _runner_for(strategy_spec)
        res_df = runner.backtest(panel=macro_panel, price_panel=price_panel)
        if res_df.is_empty() or "nav" not in res_df.columns:
            start_pos += test_step
            slice_idx += 1
            continue

        is_sub = res_df.filter(
            (pl.col("trade_date") >= is_start_d) & (pl.col("trade_date") <= is_end_d)
        )
        oos_sub = res_df.filter(
            (pl.col("trade_date") >= oos_start_d) & (pl.col("trade_date") <= oos_end_d)
        )

        if is_sub.is_empty() or oos_sub.is_empty():
            start_pos += test_step
            slice_idx += 1
            continue

        is_cagr, is_dd, is_sh = _extract_metric(is_sub)
        oos_cagr, oos_dd, oos_sh = _extract_metric(oos_sub)

        denom = is_cagr if is_cagr > 0 else 0.01
        wfe = oos_cagr / denom

        slices.append(
            WalkForwardSlice(
                slice_index=slice_idx,
                is_start=is_start_d,
                is_end=is_end_d,
                oos_start=oos_start_d,
                oos_end=oos_end_d,
                is_trading_days=len(is_sub),
                oos_trading_days=len(oos_sub),
                is_cagr=is_cagr,
                is_max_dd=is_dd,
                is_sharpe=is_sh,
                oos_cagr=oos_cagr,
                oos_max_dd=oos_dd,
                oos_sharpe=oos_sh,
                wfe_ratio=wfe,
            )
        )

        # 拼接 OOS 净值
        base_nav = oos_sub["nav"][0]
        rebased_oos = oos_sub.select(["trade_date", "nav"]).with_columns(
            (pl.col("nav") / base_nav).alias("rel_nav")
        )
        oos_nav_segments.append(rebased_oos)

        start_pos += test_step
        slice_idx += 1

    if not slices:
        return None

    # 拼接连续 OOS 净值
    stitched_rows: list[dict[str, Any]] = []
    current_cum_nav = 1.0
    for seg in oos_nav_segments:
        for row in seg.to_dicts():
            d = row["trade_date"]
            r_nav = row["rel_nav"]
            stitched_rows.append({"trade_date": d, "nav": current_cum_nav * r_nav})
        current_cum_nav = stitched_rows[-1]["nav"]

    stitched_df = (
        pl.DataFrame(stitched_rows).unique(subset=["trade_date"], keep="last").sort("trade_date")
    )
    full_cagr, full_dd, full_sh = _extract_metric(stitched_df)
    avg_wfe = sum(s.wfe_ratio for s in slices) / len(slices)

    return WalkForwardResult(
        strategy_name=strategy_name,
        slices=slices,
        stitched_oos_nav=stitched_df,
        full_oos_cagr=full_cagr,
        full_oos_max_dd=full_dd,
        full_oos_sharpe=full_sh,
        avg_wfe=avg_wfe,
    )


def render_walk_forward_markdown(results: list[WalkForwardResult]) -> str:
    """将多策略 Walk-Forward 检验结果渲染为 Markdown 表格。"""
    lines = [
        "## Walk-Forward 滚动样本外检验 (OOS Analysis)",
        "",
        "验证协议：滚动 3 年样本内 (In-Sample, 756D) -> 滚动 1 年样本外 (Out-of-Sample, 252D) 连续步进拼接。",
        "",
        "| 策略名称 | 拼接 OOS CAGR | 拼接 OOS 最大回撤 | 拼接 OOS 夏普比率 | 平均 WFE 效率比 | 样本外有效性评级 |",
        "| :--- | :---: | :---: | :---: | :---: | :--- |",
    ]

    for r in results:
        wfe_str = f"{r.avg_wfe:.2f}"
        if r.avg_wfe >= 0.7:
            grade = "🟢 极强抗过拟合 (WFE >= 0.7)"
        elif r.avg_wfe >= 0.4:
            grade = "🟡 稳健可用 (0.4 <= WFE < 0.7)"
        else:
            grade = "🔴 参数衰减明显 (WFE < 0.4)"

        lines.append(
            f"| **`{r.strategy_name}`** | **`{r.full_oos_cagr:+.2f}%`** | "
            f"**`{r.full_oos_max_dd:.2f}%`** | **`{r.full_oos_sharpe:.2f}`** | "
            f"`{wfe_str}` | {grade} |"
        )

    lines.append("")
    return "\n".join(lines)


__all__ = [
    "WalkForwardResult",
    "WalkForwardSlice",
    "render_walk_forward_markdown",
    "run_walk_forward_analysis",
]
