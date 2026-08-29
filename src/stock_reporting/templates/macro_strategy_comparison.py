"""宏观风控多策略资金曲线对比图表与 Markdown 渲染器。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

_DEFAULT_BENCHMARKS = [
    ("000985.CSI", "中证全指"),
    ("000300.SH", "沪深300"),
]


def _is_etf_strategy(name: str) -> bool:
    return name.endswith("_etf") or "etf" in name.lower()


def render_comparison_chart(
    series: dict[str, pl.DataFrame],
    out_path: Path | str,
    benchmarks_list: list[tuple[str, str]] | None = None,
) -> Path:
    """绘制纯指数理论策略与场内实盘 ETF 策略双子图资金曲线对比图。"""
    from stock_reporting.core.matplotlib_config import configure_matplotlib

    _, plt = configure_matplotlib()

    b_list = benchmarks_list or _DEFAULT_BENCHMARKS
    benchmark_labels = [label for _, label in b_list]

    theory_series = {
        name: df
        for name, df in series.items()
        if name in benchmark_labels or not _is_etf_strategy(name)
    }
    etf_series = {
        name: df
        for name, df in series.items()
        if name in benchmark_labels or _is_etf_strategy(name)
    }

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 9), dpi=150, sharex=True)

    def _plot_group(ax: Any, group_series: dict[str, pl.DataFrame], title: str) -> None:
        for name, df in group_series.items():
            if df.is_empty():
                continue
            pydates = df["trade_date"].to_list()
            navs = df["nav"].to_list()
            is_bench = any(name == label for label in benchmark_labels)
            lw = 1.2 if is_bench else 2.0
            ls = "--" if is_bench else "-"
            alpha = 0.65 if is_bench else 0.95
            ax.plot(pydates, navs, label=name, linewidth=lw, linestyle=ls, alpha=alpha)
        ax.set_title(title, fontsize=12, fontweight="semibold", pad=10)
        ax.set_ylabel("复权净值 (首日归一为 1.0)", fontsize=10)
        ax.grid(True, linestyle=":", alpha=0.5)
        ax.legend(loc="upper left", frameon=True, fontsize=8.5, ncol=3)

    _plot_group(ax1, theory_series, "一、 纯指数理论策略全周期资金曲线 (无交易摩擦)")
    _plot_group(ax2, etf_series, "二、 场内 ETF 实盘策略全周期资金曲线 (扣除佣金/滑点/死区)")

    ax2.set_xlabel("交易日期", fontsize=11)
    fig.tight_layout()

    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_p, bbox_inches="tight")
    plt.close(fig)
    return out_p


def render_comparison_markdown(
    stats: dict[str, dict[str, Any]],
    start: date | None = None,
    end: date | None = None,
    out_path: Path | str | None = None,
    benchmarks_list: list[tuple[str, str]] | None = None,
    image_rel_path: str = "multi_strategy_comparison.png",
) -> str | Path:
    """生成按【纯指数理论版】与【场内 ETF 实盘版】分组呈现的 Markdown 对比研报。"""
    b_list = benchmarks_list or _DEFAULT_BENCHMARKS
    benchmark_labels = [label for _, label in b_list if label in stats]
    strategy_labels = [name for name in stats if name not in benchmark_labels]

    theory_strategies = [s for s in strategy_labels if not _is_etf_strategy(s)]
    etf_strategies = [s for s in strategy_labels if _is_etf_strategy(s)]

    def _get_val(s: dict[str, Any], key: str, default: float = 0.0) -> float:
        v = s.get(key)
        return float(v) if v is not None else default

    def _render_table(cols: list[str], group_title: str, subtitle: str) -> str:
        header_cols = " | ".join(
            f"**{col}**" if col in strategy_labels else f"{col} (基准)" for col in cols
        )
        align_cols = " | ".join([":---:"] * len(cols))

        def _fmt_row(label: str, fn: Callable[[dict[str, Any]], str]) -> str:
            vals = " | ".join(fn(stats[col]) for col in cols)
            return f"| **{label}** | {vals} |"

        r_final = _fmt_row(
            "累计净值",
            lambda s: (
                f"**`{_get_val(s, 'final_nav', 1.0):.3f}`**"
                if s != stats.get(benchmark_labels[0] if benchmark_labels else "")
                else f"{_get_val(s, 'final_nav', 1.0):.3f}"
            ),
        )
        r_total = _fmt_row(
            "累计收益",
            lambda s: (
                f"**`{_get_val(s, 'total_return') * 100:.2f}%`**"
                if s != stats.get(benchmark_labels[0] if benchmark_labels else "")
                else f"{_get_val(s, 'total_return') * 100:.2f}%"
            ),
        )
        r_cagr = _fmt_row(
            "年化收益 (CAGR)",
            lambda s: (
                f"**`{_get_val(s, 'cagr', _get_val(s, 'annual_return')) * 100:.2f}%`**"
                if s != stats.get(benchmark_labels[0] if benchmark_labels else "")
                else f"{_get_val(s, 'cagr', _get_val(s, 'annual_return')) * 100:.2f}%"
            ),
        )
        r_maxdd = _fmt_row(
            "最大回撤 (Max DD)",
            lambda s: (
                f"**`{_get_val(s, 'max_drawdown') * 100:.2f}%`**"
                if s != stats.get(benchmark_labels[0] if benchmark_labels else "")
                else f"{_get_val(s, 'max_drawdown') * 100:.2f}%"
            ),
        )
        r_vol = _fmt_row(
            "年化波动率",
            lambda s: (
                f"**`{_get_val(s, 'annualized_volatility', _get_val(s, 'annual_volatility')) * 100:.2f}%`**"
                if s != stats.get(benchmark_labels[0] if benchmark_labels else "")
                else f"{_get_val(s, 'annualized_volatility', _get_val(s, 'annual_volatility')) * 100:.2f}%"
            ),
        )
        r_sharpe = _fmt_row(
            "夏普比率 (Sharpe)",
            lambda s: (
                f"**`{_get_val(s, 'sharpe_ratio', _get_val(s, 'sharpe')):.2f}`**"
                if s != stats.get(benchmark_labels[0] if benchmark_labels else "")
                else f"{_get_val(s, 'sharpe_ratio', _get_val(s, 'sharpe')):.2f}"
            ),
        )
        r_calmar = _fmt_row(
            "卡玛比率 (Calmar)",
            lambda s: (
                f"**`{_get_val(s, 'calmar_ratio', _get_val(s, 'calmar')):.2f}`**"
                if s != stats.get(benchmark_labels[0] if benchmark_labels else "")
                else f"{_get_val(s, 'calmar_ratio', _get_val(s, 'calmar')):.2f}"
            ),
        )

        return f"""### {group_title}
