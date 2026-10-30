"""光伏设备（630500）周期状态与防守信号特征面板 管线配置。

数据语义对齐 `scripts/industry_solar_*.py` 已验证实现（cycle_position/warning_card/
price_gate_combo/profit_turn_ext）：
- cycle_state ：产能周期四态（上行/过剩/下行/底部右侧），产业层唯一季度前瞻危险源；
- fin_defense ：成分股聚合净利 TTM 同比 <0（恶化认定，滞后防守腿）；
- price_dd    ：组件周价 52 周高点回撤 %（「确认恶化后」尾部防守补丁，非前瞻）。
全部按 release_date/披露日生效、日频前向填充（无前视），T+1 由权重层 shift(1)。

术语约定：本层（stock_analytics）产出的都是**特征（feature / 状态）**——回测/决策的输入；
**不是已验证的有效因子**。有效性由 stock_strategy 验证层确认。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = "config/analytics/photovoltaic_legs.yaml"


@dataclass(frozen=True, slots=True)
class CycleStateConfig:
    """产能周期状态门参数（对齐 cycle_position._state_row）。"""

    glut_yoy_threshold: float = 0.30
    flood_months: int = 24
    high_util_threshold: float = 70.0
    low_util_threshold: float = 45.0
    util_chg_months: int = 6
    scissors_floor: float = -0.20


@dataclass(frozen=True, slots=True)
class FinDefenseConfig:
    """财报 TTM 防守门参数（对齐 profit_turn_ext pos 门）。"""

    net_negative_threshold: float = 0.0
    disclosure_q1: str = "04-30"
    disclosure_q2: str = "08-31"
    disclosure_q3: str = "10-31"


@dataclass(frozen=True, slots=True)
class PricePatchConfig:
    """价格回撤补丁参数（对齐 price_chain_layering）。"""

    price_col: str = "module_price_cny_watt"
    drawdown_weeks: int = 52
    gate_threshold: float = 20.0


@dataclass(frozen=True, slots=True)
class DefenseWeightConfig:
    """防守门权重映射（对齐 warning_card cycfn 口径）。"""

    hold: float = 1.0
    reduced: float = 0.25
    empty: float = 0.0


@dataclass(frozen=True, slots=True)
class PhotovoltaicLegsConfig:
    """光伏深研线建腿/状态管线配置。"""

    schema_version: int = 1
    title: str = "光伏设备 630500 周期状态与防守信号特征面板"
    artifact_root: str = "data/analytics/photovoltaic"
    calendar_mart: str = "global_macro_daily"
    industry_codes: tuple[str, ...] = ("630500",)
    cycle_state: CycleStateConfig | None = None
    fin_defense: FinDefenseConfig | None = None
    price_patch: PricePatchConfig | None = None
    lifecycle_weights: dict[str, float] | None = None
    defense_weight: DefenseWeightConfig | None = None
    neutral_score: float = 50.0


def _as_str_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(v) for v in value if isinstance(v, str))


def _as_number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_cycle_state(raw: Any) -> CycleStateConfig | None:
    if not isinstance(raw, dict):
        return None
    return CycleStateConfig(
        glut_yoy_threshold=_as_number(raw.get("glut_yoy_threshold"), 0.30),
        flood_months=_as_int(raw.get("flood_months"), 24),
        high_util_threshold=_as_number(raw.get("high_util_threshold"), 70.0),
        low_util_threshold=_as_number(raw.get("low_util_threshold"), 45.0),
        util_chg_months=_as_int(raw.get("util_chg_months"), 6),
        scissors_floor=_as_number(raw.get("scissors_floor"), -0.20),
    )


def _parse_fin_defense(raw: Any) -> FinDefenseConfig | None:
    if not isinstance(raw, dict):
        return None
    return FinDefenseConfig(
        net_negative_threshold=_as_number(raw.get("net_negative_threshold"), 0.0),
        disclosure_q1=str(raw.get("disclosure_q1", "04-30")),
        disclosure_q2=str(raw.get("disclosure_q2", "08-31")),
        disclosure_q3=str(raw.get("disclosure_q3", "10-31")),
    )


def _parse_price_patch(raw: Any) -> PricePatchConfig | None:
    if not isinstance(raw, dict):
        return None
    return PricePatchConfig(
        price_col=str(raw.get("price_col", "module_price_cny_watt")),
        drawdown_weeks=_as_int(raw.get("drawdown_weeks"), 52),
        gate_threshold=_as_number(raw.get("gate_threshold"), 20.0),
    )


def _parse_defense_weight(raw: Any) -> DefenseWeightConfig | None:
    if not isinstance(raw, dict):
        return None
    return DefenseWeightConfig(
        hold=_as_number(raw.get("hold"), 1.0),
        reduced=_as_number(raw.get("reduced"), 0.25),
        empty=_as_number(raw.get("empty"), 0.0),
    )


def _parse_lifecycle(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    return {
        "上行": _as_number(raw.get("上行"), 1.0),
        "过剩": _as_number(raw.get("过剩"), 0.0),
        "下行": _as_number(raw.get("下行"), 0.8),
        "底部右侧": _as_number(raw.get("底部右侧"), 0.5),
    }


def load_photovoltaic_legs_config(
    config_path: Path | str = DEFAULT_CONFIG_PATH,
) -> PhotovoltaicLegsConfig:
    """从 YAML 读取光伏建腿/状态管线配置；文件缺失或不可解析时用全默认值。"""
    path = Path(config_path)
    if not path.exists():
        return PhotovoltaicLegsConfig()

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return PhotovoltaicLegsConfig()
    if not isinstance(payload, dict):
        return PhotovoltaicLegsConfig()

    return PhotovoltaicLegsConfig(
        schema_version=_as_int(payload.get("schema_version"), 1),
        title=str(payload.get("title", "光伏设备 630500 周期状态与防守信号特征面板")),
        artifact_root=str(payload.get("artifact_root", "data/analytics/photovoltaic")),
        calendar_mart=str(payload.get("calendar_mart", "global_macro_daily")),
        industry_codes=_as_str_list(payload.get("industry_codes")) or ("630500",),
        cycle_state=_parse_cycle_state(payload.get("cycle_state")),
        fin_defense=_parse_fin_defense(payload.get("fin_defense")),
        price_patch=_parse_price_patch(payload.get("price_patch")),
        lifecycle_weights=_parse_lifecycle(payload.get("lifecycle_weights")),
        defense_weight=_parse_defense_weight(payload.get("defense_weight")),
        neutral_score=_as_number(payload.get("neutral_score"), 50.0),
    )


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "CycleStateConfig",
    "DefenseWeightConfig",
    "FinDefenseConfig",
    "PhotovoltaicLegsConfig",
    "PricePatchConfig",
    "load_photovoltaic_legs_config",
]
