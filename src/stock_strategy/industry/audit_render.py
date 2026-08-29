"""申万行业多策略跨周期稳定性审计报告与图表渲染器。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import polars as pl


def render_industry_stability_charts(
    wide_df: pl.DataFrame,
    regime_df: pd.DataFrame,
    stress_df: pd.DataFrame,
    r3_df: pd.DataFrame,
    output_dir: Path,
) -> Path:
    """生成 4 合 1 高清行业策略稳定性对比图表。"""
    from stock_reporting.core.matplotlib_config import configure_matplotlib

    _, plt = configure_matplotlib()

    fig = plt.figure(figsize=(16, 12), dpi=140)

    # Subplot 1: 6 大范式收益
    ax1 = fig.add_subplot(2, 2, 1)
    if not regime_df.empty and {"macro_regime", "strategy", "total_return"}.issubset(
        regime_df.columns
    ):
        p_regime = regime_df.pivot(index="macro_regime", columns="strategy", values="total_return")
        p_regime.plot(kind="bar", ax=ax1, width=0.8)
        ax1.set_title("各宏观范式周期收益对比 (%)", fontsize=11, fontweight="semibold")
        ax1.set_ylabel("区间累计收益 (%)")
        ax1.grid(True, linestyle="--", alpha=0.4)
        ax1.legend(loc="upper right", fontsize=7)
        plt.setp(ax1.get_xticklabels(), rotation=20, ha="right", fontsize=8)

    # Subplot 2: 压力测试最深回撤
    ax2 = fig.add_subplot(2, 2, 2)
    if not stress_df.empty and {"crisis_name", "strategy", "max_drawdown"}.issubset(
        stress_df.columns
    ):
        p_stress = stress_df.pivot(index="crisis_name", columns="strategy", values="max_drawdown")
        p_stress.plot(kind="bar", ax=ax2, width=0.8)
        ax2.set_title("历史极端危机压力测试 (最大回撤 %)", fontsize=11, fontweight="semibold")
        ax2.set_ylabel("最大回撤 (%)")
        ax2.grid(True, linestyle="--", alpha=0.4)
        ax2.legend(loc="upper right", fontsize=7)
        plt.setp(ax2.get_xticklabels(), rotation=15, ha="right", fontsize=8)

    # Subplot 3: 滚动 3 年胜率与收益
    ax3 = fig.add_subplot(2, 2, 3)
    if not r3_df.empty and {"strategy", "win_rate", "cagr_median"}.issubset(r3_df.columns):
        r3_idx = r3_df.set_index("strategy")
        w_data = pd.DataFrame(
            {
                "正收益胜率 (%)": r3_idx["win_rate"],
                "中位数年化收益 (%)": r3_idx["cagr_median"],
            }
        )
        w_data.plot(kind="bar", ax=ax3, width=0.6, color=["#1f77b4", "#ff7f0e"])
        ax3.set_title("滚动 3 年持有期表现分布", fontsize=11, fontweight="semibold")
        ax3.set_ylabel("比率 / 年化 (%)")
        ax3.grid(True, linestyle="--", alpha=0.4)
        ax3.legend(loc="upper right", fontsize=8)
        plt.setp(ax3.get_xticklabels(), rotation=20, ha="right", fontsize=8)

    # Subplot 4: 全周期净值曲线 (对数)
    ax4 = fig.add_subplot(2, 2, 4)
    dates_list = wide_df["trade_date"].to_list()
    all_cols = [c for c in wide_df.columns if c != "trade_date"]
    for col in all_cols:
        ax4.plot(dates_list, wide_df[col].to_list(), label=col, linewidth=1.2)
    ax4.set_title("全周期累计净值全景 (对数坐标)", fontsize=11, fontweight="semibold")
    ax4.set_yscale("log")
    ax4.set_ylabel("累计净值")
    ax4.grid(True, which="both", linestyle="--", alpha=0.4)
    ax4.legend(loc="upper left", fontsize=7)

    fig.tight_layout()
    chart_path = output_dir / "strategy_stability_charts.png"
    fig.savefig(chart_path, bbox_inches="tight")
    plt.close(fig)
    return chart_path


def _format_df_table(df: pd.DataFrame) -> str:
    """自研轻量 DataFrame 转 Markdown 表格 (零第三方库依赖)。"""
    if df.empty:
        return "无数据"
    cols = [str(c) for c in df.columns]
    headers = "| " + " | ".join(cols) + " |"
    aligns = "| " + " | ".join([":---:" if i > 0 else ":---" for i in range(len(cols))]) + " |"
    rows = []
    for _, row in df.iterrows():
        r_str = "| " + " | ".join(str(row[c]) for c in df.columns) + " |"
        rows.append(r_str)
    return "\n".join([headers, aligns, *rows])


def render_industry_audit_markdown(
    regime_df: pd.DataFrame,
    stress_df: pd.DataFrame,
    r1_df: pd.DataFrame,
    r3_df: pd.DataFrame,
    guardrail_results: list[dict[str, Any]],
    output_path: Path,
) -> str:
    """渲染申万行业策略跨周期稳定性审计 Markdown 研报。"""
    regime_md = _format_df_table(regime_df)
    stress_md = _format_df_table(stress_df)
    r1_md = _format_df_table(r1_df)
    r3_md = _format_df_table(r3_df)

    guard_rows = []
    all_passed = True
    for g in guardrail_results:
        passed = g.get("passed", True)
        if not passed:
            all_passed = False
        status_str = "✅ 通过" if passed else "❌ 未通过"
        guard_rows.append(
            f"| {g.get('metric')} | {g.get('threshold')} | {g.get('actual')} | {status_str} |"
        )
    guard_table = (
        "| 门禁指标 | 约束要求 | 实际表现 | 状态 |\n| :--- | :--- | :--- | :--- |\n"
        + "\n".join(guard_rows)
    )

    overall_status = "✅ 全部门禁验证通过" if all_passed else "⚠️ 存在未达标门禁项"

    md = f"""# 申万行业轮动策略跨周期稳定性审计报告

> **审计范围**: 2015-2026 全历史 11 年（6 大宏观范式 + 4 大极端危机压力测试 + 滚动持有期胜率）
> **门禁总评**: **{overall_status}**

---


## 一、 策略防退化 CI 门禁判定 (Regression Guardrails)

{guard_table}

---

## 二、 6 大跨周期历史宏观范式切片对账

{regime_md}

---

## 三、 4 大历史极端危机压力测试 (Stress Testing)

{stress_md}

---

## 四、 滚动 1 年 (252D) 与 3 年 (756D) 胜率与回撤分布

### 1. 滚动 1 年 (252 交易日)
{r1_md}

### 2. 滚动 3 年 (756 交易日)
{r3_md}

---

## 五、 高清 4 合 1 跨周期稳定性多维对比走势图

![申万行业策略跨周期稳定性多维对比图](strategy_stability_charts.png)
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(md, encoding="utf-8")
    return md


__all__ = ["render_industry_audit_markdown", "render_industry_stability_charts"]
