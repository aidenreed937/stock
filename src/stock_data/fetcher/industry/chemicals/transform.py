"""基础化工真实基本面事实数据 (NBS产量 + 交易所仓单 + 下游需求) Schema 定义与转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.models import ChemicalMarketRecord

CHEMICAL_MARKET_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    # 1. NBS 官方月度工业品产量 (万吨 / 万重箱)
    "soda_ash_production": pl.Float64,
    "caustic_soda_production": pl.Float64,
    "synthetic_fiber_production": pl.Float64,
    "chemical_fertilizer_production": pl.Float64,
    "plastics_production": pl.Float64,
    "plate_glass_production": pl.Float64,
    # 2. 期货交易所注册仓单 (张)
    "czce_soda_ash_receipt": pl.Float64,
    "czce_pta_receipt": pl.Float64,
    "czce_urea_receipt": pl.Float64,
    # 3. 真实基准现货价 (元/吨)
    "soda_ash_price_cny": pl.Float64,
    "pta_price_cny": pl.Float64,
    "urea_price_cny": pl.Float64,
    "mdi_price_cny": pl.Float64,
    "tio2_price_cny": pl.Float64,
    "refrigerant_r32_price_cny": pl.Float64,
    # 4. 未授权商业源字段 (默认保持 NULL)
    "soda_ash_operating_rate": pl.Float64,
    "pta_operating_rate": pl.Float64,
    "chemical_social_inventory": pl.Float64,
    # 元数据
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}


def empty_chemical_market() -> pl.DataFrame:
    """构造基础化工市场空事实表骨架。"""
    return pl.DataFrame(schema=CHEMICAL_MARKET_SCHEMA)


def records_to_chemical_market_frame(
    records: Sequence[ChemicalMarketRecord],
) -> pl.DataFrame:
    """将基础化工真实物理量记录转换为强类型 Polars DataFrame。"""
    if not records:
        return empty_chemical_market()

    now_iso = datetime.now(UTC).isoformat()
    data = {
        "report_month": [r.report_month for r in records],
        "trade_date": [r.trade_date for r in records],
        "soda_ash_production": [r.soda_ash_production for r in records],
        "caustic_soda_production": [r.caustic_soda_production for r in records],
        "synthetic_fiber_production": [r.synthetic_fiber_production for r in records],
        "chemical_fertilizer_production": [r.chemical_fertilizer_production for r in records],
        "plastics_production": [r.plastics_production for r in records],
        "plate_glass_production": [r.plate_glass_production for r in records],
        "czce_soda_ash_receipt": [r.czce_soda_ash_receipt for r in records],
        "czce_pta_receipt": [r.czce_pta_receipt for r in records],
        "czce_urea_receipt": [r.czce_urea_receipt for r in records],
        "soda_ash_price_cny": [r.soda_ash_price_cny for r in records],
        "pta_price_cny": [r.pta_price_cny for r in records],
        "urea_price_cny": [r.urea_price_cny for r in records],
        "mdi_price_cny": [r.mdi_price_cny for r in records],
        "tio2_price_cny": [r.tio2_price_cny for r in records],
        "refrigerant_r32_price_cny": [r.refrigerant_r32_price_cny for r in records],
        "soda_ash_operating_rate": [r.soda_ash_operating_rate for r in records],
        "pta_operating_rate": [r.pta_operating_rate for r in records],
        "chemical_social_inventory": [r.chemical_social_inventory for r in records],
        "unit": [r.unit or "mixed" for r in records],
        "source": [r.source or "NBS/CZCE/100ppi" for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
    }

    return (
        pl.DataFrame(data, schema=CHEMICAL_MARKET_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
