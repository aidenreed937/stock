"""生意社 100ppi 商品定基指数 (cindex/ptrade-*.html) 解析器。

负责解析商品定基价格指数（以 2011-09-01 为基期 100.00）的日频点位、涨跌幅与累积涨幅。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommodityIndexRow:
    """生意社商品定基指数单日记录。"""

    trade_date: date
    ppid: int
    symbol: str
    product_name: str
    ci_value: float
    pct_change_1d: float | None
    direction: str
    cumulative_points: float | None
    cumulative_change_pct: float | None
    source: str = "100ppi_cindex"


def _clean_float(text: str | None) -> float | None:
    """清洗数字文本并转换为浮点数。"""
    if not text:
        return None
    cleaned = text.replace("&nbsp;", "").replace(",", "").replace("%", "").strip()
    if not cleaned or cleaned in ("-", "--", "null", "None", "暂无数据"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _clean_percent(text: str | None) -> float | None:
    """清洗百分比字符串并转换为小数比例 (例如 9.09% -> 0.0909)。"""
    val = _clean_float(text)
    if val is None:
        return None
    return round(val / 100.0, 6)


def _map_direction(symbol_char: str | None) -> str:
    """映射箭头符号为标准英文枚举。"""
    if not symbol_char:
        return "FLAT"
    sym = symbol_char.strip()
    if "↑" in sym or "+" in sym:
        return "UP"
    if "↓" in sym or "-" in sym:
        return "DOWN"
    return "FLAT"


def parse_100ppi_ptrade_html(
    html_text: str,
    ppid: int,
    symbol: str,
    product_name: str,
) -> list[CommodityIndexRow]:
    """从 100ppi ptrade-{ppid}.html 页面源码中解析近 90 天定基指数时序数据。

    Args:
        html_text: 页面 HTML 源码。
        ppid: 生意社商品编号 (如 968)。
        symbol: 系统标准代码 (如 'PX')。
        product_name: 商品中文名称 (如 '对二甲苯')。

    Returns:
        按日期降序排列的 CommodityIndexRow 记录列表。
    """
    if not html_text:
        return []

    soup = BeautifulSoup(html_text, "html.parser")
    table = soup.find("table")
    if not table:
        logger.warning(f"在商品 {product_name}(ID={ppid}) 的 HTML 中未找到指数表格")
        return []

    rows = table.find_all("tr")
    if len(rows) < 2:
        return []

    records: list[CommodityIndexRow] = []

    # 第一行为表头 ['日期', '数值', '较前日涨跌幅', '↑↓', '累积增长点数', '累积涨幅']
    for tr in rows[1:]:
        cols = [td.get_text(strip=True) for td in tr.find_all(["th", "td"])]
        if len(cols) < 6:
            continue

        raw_date_str = cols[0]
        try:
            trade_date = datetime.strptime(raw_date_str, "%Y-%m-%d").date()
        except ValueError:
            # 非日期行跳过
            continue

        ci_value = _clean_float(cols[1])
        if ci_value is None:
            continue

        pct_change_1d = _clean_percent(cols[2])
        direction = _map_direction(cols[3])
        cumulative_points = _clean_float(cols[4])
        cumulative_change_pct = _clean_percent(cols[5])

        records.append(
            CommodityIndexRow(
                trade_date=trade_date,
                ppid=ppid,
                symbol=symbol,
                product_name=product_name,
                ci_value=ci_value,
                pct_change_1d=pct_change_1d,
                direction=direction,
                cumulative_points=cumulative_points,
                cumulative_change_pct=cumulative_change_pct,
                source="100ppi_cindex",
            )
        )

    return records
