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


def render_comparison_chart(
    series: dict[str, pl.DataFrame],
    out_path: Path | str,
    benchmarks_list: list[tuple[str, str]] | None = None,
) -> Path:
    """绘制所有策略与基准的资金曲线多合一对比图。"""
    from stock_reporting.core.matplotlib_config import configure_matplotlib

    _, plt = configure_matplotlib()

    b_list = benchmarks_list or _DEFAULT_BENCHMARKS
    fig, ax = plt.subplots(figsize=(12, 6), dpi=150)
    for name, df in series.items():
        if df.is_empty():
            continue
        pydates = df["trade_date"].to_list()
        navs = df["nav"].to_list()
        is_bench = any(name == label for _, label in b_list)
        lw = 1.2 if is_bench else 2.0
        ls = "--" if is_bench else "-"
        alpha = 0.6 if is_bench else 0.95
        ax.plot(pydates, navs, label=name, linewidth=lw, linestyle=ls, alpha=alpha)

    ax.set_title(
        "宏观风控多策略全周期资金曲线横向对比 (2015-2026)",
        fontsize=14,
        fontweight="semibold",
        pad=12,
    )
    ax.set_xlabel("交易日期", fontsize=11)
    ax.set_ylabel("复权净值 (首日归一为 1.0)", fontsize=11)
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.legend(loc="upper left", frameon=True, fontsize=9)
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
    """生成包含全部策略绩效对比的 Markdown 研报。"""
    b_list = benchmarks_list or _DEFAULT_BENCHMARKS
    benchmark_labels = [label for _, label in b_list if label in stats]
    strategy_labels = [name for name in stats if name not in benchmark_labels]
    all_cols = benchmark_labels + strategy_labels

    header_cols = " | ".join(
        f"**{col}**" if col in strategy_labels else f"{col} (基准)" for col in all_cols
    )
    align_cols = " | ".join([":---:"] * len(all_cols))

    def _get_val(s: dict[str, Any], key: str, default: float = 0.0) -> float:
        v = s.get(key)
        return float(v) if v is not None else default

    def _fmt_row(label: str, fn: Callable[[dict[str, Any]], str]) -> str:
        vals = " | ".join(fn(stats[col]) for col in all_cols)
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

    start_str = start.isoformat() if start else "N/A"
    end_str = end.isoformat() if end else "N/A"

    content = f"""# 宏观风控多策略演进与全周期重测全景对比 (2015-2026)

本报告基于固化入库的生产级代码，对所有已配置的宏观风控策略在全量真实历史数据上进行严格横向对账。回测采用 T+1 语义（信号当日收盘生成、次日生效）；配置了 `friction` 的 ETF 实盘版已扣除佣金与滑点并受调仓死区过滤，理论版未计交易成本；均未计 T+1 涨跌停限制，仅供研究参考。

![多策略资金曲线全景对比]({image_rel_path})

---

### 全周期量化绩效总览 ({start_str} 至 {end_str})

| 核心指标项 | {header_cols} |
| :--- | {align_cols} |
{r_final}
{r_total}
{r_cagr}
{r_maxdd}
{r_vol}
{r_sharpe}
{r_calmar}

---

### 定性总结：多策略互补矩阵

- **趋势防守压舱石**：单宽基趋势择时策略，在市场面临系统性下跌时坚决破均线降仓，控制下行回撤。
- **双核风格轮动**：攻守兼备，牛市吃满成长主升浪弹性，存量熊市高股息红利托底避险。
- **资金博弈智能增强**：在风格轮动基础上融入国家队大额托底抢跑与高位散户接盘逃顶，提升胜率与极值捕获效率。

> 以上为历史回测结果，不代表未来表现；实盘需叠加交易成本、流动性约束与策略漂移再评估。
"""
    if out_path is not None:
        out_p = Path(out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(content, encoding="utf-8")
        return out_p
    return content


__all__ = ["render_comparison_chart", "render_comparison_markdown"]
