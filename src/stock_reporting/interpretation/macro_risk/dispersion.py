"""宏观风控维度的成分分歧计算。

维度分（``dim_*``）是成分分位的算术均值：一个 99 分位的筹码背离度会被
1 分位的综合主力流向稀释成「流向平衡」。本模块只负责把这种成分背离算出来，
供 ``logic.evaluate_macro_risk`` 与研报模板披露。
"""

from __future__ import annotations

from typing import Any

from stock_reporting.interpretation.macro_risk.config import safe_float


def build_component_dispersion(
    row: dict[str, Any],
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """计算各维度内部成分分位极差，披露被均值掩盖的分歧。

    极差不低于 ``component_dispersion.alert_spread`` 的维度才会返回。

    Args:
        row: 当日因子快照（含各成分 ``*_score`` 列）。
        cfg: 研报阈值配置。

    Returns:
        按极差降序排列的分歧列表，元素含
        dim/name/value/spread/parts/high/low 及标签。
    """
    block = cfg.get("component_dispersion") or {}
    if not isinstance(block, dict):
        return []
    alert = safe_float(block.get("alert_spread"), 50.0)
    comp_map = block.get("components") or {}
    if not isinstance(comp_map, dict):
        return []
    dim_cfg = cfg.get("dimensions") or {}
    out: list[dict[str, Any]] = []
    for dim_key, comps in comp_map.items():
        if not isinstance(comps, dict):
            continue
        parts: list[dict[str, Any]] = []
        for label, column in comps.items():
            raw = row.get(column)
            if raw is None:
                continue
            parts.append({"label": label, "value": safe_float(raw)})
        if len(parts) < 2:
            continue
        hi = max(parts, key=lambda p: p["value"])
        lo = min(parts, key=lambda p: p["value"])
        spread = float(hi["value"]) - float(lo["value"])
        if spread < alert:
            continue
        name = (dim_cfg.get(dim_key) or {}).get("name", dim_key)
        out.append(
            {
                "dim": dim_key,
                "name": name,
                "value": round(safe_float(row.get(f"dim_{dim_key}")), 1),
                "spread": round(spread, 1),
                "parts": parts,
                "high_label": hi["label"],
                "high": round(float(hi["value"]), 1),
                "low_label": lo["label"],
                "low": round(float(lo["value"]), 1),
            }
        )
    out.sort(key=lambda item: item["spread"], reverse=True)
    return out


__all__ = ["build_component_dispersion"]
