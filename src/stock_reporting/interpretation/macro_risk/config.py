"""宏观风控研报配置加载与分段打分辅助。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config/reporting/macro_risk_thresholds.yaml"


def load_reporting_config(config_path: Path | str | None = None) -> dict[str, Any]:
    """读取研报评级与定性话术配置文件。"""
    cfg_p = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
    if not cfg_p.is_file():
        raise FileNotFoundError(f"宏观风控研报配置不存在: {cfg_p}")

    payload = yaml.safe_load(cfg_p.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"宏观风控研报配置必须是映射对象: {cfg_p}")
    if not isinstance(payload.get("dimensions"), dict):
        raise TypeError(f"宏观风控研报配置缺少 dimensions 映射: {cfg_p}")
    if not isinstance(payload.get("indices"), dict):
        raise TypeError(f"宏观风控研报配置缺少 indices 映射: {cfg_p}")
    return payload


def safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def index_threshold(
    cfg: dict[str, Any],
    index_key: str,
    threshold_key: str,
    default: float,
) -> float:
    """读取双轨指数阈值，配置项缺失或格式异常时使用默认值。"""
    raw = cfg.get("indices", {}).get(index_key, {}).get(threshold_key, default)
    return safe_float(raw, default)


def grade_dim(
    dim_key: str,
    val: float | None,
    cfg: dict[str, Any],
    special_vars: dict[str, float | None] | None = None,
) -> tuple[str, str, str]:
    """根据 YAML 分段配置打分并匹配话术。"""
    dim_cfg = cfg.get("dimensions", {}).get(dim_key, {})
    if val is None:
        missing = dim_cfg.get("missing", {})
        return (
            missing.get("grade", "数据暂缺"),
            missing.get("icon", "⚪"),
            missing.get("comment", "历史数据不足"),
        )

    special_cases = dim_cfg.get("special_cases", [])
    if special_cases and special_vars:
        for sc in special_cases:
            cond = sc.get("condition")
            if cond == "divergence_and_flow":
                div_s = special_vars.get("div_score")
                if div_s is None:
                    continue
                div_min = safe_float(sc.get("div_score_min"), 85.0)
                val_min = safe_float(sc.get("val_min"), 65.0)
                # dim_flow 是三成分均值，主力/综合流向可能把筹码背离度稀释到中枢；
                # 背离度自身触及极值（div_override_min）时仍判背离，
                # 避免「流向平稳」掩盖单因子极值。
                override = sc.get("div_override_min")
                extreme_div = override is not None and div_s >= safe_float(override, 101.0)
                if div_s >= div_min and (val >= val_min or extreme_div):
                    return sc["grade"], sc["icon"], sc["comment"]

    tiers = dim_cfg.get("tiers", [])
    default_tier: dict[str, str] = {"grade": "正常", "icon": "⚪", "comment": "处于正常区间"}
    for t in tiers:
        if t.get("default"):
            default_tier = t
            continue
        if "min" in t and val >= float(t["min"]):
            return t["grade"], t["icon"], t["comment"]
        if "max" in t and val <= float(t["max"]):
            return t["grade"], t["icon"], t["comment"]

    return (
        default_tier.get("grade", "正常"),
        default_tier.get("icon", "⚪"),
        default_tier.get("comment", "处于正常区间"),
    )


__all__ = ["grade_dim", "index_threshold", "load_reporting_config", "safe_float"]
