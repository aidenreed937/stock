"""国家能源局通报解析器。"""

from __future__ import annotations

import re


def parse_solar_capacity_from_text(text: str) -> tuple[float | None, float | None]:
    """从国家能源局通报正文中正则提取太阳能累计装机 (GW) 与同比增速。"""
    clean_text = text.replace(" ", "").replace("\n", "").replace("\r", "")

    cap_gw: float | None = None
    pattern_cap = re.search(
        r"太阳能发电装机容量(?:约)?(\d+\.?\d*)\s*(亿千瓦|万千瓦|吉瓦|GW)", clean_text
    )
    if pattern_cap:
        val = float(pattern_cap.group(1))
        unit = pattern_cap.group(2)
        if unit == "亿千瓦":
            cap_gw = round(val * 100.0, 2)
        elif unit == "万千瓦":
            cap_gw = round(val * 0.01, 2)
        elif unit in ("吉瓦", "GW"):
            cap_gw = round(val, 2)

    yoy_val: float | None = None
    pattern_yoy = re.search(
        r"太阳能发电装机容量[^\d]*\d+\.?\d*[^，。]*[，,]同比增长(?:约)?(\d+\.?\d*)%",
        clean_text,
    )
    if pattern_yoy:
        yoy_val = round(float(pattern_yoy.group(1)) / 100.0, 4)

    return cap_gw, yoy_val


__all__ = ["parse_solar_capacity_from_text"]
