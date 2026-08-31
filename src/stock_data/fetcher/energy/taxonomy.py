"""全球能源分类法、国家/地区代码对齐与单位换算矩阵。"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class EnergyProduct(StrEnum):
    """全球统一能源产品与技术分类枚举。"""

    # 化石能源
    CRUDE_OIL = "CRUDE_OIL"
    OIL_PRODUCTS = "OIL_PRODUCTS"
    NATURAL_GAS = "NATURAL_GAS"
    LNG = "LNG"
    COAL = "COAL"
    THERMAL_POWER = "THERMAL_POWER"  # 火电/化石发电

    # 可再生与清洁能源
    SOLAR_PV = "SOLAR_PV"
    SOLAR_CSP = "SOLAR_CSP"  # 光热发电 / 聚光太阳能
    WIND_ONSHORE = "WIND_ONSHORE"
    WIND_OFFSHORE = "WIND_OFFSHORE"
    WIND_TOTAL = "WIND_TOTAL"
    HYDRO = "HYDRO"
    PUMPED_STORAGE = "PUMPED_STORAGE"  # 抽水蓄能
    NUCLEAR = "NUCLEAR"
    BIOENERGY = "BIOENERGY"
    GEOTHERMAL = "GEOTHERMAL"
    CLEAN_ENERGY_TOTAL = "CLEAN_ENERGY_TOTAL"

    # 总量
    TOTAL_ELECTRICITY = "TOTAL_ELECTRICITY"
    TOTAL_PRIMARY_ENERGY = "TOTAL_PRIMARY_ENERGY"


class EnergyFlowType(StrEnum):
    """能源流动与度量类型枚举。"""

    PRODUCTION = "PRODUCTION"  # 产量 / 发电量
    CONSUMPTION = "CONSUMPTION"  # 消费量 / 需求量
    IMPORT = "IMPORT"  # 进口量
    EXPORT = "EXPORT"  # 出口量
    NET_IMPORT = "NET_IMPORT"  # 净进口量
    CLOSING_STOCK = "CLOSING_STOCK"  # 期末显性库存
    STOCK_CHANGE = "STOCK_CHANGE"  # 库存变动
    REFINERY_INP = "REFINERY_INP"  # 炼厂加工投入
    REFINERY_OUT = "REFINERY_OUT"  # 炼厂产出
    INSTALLED_CAPACITY = "INSTALLED_CAPACITY"  # 累计装机容量
    NEW_CAPACITY = "NEW_CAPACITY"  # 新增装机容量
    EMISSIONS = "EMISSIONS"  # 碳排放量


class DataStatus(StrEnum):
    """数据状态与可信度等级。"""

    ACTUAL = "actual"  # 官方最终核定实际值
    PROVISIONAL = "provisional"  # 初步核算值
    ESTIMATED = "estimated"  # 机构模型估算值
    FORECAST = "forecast"  # 预测展望值
    REVISED = "revised"  # 历史修订值


class PeriodType(StrEnum):
    """时间粒度枚举。"""

    YEARLY = "yearly"  # YYYY
    MONTHLY = "monthly"  # YYYY-MM
    WEEKLY = "weekly"  # YYYY-Www
    DAILY = "daily"  # YYYY-MM-DD
    HOURLY = "hourly"  # YYYY-MM-DDTHH


# 常见国家及主要经济体别名到 ISO 3166-1 alpha-3 / 标准区域码映射
GEO_CODE_MAPPING: Final[dict[str, str]] = {
    # 全球与区域
    "WORLD": "WLD",
    "TOTAL WORLD": "WLD",
    "GLOBAL": "WLD",
    "WLD": "WLD",
    "EUROPEAN UNION": "EU27",
    "EU": "EU27",
    "EU27": "EU27",
    "EU28": "EU27",
    "OPEC": "OPEC",
    "OECD": "OECD",
    # 中国
    "CHINA": "CHN",
    "PRC": "CHN",
    "PEOPLE'S REPUBLIC OF CHINA": "CHN",
    "CHN": "CHN",
    "CN": "CHN",
    "中国": "CHN",
    # 美国
    "UNITED STATES": "USA",
    "USA": "USA",
    "US": "USA",
    "UNITED STATES OF AMERICA": "USA",
    "美国": "USA",
    # 欧洲主要国
    "GERMANY": "DEU",
    "DEU": "DEU",
    "DE": "DEU",
    "德国": "DEU",
    "FRANCE": "FRA",
    "FRA": "FRA",
    "FR": "FRA",
    "法国": "FRA",
    "UNITED KINGDOM": "GBR",
    "UK": "GBR",
    "GBR": "GBR",
    "英国": "GBR",
    "ITALY": "ITA",
    "ITA": "ITA",
    "SPAIN": "ESP",
    "ESP": "ESP",
    "NETHERLANDS": "NLD",
    "NLD": "NLD",
    # 亚洲主要国
    "JAPAN": "JPN",
    "JPN": "JPN",
    "JP": "JPN",
    "日本": "JPN",
    "INDIA": "IND",
    "IND": "IND",
    "IN": "IND",
    "印度": "IND",
    "SOUTH KOREA": "KOR",
    "KOREA": "KOR",
    "KOR": "KOR",
    "KR": "KOR",
    "韩国": "KOR",
    # 美洲/大洋洲/中东/其他
    "RUSSIA": "RUS",
    "RUSSIAN FEDERATION": "RUS",
    "RUSSIAN FED": "RUS",
    "RUS": "RUS",
    "俄罗斯": "RUS",
    "SAUDI ARABIA": "SAU",
    "SAU": "SAU",
    "沙特阿拉伯": "SAU",
    "BRAZIL": "BRA",
    "BRA": "BRA",
    "巴西": "BRA",
    "AUSTRALIA": "AUS",
    "AUS": "AUS",
    "澳大利亚": "AUS",
    "CANADA": "CAN",
    "CAN": "CAN",
    "加拿大": "CAN",
    "VIET NAM": "VNM",
    "VIETNAM": "VNM",
    "VNM": "VNM",
    "INDONESIA": "IDN",
    "IDN": "IDN",
    "MEXICO": "MEX",
    "MEX": "MEX",
    "TURKEY": "TUR",
    "TÜRKIYE": "TUR",
    "TURKIYE": "TUR",
    "TUR": "TUR",
    "SOUTH AFRICA": "ZAF",
    "ZAF": "ZAF",
    "IRAN": "IRN",
    "IRAN (ISLAMIC REPUBLIC OF)": "IRN",
    "IRAN IR": "IRN",
    "IRN": "IRN",
    "NORWAY": "NOR",
    "NOR": "NOR",
    "SWEDEN": "SWE",
    "SWE": "SWE",
    "DENMARK": "DNK",
    "DNK": "DNK",
    "CHILE": "CHL",
    "CHL": "CHL",
}


def normalize_geo_code(raw_geo: str) -> str:
    """标准化国家与地区名称为 ISO-3 编码或统一区域码。

    若无法识别，返回去除空格后的全大写字符串。
    """
    key = raw_geo.strip().upper()
    return GEO_CODE_MAPPING.get(key, key)


# 发电量基准换算系数 -> TWh (Terawatt-hour)
GENERATION_TO_TWH: Final[dict[str, float]] = {
    "TWH": 1.0,
    "GWH": 0.001,
    "MWH": 1e-6,
    "KWH": 1e-9,
    "BILLION_KWH": 1.0,  # 10亿度 = 1 TWh
    "TEN_THOUSAND_KWH": 1e-8,  # 万度
}

# 容量基准换算系数 -> GW (Gigawatt)
CAPACITY_TO_GW: Final[dict[str, float]] = {
    "GW": 1.0,
    "MW": 0.001,
    "KW": 1e-6,
    "W": 1e-9,
    "TEN_THOUSAND_KW": 0.01,  # 万千瓦 = 0.01 GW
    "MILLION_KW": 1.0,  # 百万千瓦 (吉瓦) = 1 GW
}

# 石油流量换算系数 -> kbpd (千桶/日)
OIL_FLOW_TO_KBPD: Final[dict[str, float]] = {
    "KBPD": 1.0,
    "KBD": 1.0,
    "BPD": 0.001,
    "BBL/D": 0.001,
    "TB/D": 1.0,
}

# 天然气流量换算系数 -> bcm (十亿立方米, Billion Cubic Metres)
GAS_FLOW_TO_BCM: Final[dict[str, float]] = {
    "BCM": 1.0,
    "MCM": 0.001,
    "BCF": 0.0283168,  # 1 Bcf ≈ 0.0283168 BCM
    "MCF": 2.83168e-5,
}

# 宏观综合能耗换算系数 -> EJ (艾焦耳, Exajoules)
ENERGY_TO_EJ: Final[dict[str, float]] = {
    "EJ": 1.0,
    "EXAJOULES": 1.0,
    "PJ": 0.001,
    "MTOE": 0.041868,  # 1 Mtoe ≈ 0.041868 EJ
    "TWH": 0.0036,  # 1 TWh = 3.6 PJ = 0.0036 EJ
}


def convert_generation_to_twh(value: float, raw_unit: str) -> float:
    """将各类发电量单位转换为标准 TWh。"""
    factor = GENERATION_TO_TWH.get(raw_unit.strip().upper())
    if factor is None:
        raise ValueError(f"不支持的发电量单位: {raw_unit}")
    return value * factor


def convert_capacity_to_gw(value: float, raw_unit: str) -> float:
    """将各类装机容量单位转换为标准 GW。"""
    factor = CAPACITY_TO_GW.get(raw_unit.strip().upper())
    if factor is None:
        raise ValueError(f"不支持的容量单位: {raw_unit}")
    return value * factor


def convert_oil_flow_to_kbpd(value: float, raw_unit: str) -> float:
    """将各类石油流量转换为标准 kbpd (千桶/日)。"""
    factor = OIL_FLOW_TO_KBPD.get(raw_unit.strip().upper())
    if factor is None:
        raise ValueError(f"不支持的石油流量单位: {raw_unit}")
    return value * factor


def convert_gas_flow_to_bcm(value: float, raw_unit: str) -> float:
    """将各类天然气流量转换为标准 bcm (十亿立方米)。"""
    factor = GAS_FLOW_TO_BCM.get(raw_unit.strip().upper())
    if factor is None:
        raise ValueError(f"不支持的天然气流量单位: {raw_unit}")
    return value * factor


def convert_energy_to_ej(value: float, raw_unit: str) -> float:
    """将宏观综合能耗转换为标准 EJ (艾焦耳)。"""
    factor = ENERGY_TO_EJ.get(raw_unit.strip().upper())
    if factor is None:
        raise ValueError(f"不支持的宏观能耗单位: {raw_unit}")
    return value * factor
