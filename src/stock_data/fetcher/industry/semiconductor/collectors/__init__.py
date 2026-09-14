"""半导体产业采集器。"""

from stock_data.fetcher.industry.semiconductor.collectors.adv_pkg_revenue import (
    TsmcAdvancedPackagingRevenueCollector,
)
from stock_data.fetcher.industry.semiconductor.collectors.channel_inventory import (
    ChannelInventoryCollector,
)
from stock_data.fetcher.industry.semiconductor.collectors.cowos_estimates import (
    CowosCapacityEstimatesCollector,
)
from stock_data.fetcher.industry.semiconductor.collectors.datatrack_memory import (
    DataTrackMemoryPriceCollector,
)
from stock_data.fetcher.industry.semiconductor.collectors.equipment_gm import (
    AmatEquipmentGmCollector,
    EquipmentGmSecCollector,
    KlacEquipmentGmCollector,
    LrcxEquipmentGmCollector,
    TelEquipmentGmCollector,
)
from stock_data.fetcher.industry.semiconductor.collectors.foundry_crawler import (
    FoundryUtilizationCrawler,
)
from stock_data.fetcher.industry.semiconductor.collectors.foundry_utilization import (
    FoundryUtilizationCollector,
)
from stock_data.fetcher.industry.semiconductor.collectors.inventory import (
    SemiconductorInventoryCollector,
)
from stock_data.fetcher.industry.semiconductor.collectors.korea_memory_dart import (
    KoreaMemoryDartCollector,
)
from stock_data.fetcher.industry.semiconductor.collectors.lead_time import ChipLeadTimeCollector
from stock_data.fetcher.industry.semiconductor.collectors.memory_price import MemoryPriceCollector
from stock_data.fetcher.industry.semiconductor.collectors.sales import SemiconductorCollector
from stock_data.fetcher.industry.semiconductor.collectors.seaj import SeajEquipmentCollector
from stock_data.fetcher.industry.semiconductor.collectors.semi import SemiEquipmentCollector
from stock_data.fetcher.industry.semiconductor.collectors.semi_crawler import SemiEquipmentCrawler
from stock_data.fetcher.industry.semiconductor.collectors.susquehanna import (
    SusquehannaLeadTimeCollector,
)
from stock_data.fetcher.industry.semiconductor.collectors.taiwan_memory import (
    TaiwanMemoryLeadCollector,
)
from stock_data.fetcher.industry.semiconductor.collectors.tsmc import TsmcLeadCollector
from stock_data.fetcher.industry.semiconductor.collectors.tsmc_adv_pkg_crawler import (
    TsmcAdvPkgRevenueCrawler,
)
from stock_data.fetcher.industry.semiconductor.collectors.wayback_memory_benchmark import (
    WaybackMemoryPriceBenchmarkCollector,
)

__all__ = [
    "AmatEquipmentGmCollector",
    "ChannelInventoryCollector",
    "ChipLeadTimeCollector",
    "CowosCapacityEstimatesCollector",
    "DataTrackMemoryPriceCollector",
    "EquipmentGmSecCollector",
    "FoundryUtilizationCollector",
    "FoundryUtilizationCrawler",
    "KlacEquipmentGmCollector",
    "KoreaMemoryDartCollector",
    "LrcxEquipmentGmCollector",
    "MemoryPriceCollector",
    "SeajEquipmentCollector",
    "SemiEquipmentCollector",
    "SemiEquipmentCrawler",
    "SemiconductorCollector",
    "SemiconductorInventoryCollector",
    "SusquehannaLeadTimeCollector",
    "TaiwanMemoryLeadCollector",
    "TelEquipmentGmCollector",
    "TsmcAdvPkgRevenueCrawler",
    "TsmcAdvancedPackagingRevenueCollector",
    "TsmcLeadCollector",
    "WaybackMemoryPriceBenchmarkCollector",
]
