"""全系统特征元数据注册中心 (FeatureRegistry)。"""

from __future__ import annotations

from dataclasses import replace
from typing import ClassVar

from stock.analytics.features.spec import (
    EntityType,
    FeatureKind,
    FeatureSpec,
    FeatureUnit,
)


class FeatureRegistry:
    """集中管理 FeatureSpec 注册与查询。"""

    _registry: ClassVar[dict[str, dict[str, FeatureSpec]]] = {}
    _current_versions: ClassVar[dict[str, str]] = {}

    @classmethod
    def register(cls, spec: FeatureSpec) -> None:
        """注册特征元数据定义。"""
        versions = cls._registry.setdefault(spec.feature_id, {})
        existing = versions.get(spec.definition_version)
        if existing is not None and existing != spec:
            raise ValueError(
                f"特征定义已存在且内容不一致: {spec.feature_id}@{spec.definition_version}"
            )
        versions[spec.definition_version] = spec
        cls._current_versions[spec.feature_id] = spec.definition_version

    @classmethod
    def get(cls, feature_id: str, definition_version: str | None = None) -> FeatureSpec:
        """根据特征 ID 获取元数据，不存在时抛出 KeyError。"""
        if feature_id not in cls._registry:
            raise KeyError(f"未注册的特征 ID: {feature_id}")
        versions = cls._registry[feature_id]
        version = definition_version or cls._current_versions[feature_id]
        if version not in versions:
            raise KeyError(f"未注册的特征版本: {feature_id}@{version}")
        return versions[version]

    @classmethod
    def get_or_none(
        cls, feature_id: str, definition_version: str | None = None
    ) -> FeatureSpec | None:
        """根据特征 ID 获取元数据，不存在时返回 None。"""
        try:
            return cls.get(feature_id, definition_version)
        except KeyError:
            return None

    @classmethod
    def list_all(cls) -> list[FeatureSpec]:
        """返回每个特征当前生效的定义。"""
        return [cls.get(feature_id) for feature_id in cls._registry]

    @classmethod
    def list_versions(cls, feature_id: str) -> list[FeatureSpec]:
        """返回指定特征的全部定义版本。"""
        if feature_id not in cls._registry:
            return []
        return list(cls._registry[feature_id].values())

    @classmethod
    def list_by_kind(cls, kind: FeatureKind) -> list[FeatureSpec]:
        """按特征语义类别筛选特征列表。"""
        return [spec for spec in cls.list_all() if spec.kind == kind]

    @classmethod
    def list_by_entity_type(cls, entity_type: EntityType) -> list[FeatureSpec]:
        """按实体粒度筛选特征列表。"""
        return [spec for spec in cls.list_all() if spec.entity_type == entity_type]

    @classmethod
    def clear(cls) -> None:
        """测试用清理注册表。"""
        cls._registry.clear()
        cls._current_versions.clear()


# ==========================================
# 内置全市场日频核心特征元数据注册
# ==========================================

