"""化工产业分源采集器。"""

from stock_data.fetcher.industry.chemicals.collectors.capacity import (
    ChemicalCapacityUtilization10Y,
    NbsChemicalsCrawler,
    NbsSodaAshCrawler,
)
from stock_data.fetcher.industry.chemicals.collectors.commodity_index import (
    DEFAULT_COMMODITY_CONFIG,
    CommodityIndexCollector,
)
from stock_data.fetcher.industry.chemicals.collectors.eastmoney_report import (
    EastmoneyReportCollector,
)
from stock_data.fetcher.industry.chemicals.collectors.futures_hold_rank import (
    FuturesHoldRankCollector,
)
from stock_data.fetcher.industry.chemicals.collectors.futures_price import (
    FuturesPriceCollector,
)
from stock_data.fetcher.industry.chemicals.collectors.inventory import (
    FuturesInventoryCollector,
)
from stock_data.fetcher.industry.chemicals.collectors.market import ChemicalsCollector
from stock_data.fetcher.industry.chemicals.collectors.monthly_survey import (
    ChemicalMonthlySurveyCollector,
)
from stock_data.fetcher.industry.chemicals.collectors.spot_price import (
    COMMODITY_CATALOG,
    ChemicalSpotPriceCollector,
)
from stock_data.fetcher.industry.chemicals.collectors.spreads import ChemicalSpreadCalculator
from stock_data.fetcher.industry.chemicals.collectors.weekly_survey import (
    ChemicalWeeklySurveyCollector,
)

__all__ = [
    "COMMODITY_CATALOG",
    "DEFAULT_COMMODITY_CONFIG",
    "ChemicalCapacityUtilization10Y",
    "ChemicalMonthlySurveyCollector",
    "ChemicalSpotPriceCollector",
    "ChemicalSpreadCalculator",
    "ChemicalWeeklySurveyCollector",
    "ChemicalsCollector",
    "CommodityIndexCollector",
    "EastmoneyReportCollector",
    "FuturesHoldRankCollector",
    "FuturesInventoryCollector",
    "FuturesPriceCollector",
    "NbsChemicalsCrawler",
    "NbsSodaAshCrawler",
]
