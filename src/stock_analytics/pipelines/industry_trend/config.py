"""申万行业产业趋势跟踪管线配置。

产业趋势跟踪与「行业轮动」是两套独立体系：
- 行业轮动：A 股内部截面矛盾（动量/剪刀差/拥挤度），高频博弈；
- 产业趋势跟踪：周期尺度（季度/半年）全球资本开支方向的承接与确认。

产业趋势量化框架（深研线簇·产业腿激活 × 财报滞后验证 × 动量兜底）：
1. 选景气 = 深研线簇（产业腿激活）+ 无腿动量兜底：有产业供需腿行业用剪刀差 LONG + DOI 激活入选并择时（半导体完整实证，化工/计算机有腿待推广）；无腿行业用 `return_60d` 动量 Top3 + 估值/组合防守门（滞后，不宣称前瞻）；现实景气（prosperity/crowding 面板列）仅事后确认，不参与实盘选股；
2. 财报滞后验证 · 量价齐升 supply_demand_score：公司经营与财报是滞后数据，仅事后验证供需逻辑是否兑现，不作前瞻选股；
3. 财报滞后验证 · 毛利率扩张 bargaining_score：仅事后验证定价权/盈利质量，不作前瞻选股；
4. 全球方向 direction_score：仅作可选加权与拐点预警参考，不作判定层（数据现状记录）；
5. 真前瞻在产业供需剪刀差（半导体 270100 见 framework_semiconductor.md），深研线簇逐一建腿，本管线提供公共面板不重复行业专属实现。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = "config/analytics/industry_trend_tracking.yaml"

# 默认因子权重：精确对齐已验证 milestone（现实景气 2/3 + 拥挤度防守 1/3）。
# 财报滞后验证（supply_demand/bargaining）与全球方向（direction）因子默认权重 0：财报层不作前瞻选股，数据/调优后激活。
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
    direction_defensive_gate: bool = True  # 因子层防守门开关（对比实验用）

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
        direction_defensive_gate=bool(payload.get("direction_defensive_gate", True)),
    )


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_WEIGHTS",
    "IndustryTrendConfig",
    "load_industry_trend_config",
]
