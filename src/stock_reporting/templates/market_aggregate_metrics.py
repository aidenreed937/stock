"""全市场聚合报告的指标映射与展示格式化。"""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stock_reporting.interpretation.market_aggregate.config import MarketAggregateConfig


def build_metric_sections(config: MarketAggregateConfig, snapshot: Any) -> list[dict[str, Any]]:
    """按 YAML 中的顺序和分组构造指标行。"""
    sections: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for metric in config.report.metrics:
        if not metric.enabled:
            continue
        value, available = _metric_value(metric.metric_id, snapshot)
        sections.setdefault(metric.section, []).append(
            {
                "metric_id": metric.metric_id,
                "label": metric.label,
                "value": value,
                "available": available,
                "note": metric.note,
            }
        )
    return [{"title": title, "rows": rows} for title, rows in sections.items()]


def _metric_value(metric_id: str, snapshot: Any) -> tuple[str, bool]:
    if metric_id == "coverage":
        return (
            f"{snapshot.returned_count}/{snapshot.reported_count} ({snapshot.coverage_ratio:.2%})",
            True,
        )
    if metric_id == "breadth_counts":
        return f"{snapshot.advance_count} / {snapshot.decline_count} / {snapshot.flat_count}", True
    if metric_id == "breadth_shares":
        return f"{_share(snapshot.advance_share)} / {_share(snapshot.decline_share)}", True
    if metric_id == "advance_decline_ratio":
        return _ratio(snapshot.advance_decline_ratio), snapshot.advance_decline_ratio is not None
    if metric_id == "strong_move_counts":
        return (
            f"{snapshot.strong_up_count} / {snapshot.strong_down_count} "
            f"（±{snapshot.strong_up_threshold_pct:.1f}%）",
            True,
        )
    if metric_id == "change_distribution":
        return (
            f"{_pct(snapshot.pct_change_p25)} / {_pct(snapshot.median_pct_change)} "
            f"/ {_pct(snapshot.pct_change_p75)}",
            any(
                value is not None
                for value in (
                    snapshot.pct_change_p25,
                    snapshot.median_pct_change,
                    snapshot.pct_change_p75,
                )
            ),
        )
    if metric_id == "weighted_pct_change":
        return _pct(snapshot.weighted_pct_change), snapshot.weighted_pct_change is not None
    if metric_id == "amount_total":
        return _money(snapshot.amount_total_yuan), snapshot.amount_total_yuan is not None
    if metric_id == "market_value":
        return (
            f"{_money(snapshot.total_market_value_yuan)} / "
            f"{_money(snapshot.free_float_market_value_yuan)}",
            any(
                value is not None
                for value in (
                    snapshot.total_market_value_yuan,
                    snapshot.free_float_market_value_yuan,
                )
            ),
        )
    if metric_id == "free_float_turnover":
        return _pct(snapshot.free_float_turnover_pct), snapshot.free_float_turnover_pct is not None
    if metric_id == "amount_top_5pct_share":
        return _share(snapshot.amount_top_5pct_share), snapshot.amount_top_5pct_share is not None
    return "-", False


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}%"


def _share(value: float | None) -> str:
    return "-" if value is None else f"{value:.2%}"


def _ratio(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _money(value: float | None) -> str:
    if value is None:
        return "-"
    if value >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:.2f}万亿"
    if value >= 100_000_000:
        return f"{value / 100_000_000:.2f}亿"
    if value >= 10_000:
        return f"{value / 10_000:.2f}万"
    return f"{value:.0f}元"


__all__ = ["build_metric_sections"]
