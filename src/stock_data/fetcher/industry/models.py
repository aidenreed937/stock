"""垂直产业景气指标契约模型 (含显式计量单位、数据血统与状态元数据)。"""

from stock_data.fetcher.industry.agriculture.models import AgriculturePorkRecord
from stock_data.fetcher.industry.automotive.models import NevMonthlyRecord
from stock_data.fetcher.industry.chemicals.models import ChemicalMarketRecord
from stock_data.fetcher.industry.cloud.models import CloudCapexRecord
from stock_data.fetcher.industry.coal.models import CoalMarketRecord
from stock_data.fetcher.industry.consumer.models import LiquorWholesaleRecord
from stock_data.fetcher.industry.customs.models import CustomsTradeRecord
from stock_data.fetcher.industry.electronics.models import ConsumerElectronicsRecord
from stock_data.fetcher.industry.machinery.models import ConstructionMachineryRecord
from stock_data.fetcher.industry.metals.models import NonFerrousMetalsRecord
from stock_data.fetcher.industry.pharma.models import (
    PharmaBdAssetRecord,
    PharmaBdDealRecord,
    PharmaBdEventRecord,
    PharmaLicenseOutRecord,
)
from stock_data.fetcher.industry.power.models import (
    PolysiliconBalanceRecord,
    PolysiliconInventoryMonthlyRecord,
    PolysiliconSupplyMonthlyRecord,
    PvWaferMonthlyRecord,
    SiliconWaferMonthlyRecord,
    SolarCapacityRecord,
    SolarCellNbsRecord,
    SolarPriceChainRecord,
    SolarSupplyDemandRecord,
)
from stock_data.fetcher.industry.semiconductor.models import (
    ChipLeadTimeRecord,
    SemiconductorEquipmentRecord,
    SemiconductorInventoryRecord,
    SemiconductorLeadRecord,
    SemiconductorSalesRecord,
)
from stock_data.fetcher.industry.shipping.models import ShippingIndicesRecord

__all__ = [
    "AgriculturePorkRecord",
    "ChemicalMarketRecord",
    "ChipLeadTimeRecord",
    "CloudCapexRecord",
    "CoalMarketRecord",
    "ConstructionMachineryRecord",
    "ConsumerElectronicsRecord",
    "CustomsTradeRecord",
    "LiquorWholesaleRecord",
    "NevMonthlyRecord",
    "NonFerrousMetalsRecord",
    "PharmaBdAssetRecord",
    "PharmaBdDealRecord",
    "PharmaBdEventRecord",
    "PharmaLicenseOutRecord",
    "PolysiliconBalanceRecord",
    "PolysiliconInventoryMonthlyRecord",
    "PolysiliconSupplyMonthlyRecord",
    "PvWaferMonthlyRecord",
    "SemiconductorEquipmentRecord",
    "SemiconductorInventoryRecord",
    "SemiconductorLeadRecord",
    "SemiconductorSalesRecord",
    "ShippingIndicesRecord",
    "SiliconWaferMonthlyRecord",
    "SolarCapacityRecord",
    "SolarCellNbsRecord",
    "SolarPriceChainRecord",
    "SolarSupplyDemandRecord",
]
