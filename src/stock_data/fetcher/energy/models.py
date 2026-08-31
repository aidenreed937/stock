"""全球能源领域强类型数据契约与黄金表记录模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

import polars as pl

from stock_data.fetcher.energy.taxonomy import (
    DataStatus,
    EnergyFlowType,
    EnergyProduct,
    PeriodType,
)


@dataclass(frozen=True)
class EnergyMetricRecord:
    """全球能源标准化记录通用契约 (L3/L4 统一事实输入)."""

    geo_code: str  # ISO-3 / 区域代码 (如 CHN, USA, WLD, EU27)
    period: str  # YYYY 或 YYYY-MM 或 YYYY-MM-DD
    period_type: PeriodType | str  # yearly | monthly | weekly | daily
    energy_category: str  # petroleum | gas | coal | power | macro | renewables
    product: EnergyProduct | str  # CRUDE_OIL | SOLAR_PV | NATURAL_GAS 等
    flow_type: EnergyFlowType | str  # PRODUCTION | CONSUMPTION | CAPACITY | STOCK 等
    standard_value: float  # 标准化基准单位数值 (如 TWh, GW, kbpd, bcm, EJ)
    standard_unit: str  # 标准化基准单位
    raw_value: float | None = None  # 原始源数值
    raw_unit: str = ""  # 原始计量单位
    source: str = ""  # EI | JODI | EIA | EMBER | IRENA | EUROSTAT | NEA
    source_dataset: str = ""  # 数据集名称或表名
    data_status: DataStatus | str = DataStatus.ACTUAL  # actual | provisional | estimated 等
    release_date: date | None = None  # 官方发布日期
    collected_at: str = ""  # 采集时间戳 (ISO 8601)
    source_url: str = ""  # 数据来源 URL 或 API Endpoint


@dataclass(frozen=True)
class GlobalOilGasBalanceRecord:
    """月度油气供需平衡记录 (对应 global_oil_gas_balance.parquet)."""

    geo_code: str  # ISO-3 编码
    trade_date: date  # 月末对齐自然日
    period: str  # YYYY-MM
    product: str  # CRUDE_OIL | OIL_PRODUCTS | NATURAL_GAS | LNG
    flow_type: str  # PRODUCTION | CONSUMPTION | IMPORT | EXPORT | CLOSING_STOCK | REFINERY_INP
    standard_value: float  # 标准化数值 (石油: kbpd, 天然气: bcm)
    standard_unit: str  # kbpd | bcm
    raw_value: float | None = None
    raw_unit: str = ""
    source: str = "JODI"  # JODI | EIA | OPEC | CUSTOMS
    source_dataset: str = ""
    data_status: str = "actual"  # actual | provisional | estimated
    release_date: date | None = None
    collected_at: str = ""


@dataclass(frozen=True)
class GlobalPowerGenerationRecord:
    """月度/年度全球发电结构与碳排记录 (对应 global_power_generation.parquet)."""

    geo_code: str  # ISO-3 编码
    trade_date: date  # 对齐自然日 (月末或年末)
    period: str  # YYYY-MM 或 YYYY
    period_type: str  # monthly | yearly
    technology: str  # SOLAR_PV | WIND_TOTAL | HYDRO | NUCLEAR | THERMAL_POWER | TOTAL_ELECTRICITY
    generation_twh: float  # 发电量 (TWh)
    yoy_growth: float | None = None  # 同比增速 (如 0.15 记 15%)
    share_percent: float | None = None  # 发电结构占比 (0~100)
    emissions_mtco2: float | None = None  # 电力碳排放量 (百万吨 CO2)
    source: str = "EMBER"  # EMBER | EI | EIA | EUROSTAT | NEA
    data_status: str = "actual"
    release_date: date | None = None
    collected_at: str = ""


@dataclass(frozen=True)
class GlobalRenewableCapacityRecord:
    """年度全球新能源装机容量记录 (对应 global_renewable_capacity.parquet)."""

    geo_code: str  # ISO-3 编码
    year: int  # YYYY
    technology: str  # SOLAR_PV | WIND_ONSHORE | WIND_OFFSHORE | HYDRO | BIOENERGY 等
    capacity_gw: float  # 累计装机容量 (GW)
    new_added_gw: float | None = None  # 当年新增装机容量 (GW)
    yoy_growth: float | None = None  # 累计装机同比增速
    source: str = "IRENA"  # IRENA | EI | NEA | EUROSTAT
    data_status: str = "actual"
    release_date: date | None = None
    collected_at: str = ""


@dataclass(frozen=True)
class GlobalMacroEnergyBaselineRecord:
    """EI/UNSD 长周期全球能源总盘基准 (对应 global_energy_macro_baseline.parquet)."""

    geo_code: str  # ISO-3 编码
    year: int  # 1965~至今
    energy_type: str  # OIL | GAS | COAL | NUCLEAR | HYDRO | RENEWABLES | TOTAL_PRIMARY_ENERGY
    flow_type: str  # PRIMARY_CONSUMPTION | PRODUCTION | EMISSIONS
    value_ej: float  # 艾焦耳 (Exajoules)
    value_mtoe: float | None = None  # 百万吨油当量 (Mtoe)
    source: str = "EI"  # EI | UNSD | IEA
    collected_at: str = ""


@dataclass(frozen=True)
class EnergyCrossSourceAuditRecord:
    """多源交叉对账与异常标记记录 (对应 energy_cross_source_audit.parquet)."""

    audit_date: date  # 审计执行日期
    audit_rule: str  # 审计规则名称 (如 TOTAL_CONSISTENCY, MIRROR_TRADE, CAPACITY_FACTOR)
    geo_code: str  # ISO-3 编码
    period: str  # 时间周期
    product: str  # 能源品类或技术
    source_a: str  # 数据源 A
    value_a: float  # 数据源 A 数值
    source_b: str  # 数据源 B
    value_b: float  # 数据源 B 数值
    diff_percent: float  # 相对差异比例 (abs(a - b) / mean(a, b))
    discrepancy_status: str  # PASS | FLAGGED | CRITICAL
    details: str = ""  # 差异诊断与说明


def records_to_oil_gas_balance_frame(records: list[GlobalOilGasBalanceRecord]) -> pl.DataFrame:
    """将月度油气供需平衡记录转换为强类型 Polars DataFrame."""
    if not records:
        return pl.DataFrame(
            schema={
                "geo_code": pl.Utf8,
                "trade_date": pl.Date,
                "period": pl.Utf8,
                "product": pl.Utf8,
                "flow_type": pl.Utf8,
                "standard_value": pl.Float64,
                "standard_unit": pl.Utf8,
                "raw_value": pl.Float64,
                "raw_unit": pl.Utf8,
                "source": pl.Utf8,
                "source_dataset": pl.Utf8,
                "data_status": pl.Utf8,
                "release_date": pl.Date,
                "collected_at": pl.Utf8,
            }
        )
    return pl.DataFrame([asdict(r) for r in records])


def records_to_power_generation_frame(records: list[GlobalPowerGenerationRecord]) -> pl.DataFrame:
    """将全球发电结构记录转换为强类型 Polars DataFrame."""
    if not records:
        return pl.DataFrame(
            schema={
                "geo_code": pl.Utf8,
                "trade_date": pl.Date,
                "period": pl.Utf8,
                "period_type": pl.Utf8,
                "technology": pl.Utf8,
                "generation_twh": pl.Float64,
                "yoy_growth": pl.Float64,
                "share_percent": pl.Float64,
                "emissions_mtco2": pl.Float64,
                "source": pl.Utf8,
                "data_status": pl.Utf8,
                "release_date": pl.Date,
                "collected_at": pl.Utf8,
            }
        )
    return pl.DataFrame([asdict(r) for r in records])


def records_to_renewable_capacity_frame(
    records: list[GlobalRenewableCapacityRecord],
) -> pl.DataFrame:
    """将全球可再生能源装机记录转换为强类型 Polars DataFrame."""
    if not records:
        return pl.DataFrame(
            schema={
                "geo_code": pl.Utf8,
                "year": pl.Int64,
                "technology": pl.Utf8,
                "capacity_gw": pl.Float64,
                "new_added_gw": pl.Float64,
                "yoy_growth": pl.Float64,
                "source": pl.Utf8,
                "data_status": pl.Utf8,
                "release_date": pl.Date,
                "collected_at": pl.Utf8,
            }
        )
    return pl.DataFrame([asdict(r) for r in records])


def records_to_macro_energy_baseline_frame(
    records: list[GlobalMacroEnergyBaselineRecord],
) -> pl.DataFrame:
    """将长周期全球能源基准记录转换为强类型 Polars DataFrame."""
    if not records:
        return pl.DataFrame(
            schema={
                "geo_code": pl.Utf8,
                "year": pl.Int64,
                "energy_type": pl.Utf8,
                "flow_type": pl.Utf8,
                "value_ej": pl.Float64,
                "value_mtoe": pl.Float64,
                "source": pl.Utf8,
                "collected_at": pl.Utf8,
            }
        )
    return pl.DataFrame([asdict(r) for r in records])


def records_to_energy_audit_frame(records: list[EnergyCrossSourceAuditRecord]) -> pl.DataFrame:
    """将多源对账审计记录转换为强类型 Polars DataFrame."""
    if not records:
        return pl.DataFrame(
            schema={
                "audit_date": pl.Date,
                "audit_rule": pl.Utf8,
                "geo_code": pl.Utf8,
                "period": pl.Utf8,
                "product": pl.Utf8,
                "source_a": pl.Utf8,
                "value_a": pl.Float64,
                "source_b": pl.Utf8,
                "value_b": pl.Float64,
                "diff_percent": pl.Float64,
                "discrepancy_status": pl.Utf8,
                "details": pl.Utf8,
            }
        )
    return pl.DataFrame([asdict(r) for r in records])