_BUILTIN_MARKET_DAILY_SPECS: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        feature_id="total_turnover",
        kind=FeatureKind.AGGREGATE,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.CNY,
        required_datasets=("stock_daily_bar",),
        required_columns=("trade_date", "amount"),
        is_materialized_wide=True,
        description="全市场 A 股日成交总额（元）",
    ),
    FeatureSpec(
        feature_id="adv_dec_ratio",
        kind=FeatureKind.INDICATOR,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.RATIO,
        required_datasets=("stock_daily_bar",),
        required_columns=("trade_date", "symbol", "close"),
        is_materialized_wide=True,
        description="全市场涨跌家数比（上涨家数 / 下跌家数）",
    ),
    FeatureSpec(
        feature_id="advance_ratio",
        kind=FeatureKind.INDICATOR,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.RATIO,
        required_datasets=("stock_daily_bar",),
        required_columns=("trade_date", "symbol", "close"),
        definition_version="v2",
        is_materialized_wide=True,
        description="全市场上涨家数占比（上涨家数 / 有效涨跌个股数）",
    ),
    FeatureSpec(
        feature_id="above_ma20_ratio",
        kind=FeatureKind.INDICATOR,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.RATIO,
        lookback_days=20,
        definition_version="v2",
        required_datasets=("stock_daily_bar",),
        required_columns=("trade_date", "symbol", "close"),
        is_materialized_wide=True,
        description="站上 20 日均线的个股占比",
    ),
    FeatureSpec(
        feature_id="above_ma60_ratio",
        kind=FeatureKind.INDICATOR,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.RATIO,
        lookback_days=60,
        definition_version="v2",
        required_datasets=("stock_daily_bar",),
        required_columns=("trade_date", "symbol", "close"),
        is_materialized_wide=True,
        description="站上 60 日均线的个股占比",
    ),
    FeatureSpec(
        feature_id="above_ma120_ratio",
        kind=FeatureKind.INDICATOR,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.RATIO,
        lookback_days=120,
        definition_version="v2",
        required_datasets=("stock_daily_bar",),
        required_columns=("trade_date", "symbol", "close"),
        is_materialized_wide=True,
        description="站上 120 日均线的个股占比",
    ),
    FeatureSpec(
        feature_id="new_high_252d_ratio",
        kind=FeatureKind.INDICATOR,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.RATIO,
        lookback_days=252,
        definition_version="v2",
        required_datasets=("stock_daily_bar",),
        required_columns=("trade_date", "symbol", "close"),
        is_materialized_wide=True,
        description="创 252 日新高的个股占比",
    ),
    FeatureSpec(
        feature_id="new_low_252d_ratio",
        kind=FeatureKind.INDICATOR,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.RATIO,
        lookback_days=252,
        definition_version="v2",
        required_datasets=("stock_daily_bar",),
        required_columns=("trade_date", "symbol", "close"),
        is_materialized_wide=True,
        description="创 252 日新低的个股占比",
    ),
    FeatureSpec(
        feature_id="margin_buy_ratio",
        kind=FeatureKind.INDICATOR,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.RATIO,
        required_datasets=("margin", "stock_daily_bar"),
        required_columns=("trade_date", "rzmre"),
        is_materialized_wide=True,
        description="全市场融资买入额占成交额比重 (rzmre / total_turnover)",
    ),
    FeatureSpec(
        feature_id="margin_balance",
        kind=FeatureKind.AGGREGATE,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.CNY,
        required_datasets=("margin",),
        required_columns=("trade_date", "rzye", "rqye", "rzrqye"),
        is_materialized_wide=True,
        description="全市场两融余额（元）",
    ),
    FeatureSpec(
        feature_id="market_turnover_rate",
        kind=FeatureKind.INDICATOR,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.RATIO,
        required_datasets=("daily_basic",),
        required_columns=("trade_date", "turnover_rate_f"),
        is_materialized_wide=True,
        description="全市场自由流通换手率算术均值",
    ),
    FeatureSpec(
        feature_id="main_net_inflow_ratio",
        kind=FeatureKind.INDICATOR,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.RATIO,
        required_datasets=("moneyflow", "stock_daily_bar"),
        required_columns=("trade_date", "net_mf_amount"),
        is_materialized_wide=True,
        description="主力净流入占成交额比重",
    ),
    FeatureSpec(
        feature_id="limit_up_count",
        kind=FeatureKind.AGGREGATE,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.COUNT,
        required_datasets=("limit_list_d",),
        required_columns=("trade_date", "limit"),
        is_materialized_wide=True,
        description="全市场涨停家数",
    ),
    FeatureSpec(
        feature_id="limit_down_count",
        kind=FeatureKind.AGGREGATE,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.COUNT,
        required_datasets=("limit_list_d",),
        required_columns=("trade_date", "limit"),
        is_materialized_wide=True,
        description="全市场跌停家数",
    ),
    FeatureSpec(
        feature_id="broken_limit_count",
        kind=FeatureKind.AGGREGATE,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.COUNT,
        required_datasets=("limit_list_d",),
        required_columns=("trade_date", "limit"),
        is_materialized_wide=True,
        description="全市场炸板（曾涨停未封住）家数",
    ),
    FeatureSpec(
        feature_id="broken_limit_ratio",
        kind=FeatureKind.INDICATOR,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.RATIO,
        required_datasets=("limit_list_d",),
        required_columns=("trade_date", "limit"),
        is_materialized_wide=True,
        description="全市场炸板率（炸板数 / (涨停数 + 炸板数)）",
    ),
)

