"""熊市区间识别管线配置加载。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class BearRegimeConfig:
    """熊市识别双引擎阈值配置。"""

    # 引擎 1: 价格回撤
    drawdown_threshold: float = -0.20
    price_min_days: int = 60
    price_gap_buffer: int = 60

    # 引擎 2: 四低共振
    valuation_threshold: float = 30.0
    crowding_threshold: float = 30.0
    leverage_threshold: float = 40.0
    price_rank_threshold: float = 0.20  # 价格 250 日滚动分位低位阈值
    factor_score_min: int = 3
    factor_min_days: int = 60
    factor_gap_buffer: int = 10

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> BearRegimeConfig:
        d = dict(data or {})
        return cls(
            drawdown_threshold=float(d.get("drawdown_threshold", -0.20)),
            price_min_days=int(d.get("price_min_days", 60)),
            price_gap_buffer=int(d.get("price_gap_buffer", 60)),
            valuation_threshold=float(d.get("valuation_threshold", 30.0)),
            crowding_threshold=float(d.get("crowding_threshold", 30.0)),
            leverage_threshold=float(d.get("leverage_threshold", 40.0)),
            price_rank_threshold=float(d.get("price_rank_threshold", 0.20)),
            factor_score_min=int(d.get("factor_score_min", 3)),
            factor_min_days=int(d.get("factor_min_days", 60)),
            factor_gap_buffer=int(d.get("factor_gap_buffer", 10)),
        )


def load_bear_regime_config(
    config_path: Path | str = "config/analytics/bear_regime.yaml",
) -> BearRegimeConfig:
    """加载熊市识别管线配置。"""
    path = Path(config_path)
    if not path.exists():
        return BearRegimeConfig()
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return BearRegimeConfig.from_mapping(
        raw.get("bear_regime", {}) if isinstance(raw, dict) else None
    )


__all__ = ["BearRegimeConfig", "load_bear_regime_config"]
