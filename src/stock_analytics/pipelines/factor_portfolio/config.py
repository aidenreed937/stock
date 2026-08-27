"""因子组合分数管线配置。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Self

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config/analytics/factor_portfolio.yaml"


@dataclass(frozen=True, slots=True)
class FactorPortfolioConfig:
    """因子组合分数管线配置。"""

    schema_version: int = 1
    title: str = "因子组合分数报告"
    artifact_root: str = "data/analytics/factor_portfolio"
    window_days: int = 1095
    price_col: str = "close"
    rebalance_days: int = 5
    top_n: int = 10
    min_valid_factors: int = 3
    min_trade_days: int = 200
    factor_research_dir: str | None = None
    factor_whitelist: tuple[str, ...] = ()

    def with_artifact_root(self, output_root: Path | str | None) -> Self:
        """覆盖产物根目录（CLI --output-root）。"""
        if output_root is None:
            return self
        return replace(self, artifact_root=str(Path(output_root)))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        """从 YAML 映射构造配置。"""
        whitelist = tuple(str(f) for f in data.get("factor_whitelist", ()))
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            title=str(data.get("title", "因子组合分数报告")),
            artifact_root=str(data.get("artifact_root", "data/analytics/factor_portfolio")),
            window_days=int(data.get("window_days", 1095)),
            price_col=str(data.get("price_col", "close")),
            rebalance_days=int(data.get("rebalance_days", 5)),
            top_n=int(data.get("top_n", 10)),
            min_valid_factors=int(data.get("min_valid_factors", 3)),
            min_trade_days=int(data.get("min_trade_days", 200)),
            factor_research_dir=data.get("factor_research_dir"),
            factor_whitelist=whitelist,
        )


def load_factor_portfolio_config(
    config_path: Path | str = DEFAULT_CONFIG_PATH,
) -> FactorPortfolioConfig:
    """加载因子组合分数管线配置。"""
    with open(config_path, encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    section = raw.get("factor_portfolio", raw)
    if not isinstance(section, Mapping):
        raise ValueError(f"配置缺少 factor_portfolio 节: {config_path}")
    return FactorPortfolioConfig.from_mapping(section)


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "FactorPortfolioConfig",
    "load_factor_portfolio_config",
]
