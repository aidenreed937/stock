"""半导体产业采集器。"""

from stock_data.fetcher.industry.semiconductor.collectors.channel_inventory import (
    ChannelInventoryCollector,
)
from stock_data.fetcher.industry.semiconductor.collectors.datatrack_memory import (
    DataTrackMemoryPriceCollector,
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
from stock_data.fetcher.industry.semiconductor.collectors.lead_time import ChipLeadTimeCollector
from stock_data.fetcher.industry.semiconductor.collectors.memory_price import MemoryPriceCollector
from stock_data.fetcher.industry.semiconductor.collectors.sales import SemiconductorCollector
from stock_data.fetcher.industry.semiconductor.collectors.seaj import SeajEquipmentCollector
from stock_data.fetcher.industry.semiconductor.collectors.semi import SemiEquipmentCollector
from stock_data.fetcher.industry.semiconductor.collectors.semi_crawler import SemiEquipmentCrawler
from stock_data.fetcher.industry.semiconductor.collectors.taiwan_memory import (
    TaiwanMemoryLeadCollector,
)
from stock_data.fetcher.industry.semiconductor.collectors.tsmc import TsmcLeadCollector

__all__ = [
    "ChannelInventoryCollector",
    "ChipLeadTimeCollector",
    "DataTrackMemoryPriceCollector",
    "FoundryUtilizationCollector",
    "FoundryUtilizationCrawler",
    "MemoryPriceCollector",
    "SeajEquipmentCollector",
    "SemiEquipmentCollector",
    "SemiEquipmentCrawler",
    "SemiconductorCollector",
    "SemiconductorInventoryCollector",
    "TaiwanMemoryLeadCollector",
    "TsmcLeadCollector",
]
