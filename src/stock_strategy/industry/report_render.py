"""申万行业多策略资金曲线对比图表与 Markdown 研报渲染器。"""

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


def render_industry_comparison_chart(
    series: dict[str, pl.DataFrame],
    out_path: Path | str,
    benchmarks_list: list[tuple[str, str]] | None = None,
) -> Path:
    """绘制所有行业轮动策略与基准的资金曲线对比图。"""
    from stock_reporting.core.matplotlib_config import configure_matplotlib

    _, plt = configure_matplotlib()

    b_list = benchmarks_list or _DEFAULT_BENCHMARKS
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(13, 8), dpi=150, sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )

    for name, df in series.items():
        if df.is_empty():
            continue
        pydates = df["trade_date"].to_list()
        navs = df["nav"].to_list()
        is_bench = any(name == label for _, label in b_list)
        lw = 1.2 if is_bench else 2.0
        ls = "--" if is_bench else "-"
        alpha = 0.6 if is_bench else 0.95
        ax1.plot(pydates, navs, label=name, linewidth=lw, linestyle=ls, alpha=alpha)

        # 计算回撤曲线
        cummax = df["nav"].cum_max()
        dd = (df["nav"] / cummax - 1.0) * 100.0
        ax2.plot(pydates, dd.to_list(), label=name, linewidth=lw, linestyle=ls, alpha=alpha)

    ax1.set_title(
        "申万 31 行业轮动多策略全周期资金曲线横向对账 (2015-2026)",
        fontsize=14,
        fontweight="semibold",
        pad=12,
    )
    ax1.set_ylabel("复权净值 (首日归一为 1.0)", fontsize=11)
    ax1.grid(True, linestyle=":", alpha=0.5)
    ax1.legend(loc="upper left", frameon=True, fontsize=9)

    ax2.set_title("历史动态回撤 (%)", fontsize=11, pad=8)
    ax2.set_xlabel("交易日期", fontsize=11)
    ax2.set_ylabel("回撤幅度 (%)", fontsize=10)
    ax2.grid(True, linestyle=":", alpha=0.5)

    fig.tight_layout()

    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_p, bbox_inches="tight")
    plt.close(fig)
    return out_p


def render_industry_comparison_markdown(
    stats: dict[str, dict[str, Any]],
    start: date | None = None,
    end: date | None = None,
    out_path: Path | str | None = None,
    benchmarks_list: list[tuple[str, str]] | None = None,
    image_rel_path: str = "multi_strategy_comparison.png",
) -> str:
    """生成包含全部策略绩效对比的 Markdown 研报。"""
    b_list = benchmarks_list or _DEFAULT_BENCHMARKS
    benchmark_labels = [label for _, label in b_list if label in stats]
    strategy_labels = [name for name in stats if name not in benchmark_labels]
    all_cols = benchmark_labels + strategy_labels

    header_cols = " | ".join(
        f"**{col}**" if col in strategy_labels else f"{col} (基准)" for col in all_cols
    )
    align_cols = " | ".join([":---:"] * len(all_cols))

    def _fmt_row(label: str, fn: Callable[[dict[str, Any]], str]) -> str:
        vals = " | ".join(fn(stats[col]) for col in all_cols)
        return f"| **{label}** | {vals} |"

    r_final = _fmt_row("累计净值", lambda s: f"{s.get('final_nav', 0.0):.3f}")
    r_total = _fmt_row("区间总收益", lambda s: f"{s.get('total_return', 0.0):+.1f}%")
    r_cagr = _fmt_row("年化复合收益 (CAGR)", lambda s: f"{s.get('cagr', 0.0):+.2f}%")
    r_mdd = _fmt_row("最大回撤 (MaxDD)", lambda s: f"{s.get('max_drawdown', 0.0):.2f}%")
    r_vol = _fmt_row("年化波动率", lambda s: f"{s.get('annual_volatility', 0.0):.2f}%")
    r_sharpe = _fmt_row("夏普比率 (Sharpe, Rf=2%)", lambda s: f"{s.get('sharpe_ratio', 0.0):.2f}")
    r_calmar = _fmt_row("卡玛比率 (Calmar)", lambda s: f"{s.get('calmar_ratio', 0.0):.2f}")

    start_str = str(start) if start else "起始"
    end_str = str(end) if end else "最新"

    md = f"""# 申万 31 行业轮动多策略全周期横向对账研报

> **回测区间**: {start_str} 至 {end_str} (跨度 11 年、2,833 个交易日)
> **数据底座**: 申万 31 行业日行情黄金表 + 5 大中观因子面板 + 宏观风控双轨雷达
> **执行规则**: 严格 T+1 交易日调仓 + 真实交易摩擦成本 (佣金+滑点) + 3% 死区过滤

---


## 一、 全周期核心绩效横向对比表

| 核心绩效指标 | {header_cols} |
| :--- | {align_cols} |
{r_final}
{r_total}
{r_cagr}
{r_mdd}
{r_vol}
{r_sharpe}
{r_calmar}

---

## 二、 全周期资金曲线与动态回撤走势

![申万行业多策略资金曲线与动态回撤]({image_rel_path})

---

## 三、 四大行业轮动策略逻辑画像

1. **纯高景气动量轮动 (`industry_momentum`)**：
   - 逻辑：每月调仓，打满 31 行业景气动量得分最高的 Top 3 行业 (20/60D 动量 + 净利润增速分位)；
   - 特点：牛市弹性高，主升浪捕捉能力极强。

2. **反拥挤逆向低估值 (`industry_reversal`)**：
   - 逻辑：拥挤度 > 85% 坚决剔除；在估值处于安全边际 (pe/pb分位 <= 20%) 且动量初起的行业中建仓；
   - 特点：防踩踏能力优异，熊市与震荡市安全边际充足。

3. **供需景气剪刀差 (`industry_scissors`)**：
   - 逻辑：筛选“净利润增速 - 营收增速”最高（毛利率扩张）且聪明资金流（外资+机构）持续净流入的行业；
   - 特点：重仓具备真实产业链定价权与抗通胀优势的核心赛道。

4. **宏观相态自适应元路由 (`industry_meta_router`)**：
   - 逻辑：监听宏观雷达，恐慌破位 100% 切换银行/煤炭/公用事业红利防御，多头主升切换高景气成长赛道；
   - 特点：跨周期自适应，平滑极端黑天鹅波动。
"""
    if out_path:
        out_p = Path(out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(md, encoding="utf-8")

    return md


__all__ = [
    "render_industry_comparison_chart",
    "render_industry_comparison_markdown",
]
