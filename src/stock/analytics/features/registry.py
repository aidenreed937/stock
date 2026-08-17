"""全系统特征元数据注册中心 (FeatureRegistry)。"""

from __future__ import annotations

from typing import ClassVar

from stock.analytics.features.spec import (
    EntityType,
    FeatureKind,
    FeatureSpec,
    FeatureUnit,
)


class FeatureRegistry:
    """集中管理 FeatureSpec 注册与查询。"""

    _registry: ClassVar[dict[str, FeatureSpec]] = {}

    @classmethod
    def register(cls, spec: FeatureSpec) -> None:
        """注册特征元数据定义。"""
        cls._registry[spec.feature_id] = spec

    @classmethod
    def get(cls, feature_id: str) -> FeatureSpec:
        """根据特征 ID 获取元数据，不存在时抛出 KeyError。"""
        if feature_id not in cls._registry:
            raise KeyError(f"未注册的特征 ID: {feature_id}")
        return cls._registry[feature_id]

    @classmethod
    def get_or_none(cls, feature_id: str) -> FeatureSpec | None:
        """根据特征 ID 获取元数据，不存在时返回 None。"""
        return cls._registry.get(feature_id)

    @classmethod
    def list_all(cls) -> list[FeatureSpec]:
        """返回已注册的所有特征列表。"""
        return list(cls._registry.values())

    @classmethod
    def list_by_kind(cls, kind: FeatureKind) -> list[FeatureSpec]:
        """按特征语义类别筛选特征列表。"""
        return [s for s in cls._registry.values() if s.kind == kind]

    @classmethod
    def list_by_entity_type(cls, entity_type: EntityType) -> list[FeatureSpec]:
        """按实体粒度筛选特征列表。"""
        return [s for s in cls._registry.values() if s.entity_type == entity_type]

    @classmethod
    def clear(cls) -> None:
        """测试用清理注册表。"""
        cls._registry.clear()


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
        is_materialized_wide=True,
        description="全市场上涨家数占比（上涨家数 / 总有效个股数）",
    ),
    FeatureSpec(
        feature_id="above_ma20_ratio",
        kind=FeatureKind.INDICATOR,
        entity_type=EntityType.MARKET,
        unit=FeatureUnit.RATIO,
        lookback_days=20,
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

for spec in _BUILTIN_MARKET_DAILY_SPECS:
    FeatureRegistry.register(spec)
