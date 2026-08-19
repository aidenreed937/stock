"""全市场聚合监控配置加载。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Self, cast

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config/analytics/market_aggregate.yaml"


@dataclass(frozen=True, slots=True)
class MarketAggregateFetchConfig:
    """腾讯批量行情接口请求参数。"""

    batch_size: int = 100
    timeout_seconds: float = 5.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.2

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> Self:
        """从 YAML 映射构造请求配置。"""
        data = data or {}
        return cls(
            batch_size=int(data.get("batch_size", 100)),
            timeout_seconds=float(data.get("timeout_seconds", 5.0)),
            max_retries=int(data.get("max_retries", 2)),
            retry_backoff_seconds=float(data.get("retry_backoff_seconds", 0.2)),
        )


@dataclass(frozen=True, slots=True)
class MarketAggregateUniverseConfig:
    """全市场聚合使用的本地股票全集配置。"""

    dataset: str = "stock_basic"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> Self:
        """从 YAML 映射构造股票全集配置。"""
        data = data or {}
        return cls(dataset=str(data.get("dataset", "stock_basic")))


@dataclass(frozen=True, slots=True)
class MarketAggregateCacheConfig:
    """市场聚合进程内缓存失效参数。"""

    fresh_ttl_seconds: float = 30.0
    max_age_seconds: float = 300.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> Self:
        """从 YAML 映射构造缓存配置。"""
        data = data or {}
        return cls(
            fresh_ttl_seconds=float(data.get("fresh_ttl_seconds", 30.0)),
            max_age_seconds=float(data.get("max_age_seconds", 300.0)),
        )


@dataclass(frozen=True, slots=True)
class MarketAggregateThresholdConfig:
    """市场聚合派生阈值。"""

    strong_move_pct: float = 5.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> Self:
        """从 YAML 映射构造阈值配置。"""
        data = data or {}
        return cls(strong_move_pct=float(data.get("strong_move_pct", 5.0)))


@dataclass(frozen=True, slots=True)
class MarketAggregateQualityConfig:
    """市场聚合质量判定参数。"""

    min_coverage_ratio: float = 0.95

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> Self:
        """从 YAML 映射构造质量配置。"""
        data = data or {}
        return cls(min_coverage_ratio=float(data.get("min_coverage_ratio", 0.95)))


@dataclass(frozen=True, slots=True)
class MarketAggregateRawConfig:
    """实时聚合 RAW 留档参数。"""

    flush_interval_seconds: float = 60.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> Self:
        """从 YAML 映射构造 RAW 留档配置。"""
        data = data or {}
        return cls(flush_interval_seconds=float(data.get("flush_interval_seconds", 60.0)))


@dataclass(frozen=True, slots=True)
class MarketAggregateMetricConfig:
    """报告中的单个聚合指标显示配置。"""

    metric_id: str
    label: str
    section: str = "市场状态"
    enabled: bool = True
    note: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        """从 YAML 映射构造指标显示配置。"""
        metric_id = str(data["id"])
        return cls(
            metric_id=metric_id,
            label=str(data.get("label", metric_id)),
            section=str(data.get("section", "市场状态")),
            enabled=bool(data.get("enabled", True)),
            note=str(data.get("note", "")),
        )


@dataclass(frozen=True, slots=True)
class MarketAggregateReportConfig:
    """市场聚合报告模板与字段配置。"""

    report_template: str = "aggregate/market_aggregate.md.j2"
    human_template: str = "aggregate/market_aggregate_human.md.j2"
    table_template: str = "aggregate/market_aggregate_table.md.j2"
    quality_template: str = "aggregate/market_aggregate_quality.md.j2"
    metrics: tuple[MarketAggregateMetricConfig, ...] = ()
    limitations: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> Self:
        """从 YAML 映射构造报告配置。"""
        data = data or {}
        raw_metrics = _as_sequence(
            data.get("metrics", _default_metric_mappings()), "report.metrics"
        )
        raw_limitations = _as_sequence(
            data.get("limitations", _default_limitations()), "report.limitations"
        )
        return cls(
            report_template=str(data.get("template", "aggregate/market_aggregate.md.j2")),
            human_template=str(
                data.get("human_template", "aggregate/market_aggregate_human.md.j2")
            ),
            table_template=str(
                data.get("table_template", "aggregate/market_aggregate_table.md.j2")
            ),
            quality_template=str(
                data.get("quality_template", "aggregate/market_aggregate_quality.md.j2")
            ),
            metrics=tuple(
                MarketAggregateMetricConfig.from_mapping(_as_mapping(item, "report.metric"))
                for item in raw_metrics
            ),
            limitations=tuple(str(value) for value in raw_limitations),
        )


@dataclass(frozen=True, slots=True)
class MarketAggregateConfig:
    """全市场聚合监控顶层配置。"""

    schema_version: int
    title: str
    artifact_root: Path
    source: str
    scope: str
    interval_seconds: float
    universe: MarketAggregateUniverseConfig
    fetch: MarketAggregateFetchConfig
    cache: MarketAggregateCacheConfig
    thresholds: MarketAggregateThresholdConfig
    quality: MarketAggregateQualityConfig
    raw: MarketAggregateRawConfig
    report: MarketAggregateReportConfig

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Self:
        """从 YAML 顶层映射构造聚合监控配置。"""
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            title=str(data.get("title", "A 股全市场实时聚合监控")),
            artifact_root=Path(str(data.get("artifact_root", "data/analytics/market_aggregate"))),
            source=str(data.get("source", "tencent")),
            scope=str(data.get("scope", "a_share_full_market")),
            interval_seconds=float(data.get("interval_seconds", 60.0)),
            universe=MarketAggregateUniverseConfig.from_mapping(
                _optional_mapping(data.get("universe"), "universe")
            ),
            fetch=MarketAggregateFetchConfig.from_mapping(
                _optional_mapping(data.get("fetch"), "fetch")
            ),
            cache=MarketAggregateCacheConfig.from_mapping(
                _optional_mapping(data.get("cache"), "cache")
            ),
            thresholds=MarketAggregateThresholdConfig.from_mapping(
                _optional_mapping(data.get("thresholds"), "thresholds")
            ),
            quality=MarketAggregateQualityConfig.from_mapping(
                _optional_mapping(data.get("quality"), "quality")
            ),
            raw=MarketAggregateRawConfig.from_mapping(_optional_mapping(data.get("raw"), "raw")),
            report=MarketAggregateReportConfig.from_mapping(
                _optional_mapping(data.get("report"), "report")
            ),
        )

    def with_artifact_root(self, artifact_root: Path | str | None) -> Self:
        """返回覆盖产物根目录后的配置。"""
        if artifact_root is None:
            return self
        return replace(self, artifact_root=Path(artifact_root))

    def with_runtime_overrides(
        self,
        *,
        batch_size: int | None = None,
        strong_move_pct: float | None = None,
    ) -> Self:
        """返回应用 CLI 临时覆盖参数后的配置。"""
        return replace(
            self,
            fetch=replace(
                self.fetch,
                batch_size=self.fetch.batch_size if batch_size is None else batch_size,
            ),
            thresholds=replace(
                self.thresholds,
                strong_move_pct=(
                    self.thresholds.strong_move_pct if strong_move_pct is None else strong_move_pct
                ),
            ),
        )


def load_market_aggregate_config(
    config_path: Path | str = DEFAULT_CONFIG_PATH,
) -> MarketAggregateConfig:
    """加载全市场聚合监控 YAML 配置。"""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"全市场聚合监控配置不存在: {path}")
    with path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file)
    root = _as_mapping(raw, "market_aggregate.yaml")
    data = _as_mapping(root.get("market_aggregate"), "market_aggregate")
    return MarketAggregateConfig.from_mapping(data)


def _default_metric_mappings() -> list[dict[str, str]]:
    return [
        {"id": "coverage", "label": "覆盖数 / 返回数 / 覆盖率", "section": "覆盖与质量"},
        {"id": "breadth_counts", "label": "上涨 / 下跌 / 平盘", "section": "市场广度"},
        {"id": "breadth_shares", "label": "上涨占比 / 下跌占比", "section": "市场广度"},
        {"id": "advance_decline_ratio", "label": "涨跌比（上涨 / 下跌）", "section": "市场广度"},
        {
            "id": "strong_move_counts",
            "label": "强势上涨 / 强势下跌",
            "section": "市场广度",
        },
        {
            "id": "change_distribution",
            "label": "P25 / 中位 / P75 涨跌幅",
            "section": "涨跌分布",
        },
        {
            "id": "weighted_pct_change",
            "label": "成交额加权涨跌幅",
            "section": "涨跌分布",
        },
        {"id": "amount_total", "label": "全市场成交额", "section": "成交与市值"},
        {"id": "market_value", "label": "总市值 / 流通市值", "section": "成交与市值"},
        {"id": "free_float_turnover", "label": "流通市值换手率", "section": "成交与市值"},
        {
            "id": "amount_top_5pct_share",
            "label": "成交额前 5% 集中度",
            "section": "成交与市值",
        },
    ]


def _default_limitations() -> list[str]:
    return [
        "本报告是全市场聚合摘要，不包含逐标的实时明细。",
        "强势上涨/下跌阈值仅表示涨跌幅达到配置阈值，不等同于涨跌停统计。",
        "本通道不计算全市场 MA20/MA60 比例、行业轮动或涨跌停事件。",
        "覆盖率低于质量阈值或使用缓存时，应结合 status 与 freshness 谨慎解读。",
    ]


def _optional_mapping(value: Any, name: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    return _as_mapping(value, name)


def _as_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} 必须是映射对象")
    return cast("Mapping[str, Any]", value)


def _as_sequence(value: Any, name: str) -> Sequence[Any]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise TypeError(f"{name} 必须是列表")
    return tuple(value)


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "MarketAggregateCacheConfig",
    "MarketAggregateConfig",
    "MarketAggregateFetchConfig",
    "MarketAggregateMetricConfig",
    "MarketAggregateQualityConfig",
    "MarketAggregateRawConfig",
    "MarketAggregateReportConfig",
    "MarketAggregateThresholdConfig",
    "MarketAggregateUniverseConfig",
    "load_market_aggregate_config",
]
