"""基础化工真实基本面事实数据 (NBS产量 + 交易所仓单 + 下游需求) Schema 定义与转换器。"""

from collections.abc import Sequence
from datetime import UTC, datetime

import polars as pl

from stock_data.fetcher.industry.chemicals.models import ChemicalMarketRecord
from stock_data.fetcher.industry.chemicals.schemas import (
    CHEMICAL_MARKET_RAW_SCHEMA,
    CHEMICAL_MARKET_SCHEMA,
)


def empty_chemical_market() -> pl.DataFrame:
    """构造基础化工市场空事实表骨架。"""
    return pl.DataFrame(schema=CHEMICAL_MARKET_SCHEMA)


def empty_raw_chemical_market() -> pl.DataFrame:
    """构造化工市场 RAW 空事实表骨架。"""
    return pl.DataFrame(schema=CHEMICAL_MARKET_RAW_SCHEMA)


def _raw_text(value: object) -> str | None:
    return None if value is None else str(value)


def records_to_raw_chemical_market_frame(
    records: Sequence[ChemicalMarketRecord],
) -> pl.DataFrame:
    """保留源端值文本与快照血缘，不计算派生指标。"""
    if not records:
        return empty_raw_chemical_market()

    def values(field: str) -> list[object]:
        return [_raw_text(getattr(record, field)) for record in records]

    data: dict[str, list[object]] = {
        "report_month": [record.report_month for record in records],
        "trade_date": [record.trade_date for record in records],
        **{
            f"{field}_raw": values(field)
            for field in (
                "soda_ash_production",
                "caustic_soda_production",
                "synthetic_fiber_production",
                "chemical_fertilizer_production",
                "plastics_production",
                "plate_glass_production",
                "spot_soda_ash_price_cny",
                "spot_pta_price_cny",
                "spot_urea_price_cny",
                "spot_mdi_price_cny",
                "spot_tio2_price_cny",
                "spot_refrigerant_r32_price_cny",
                "soda_ash_operating_rate",
                "pta_operating_rate",
                "chemical_social_inventory",
            )
        },
        "unit": [record.unit or "mixed" for record in records],
        "source": [record.source for record in records],
        "source_url": [record.source_url or "" for record in records],
        "release_date": [record.release_date for record in records],
        "data_status": [record.data_status or "actual" for record in records],
        "collected_at": [record.collected_at for record in records],
        "raw_content_sha256": [record.raw_content_sha256 for record in records],
        "raw_snapshot_path": [record.raw_snapshot_path for record in records],
        "mdi_source": [record.mdi_source for record in records],
        "mdi_source_url": [record.mdi_source_url for record in records],
        "mdi_release_date": [record.mdi_release_date for record in records],
        "mdi_raw_content_sha256": [record.mdi_raw_content_sha256 for record in records],
        "mdi_raw_snapshot_path": [record.mdi_raw_snapshot_path for record in records],
        "tio2_source": [record.tio2_source for record in records],
        "tio2_source_url": [record.tio2_source_url for record in records],
        "tio2_release_date": [record.tio2_release_date for record in records],
        "tio2_raw_content_sha256": [record.tio2_raw_content_sha256 for record in records],
        "tio2_raw_snapshot_path": [record.tio2_raw_snapshot_path for record in records],
    }
    return (
        pl.DataFrame(data, schema=CHEMICAL_MARKET_RAW_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )


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
        "spot_soda_ash_price_cny": [r.spot_soda_ash_price_cny for r in records],
        "spot_pta_price_cny": [r.spot_pta_price_cny for r in records],
        "spot_urea_price_cny": [r.spot_urea_price_cny for r in records],
        "spot_mdi_price_cny": [r.spot_mdi_price_cny for r in records],
        "spot_tio2_price_cny": [r.spot_tio2_price_cny for r in records],
        "spot_refrigerant_r32_price_cny": [r.spot_refrigerant_r32_price_cny for r in records],
        "soda_ash_operating_rate": [r.soda_ash_operating_rate for r in records],
        "pta_operating_rate": [r.pta_operating_rate for r in records],
        "chemical_social_inventory": [r.chemical_social_inventory for r in records],
        "unit": [r.unit or "mixed" for r in records],
        "source": [r.source for r in records],
        "source_url": [r.source_url or "" for r in records],
        "release_date": [r.release_date for r in records],
        "data_status": [r.data_status or "actual" for r in records],
        "collected_at": [r.collected_at or now_iso for r in records],
        "mdi_source": [r.mdi_source for r in records],
        "mdi_source_url": [r.mdi_source_url for r in records],
        "mdi_release_date": [r.mdi_release_date for r in records],
        "tio2_source": [r.tio2_source for r in records],
        "tio2_source_url": [r.tio2_source_url for r in records],
        "tio2_release_date": [r.tio2_release_date for r in records],
    }

    return (
        pl.DataFrame(data, schema=CHEMICAL_MARKET_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
