"""Ember 全球电力与发电结构数据集常量与映射字典。"""

from __future__ import annotations

from typing import Final

from stock_data.fetcher.energy.taxonomy import EnergyProduct

# Ember 官方公开长期有效直链 (CC-BY-4.0 开放数据集)
EMBER_YEARLY_FULL_URL: Final[str] = (
    "https://files.ember-energy.org/public-downloads/yearly_full_release_long_format.csv"
)
EMBER_MONTHLY_FULL_URL: Final[str] = (
    "https://files.ember-energy.org/public-downloads/monthly_full_release_long_format.csv"
)

# Ember Variable 到 EnergyProduct 标准技术枚举映射
EMBER_TECH_MAPPING: Final[dict[str, str]] = {
    "Solar": EnergyProduct.SOLAR_PV,
    "Wind": EnergyProduct.WIND_TOTAL,
    "Hydro": EnergyProduct.HYDRO,
    "Nuclear": EnergyProduct.NUCLEAR,
    "Coal": EnergyProduct.COAL,
    "Gas": EnergyProduct.NATURAL_GAS,
    "Bioenergy": EnergyProduct.BIOENERGY,
    "Clean": EnergyProduct.CLEAN_ENERGY_TOTAL,
    "Fossil": EnergyProduct.THERMAL_POWER,
    "Total Generation": EnergyProduct.TOTAL_ELECTRICITY,
}
