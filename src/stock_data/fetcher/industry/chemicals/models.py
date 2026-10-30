"""化工产业数据记录模型。"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ChemicalMarketRecord:
    """基础化工真实基本面物理量事实记录。"""

    report_month: str
    trade_date: date
    soda_ash_production: float | None = None
    caustic_soda_production: float | None = None
    synthetic_fiber_production: float | None = None
    chemical_fertilizer_production: float | None = None
    plastics_production: float | None = None
    plate_glass_production: float | None = None
    spot_soda_ash_price_cny: float | None = None
    spot_pta_price_cny: float | None = None
    spot_urea_price_cny: float | None = None
    spot_mdi_price_cny: float | None = None
    spot_tio2_price_cny: float | None = None
    spot_refrigerant_r32_price_cny: float | None = None
    soda_ash_operating_rate: float | None = None
    pta_operating_rate: float | None = None
    chemical_social_inventory: float | None = None
    unit: str = "mixed"
    source: str = ""
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""
    raw_content_sha256: str = ""
    raw_snapshot_path: str = ""
    mdi_source: str = ""
    mdi_source_url: str = ""
    mdi_release_date: date | None = None
    mdi_raw_content_sha256: str = ""
    mdi_raw_snapshot_path: str = ""
    tio2_source: str = ""
    tio2_source_url: str = ""
    tio2_release_date: date | None = None
    tio2_raw_content_sha256: str = ""
    tio2_raw_snapshot_path: str = ""

    # 向后兼容别名属性
    @property
    def mdi_price_cny(self) -> float | None:
        return self.spot_mdi_price_cny

    @property
    def tio2_price_cny(self) -> float | None:
        return self.spot_tio2_price_cny

    @property
    def soda_ash_price_cny(self) -> float | None:
        return self.spot_soda_ash_price_cny

    @property
    def pta_price_cny(self) -> float | None:
        return self.spot_pta_price_cny

    @property
    def urea_price_cny(self) -> float | None:
        return self.spot_urea_price_cny

    @property
    def refrigerant_r32_price_cny(self) -> float | None:
        return self.spot_refrigerant_r32_price_cny


@dataclass(frozen=True)
class ChemicalSpotPriceRecord:
    """基础化工现货价格事实记录（出厂价/贸易基准价）。"""

    product_name: str
    symbol: str
    trade_date: date
    spot_price_cny: float
    spec: str = ""
    region: str = ""
    unit: str = "元/吨"
    source: str = ""
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""
    raw_content_sha256: str = ""
    raw_snapshot_path: str = ""


@dataclass(frozen=True)
class ChemicalFuturesDailyRecord:
    """基础化工期货交易所日度行情记录。"""

    symbol: str
    contract: str
    trade_date: date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    settle: float | None = None
    volume: float | None = None
    open_interest: float | None = None
    unit: str = "元/吨"
    exchange: str = ""
    source: str = "exchange_daily"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""
    raw_content_sha256: str = ""
    raw_snapshot_path: str = ""


__all__ = [
    "ChemicalFuturesDailyRecord",
    "ChemicalMarketRecord",
    "ChemicalSpotPriceRecord",
]
