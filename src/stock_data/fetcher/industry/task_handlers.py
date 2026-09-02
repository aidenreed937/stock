"""垂直产业简单端点处理器映射。"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.agriculture import (
    AgriculturePorkCollector,
    records_to_agriculture_pork_frame,
)
from stock_data.fetcher.industry.automotive import NevCollector, records_to_nev_frame
from stock_data.fetcher.industry.chemicals import (
    ChemicalsCollector,
    records_to_chemical_market_frame,
)
from stock_data.fetcher.industry.chemicals.capacity_utilization_10y import (
    ChemicalCapacityUtilization10Y,
)
from stock_data.fetcher.industry.chemicals.futures_hold_rank_collector import (
    FuturesHoldRankCollector,
)
from stock_data.fetcher.industry.chemicals.futures_inventory_collector import (
    FuturesInventoryCollector,
)
from stock_data.fetcher.industry.chemicals.spread_calculator import ChemicalSpreadCalculator
from stock_data.fetcher.industry.chemicals.weekly_survey_collector import (
    ChemicalWeeklySurveyCollector,
)
from stock_data.fetcher.industry.cloud import CloudCapexCollector, records_to_cloud_capex_frame
from stock_data.fetcher.industry.coal import CoalMarketCollector, records_to_coal_market_frame
from stock_data.fetcher.industry.consumer import (
    LiquorWholesaleCollector,
    records_to_liquor_wholesale_frame,
)
from stock_data.fetcher.industry.electronics import (
    ConsumerElectronicsCollector,
    records_to_consumer_electronics_frame,
)
from stock_data.fetcher.industry.machinery import MachineryCollector, records_to_machinery_frame
from stock_data.fetcher.industry.metals import NonFerrousCollector, records_to_metals_frame
from stock_data.fetcher.industry.pharma import PharmaBdCollector, records_to_pharma_bd_frame
from stock_data.fetcher.industry.power import (
    NbsSolarCellCollector,
    PvPriceChainCollector,
    SolarCollector,
    records_to_solar_cell_nbs_frame,
    records_to_solar_frame,
    records_to_solar_price_chain_frame,
)
from stock_data.fetcher.industry.semiconductor import (
    ChipLeadTimeCollector,
    FoundryUtilizationCollector,
    SeajEquipmentCollector,
    SemiconductorCollector,
    SemiEquipmentCollector,
    TsmcLeadCollector,
    records_to_chip_lead_time_frame,
    records_to_semiconductor_equipment_frame,
    records_to_semiconductor_frame,
    records_to_semiconductor_lead_frame,
)
from stock_data.fetcher.industry.semiconductor.inventory_collector import (
    SemiconductorInventoryCollector,
)
from stock_data.fetcher.industry.shipping import ShippingCollector, records_to_shipping_frame

RecordHandler = tuple[
    Callable[[Path, bool], Any],
    Callable[[Any], pl.DataFrame],
    str,
    list[str] | None,
]
FrameHandler = tuple[Callable[[Path, bool], pl.DataFrame], str, list[str]]


def collector(factory: type[Any], method: str = "collect") -> Callable[[Path, bool], Any]:
    """生成统一 raw_path/force 采集入口。"""

    def run(raw_path: Path, force: bool) -> Any:
        target = factory(raw_dir=raw_path)
        collect = getattr(target, method)
        try:
            return collect(force=force)
        except TypeError:
            return collect()

    return run


SIMPLE_RECORD_HANDLERS: dict[str, RecordHandler] = {
    "semiconductor_sales": (
        collector(SemiconductorCollector),
        records_to_semiconductor_frame,
        "semiconductor_sales.parquet",
        None,
    ),
    "semiconductor_equipment": (
        collector(SeajEquipmentCollector),
        records_to_semiconductor_equipment_frame,
        "semiconductor_equipment.parquet",
        None,
    ),
    "nev_monthly_sales": (
        collector(NevCollector),
        records_to_nev_frame,
        "nev_monthly_sales.parquet",
        None,
    ),
    "solar_capacity": (
        collector(SolarCollector),
        records_to_solar_frame,
        "solar_capacity.parquet",
        None,
    ),
    "non_ferrous_metals": (
        collector(NonFerrousCollector),
        records_to_metals_frame,
        "non_ferrous_metals.parquet",
        ["trade_date"],
    ),
    "pharma_license_out": (
        collector(PharmaBdCollector),
        records_to_pharma_bd_frame,
        "pharma_license_out.parquet",
        ["report_month"],
    ),
    "cloud_capex_quarterly": (
        collector(CloudCapexCollector),
        records_to_cloud_capex_frame,
        "cloud_capex_quarterly.parquet",
        ["report_quarter"],
    ),
    "construction_machinery": (
        collector(MachineryCollector),
        records_to_machinery_frame,
        "construction_machinery.parquet",
        ["report_month"],
    ),
    "shipping_indices": (
        collector(ShippingCollector),
        records_to_shipping_frame,
        "shipping_indices.parquet",
        ["trade_date"],
    ),
    "semiconductor_lead": (
        collector(TsmcLeadCollector),
        records_to_semiconductor_lead_frame,
        "semiconductor_lead.parquet",
        ["report_month"],
    ),
    "chip_lead_time": (
        collector(ChipLeadTimeCollector),
        records_to_chip_lead_time_frame,
        "chip_lead_time.parquet",
        ["report_month"],
    ),
    "chemical_market": (
        collector(ChemicalsCollector),
        records_to_chemical_market_frame,
        "chemical_market.parquet",
        ["report_month"],
    ),
    "solar_price_chain": (
        collector(PvPriceChainCollector),
        records_to_solar_price_chain_frame,
        "solar_price_chain.parquet",
        ["report_date"],
    ),
    "solar_cell_nbs": (
        collector(NbsSolarCellCollector),
        records_to_solar_cell_nbs_frame,
        "solar_cell_production.parquet",
        ["report_month"],
    ),
    "agriculture_pork": (
        collector(AgriculturePorkCollector),
        records_to_agriculture_pork_frame,
        "agriculture_pork.parquet",
        ["report_month"],
    ),
    "liquor_wholesale": (
        collector(LiquorWholesaleCollector),
        records_to_liquor_wholesale_frame,
        "liquor_wholesale.parquet",
        ["report_date"],
    ),
    "consumer_electronics": (
        collector(ConsumerElectronicsCollector),
        records_to_consumer_electronics_frame,
        "consumer_electronics.parquet",
        ["report_quarter"],
    ),
    "coal_market": (
        collector(CoalMarketCollector),
        records_to_coal_market_frame,
        "coal_market.parquet",
        ["report_date"],
    ),
}

SIMPLE_FRAME_HANDLERS: dict[str, FrameHandler] = {
    "semiconductor_equipment_semi": (
        collector(SemiEquipmentCollector),
        "semiconductor_equipment_semi.parquet",
        ["report_quarter"],
    ),
    "chemical_futures_inventory": (
        collector(FuturesInventoryCollector),
        "futures_inventory.parquet",
        ["symbol", "trade_date"],
    ),
    "chemical_weekly_survey": (
        collector(ChemicalWeeklySurveyCollector),
        "chemical_weekly_survey.parquet",
        ["product_name", "report_date"],
    ),
    "foundry_capacity_utilization": (
        collector(FoundryUtilizationCollector),
        "foundry_capacity_utilization.parquet",
        ["report_quarter"],
    ),
    "chemical_capacity_utilization_10y": (
        collector(ChemicalCapacityUtilization10Y, "build_10y_utilization"),
        "chemical_capacity_utilization_10y.parquet",
        ["trade_date"],
    ),
    "chemical_spreads": (
        collector(ChemicalSpreadCalculator, "build_historical_spreads"),
        "chemical_spreads.parquet",
        ["product_name", "trade_date"],
    ),
    "futures_hold_rank": (
        collector(FuturesHoldRankCollector),
        "futures_hold_rank.parquet",
        ["symbol", "trade_date"],
    ),
    "semiconductor_inventory_days": (
        collector(SemiconductorInventoryCollector),
        "semiconductor_inventory_days.parquet",
        ["report_quarter", "symbol"],
    ),
}