> {subtitle}

| 核心指标项 | {header_cols} |
| :--- | {align_cols} |
{r_final}
{r_total}
{r_cagr}
{r_maxdd}
{r_vol}
{r_sharpe}
{r_calmar}
"""

    theory_cols = benchmark_labels + theory_strategies
    etf_cols = benchmark_labels + etf_strategies

    theory_table = _render_table(
        theory_cols,
        "一、 纯指数理论策略对比 (Theoretical Index Strategies)",
        "用于检验策略底层量化逻辑、宏观因子与状态机转移机制的理论上限（未计交易佣金与滑点）。",
    )
    etf_table = _render_table(
        etf_cols,
        "二、 场内 ETF 实盘策略对比 (Live Tradable ETF Strategies)",
        "普通股票账户可直接一键报单交易；已扣除万1佣金、万5冲击滑点并受 3% 调仓死区过滤；价格采用未复权收盘价（未计分红再投资，对高股息品种属保守低估）。",
    )

    start_str = start.isoformat() if start else "N/A"
    end_str = end.isoformat() if end else "N/A"

    # ---- 定性总结：数字一律动态取自 stats，避免与表格漂移 ----
    def _fmt_pct(v: float) -> str:
        return f"{v * 100:.2f}%"

    summary_lines: list[str] = ["### 三、 定性总结与实战选型", ""]
    v5_stats = stats.get("macro_rotation_v5_etf")
    if v5_stats:
        v5_cagr = _get_val(v5_stats, "cagr", _get_val(v5_stats, "annual_return"))
        v5_sharpe = _get_val(v5_stats, "sharpe_ratio", _get_val(v5_stats, "sharpe"))
        summary_lines.append(
            f"- **实盘收益与夏普冠军**：**`macro_rotation_v5_etf`** 在双核轮动基础上"
            f"引入聪明钱假黄金坑确认过滤，实盘 CAGR 达 **{_fmt_pct(v5_cagr)}**、"
            f"夏普 **{v5_sharpe:.2f}**，综合收益风险比最优；"
        )
    aw_stats = stats.get("macro_all_weather_etf")
    if aw_stats:
        aw_vol = _get_val(
            aw_stats, "annualized_volatility", _get_val(aw_stats, "annual_volatility")
        )
        aw_dd = _get_val(aw_stats, "max_drawdown")
        summary_lines.append(
            f"- **大类资产稳健防御**：**`macro_all_weather_etf`** 引入国债与黄金跨资产避险，"
            f"年化波动率压至 **{_fmt_pct(aw_vol)}**，最大回撤收窄至 **{_fmt_pct(aw_dd)}**。"
        )
    summary_lines.extend(
        [
            "",
            "> 以上为历史回测结果，不代表未来表现；实盘需叠加交易成本、流动性约束与策略漂移再评估。",
        ]
    )
    content = f"""# 宏观风控多策略全周期横向对账全景报告 ({start_str} 至 {end_str})

本报告基于固化入库的生产级代码，对所有已配置的宏观风控策略在全量真实历史数据上进行严格横向对账。回测采用 T+1 语义（信号当日收盘生成、次日生效）。

![多策略资金曲线全景对比]({image_rel_path})

---

{theory_table}

---

{etf_table}

---

{chr(10).join(summary_lines)}
"""
    if out_path is not None:
        out_p = Path(out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(content, encoding="utf-8")
        return out_p
    return content


__all__ = ["render_comparison_chart", "render_comparison_markdown"]
