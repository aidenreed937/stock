"""宏观风控多策略跨周期稳定性审计报告与图表渲染器。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import polars as pl


def render_stability_charts(
    wide_df: pl.DataFrame,
    regime_df: pd.DataFrame,
    stress_df: pd.DataFrame,
    r3: pd.DataFrame,
    output_dir: Path,
) -> Path:
    """生成 4 合 1 高清对比图表。"""
    from stock_reporting.core.matplotlib_config import configure_matplotlib

    matplotlib, plt = configure_matplotlib()

    fig = plt.figure(figsize=(16, 12))

    # Subplot 1: 6 大范式收益
    ax1 = fig.add_subplot(2, 2, 1)
    p_regime = regime_df.pivot(index="宏观范式", columns="标的/策略", values="区间累计收益")
    p_regime.plot(kind="bar", ax=ax1, width=0.8)
    ax1.set_title("各宏观范式周期收益对比")
    ax1.set_ylabel("区间累计收益")
    ax1.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax1.grid(True, linestyle="--", alpha=0.4)
    ax1.legend(loc="upper right", fontsize=7)
    plt.setp(ax1.get_xticklabels(), rotation=20, ha="right", fontsize=8)

    # Subplot 2: 压力测试最深回撤
    ax2 = fig.add_subplot(2, 2, 2)
    p_stress = stress_df.pivot(index="压力测试情景", columns="标的/策略", values="区间最深回撤")
    p_stress.plot(kind="bar", ax=ax2, width=0.8)
    ax2.set_title("历史极端危机压力测试 (最深回撤)")
    ax2.set_ylabel("最大回撤")
    ax2.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax2.grid(True, linestyle="--", alpha=0.4)
    ax2.legend(loc="lower right", fontsize=7)
    plt.setp(ax2.get_xticklabels(), rotation=15, ha="right", fontsize=8)

    # Subplot 3: 滚动 3 年表现
    ax3 = fig.add_subplot(2, 2, 3)
    if not r3.empty:
        r3_idx = r3.set_index("标的/策略")
        w_data = pd.DataFrame(
            {
                "跑赢全指胜率": r3_idx["跑赢基准(全指)概率"],
                "中位数收益率": r3_idx["中位数收益率"],
            }
        )
        w_data.plot(kind="bar", ax=ax3, width=0.6, color=["#1f77b4", "#ff7f0e"])
        ax3.set_title("滚动 3 年持有期表现分布")
        ax3.set_ylabel("比率")
        ax3.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
        ax3.grid(True, linestyle="--", alpha=0.4)
        ax3.legend(loc="upper right", fontsize=8)
        plt.setp(ax3.get_xticklabels(), rotation=20, ha="right", fontsize=8)

    # Subplot 4: 全周期净值曲线 (对数)
    ax4 = fig.add_subplot(2, 2, 4)
    dates_list = wide_df["trade_date"].to_list()
    all_cols = [c for c in wide_df.columns if c != "trade_date"]
    for col in all_cols:
        ax4.plot(dates_list, wide_df[col].to_list(), label=col, linewidth=1.1)
    ax4.set_title("全周期累计净值曲线全景 (对数坐标)")
    ax4.set_yscale("log")
    ax4.set_ylabel("累计净值")
    ax4.grid(True, which="both", linestyle="--", alpha=0.4)
    ax4.legend(loc="upper left", fontsize=7)

    fig.tight_layout()
    chart_path = output_dir / "strategy_stability_charts.png"
    fig.savefig(chart_path, dpi=130)
    plt.close(fig)
    return chart_path


def render_audit_markdown(
    wide_df: pl.DataFrame,
    regime_df: pd.DataFrame,
    stress_df: pd.DataFrame,
    rolling_df: pd.DataFrame,
    chart_file: Path | None,
    report_file: Path,
) -> None:
    """渲染结构化 Markdown 审计报告。"""

    def _pct(v: Any) -> str:
        if pd.isna(v) or v is None:
            return "—"
        return f"{float(v) * 100:+.2f}%" if float(v) != 0 else "0.00%"

    def _num(v: Any, digits: int = 2) -> str:
        if pd.isna(v) or v is None:
            return "—"
        return f"{float(v):.{digits}f}"

    regime_md = ""
    for r_name, grp in regime_df.groupby("宏观范式", sort=False):
        t_span = grp["时间区间"].iloc[0]
        regime_md += f"\n#### {r_name} ({t_span})\n\n"
        regime_md += "| 标的/策略 | 区间累计收益 | 年化收益 (CAGR) | 区间最大回撤 | 年化波动率 | 夏普比率 |\n"
        regime_md += "| :--- | :---: | :---: | :---: | :---: | :---: |\n"
        for _, row in grp.iterrows():
            name_c = (
                f"**`{row['标的/策略']}`**"
                if "macro" in str(row["标的/策略"])
                else str(row["标的/策略"])
            )
            regime_md += f"| {name_c} | {_pct(row['区间累计收益'])} | {_pct(row['年化收益(CAGR)'])} | {_pct(row['区间最大回撤'])} | {_pct(row['年化波动率'])} | {_num(row['夏普比率'])} |\n"

    stress_md = (
        "| 压力测试情景 | 危机时间区间 | 核心情景特征 | 标的/策略 | 区间跌幅 | 极端最深回撤 |\n"
    )
    stress_md += "| :--- | :--- | :--- | :--- | :---: | :---: |\n"
    for _, row in stress_df.iterrows():
        name_c = (
            f"**`{row['标的/策略']}`**"
            if "macro" in str(row["标的/策略"])
            else str(row["标的/策略"])
        )
        stress_md += f"| {row['压力测试情景']} | {row['危机区间']} | {row['场景特征']} | {name_c} | {_pct(row['区间跌幅'])} | {_pct(row['区间最深回撤'])} |\n"

    rolling_md = "| 标的/策略 | 滚动持有期 | 滚动窗口数 | 绝对正收益胜率 | 跑赢全指胜率 | 中位数收益率 | 最佳收益 | 最差收益 | 极端最深回撤 |\n"
    rolling_md += "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n"
    for _, row in rolling_df.iterrows():
        name_c = (
            f"**`{row['标的/策略']}`**"
            if "macro" in str(row["标的/策略"])
            else str(row["标的/策略"])
        )
        rolling_md += f"| {name_c} | {row['滚动窗口']} | {int(row['测试窗口总数'])} | **{_pct(row['正收益胜率'])}** | **{_pct(row['跑赢基准(全指)概率'])}** | {_pct(row['中位数收益率'])} | {_pct(row['最佳区间收益'])} | {_pct(row['最差区间收益'])} | {_pct(row['极端最深回撤'])} |\n"

    img_line = f"![多策略跨周期稳定性对比图]({chart_file.name})\n" if chart_file else ""

    content = f"""# 宏观风控多策略全周期稳定性审计报告

> **审计交易日总数**：{len(wide_df)} 交易日 ({wide_df["trade_date"].min()!s} ~ {wide_df["trade_date"].max()!s})
> **审计覆盖**：6 大宏观范式切片 + 4 大极端危机压力测试 + 滚动 1Y/3Y 胜率对账
> **生成时间**：{date.today()}

{img_line}
---

## 一、 跨 6 大宏观范式分段回溯审计 (Regime Analysis)

{regime_md}

---

## 二、 历史极端黑天鹅压力测试 (Stress Testing)

{stress_md}

---

## 三、 任意时点入场滚动 1 年 (252D) 与 3 年 (756D) 稳定性统计

{rolling_md}
"""
    report_file.write_text(content, encoding="utf-8")


__all__ = ["render_audit_markdown", "render_stability_charts"]
