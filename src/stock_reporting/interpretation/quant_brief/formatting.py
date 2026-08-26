"""quant_brief Markdown 渲染格式化辅助（拆分模块，控制模板文件规模）。"""

from __future__ import annotations

from typing import Any


def _format_cross_cycle_table(table: object) -> list[dict[str, str]]:
    """把三周期表转成 md 模板友好结构。"""
    if not isinstance(table, dict):
        return []
    layers = (
        ("long", "长周期（60-120日）", "赔率"),
        ("medium", "中周期（20日）", "中枢"),
        ("short", "短周期（5-10日）", "胜率"),
    )
    rows: list[dict[str, str]] = []
    for key, layer, role in layers:
        item = table.get(key)
        if not isinstance(item, dict):
            rows.append({"layer": layer, "readings": "-", "role": role})
            continue
        if key == "long":
            readings = (
                f"慢温 {_value_text(item.get('slow_temperature'))}；"
                f"60日扩散 {_percent_text(item.get('diffusion_60d_share'))}"
            )
        elif key == "medium":
            readings = (
                f"综合 {_value_text(item.get('composite'))}；背离 {_value_text(item.get('divergence'))}"
                f"（{item.get('divergence_level') or '-'}）"
            )
        else:
            readings = (
                f"短线5d {_value_text(item.get('short_term_5d'))}；10d {_value_text(item.get('short_term_10d'))}"
                f"；外盘 {item.get('external') or '-'}"
            )
        rows.append({"layer": layer, "readings": readings, "role": role})
    return rows


def _format_trajectory(trajectory: object) -> str:
    if not isinstance(trajectory, dict) or not trajectory:
        return "历史索引缺失，轨迹修正未启用。"
    parts = []
    if trajectory.get("divergence_transition"):
        parts.append(f"背离迁移 {trajectory['divergence_transition']}")
    if trajectory.get("d5_composite_direction"):
        direction = {
            "up": "连续上行",
            "down": "连续下行",
            "flat": "基本走平",
            "insufficient": "数据不足",
        }.get(str(trajectory["d5_composite_direction"]), str(trajectory["d5_composite_direction"]))
        parts.append(f"近5日综合温度 {direction}")
    if trajectory.get("slow_5d_delta_pp") is not None:
        parts.append(f"慢温5日变化 {trajectory['slow_5d_delta_pp']:+.2f}pp")
    return "；".join(parts) if parts else "无可用轨迹事实。"


def _format_score_parts(cross_cycle: dict[str, Any]) -> dict[str, list[str]]:
    """把 S/O 分项转成 md 模板友好的文本列表。"""
    result: dict[str, list[str]] = {"win": [], "odds": []}
    for key, label in (("win", "胜率环境"), ("odds", "赔率环境")):
        parts = cross_cycle.get(f"{key}_parts")
        if not isinstance(parts, dict) or not parts:
            result[key] = [f"{label}分项缺失。"]
            continue
        result[key] = [
            f"{name} {value:+.0f}"
            for name, value in parts.items()
            if isinstance(value, int | float)
        ]
        if not result[key]:
            result[key] = [f"{label}无有效分项。"]
    return result


def _format_extreme_windows(extreme_state: dict[str, Any]) -> list[dict[str, str]]:
    """把极端状态窗口转成 md 模板友好的行。"""
    if not isinstance(extreme_state, dict) or not extreme_state:
        return []
    rows: list[dict[str, str]] = []
    for key, name in (
        ("hot_window", "高温窗口"),
        ("frozen_window", "冰点窗口"),
        ("crowded_window", "拥挤窗口"),
    ):
        item = extreme_state.get(key)
        if not isinstance(item, dict):
            continue
        triggered = bool(item.get("triggered"))
        if key == "hot_window":
            detail = f"综合 {_value_text(item.get('composite'))}，阈值 {_value_text(item.get('threshold'))}"
        elif key == "frozen_window":
            detail = (
                f"综合 {_value_text(item.get('composite'))}（冰点背离 "
                f"{'是' if item.get('ice_divergence') else '否'}），阈值 {_value_text(item.get('threshold'))}"
            )
        else:
            detail = f"{item.get('crowded_count', 0)} 个行业（{'、'.join(item.get('crowded_industries') or [])}）"
        rows.append(
            {
                "name": name,
                "status": "触发" if triggered else "未触发",
                "detail": detail,
            }
        )
    return rows


