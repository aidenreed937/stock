"""申万行业产业趋势跟踪管线配置。

产业趋势跟踪与「行业轮动」是两套独立体系：
- 行业轮动：A 股内部截面矛盾（动量/剪刀差/拥挤度），高频博弈；
- 产业趋势跟踪：周期尺度（季度/半年）全球资本开支方向的承接与确认。

三层共振框架（方向 × 供需 × 议价权）：
1. 方向层 direction_score：全球资本开支/出货方向（数据缺口，默认中性）；
2. 供需层 supply_demand_score：量价齐升（营收 + 净利双正）才是真需求驱动；
3. 议价权层 bargaining_score：量价齐升门内的毛利率扩张（净利增速 > 营收增速）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = "config/analytics/industry_trend_tracking.yaml"

# 默认因子权重：精确对齐已验证 milestone（现实景气 2/3 + 拥挤度防守 1/3）。
# 三层框架因子（direction/supply_demand/bargaining）默认权重 0，数据/调优后激活。
DEFAULT_WEIGHTS: dict[str, float] = {
    "direction": 0.0,
    "supply_demand": 0.0,
    "bargaining": 0.0,
    "prosperity": 2.0 / 3.0,
    "crowding": 1.0 / 3.0,
}


@dataclass(frozen=True, slots=True)
class IndustryTrendConfig:
    """产业趋势跟踪因子面板配置。"""

    schema_version: int = 1
    title: str = "申万行业产业趋势跟踪因子面板"
    artifact_root: str = "data/analytics/industry_trend"
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    trend_lookback: int = 63  # 环比改善窗口（季度交易日数）
    supply_contract_penalty: float = 20.0  # 供给收缩（营收负、净利正）质量分
    double_negative_penalty: float = 10.0  # 双负（营收负、净利负）质量分
    bargaining_neutral: float = 30.0  # 量价齐升门外议价权中性分
    direction_neutral: float = 50.0  # 全球方向数据缺口时的中性分
    direction_high_threshold: float = 66.0  # 方向高位阈值（触发防守门）
    direction_risk_penalty: float = 20.0  # 方向高位 × 非量价齐升 的防守减分

    @property
    def weight_sum(self) -> float:
        return sum(self.weights.values())


def load_industry_trend_config(
    config_path: Path | str = DEFAULT_CONFIG_PATH,
) -> IndustryTrendConfig:
    """从 YAML 读取产业趋势跟踪配置；缺失时使用默认值。"""
    path = Path(config_path)
    if not path.exists():
        return IndustryTrendConfig()

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return IndustryTrendConfig()

    if not isinstance(payload, dict):
        return IndustryTrendConfig()

    weights = dict(DEFAULT_WEIGHTS)
    raw_weights = payload.get("weights")
    if isinstance(raw_weights, dict):
        for key, value in raw_weights.items():
            if key in weights:
                weights[key] = float(value)

    def _number(key: str, default: float) -> float:
        value: Any = payload.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _integer(key: str, default: int) -> int:
        value: Any = payload.get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    return IndustryTrendConfig(
        schema_version=_integer("schema_version", 1),
        title=str(payload.get("title", "申万行业产业趋势跟踪因子面板")),
        artifact_root=str(payload.get("artifact_root", "data/analytics/industry_trend")),
        weights=weights,
        trend_lookback=max(_integer("trend_lookback", 63), 1),
        supply_contract_penalty=_number("supply_contract_penalty", 20.0),
        double_negative_penalty=_number("double_negative_penalty", 10.0),
        bargaining_neutral=_number("bargaining_neutral", 30.0),
        direction_neutral=_number("direction_neutral", 50.0),
        direction_high_threshold=_number("direction_high_threshold", 66.0),
        direction_risk_penalty=_number("direction_risk_penalty", 20.0),
    )


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_WEIGHTS",
    "IndustryTrendConfig",
    "load_industry_trend_config",
]
