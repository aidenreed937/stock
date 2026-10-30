"""半导体周期各历史时期需求驱动配置加载器与时代路由。

对应配置文件：config/industry/semiconductor/demand_drivers.yaml
将硬编码的"云 CapEx(需求,领先)"解耦为时代配置驱动：
根据分析年份或截面时期，动态路由对应时期的主导需求驱动、领先指标与传导链条。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_DEMAND_DRIVERS_PATH = "config/industry/semiconductor/demand_drivers.yaml"


@dataclass(frozen=True, slots=True)
class LeadingIndicatorConfig:
    """时代领先需求指标。"""

    name: str
    indicator_type: str
    source_proxy: str
    lead_time: str
    description: str


@dataclass(frozen=True, slots=True)
class EraConfig:
    """半导体历史时代需求驱动配置。"""

    id: str
    name: str
    start_year: int
    end_year: int
    primary_demand_driver: str
    transmission_chain: str
    leading_indicators: tuple[LeadingIndicatorConfig, ...]
    key_chips: tuple[str, ...]
    supply_bottleneck: str
    inflection_triggers_peak: tuple[str, ...]
    inflection_triggers_trough: tuple[str, ...]

    def matches_year(self, year: int) -> bool:
        """判断某年份是否落在当前时代区间内。"""
        return self.start_year <= year <= self.end_year


@dataclass(frozen=True, slots=True)
class DemandDriversConfig:
    """分时期需求驱动全局配置。"""

    schema_version: int
    title: str
    description: str
    eras: tuple[EraConfig, ...]
    default_cross_cycle: dict[str, Any]

    def get_era_by_year(self, year: int) -> EraConfig | None:
        """根据年份匹配对应的时代需求驱动配置。"""
        for era in self.eras:
            if era.matches_year(year):
                return era
        return None


def _parse_indicators(raw_indicators: Any) -> tuple[LeadingIndicatorConfig, ...]:
    if not isinstance(raw_indicators, list):
        return ()
    out: list[LeadingIndicatorConfig] = []
    for item in raw_indicators:
        if not isinstance(item, dict):
            continue
        lead_time = ""
        if "lead_time_quarters" in item:
            lead_time = f"{item['lead_time_quarters']} 季度"
        elif "lead_time_months" in item:
            lead_time = f"{item['lead_time_months']} 个月"

        out.append(
            LeadingIndicatorConfig(
                name=str(item.get("name", "")),
                indicator_type=str(item.get("indicator_type", "")),
                source_proxy=str(item.get("source_proxy", "")),
                lead_time=lead_time,
                description=str(item.get("description", "")),
            )
        )
    return tuple(out)


def _parse_str_tuple(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(str(x) for x in raw if isinstance(x, str))


def load_demand_drivers_config(
    config_path: Path | str = DEFAULT_DEMAND_DRIVERS_PATH,
) -> DemandDriversConfig:
    """从 YAML 读取半导体周期分时期需求驱动配置。"""
    path = Path(config_path)
    if not path.exists():
        return DemandDriversConfig(
            schema_version=1,
            title="",
            description="",
            eras=(),
            default_cross_cycle={},
        )

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return DemandDriversConfig(
            schema_version=1,
            title="",
            description="",
            eras=(),
            default_cross_cycle={},
        )

    if not isinstance(payload, dict):
        return DemandDriversConfig(
            schema_version=1,
            title="",
            description="",
            eras=(),
            default_cross_cycle={},
        )

    eras_out: list[EraConfig] = []
    raw_eras = payload.get("eras", [])
    if isinstance(raw_eras, list):
        for raw_era in raw_eras:
            if not isinstance(raw_era, dict):
                continue
            triggers = raw_era.get("inflection_triggers", {})
            peak_triggers = triggers.get("peak", []) if isinstance(triggers, dict) else []
            trough_triggers = triggers.get("trough", []) if isinstance(triggers, dict) else []

            eras_out.append(
                EraConfig(
                    id=str(raw_era.get("id", "")),
                    name=str(raw_era.get("name", "")),
                    start_year=int(raw_era.get("start_year", 0)),
                    end_year=int(raw_era.get("end_year", 9999)),
                    primary_demand_driver=str(raw_era.get("primary_demand_driver", "")),
                    transmission_chain=str(raw_era.get("transmission_chain", "")),
                    leading_indicators=_parse_indicators(raw_era.get("leading_indicators")),
                    key_chips=_parse_str_tuple(raw_era.get("key_chips")),
                    supply_bottleneck=str(raw_era.get("supply_bottleneck", "")),
                    inflection_triggers_peak=_parse_str_tuple(peak_triggers),
                    inflection_triggers_trough=_parse_str_tuple(trough_triggers),
                )
            )

    return DemandDriversConfig(
        schema_version=int(payload.get("schema_version", 1)),
        title=str(payload.get("title", "")),
        description=str(payload.get("description", "")),
        eras=tuple(eras_out),
        default_cross_cycle=payload.get("default_cross_cycle", {})
        if isinstance(payload.get("default_cross_cycle"), dict)
        else {},
    )
