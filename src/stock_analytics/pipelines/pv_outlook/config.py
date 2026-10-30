"""光伏景气前瞻仪表盘 (pv_outlook) 管线配置。

产物定位：不等财报（滞后确认），用产业数据前瞻景气方向——周度价格链价差（毛利空间）、
月度装机/库存/供需水位、数据缺口矩阵、外部核验事实（强制携带信源与日期）。

术语约定：本层产出的是**前瞻信号面板（分析产物）**，是决策参考输入；
有效性不在此处断言，与 ``photovoltaic_legs`` 的"特征/状态"分层一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = "config/analytics/pv_outlook.yaml"


@dataclass(frozen=True, slots=True)
class DatasetTrackSpec:
    """单个跟踪数据集的缺口判定规格。"""

    dataset: str
    source: str = ""
    cadence: str = "monthly"  # weekly | monthly
    release_lag_days: int = 40


@dataclass(frozen=True, slots=True)
class SpreadConfig:
    """价差（毛利空间）计算参数——简化口径，用于趋势跟踪而非绝对盈利测算。"""

    wafers_per_piece: float = 6.6  # 每片硅片对应组件功率 (W/片, 182mm 近似)
    polysilicon_per_watt_g: float = 2.1  # 每瓦硅片硅料单耗 (g/W)


@dataclass(frozen=True, slots=True)
class ScoringConfig:
    """前瞻评分阈值（机制透明，参数集中可调）。"""

    spread_lookback_weeks: int = 12
    module_price_yoy_positive: bool = True
    install_mom_positive: bool = True
    inventory_rebuild_threshold_w_tons: float = 5.0  # 多晶硅库存单月环比阈值（万吨）


@dataclass(frozen=True, slots=True)
class ExternalFact:
    """外部核验事实：自动管线不联网，外部事实人工核验后填入，强制携带信源与日期。"""

    fact: str
    source: str
    published_date: date
    url: str = ""


_DEFAULT_DATASETS: tuple[DatasetTrackSpec, ...] = (
    DatasetTrackSpec("solar_price_chain", "InfoLink Consulting 周度光伏现货价格", "weekly", 14),
    DatasetTrackSpec("solar_capacity", "国家能源局 (NEA) 月度新增并网装机", "monthly", 40),
    DatasetTrackSpec("polysilicon_inventory_monthly", "硅业分会 多晶硅月度库存", "monthly", 20),
    DatasetTrackSpec("polysilicon_supply_monthly", "硅业分会 多晶硅月度产量", "monthly", 20),
    DatasetTrackSpec("polysilicon_balance", "派生：多晶硅供需平衡", "monthly", 20),
    DatasetTrackSpec("solar_supply_demand", "派生：光伏供需剪刀差", "monthly", 45),
    DatasetTrackSpec("solar_cell_production", "国家统计局 (NBS) 太阳能电池月度产量", "monthly", 40),
    DatasetTrackSpec("customs_trade_gacc", "海关总署 (GACC) 光伏电池及组件出口", "monthly", 35),
)


@dataclass(frozen=True, slots=True)
class PvOutlookConfig:
    """光伏景气前瞻仪表盘管线配置。"""

    schema_version: int = 1
    title: str = "光伏景气前瞻仪表盘 (组件/辅材/硅料)"
    artifact_root: str = "data/analytics/pv_outlook"
    datasets: tuple[DatasetTrackSpec, ...] = _DEFAULT_DATASETS
    spread: SpreadConfig = field(default_factory=SpreadConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    external_facts: tuple[ExternalFact, ...] = ()


def _as_str(value: Any, default: str) -> str:
    return str(value) if isinstance(value, str) and value else default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes")
    return default


def _parse_datasets(payload: Any) -> tuple[DatasetTrackSpec, ...]:
    if not isinstance(payload, dict):
        return _DEFAULT_DATASETS
    specs: list[DatasetTrackSpec] = []
    for name, spec in payload.items():
        if not isinstance(spec, dict):
            continue
        specs.append(
            DatasetTrackSpec(
                dataset=str(name),
                source=_as_str(spec.get("source"), ""),
                cadence=_as_str(spec.get("cadence"), "monthly"),
                release_lag_days=_as_int(spec.get("release_lag_days"), 40),
            )
        )
    return tuple(specs) if specs else _DEFAULT_DATASETS


def _parse_external_facts(payload: Any) -> tuple[ExternalFact, ...]:
    if not isinstance(payload, list):
        return ()
    facts: list[ExternalFact] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        raw_date = item.get("published_date")
        if not isinstance(raw_date, str):
            continue
        try:
            published = date.fromisoformat(raw_date)
        except ValueError:
            continue
        facts.append(
            ExternalFact(
                fact=_as_str(item.get("fact"), ""),
                source=_as_str(item.get("source"), ""),
                published_date=published,
                url=_as_str(item.get("url"), ""),
            )
        )
    return tuple(f for f in facts if f.fact and f.source)


def load_pv_outlook_config(config: str | Path | None = None) -> PvOutlookConfig:
    """从 YAML 读取前瞻仪表盘配置；文件缺失或不可解析时用全默认值。"""
    path = Path(config) if config else Path(DEFAULT_CONFIG_PATH)
    payload: dict[str, Any] = {}
    if path.exists():
        try:
            with path.open(encoding="utf-8") as fh:
                loaded = yaml.safe_load(fh) or {}
            if isinstance(loaded, dict):
                payload = loaded
        except yaml.YAMLError:
            payload = {}
    raw_spread = payload.get("spread")
    raw_scoring = payload.get("scoring")
    spread_payload: dict[str, Any] = raw_spread if isinstance(raw_spread, dict) else {}
    scoring_payload: dict[str, Any] = raw_scoring if isinstance(raw_scoring, dict) else {}
    return PvOutlookConfig(
        schema_version=_as_int(payload.get("schema_version"), 1),
        title=_as_str(payload.get("title"), "光伏景气前瞻仪表盘 (组件/辅材/硅料)"),
        artifact_root=_as_str(payload.get("artifact_root"), "data/analytics/pv_outlook"),
        datasets=_parse_datasets(payload.get("datasets")),
        spread=SpreadConfig(
            wafers_per_piece=_as_float(spread_payload.get("wafers_per_piece"), 6.6),
            polysilicon_per_watt_g=_as_float(spread_payload.get("polysilicon_per_watt_g"), 2.1),
        ),
        scoring=ScoringConfig(
            spread_lookback_weeks=_as_int(scoring_payload.get("spread_lookback_weeks"), 12),
            module_price_yoy_positive=_as_bool(
                scoring_payload.get("module_price_yoy_positive"), True
            ),
            install_mom_positive=_as_bool(scoring_payload.get("install_mom_positive"), True),
            inventory_rebuild_threshold_w_tons=_as_float(
                scoring_payload.get("inventory_rebuild_threshold_w_tons"), 5.0
            ),
        ),
        external_facts=_parse_external_facts(payload.get("external_facts")),
    )
