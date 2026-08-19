"""投资者简报配置加载。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Self, cast

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config/analytics/investor_brief.yaml"


@dataclass(frozen=True, slots=True)
class InvestorBriefConfig:
    """投资者简报顶层配置。"""

    schema_version: int
    title: str
    artifact_root: Path
    market_temperature_root: Path
    industry_structure_root: Path
    max_candidate_industries: int = 5
    max_risk_industries: int = 5
    max_lagging_industries: int = 3

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        """从 YAML 字典构造配置对象。"""
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            title=str(data.get("title", "A 股投资者简报")),
            artifact_root=Path(str(data.get("artifact_root", "data/analytics/investor_brief"))),
            market_temperature_root=Path(
                str(data.get("market_temperature_root", "data/analytics/market_temperature"))
            ),
            industry_structure_root=Path(
                str(data.get("industry_structure_root", "data/analytics/industry_structure"))
            ),
            max_candidate_industries=int(data.get("max_candidate_industries", 5)),
            max_risk_industries=int(data.get("max_risk_industries", 5)),
            max_lagging_industries=int(data.get("max_lagging_industries", 3)),
        )

    def with_artifact_root(self, artifact_root: Path | str | None) -> Self:
        """返回覆盖产物根目录后的配置。"""
        if artifact_root is None:
            return self
        return replace(self, artifact_root=Path(artifact_root))


def load_investor_brief_config(
    config_path: Path | str = DEFAULT_CONFIG_PATH,
) -> InvestorBriefConfig:
    """加载投资者简报 YAML 配置。"""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"投资者简报配置不存在: {path}")
    with path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file)
    root = _as_mapping(raw, "investor_brief.yaml")
    data = _as_mapping(root.get("investor_brief"), "investor_brief")
    return InvestorBriefConfig.from_mapping(data)


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} 必须是映射对象")
    return cast("Mapping[str, Any]", value)
