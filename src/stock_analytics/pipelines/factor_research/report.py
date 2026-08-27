"""因子准入评估报告渲染（markdown + json）。"""

from __future__ import annotations

from datetime import date
from typing import Any

from stock_analytics.pipelines.factor_research.config import FactorResearchConfig

_VERDICT_LABEL = {
    "pass": "通过",
    "fail": "未通过",
    "insufficient": "样本不足",
}


def build_report(
    config: FactorResearchConfig,
    as_of_date: date,
    window_start: date,
    factors: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """组装 markdown 与 json 报告。

    Returns:
        (report_markdown, report_json)
    """
    pass_count = sum(1 for f in factors if f["verdict"] == "pass")
    report_json = {
        "as_of_date": as_of_date.isoformat(),
        "window_start": window_start.isoformat(),
        "window_days": config.window_days,
        "horizons": list(config.horizons),
        "decision_horizon": config.decision_horizon,
        "price_col": config.price_col,
        "data_note": "前向收益基于未复权收盘价；除权日收益可能失真，结论仅供研究参考。",
        "thresholds": {
            "icir": config.thresholds.icir,
            "t_stat": config.thresholds.t_stat,
            "long_short_mean": config.thresholds.long_short_mean,
        },
        "factor_pool_size": len(factors),
        "pass_count": pass_count,
        "factors": factors,
    }

    lines: list[str] = [
        f"# {config.title}",
        "",
        f"- 评估窗口：{window_start.isoformat()} ~ {as_of_date.isoformat()}（{config.window_days} 自然日）",
        f"- 前向收益窗口（交易日）：{' / '.join(str(h) for h in config.horizons)}；"
        f"准入主口径 {config.decision_horizon}d",
        f"- 价格基准：`{config.price_col}`（未复权口径，除权日收益可能失真）",
        f"- 准入阈值：ICIR ≥ {config.thresholds.icir}，t ≥ {config.thresholds.t_stat}，"
        f"多空价差（按方向）≥ {config.thresholds.long_short_mean}",
        f"- 评估因子 {len(factors)} 个，通过 {pass_count} 个",
        "",
        "## 因子准入结论",
        "",
        "| 因子 | 单位 | 方向 | 主口径天数 | IC 均值 | ICIR | t 统计量 | 单调性 | 多空价差 | 准入 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for factor in factors:
        monotonicity = (
            f"{factor['monotonicity_spearman']:+.2f}"
            if factor["monotonicity_spearman"] is not None
            else "-"
        )
        lines.append(
            "| {feature_id} | {unit} | {direction} | {n_days} | {ic_mean} | {icir} | "
            "{t_stat} | {monotonicity} | {long_short_mean:+.3f} | {verdict} |".format(
                feature_id=factor["feature_id"],
                unit=factor["unit"],
                direction=factor["direction"],
                n_days=factor["n_days"],
                ic_mean=_fmt(factor["ic_mean"]),
                icir=_fmt(factor["icir"]),
                t_stat=_fmt(factor["t_stat"]),
                monotonicity=monotonicity,
                long_short_mean=factor["long_short_mean"],
                verdict=_VERDICT_LABEL.get(factor["verdict"], factor["verdict"]),
            )
        )

    lines.extend(
        [
            "",
            "## 信息衰减（各 horizon 平均 IC）",
            "",
            "| 因子 | " + " | ".join(f"{h}d" for h in config.horizons) + " |",
            "| --- | " + " | ".join("---" for _ in config.horizons) + " |",
        ]
    )
    for factor in factors:
        row = [factor["feature_id"]]
        for horizon in config.horizons:
            stats = factor["horizon_stats"].get(str(horizon), {})
            row.append(_fmt(stats.get("ic_mean")))
        lines.append("| " + " | ".join(row) + " |")

    lines.extend(
        [
            "",
            "## 未通过说明",
            "",
        ]
    )
    failed = [f for f in factors if f["verdict"] == "fail"]
    if failed:
        for factor in failed:
            lines.append(f"- `{factor['feature_id']}`：{'；'.join(factor['reasons'])}")
    else:
        lines.append("- 无")
    lines.append("")

    return "\n".join(lines), report_json


def _fmt(value: float | None) -> str:
    """格式化浮点统计量为报告字符串。"""
    if value is None:
        return "-"
    return f"{value:.4f}"


__all__ = ["build_report"]
