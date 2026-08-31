"""国家能源局 (NEA) 电力与新能源数据常量与指标映射字典。"""

from __future__ import annotations

from typing import Final

NEA_BASE_URL: Final[str] = "https://www.nea.gov.cn"
NEA_NEWS_URL: Final[str] = "https://www.nea.gov.cn/xwfb/index.htm"

NEA_SCAN_CHANNELS: Final[list[str]] = [
    "https://www.nea.gov.cn/xwfb/index.htm",
    "https://www.nea.gov.cn/xwfb/index_2.htm",
    "https://www.nea.gov.cn/xwfb/index_3.htm",
    "https://www.nea.gov.cn/index.htm",
]

# 官方已核定的历史各年份与月份统计数据直链池 (2014~2026 连续历史)
NEA_HISTORICAL_URLS: Final[list[str]] = [
    # 2026
    "https://www.nea.gov.cn/20260825/1430d07985474c5b8110552785f1c74b/c.html",  # 2026-07
    # 2025
    "https://www.nea.gov.cn/20251226/640306962d7d421b921b902f48a04b47/c.html",  # 2025-11
    "https://www.nea.gov.cn/20251125/c08a5f9b4a54481696a432ecd6c70dd3/c.html",  # 2025-10
    "https://www.nea.gov.cn/20251026/70d3b88f62f1401bbe47a8212e06ad8e/c.html",  # 2025-09
    "https://www.nea.gov.cn/20250823/7e111f0a60ac44438346bd8332db345e/c.html",  # 2025-07
    "https://www.nea.gov.cn/20250723/d7a5d6cc916e40bcb04c7d7e74d03213/c.html",  # 2025-06
    "https://www.nea.gov.cn/20250522/ba33708cb5e749378a21c955170069c1/c.html",  # 2025-04
    "https://www.nea.gov.cn/20250320/977e24cb6295485fb6283d656c70bcc3/c.html",  # 2025-02
    # 2024
    "https://www.nea.gov.cn/20250121/097bfd7c1cd3498897639857d86d5dac/c.html",  # 2024-12 (2024全年)
    "https://www.nea.gov.cn/20241220/73f189cc6e6540caafac2b819623fc08/c.html",  # 2024-11
    "https://www.nea.gov.cn/2024-10/21/c_1212405574.htm",  # 2024-09
    "http://www.nea.gov.cn/2024-07/20/c_1310782235.htm",  # 2024-06
    # 2023
    "https://www.nea.gov.cn/2024-01/26/c_1310762246.htm",  # 2023-12 (2023全年)
    "https://www.nea.gov.cn/2023-12/20/c_1310756286.htm",  # 2023-11
    # 2022
    "https://www.nea.gov.cn/2023-01/18/c_1310691509.htm",  # 2022-12 (2022全年)
    "http://www.nea.gov.cn/2022-11/22/c_1310678885.htm",  # 2022-10
    # 2021
    "http://www.nea.gov.cn/2022-01/26/c_1310441589.htm",  # 2021-12 (2021全年)
    # 2020
    "https://www.nea.gov.cn/2021-01/20/c_139683739.htm",  # 2020-12 (2020全年)
    # 2019
    "https://www.nea.gov.cn/2020-01/20/c_138720881.htm",  # 2019-12 (2019全年)
    # 2018
    "https://hzj.nea.gov.cn/dtyw/gjnyjdt/202309/t20230913_74423.html",  # 2018-12 (2018全年)
    # 2017
    "https://www.nea.gov.cn/2018-01/22/c_136914154.htm",  # 2017-12 (2017全年)
    # 2016
    "https://www.nea.gov.cn/2017-01/16/c_135986964.htm",  # 2016-12 (2016全年)
    # 2015
    "http://www.nea.gov.cn/2016-01/15/c_135013789.htm",  # 2015-12 (2015全年)
    # 2014
    "https://www.nea.gov.cn/2015-01/16/c_133923477.htm",  # 2014-12 (2014全年)
]

NEA_HEADERS: Final[dict[str, str]] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/128.0.0.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# 指标名称归一化映射 (指标名称 -> (标准产品代码, 度量流向, 原始单位))
NEA_TABLE_INDICATOR_MAPPING: Final[dict[str, tuple[str, str, str]]] = {
    # 累计装机容量 (万千瓦 -> GW)
    "全国发电装机容量": ("TOTAL_ELECTRICITY", "INSTALLED_CAPACITY", "ten_thousand_kw"),
    "全口径发电设备容量": ("TOTAL_ELECTRICITY", "INSTALLED_CAPACITY", "ten_thousand_kw"),
    "其中：水电": ("HYDRO", "INSTALLED_CAPACITY", "ten_thousand_kw"),
    "其中:水 电": ("HYDRO", "INSTALLED_CAPACITY", "ten_thousand_kw"),
    "其中:水电": ("HYDRO", "INSTALLED_CAPACITY", "ten_thousand_kw"),
    "水电": ("HYDRO", "INSTALLED_CAPACITY", "ten_thousand_kw"),
    "火电": ("THERMAL_POWER", "INSTALLED_CAPACITY", "ten_thousand_kw"),
    "其中:火 电": ("THERMAL_POWER", "INSTALLED_CAPACITY", "ten_thousand_kw"),
    "核电": ("NUCLEAR", "INSTALLED_CAPACITY", "ten_thousand_kw"),
    "其中:核 电": ("NUCLEAR", "INSTALLED_CAPACITY", "ten_thousand_kw"),
    "风电": ("WIND_TOTAL", "INSTALLED_CAPACITY", "ten_thousand_kw"),
    "并网风电": ("WIND_TOTAL", "INSTALLED_CAPACITY", "ten_thousand_kw"),
    "太阳能发电": ("SOLAR_PV", "INSTALLED_CAPACITY", "ten_thousand_kw"),
    "并网太阳能发电": ("SOLAR_PV", "INSTALLED_CAPACITY", "ten_thousand_kw"),
    # 设备利用小时数 (小时)
    "全国发电设备累计平均利用小时": ("TOTAL_ELECTRICITY", "UTILIZATION_HOURS", "hours"),
    "发电设备累计平均利用小时": ("TOTAL_ELECTRICITY", "UTILIZATION_HOURS", "hours"),
    "6000千瓦及以上电厂发电设备利用小时": ("TOTAL_ELECTRICITY", "UTILIZATION_HOURS", "hours"),
    # 投资完成额 (亿元)
    "电源工程投资完成": ("POWER_CAPEX", "INVESTMENT", "billion_cny"),
    "电源工程建设投资完成额": ("POWER_CAPEX", "INVESTMENT", "billion_cny"),
    "电源基本建设投资完成额": ("POWER_CAPEX", "INVESTMENT", "billion_cny"),
    "电网工程投资完成": ("GRID_CAPEX", "INVESTMENT", "billion_cny"),
    "电网工程建设投资完成额": ("GRID_CAPEX", "INVESTMENT", "billion_cny"),
    "电网基本建设投资完成额": ("GRID_CAPEX", "INVESTMENT", "billion_cny"),
    # 新增发电装机容量 (万千瓦 -> GW)
    "新增发电装机容量": ("TOTAL_ELECTRICITY", "NEW_CAPACITY", "ten_thousand_kw"),
    "发电新增设备容量": ("TOTAL_ELECTRICITY", "NEW_CAPACITY", "ten_thousand_kw"),
}