_ADDITIONAL_MARKET_DAILY_SPECS: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        feature_id="total_stocks",
        kind=FeatureKind.AGGREGATE,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.COUNT,
        required_datasets=("stock_daily_bar",),
        required_columns=("trade_date", "symbol"),
        is_materialized_wide=True,
        description="全市场当日有效个股数",
    ),
    FeatureSpec(
        feature_id="margin_buy_amount",
        kind=FeatureKind.AGGREGATE,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.CNY,
        required_datasets=("margin",),
        required_columns=("trade_date", "rzmre"),
        is_materialized_wide=True,
        description="全市场融资买入额（元）",
    ),
    FeatureSpec(
        feature_id="main_net_inflow",
        kind=FeatureKind.AGGREGATE,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.CNY,
        required_datasets=("moneyflow",),
        required_columns=("trade_date", "net_mf_amount"),
        is_materialized_wide=True,
        description="全市场主力净流入额（元）",
    ),
    FeatureSpec(
        feature_id="market_circ_mv",
        kind=FeatureKind.AGGREGATE,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.CNY,
        required_datasets=("daily_basic",),
        required_columns=("trade_date", "circ_mv"),
        is_materialized_wide=True,
        description="全市场流通市值（元）",
    ),
    FeatureSpec(
        feature_id="margin_penetration",
        kind=FeatureKind.INDICATOR,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.RATIO,
        required_datasets=("margin", "daily_basic"),
        required_columns=("trade_date", "rzrqye", "circ_mv"),
        is_materialized_wide=True,
        description="全市场两融余额占流通市值比重",
    ),
    FeatureSpec(
        feature_id="option_put_call_volume_ratio",
        kind=FeatureKind.INDICATOR,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.RATIO,
        required_datasets=("opt_daily", "opt_basic"),
        required_columns=("trade_date", "vol", "call_put"),
        is_materialized_wide=True,
        description="全市场期权认沽/认购成交量比",
    ),
    FeatureSpec(
        feature_id="option_put_call_oi_ratio",
        kind=FeatureKind.INDICATOR,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.RATIO,
        required_datasets=("opt_daily", "opt_basic"),
        required_columns=("trade_date", "oi", "call_put"),
        is_materialized_wide=True,
        description="全市场期权认沽/认购持仓量比",
    ),
    FeatureSpec(
        feature_id="option_amount",
        kind=FeatureKind.AGGREGATE,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.CNY,
        required_datasets=("opt_daily",),
        required_columns=("trade_date", "amount"),
        is_materialized_wide=True,
        description="全市场期权成交额（元）",
    ),
    FeatureSpec(
        feature_id="option_open_interest",
        kind=FeatureKind.AGGREGATE,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.COUNT,
        required_datasets=("opt_daily",),
        required_columns=("trade_date", "oi"),
        is_materialized_wide=True,
        description="全市场期权持仓量（合约数）",
    ),
    FeatureSpec(
        feature_id="option_near_month_amount_share",
        kind=FeatureKind.INDICATOR,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.PERCENT,
        required_datasets=("opt_daily", "opt_basic"),
        required_columns=("trade_date", "amount", "s_month"),
        is_materialized_wide=True,
        description="近月期权成交额占比（百分数）",
    ),
)


def _legacy_v1_spec(spec: FeatureSpec) -> FeatureSpec:
    """构造与当前定义同字段但标记为 v1 的历史定义。

    长表按定义版本永久保留存量行，历史版本必须可解析；v1 与 v2
    的字段差异仅在版本号与 advance_ratio 的口径描述。
    """
    description = spec.description
    if spec.feature_id == "advance_ratio":
        description = "全市场上涨家数占比（上涨家数 / 总有效个股数）"
    return replace(spec, definition_version="v1", description=description)


_LEGACY_MARKET_DAILY_SPECS: tuple[FeatureSpec, ...] = tuple(
    _legacy_v1_spec(spec) for spec in _BUILTIN_MARKET_DAILY_SPECS if spec.definition_version != "v1"
)

# 注册顺序即版本序列：历史版本在前，当前版本最后注册（_current_versions 取最后注册者）
for spec in _LEGACY_MARKET_DAILY_SPECS:
    FeatureRegistry.register(spec)
for spec in (*_BUILTIN_MARKET_DAILY_SPECS, *_ADDITIONAL_MARKET_DAILY_SPECS):
    FeatureRegistry.register(spec)
