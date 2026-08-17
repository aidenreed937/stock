"""审计数据集领域与时态周期注册表 (SSOT 统一审计元数据模型)。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from stock_data.audit.domains import AuditDomain, AuditFrequency

if TYPE_CHECKING:
    from stock_data.audit.benchmarks.base import BenchmarkProvider
    from stock_data.catalog import DataCatalog


@dataclass(frozen=True)
class DatasetAuditSpec:
    """单个数据集的审计行为与事实基准映射契约。"""

    dataset: str
    data_source: str
    domain: AuditDomain
    frequency: AuditFrequency
    min_expected_ratio: float = 0.98  # 最小容忍覆盖率 (如 98%)
    is_partitioned: bool = True
    raw_reconciliation_exempt: bool = False
    raw_reconciliation_reason: str = ""
    lineage_status: str = "raw_backed"
    source_endpoint: str = ""


# 全库核心数据集审计规则注册表
AUDIT_DATASET_REGISTRY: dict[str, DatasetAuditSpec] = {
    # 1. 个股微观领域 (EQUITY - DAILY)
    "stock_daily_bar": DatasetAuditSpec(
        dataset="stock_daily_bar",
        data_source="tushare",
        domain=AuditDomain.EQUITY,
        frequency=AuditFrequency.DAILY,
        min_expected_ratio=0.999,
    ),
    "daily_basic": DatasetAuditSpec(
        dataset="daily_basic",
        data_source="tushare",
        domain=AuditDomain.EQUITY,
        frequency=AuditFrequency.DAILY,
        min_expected_ratio=0.98,
    ),
    "adj_factor": DatasetAuditSpec(
        dataset="adj_factor",
        data_source="tushare",
        domain=AuditDomain.EQUITY,
        frequency=AuditFrequency.DAILY,
        min_expected_ratio=0.999,
    ),
    "stk_limit": DatasetAuditSpec(
        dataset="stk_limit",
        data_source="tushare",
        domain=AuditDomain.EQUITY,
        frequency=AuditFrequency.DAILY,
        min_expected_ratio=0.98,
    ),
    "limit_list_d": DatasetAuditSpec(
        dataset="limit_list_d",
        data_source="tushare",
        domain=AuditDomain.EQUITY,
        frequency=AuditFrequency.DAILY,
        # 该接口只返回涨停、跌停和炸板事件，不是全市场逐股行情全集。
        min_expected_ratio=0.0,
    ),
    "moneyflow": DatasetAuditSpec(
        dataset="moneyflow",
        data_source="tushare",
        domain=AuditDomain.EQUITY,
        frequency=AuditFrequency.DAILY,
        min_expected_ratio=0.98,
    ),
    "margin_detail": DatasetAuditSpec(
        dataset="margin_detail",
        data_source="tushare",
        domain=AuditDomain.EQUITY,
        frequency=AuditFrequency.DAILY,
        min_expected_ratio=0.95,
    ),
    "hk_hold": DatasetAuditSpec(
        dataset="hk_hold",
        data_source="tushare",
        domain=AuditDomain.EQUITY,
        frequency=AuditFrequency.DAILY,
        min_expected_ratio=0.90,
    ),
    # 2. 中观行业领域 (INDUSTRY - DAILY)
    "sw_daily": DatasetAuditSpec(
        dataset="sw_daily",
        data_source="tushare",
        domain=AuditDomain.INDUSTRY,
        frequency=AuditFrequency.DAILY,
        min_expected_ratio=1.0,
    ),
    "sw_industry": DatasetAuditSpec(
        dataset="sw_industry",
        data_source="lixinger",
        domain=AuditDomain.INDUSTRY,
        frequency=AuditFrequency.DAILY,
        min_expected_ratio=1.0,
    ),
    "sw_2021_fundamental": DatasetAuditSpec(
        dataset="sw_2021_fundamental",
        data_source="lixinger",
        domain=AuditDomain.INDUSTRY,
        frequency=AuditFrequency.DAILY,
        min_expected_ratio=1.0,
        raw_reconciliation_exempt=True,
        raw_reconciliation_reason="LiXinger 行业估值接口当前返回 403，暂按 Curated-only 数据集审计",
        lineage_status="raw_backed",
        source_endpoint="cn/industry/fundamental/sw_2021",
    ),
    "sw_2021_l2_fundamental": DatasetAuditSpec(
        dataset="sw_2021_l2_fundamental",
        data_source="lixinger",
        domain=AuditDomain.INDUSTRY,
        frequency=AuditFrequency.DAILY,
        min_expected_ratio=1.0,
        lineage_status="raw_backed",
        source_endpoint="cn/industry/fundamental/sw_2021",
    ),
    # 3. 大盘指数领域 (INDEX - DAILY)
    "index_daily": DatasetAuditSpec(
        dataset="index_daily",
        data_source="tushare",
        domain=AuditDomain.INDEX,
        frequency=AuditFrequency.DAILY,
        min_expected_ratio=1.0,
    ),
    "index_daily_bar": DatasetAuditSpec(
        dataset="index_daily_bar",
        data_source="tushare",
        domain=AuditDomain.INDEX,
        frequency=AuditFrequency.DAILY,
        min_expected_ratio=1.0,
    ),
    "index_fundamental": DatasetAuditSpec(
        dataset="index_fundamental",
        data_source="lixinger",
        domain=AuditDomain.INDEX,
        frequency=AuditFrequency.DAILY,
        min_expected_ratio=1.0,
    ),
    # 4. 宏观流动性领域 (MACRO_LIQUIDITY - DAILY)
    "margin": DatasetAuditSpec(
        dataset="margin",
        data_source="tushare",
        domain=AuditDomain.MACRO_LIQUIDITY,
        frequency=AuditFrequency.DAILY,
        min_expected_ratio=1.0,
        is_partitioned=False,
    ),
    "moneyflow_hsgt": DatasetAuditSpec(
        dataset="moneyflow_hsgt",
        data_source="tushare",
        domain=AuditDomain.MACRO_LIQUIDITY,
        frequency=AuditFrequency.DAILY,
        min_expected_ratio=1.0,
        is_partitioned=False,
    ),
    "national_debt": DatasetAuditSpec(
        dataset="national_debt",
        data_source="lixinger",
        domain=AuditDomain.MACRO_LIQUIDITY,
        frequency=AuditFrequency.DAILY,
        min_expected_ratio=1.0,
        is_partitioned=False,
    ),
    "shibor": DatasetAuditSpec(
        dataset="shibor",
        data_source="tushare",
        domain=AuditDomain.MACRO_LIQUIDITY,
        frequency=AuditFrequency.DAILY,
        min_expected_ratio=1.0,
        is_partitioned=False,
    ),
    # 5. 宏观经济基本面 (MACRO_ECON - MONTHLY/QUARTERLY)
    "cn_cpi": DatasetAuditSpec(
        dataset="cn_cpi",
        data_source="tushare",
        domain=AuditDomain.MACRO_ECON,
        frequency=AuditFrequency.MONTHLY,
        is_partitioned=False,
    ),
    "cn_ppi": DatasetAuditSpec(
        dataset="cn_ppi",
        data_source="tushare",
        domain=AuditDomain.MACRO_ECON,
        frequency=AuditFrequency.MONTHLY,
        is_partitioned=False,
    ),
    "cn_pmi": DatasetAuditSpec(
        dataset="cn_pmi",
        data_source="tushare",
        domain=AuditDomain.MACRO_ECON,
        frequency=AuditFrequency.MONTHLY,
        is_partitioned=False,
    ),
    "cn_gdp": DatasetAuditSpec(
        dataset="cn_gdp",
        data_source="tushare",
        domain=AuditDomain.MACRO_ECON,
        frequency=AuditFrequency.QUARTERLY,
        is_partitioned=False,
    ),
    # 6. 元数据字典领域 (METADATA - STATIC)
    "stock_basic": DatasetAuditSpec(
        dataset="stock_basic",
        data_source="tushare",
        domain=AuditDomain.METADATA,
        frequency=AuditFrequency.STATIC,
        is_partitioned=False,
    ),
    "index_basic": DatasetAuditSpec(
        dataset="index_basic",
        data_source="tushare",
        domain=AuditDomain.METADATA,
        frequency=AuditFrequency.STATIC,
        is_partitioned=False,
    ),
}


def get_audit_spec(dataset: str, data_source: str = "tushare") -> DatasetAuditSpec:
    """获取指定数据集的审计规范，未显式声明时自动派生默认规范。"""
    if data_source == "alphavantage" and dataset in {"fx_daily", "macro_indicators"}:
        return DatasetAuditSpec(
            dataset=dataset,
            data_source=data_source,
            domain=AuditDomain.MACRO_LIQUIDITY,
            frequency=AuditFrequency.DAILY,
            min_expected_ratio=1.0,
            is_partitioned=False,
            source_endpoint="FX_DAILY",
        )
    # 兼容 sw_industry 别名到 sw_2021_fundamental (lixinger)
    lookup_name = dataset
    if dataset == "sw_industry" and data_source == "lixinger":
        lookup_name = "sw_2021_fundamental"

    if lookup_name in AUDIT_DATASET_REGISTRY:
        return AUDIT_DATASET_REGISTRY[lookup_name]

    return DatasetAuditSpec(
        dataset=dataset,
        data_source=data_source,
        domain=AuditDomain.EQUITY,
        frequency=AuditFrequency.DAILY,
    )


def resolve_benchmark_provider(
    spec: DatasetAuditSpec,
    catalog: DataCatalog | None = None,
) -> BenchmarkProvider:
    """根据审计规范的 Domain 和 Frequency 自动路由到对应的事实基准提供者。"""
    from stock_data.audit.benchmarks.calendar import MacroCalendarBenchmarkProvider
    from stock_data.audit.benchmarks.equity import EquityDailyBenchmarkProvider
    from stock_data.audit.benchmarks.index import IndexDailyBenchmarkProvider
    from stock_data.audit.benchmarks.industry import IndustryDailyBenchmarkProvider

    if spec.domain == AuditDomain.EQUITY and spec.frequency == AuditFrequency.DAILY:
        return EquityDailyBenchmarkProvider(catalog=catalog)
    if spec.domain == AuditDomain.INDUSTRY and spec.frequency == AuditFrequency.DAILY:
        return IndustryDailyBenchmarkProvider(catalog=catalog, data_source=spec.data_source)
    if spec.domain == AuditDomain.INDEX and spec.frequency == AuditFrequency.DAILY:
        return IndexDailyBenchmarkProvider(catalog=catalog)
    if spec.domain == AuditDomain.MACRO_ECON:
        freq_str = "monthly" if spec.frequency == AuditFrequency.MONTHLY else "quarterly"
        return MacroCalendarBenchmarkProvider(frequency=freq_str)

    # 默认回退为个股基准
    return EquityDailyBenchmarkProvider(catalog=catalog)
