"""外盘风险配置模型。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Self, cast


@dataclass(frozen=True, slots=True)
class ExternalShockRuleConfig:
    """单个外盘单日冲击规则。"""

    metric_id: str
    operator: str
    threshold: float
    label: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        """从 YAML 字典构造外盘冲击规则。"""
        operator = str(data.get("operator", "gte"))
        if operator not in {"gte", "gt", "lte", "lt", "eq"}:
            raise ValueError(f"不支持的外盘冲击比较符: {operator}")
        metric_id = str(data["metric_id"])
        return cls(
            metric_id=metric_id,
            operator=operator,
            threshold=float(data["threshold"]),
            label=str(data.get("label", metric_id)),
        )


def _default_external_shock_rules() -> tuple[ExternalShockRuleConfig, ...]:
    return (
        ExternalShockRuleConfig("macro_sp500_1d_return", "lte", -0.01, "标普500"),
        ExternalShockRuleConfig("macro_nasdaq_1d_return", "lte", -0.01, "纳斯达克"),
        ExternalShockRuleConfig("macro_sox_1d_return", "lte", -0.03, "费城半导体"),
        ExternalShockRuleConfig("macro_vix_1d_change", "gte", 0.03, "VIX"),
        ExternalShockRuleConfig("macro_us_10y_1d_change", "gte", 0.05, "美债10年期收益率"),
    )


@dataclass(frozen=True, slots=True)
class ExternalShockConfig:
    """外盘单日冲击检测配置。"""

    min_trigger_count: int = 1
    rules: tuple[ExternalShockRuleConfig, ...] = field(
        default_factory=_default_external_shock_rules
    )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> Self:
        """从 YAML 字典构造外盘单日冲击配置。"""
        if data is None:
            return cls()
        raw_rules = data.get("rules")
        rules = (
            _default_external_shock_rules()
            if raw_rules is None
            else tuple(
                ExternalShockRuleConfig.from_mapping(_as_mapping(item, "external_shock_rule"))
                for item in _as_sequence(raw_rules, "external_risk.shock.rules")
            )
        )
        min_trigger_count = int(data.get("min_trigger_count", 1))
        if min_trigger_count < 1:
            raise ValueError("external_risk.shock.min_trigger_count 必须大于等于 1")
        return cls(min_trigger_count=min_trigger_count, rules=rules)


@dataclass(frozen=True, slots=True)
class ExternalRiskConfig:
    """外盘背景压力与单日冲击配置。"""

    background_pressure_metric_id: str = "macro_external_pressure_temperature"
    environment_temperature_metric_id: str = "macro_external_environment_temperature"
    shock: ExternalShockConfig = field(default_factory=ExternalShockConfig)
    transmission_status_on_shock: str = "pending_next_ashare_session"
    transmission_status_without_shock: str = "not_applicable"
    transmission_status_insufficient: str = "insufficient_external_data"
    message_on_shock: str = "外盘短线冲击已出现，等待下一交易日 A 股确认。"
    message_without_shock: str = "当前未检测到配置阈值触发的外盘短线冲击。"
    message_insufficient: str = "外盘单日冲击数据不足，暂不能判断。"
    observation_focus: tuple[str, ...] = (
        "科技成长",
        "两融",
        "主力净流入",
        "上涨行业扩散",
    )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> Self:
        """从 YAML 字典构造外盘风险配置。"""
        if data is None:
            return cls()
        raw_focus = data.get("observation_focus")
        return cls(
            background_pressure_metric_id=str(
                data.get("background_pressure_metric_id", "macro_external_pressure_temperature")
            ),
            environment_temperature_metric_id=str(
                data.get(
                    "environment_temperature_metric_id",
                    "macro_external_environment_temperature",
                )
            ),
            shock=ExternalShockConfig.from_mapping(
                _as_mapping(data.get("shock"), "external_risk.shock")
                if data.get("shock") is not None
                else None
            ),
            transmission_status_on_shock=str(
                data.get("transmission_status_on_shock", "pending_next_ashare_session")
            ),
            transmission_status_without_shock=str(
                data.get("transmission_status_without_shock", "not_applicable")
            ),
            transmission_status_insufficient=str(
                data.get("transmission_status_insufficient", "insufficient_external_data")
            ),
            message_on_shock=str(
                data.get("message_on_shock", "外盘短线冲击已出现，等待下一交易日 A 股确认。")
            ),
            message_without_shock=str(
                data.get("message_without_shock", "当前未检测到配置阈值触发的外盘短线冲击。")
            ),
            message_insufficient=str(
                data.get("message_insufficient", "外盘单日冲击数据不足，暂不能判断。")
            ),
            observation_focus=(
                cls().observation_focus
                if raw_focus is None
                else tuple(
                    str(item) for item in _as_sequence(raw_focus, "external_risk.observation_focus")
                )
            ),
        )


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} 必须是映射对象")
    return cast("Mapping[str, Any]", value)


def _as_sequence(value: Any, name: str) -> Sequence[Any]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise TypeError(f"{name} 必须是列表")
    sequence_value: Sequence[Any] = value
    return sequence_value