def _format_rows(rows: object) -> list[dict[str, str]]:
    if not isinstance(rows, list):
        return []
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        result.append(
            {
                "industry_name": str(row.get("industry_name") or row.get("industry_code") or ""),
                "structure_score": _value_text(row.get("structure_score")),
                "return_20d": _percent_text(row.get("return_20d")),
                "return_60d": _percent_text(row.get("return_60d")),
                "crowding_temperature": _value_text(row.get("crowding_temperature")),
                "tcr": _percent_text(row.get("tcr")),
                "fund_flow_score": _value_text(row.get("fund_flow_score")),
                "tags": str(row.get("tags") or ""),
                "reason": str(row.get("reason") or ""),
            }
        )
    return result


def _format_risk_gates(gates: object) -> list[dict[str, str]]:
    if not isinstance(gates, list):
        return []
    result = []
    for gate in gates:
        if not isinstance(gate, dict):
            continue
        result.append(
            {
                "title": str(gate.get("title") or ""),
                "status": str(gate.get("status_label") or gate.get("status") or ""),
                "facts": str(gate.get("facts_text") or "-"),
                "message": str(gate.get("message") or ""),
                "action": str(gate.get("action") or ""),
            }
        )
    return result


def _format_funding_health(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {
            "status": "资料不足",
            "main_flow_label": "主力大单净流入占比",
            "main_flow": "-",
            "cumulative_flow": "-",
            "super_large_flow": "-",
            "margin_buy": "-",
            "margin_growth20": "-",
            "margin_growth60": "-",
            "margin_penetration": "-",
            "margin_penetration_percentile": "-",
            "action": "补齐资金与两融事实。",
            "note": "-",
        }
    return {
        "status": str(value.get("status_label") or value.get("status") or "资料不足"),
        "main_flow_label": (
            "主力大单净流入占比"
            if value.get("main_large_order_net_inflow_share_source")
            == "main_large_order_net_inflow_share"
            else "主力净流入代理占比"
        ),
        "main_flow": _ratio_percent_text(value.get("main_large_order_net_inflow_share")),
        "cumulative_flow": _ratio_percent_text(value.get("main_money_net_inflow_share_20d_cum")),
        "super_large_flow": _ratio_percent_text(value.get("super_large_net_inflow_share")),
        "margin_buy": _ratio_percent_text(value.get("margin_buy_share")),
        "margin_growth20": _ratio_percent_text(value.get("margin_balance_growth_20d")),
        "margin_growth60": _ratio_percent_text(value.get("margin_balance_growth_60d")),
        "margin_penetration": _ratio_percent_text(value.get("margin_penetration")),
        "margin_penetration_percentile": _value_text(
            value.get("margin_penetration_percentile_1250d")
        ),
        "action": str(value.get("action") or "-"),
        "note": str(value.get("note") or "-"),
    }


def _breadth_text(count: object, total: object) -> str:
    count_text = _value_text(count)
    total_text = _value_text(total)
    return "-" if count_text == "-" else f"{count_text}/{total_text}"


def _percent_text(value: object) -> str:
    numeric = _as_float(value)
    return "-" if numeric is None else f"{numeric:.2f}%"


def _ratio_percent_text(value: object) -> str:
    numeric = _as_float(value)
    return "-" if numeric is None else f"{numeric * 100:.2f}%"


def _value_text(value: object) -> str:
    numeric = _as_float(value)
    return "-" if numeric is None else f"{numeric:.2f}"


def _nested(value: object, first: str, second: str) -> object:
    if not isinstance(value, dict):
        return None
    return value.get(first, {}).get(second) if isinstance(value.get(first), dict) else None


def _as_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, int | float | str):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "_as_float",
    "_breadth_text",
    "_format_cross_cycle_table",
    "_format_extreme_windows",
    "_format_funding_health",
    "_format_risk_gates",
    "_format_rows",
    "_format_score_parts",
    "_format_trajectory",
    "_nested",
    "_percent_text",
    "_ratio_percent_text",
    "_value_text",
]
