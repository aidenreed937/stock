"""半导体深研线：供需剪刀差 + 结构性确认腿 管线。

本层（stock_analytics）产出的是**特征（feature / 候选因子）**——回测的输入，
不是已验证的有效因子；因子有效性由 stock_strategy 验证层确认。
"""

from __future__ import annotations

from stock_analytics.pipelines.semiconductor.config import (
    DEFAULT_CONFIG_PATH,
    MonthlySource,
    QuarterlySource,
    ScissorsConfig,
    SemiconductorLegsConfig,
    StructuralConfig,
    load_semiconductor_legs_config,
)
from stock_analytics.pipelines.semiconductor.legs import (
    build_demand_leg,
    build_monthly_leg,
    build_quarterly_leg,
    build_semiconductor_legs_panel,
    build_structural_legs,
    build_supply_leg,
    load_calendar,
)
from stock_analytics.pipelines.semiconductor.pipeline import (
    SemiconductorLegsPipeline,
    SemiconductorLegsRunResult,
    load_latest_semiconductor_legs,
    run_semiconductor_legs,
)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "MonthlySource",
    "QuarterlySource",
    "ScissorsConfig",
    "SemiconductorLegsConfig",
    "SemiconductorLegsPipeline",
    "SemiconductorLegsRunResult",
    "StructuralConfig",
    "build_demand_leg",
    "build_monthly_leg",
    "build_quarterly_leg",
    "build_semiconductor_legs_panel",
    "build_structural_legs",
    "build_supply_leg",
    "load_calendar",
    "load_latest_semiconductor_legs",
    "load_semiconductor_legs_config",
    "run_semiconductor_legs",
]
