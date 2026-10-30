"""半导体深研线：供需剪刀差 + 结构性确认腿 管线配置。

数据腿语义对齐 `scripts/industry_direction_map.py` 中已验证的半导体腿部实现
（`build_semi_demand_direction` / `build_semi_equipment_direction` /
`build_semi_structural_direction` / `build_semiconductor_structural_legs`）：
- 剪刀差 = demand(T read + SIA sales 均值合成) − supply(SEAJ 设备出货)；
- 结构性腿 = ai_capex(云 CapEx 季度)，独立分组不入剪刀差。
全部按 release_date 生效、0-100 滚动分位、日频前向填充（无前视）。

术语约定：本层（stock_analytics）产出的都是**特征（feature / 候选因子）**——由产业数据
算出的 0-100 分位序列，是回测的输入；**不是已验证的有效因子**。因子的有效性（IC/回测/
敏感性）由 stock_strategy 验证层确认。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = "config/analytics/semiconductor_legs.yaml"


@dataclass(frozen=True, slots=True)
class MonthlySource:
    """按月频（release_date 生效、36 月滚动分位）构建的实物流量源。"""

    source: str
    column: str
    window_months: int = 36


@dataclass(frozen=True, slots=True)
class QuarterlySource:
    """按季频（release_date 生效、12 季滚动分位）构建的实物流量源。"""

    source: str
    column: str
    window_quarters: int = 12


@dataclass(frozen=True, slots=True)
class ScissorsConfig:
    """剪刀差腿配置：demand 多源均值合成，supply 单源。"""

    demand_sources: tuple[MonthlySource, ...]
    supply: MonthlySource


@dataclass(frozen=True, slots=True)
class StructuralConfig:
    """结构性确认腿配置（leg_type 独立分组，不入剪刀差）。"""

    ai_capex: QuarterlySource
    legs: dict[str, QuarterlySource] | None = None


@dataclass(frozen=True, slots=True)
class SemiconductorLegsConfig:
    """半导体深研线建腿管线配置。"""

    schema_version: int = 1
    title: str = "半导体深研线供需剪刀差与结构性确认腿"
    artifact_root: str = "data/analytics/semiconductor"
    calendar_mart: str = "global_macro_daily"
    industry_codes: tuple[str, ...] = ("270100",)
    scissors: ScissorsConfig | None = None
    structural: StructuralConfig | None = None
    neutral_score: float = 50.0


def _as_str_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(v) for v in value if isinstance(v, str))


def _load_demand_sources(raw: Any) -> tuple[MonthlySource, ...]:
    if not isinstance(raw, list):
        return ()
    out: list[MonthlySource] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        src = str(item.get("source", "")).strip()
        col = str(item.get("column", "")).strip()
        if not src or not col:
            continue
        out.append(
            MonthlySource(
                source=src,
                column=col,
                window_months=max(int(item.get("window_months", 36)), 1),
            )
        )
    return tuple(out)


def load_semiconductor_legs_config(
    config_path: Path | str = DEFAULT_CONFIG_PATH,
) -> SemiconductorLegsConfig:
    """从 YAML 读取半导体建腿管线配置；文件缺失或不可解析时用全默认值。"""
    path = Path(config_path)
    if not path.exists():
        return SemiconductorLegsConfig()

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return SemiconductorLegsConfig()
    if not isinstance(payload, dict):
        return SemiconductorLegsConfig()

    def _number(key: str, default: float) -> float:
        try:
            return float(payload.get(key, default))
        except (TypeError, ValueError):
            return default

    def _integer(key: str, default: int) -> int:
        try:
            return int(payload.get(key, default))
        except (TypeError, ValueError):
            return default

    scissors = _parse_scissors(payload.get("scissors"))
    structural = _parse_structural(payload.get("structural"))

    return SemiconductorLegsConfig(
        schema_version=_integer("schema_version", 1),
        title=str(payload.get("title", "半导体深研线供需剪刀差与结构性确认腿")),
        artifact_root=str(payload.get("artifact_root", "data/analytics/semiconductor")),
        calendar_mart=str(payload.get("calendar_mart", "global_macro_daily")),
        industry_codes=_as_str_list(payload.get("industry_codes")) or ("270100",),
        scissors=scissors,
        structural=structural,
        neutral_score=_number("neutral_score", 50.0),
    )


def _parse_scissors(raw: Any) -> ScissorsConfig | None:
    if not isinstance(raw, dict):
        return None
    demand_raw = raw.get("demand_sources")
    demand_sources = _load_demand_sources(demand_raw)
    if not demand_sources:
        return None

    supply_raw = raw.get("supply")
    if not isinstance(supply_raw, dict):
        return None
    src = str(supply_raw.get("source", "")).strip()
    col = str(supply_raw.get("column", "")).strip()
    if not src or not col:
        return None
    supply = MonthlySource(
        source=src,
        column=col,
        window_months=max(int(supply_raw.get("window_months", 36)), 1),
    )
    return ScissorsConfig(demand_sources=demand_sources, supply=supply)


def _parse_structural(raw: Any) -> StructuralConfig | None:
    if not isinstance(raw, dict):
        return None

    parsed_legs: dict[str, QuarterlySource] = {}
    for key, val in raw.items():
        if not isinstance(val, dict):
            continue
        src = str(val.get("source", "")).strip()
        col = str(val.get("column", "")).strip()
        if not (src and col):
            continue
        parsed_legs[key] = QuarterlySource(
            source=src,
            column=col,
            window_quarters=max(int(val.get("window_quarters", 12)), 1),
        )

    if not parsed_legs:
        return None

    ai_capex = parsed_legs.get("ai_capex") or next(iter(parsed_legs.values()))

    return StructuralConfig(
        ai_capex=ai_capex,
        legs=parsed_legs,
    )


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "MonthlySource",
    "QuarterlySource",
    "ScissorsConfig",
    "SemiconductorLegsConfig",
    "StructuralConfig",
    "load_semiconductor_legs_config",
]
