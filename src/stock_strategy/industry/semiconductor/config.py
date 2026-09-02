"""半导体深研线回测/IC 验证研究配置。

把研究的结构性参数（目标行业、窗口、样本外起点、f60、IC 验证腿、指标年化、防守阈值）
从代码提为配置驱动（``config/strategy/semiconductor_research.yaml``），
默认值对齐 methodology 定稿阈值（framework_semiconductor.md，阈值不重炒纪律）。

术语约定：本层（stock_strategy）是**验证层**——消费 stock_analytics 产出的
特征（feature / 候选因子），通过 IC / 回测 / 敏感性扫描**验证其是否为有效因子（factor）**。
本层不产生新特征。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = "config/strategy/semiconductor_research.yaml"


@dataclass(frozen=True, slots=True)
class DefenseConfig:
    """事件状态机防守门阈值（methodology 定稿值）。"""

    scissors_lt: float = 0.0
    doi_ge: float = 70.0
    drawdown_weight: float = 0.3


@dataclass(frozen=True, slots=True)
class SemiconductorResearchConfig:
    """半导体深研线研究配置。"""

    schema_version: int = 1
    title: str = "半导体深研线回测/IC 验证研究配置"
    output_dir: str = "data/strategy/semiconductor"
    industry: str = "270100"
    start_date: date = date(2018, 1, 1)
    oos_start: date = date(2022, 1, 1)
    fwd_horizon: int = 60
    ic_min_samples: int = 30
    ic_legs: tuple[str, ...] = ("ai_capex_score", "storage_score")
    trading_days: int = 252
    defense: DefenseConfig = field(default_factory=DefenseConfig)


def _parse_date(value: Any, default: date) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return default


def _parse_str_list(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, list):
        return default
    items = tuple(str(v) for v in value if isinstance(v, str))
    return items or default


def load_semiconductor_research_config(
    config_path: Path | str = DEFAULT_CONFIG_PATH,
) -> SemiconductorResearchConfig:
    """从 YAML 读取研究配置；文件缺失或不可解析时用全默认值。"""
    path = Path(config_path)
    if not path.exists():
        return SemiconductorResearchConfig()

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return SemiconductorResearchConfig()
    if not isinstance(payload, dict):
        return SemiconductorResearchConfig()

    defense = DefenseConfig(
        scissors_lt=float(payload.get("defense", {}).get("scissors_lt", 0.0)),
        doi_ge=float(payload.get("defense", {}).get("doi_ge", 70.0)),
        drawdown_weight=float(payload.get("defense", {}).get("drawdown_weight", 0.3)),
    )

    def _int(key: str, default: int) -> int:
        try:
            return int(payload.get(key, default))
        except (TypeError, ValueError):
            return default

    return SemiconductorResearchConfig(
        schema_version=_int("schema_version", 1),
        title=str(payload.get("title", "半导体深研线回测/IC 验证研究配置")),
        output_dir=str(payload.get("output_dir", "data/strategy/semiconductor")),
        industry=str(payload.get("industry", "270100")),
        start_date=_parse_date(payload.get("start_date"), date(2018, 1, 1)),
        oos_start=_parse_date(payload.get("oos_start"), date(2022, 1, 1)),
        fwd_horizon=max(_int("fwd_horizon", 60), 1),
        ic_min_samples=max(_int("ic_min_samples", 30), 1),
        ic_legs=_parse_str_list(payload.get("ic_legs"), ("ai_capex_score", "storage_score")),
        trading_days=max(_int("trading_days", 252), 1),
        defense=defense,
    )


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "DefenseConfig",
    "SemiconductorResearchConfig",
    "load_semiconductor_research_config",
]
