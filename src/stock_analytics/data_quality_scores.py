"""评分结果相关的数据质量提示。"""

from __future__ import annotations

from typing import Any


def score_quality_issues(dimensions: list[dict[str, Any]]) -> list[dict[str, str]]:
    """为降级的维度主温度生成质量警告。"""
    issues: list[dict[str, str]] = []
    labels = {"activity": "活跃水位", "slow": "慢情绪"}
    for item in dimensions:
        source = str(item.get("temperature_source") or "")
        if source not in labels:
            continue
        dimension = str(item.get("name") or item.get("dimension_id") or "维度")
        issues.append(
            {
                "severity": "warning",
                "id": "dimension_temperature_fallback",
                "message": f"{dimension}主温度已降级为{labels[source]}口径，主动能指标无可用事实。",
            }
        )
    return issues
