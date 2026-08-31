"""IRENA (国际可再生能源署) 常量与技术映射表。"""

from __future__ import annotations

from typing import Final

from stock_data.fetcher.energy.taxonomy import EnergyProduct

IRENA_BASE_URL: Final[str] = "https://www.irena.org"
IRENA_TOOLS_URL: Final[str] = "https://www.irena.org/Data/Downloads/Tools"
IRENA_PXWEB_URL: Final[str] = "https://pxweb.irena.org"

# IRENA 26 种官方细分技术名称到标准 EnergyProduct 枚举的映射表
IRENA_TECH_MAPPING: Final[dict[str, EnergyProduct]] = {
    # 太阳能
    "Solar photovoltaic": EnergyProduct.SOLAR_PV,
    "Solar energy": EnergyProduct.SOLAR_PV,
    "Solar thermal energy": EnergyProduct.SOLAR_CSP,
    "Concentrated solar power": EnergyProduct.SOLAR_CSP,
    # 风电
    "Onshore wind energy": EnergyProduct.WIND_ONSHORE,
    "Offshore wind energy": EnergyProduct.WIND_OFFSHORE,
    "Wind energy": EnergyProduct.WIND_TOTAL,
    # 水电与抽水蓄能
    "Renewable hydropower": EnergyProduct.HYDRO,
    "Renewable hydropower (including mixed plants)": EnergyProduct.HYDRO,
    "Hydropower": EnergyProduct.HYDRO,
    "Pure pumped storage": EnergyProduct.PUMPED_STORAGE,
    "Pumped hydro": EnergyProduct.PUMPED_STORAGE,
    # 生物质能
    "Bioenergy": EnergyProduct.BIOENERGY,
    "Solid biofuels": EnergyProduct.BIOENERGY,
    "Liquid biofuels": EnergyProduct.BIOENERGY,
    "Gas biofuels": EnergyProduct.BIOENERGY,
    "Renewable waste": EnergyProduct.BIOENERGY,
    # 地热
    "Geothermal energy": EnergyProduct.GEOTHERMAL,
    # 总量
    "Total renewable energy": EnergyProduct.CLEAN_ENERGY_TOTAL,
    "Total non-renewable energy": EnergyProduct.THERMAL_POWER,
    "Nuclear energy": EnergyProduct.NUCLEAR,
}
