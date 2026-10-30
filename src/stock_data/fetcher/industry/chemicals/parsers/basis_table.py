"""生意社 100ppi 每日现期对比表 (sf/day-*.html) 解析器。

负责从 100ppi 每日静态 HTML 档案中解析大宗商品现货基准价、期货主力结算价与基差率。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# 商品名称到系统标准 symbol 的映射
COMMODITY_BASIS_NAME_MAP: dict[str, str] = {
    "PTA": "TA",
    "精对苯二甲酸": "TA",
    "纯碱": "SA",
    "重质纯碱": "SA",
    "轻质纯碱": "SA_light",
    "乙二醇": "MEG",
    "甲醇": "MA",
    "甲醇MA": "MA",
    "聚氯乙烯": "V",
    "PVC": "V",
    "尿素": "UR",
    "玻璃": "FG",
    "平板玻璃": "FG",
    "浮法玻璃": "FG",
    "烧碱": "SH",
    "聚丙烯": "PP",
    "PP": "PP",
    "聚乙烯": "L",
    "塑料": "L",
    "LLDPE": "L",
    "苯乙烯": "EB",
    "动力煤": "ZC",
    "工业硅": "SI",
    "涤纶短纤": "PF",
    "短纤": "PF",
    "天然橡胶": "RU",
    "橡胶": "RU",
    "石油沥青": "BU",
    "沥青": "BU",
    "生猪": "LH",
    "铜": "CU",
    "铝": "AL",
    "锌": "ZN",
    "铅": "PB",
    "镍": "NI",
    "锡": "SN",
    "螺纹钢": "RB",
    "热轧卷板": "HC",
    "焦炭": "J",
    "焦煤": "JM",
    "铁矿石": "I",
}


@dataclass(frozen=True)
class ChemicalBasisRow:
    """100ppi 现期对比表单条记录。"""

    trade_date: date
    product_name: str
    symbol: str
    spot_price_cny: float
    near_contract: str
    near_contract_price: float | None
    dom_contract: str
    dom_contract_price: float | None
    basis_cny: float | None
    basis_rate_pct: float | None
    unit: str
    source: str = "100ppi_sf"


def _clean_number(text: str | None) -> float | None:
    """清洗提取浮点数值。"""
    if not text:
        return None
    cleaned = text.replace("&nbsp;", "").replace(",", "").replace("%", "").strip()
    if not cleaned or cleaned in ("-", "--", "null", "None", "暂无数据"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_100ppi_basis_html(
    html_text: str,
    trade_date: date,
    target_symbols: set[str] | None = None,
) -> list[ChemicalBasisRow]:
    """从 100ppi 每日现期表 HTML 中解析所有商品记录。

    Args:
        html_text: 页面 HTML 源代码。
        trade_date: 对应交易日。
        target_symbols: 可选过滤的品类代码集合（如 {'TA', 'SA', 'MEG'}），None 表示全量提取。

    Returns:
        解析成功的 ChemicalBasisRow 记录列表。
    """
    if not html_text:
        return []

    soup = BeautifulSoup(html_text, "html.parser")
    table = soup.find("table", id="fdata")
    if table is None:
        # 回退策略：按 class 查找
        tables = soup.find_all("table", class_="ftab")
        if tables:
            table = tables[0]

    if table is None:
        logger.warning(f"在 {trade_date} 的 HTML 中未找到现期对比表 (#fdata)")
        return []

    rows = table.find_all("tr")
    records: list[ChemicalBasisRow] = []

    for row in rows:
        tds = row.find_all("td", recursive=False)
        if len(tds) < 8:
            continue

        raw_name = tds[0].get_text(strip=True)
        # 过滤表头及交易所小节标题
        if not raw_name or any(
            h in raw_name
            for h in (
                "商品",
                "价格",
                "交易所",
                "上海期货交易所",
                "郑州商品交易所",
                "大连商品交易所",
                "广州期货交易所",
            )
        ):
            continue

        # 匹配标准化代码
        symbol = COMMODITY_BASIS_NAME_MAP.get(raw_name)
        if not symbol:
            # 尝试去除括号与字母后缀
            cleaned_name = re.sub(r"[a-zA-Z0-9\(\)（）\s]", "", raw_name)
            symbol = COMMODITY_BASIS_NAME_MAP.get(cleaned_name)

        if not symbol:
            continue

        if target_symbols is not None and symbol not in target_symbols:
            continue

        spot_price = _clean_number(tds[1].get_text(strip=True))
        if spot_price is None or spot_price <= 0:
            continue

        near_contract = tds[2].get_text(strip=True).replace("&nbsp;", "")
        near_price = _clean_number(tds[3].get_text(strip=True))

        dom_contract = tds[5].get_text(strip=True).replace("&nbsp;", "")
        dom_price = _clean_number(tds[6].get_text(strip=True))

        # 提取现期差与基差率
        diff_cell_text = tds[7].get_text(" ", strip=True)
        diff_parts = diff_cell_text.split()
        basis_val = _clean_number(diff_parts[0]) if diff_parts else None
        basis_rate = _clean_number(diff_parts[1]) if len(diff_parts) > 1 else None

        # 若未直接提取到基差且主力期货价存在，则按公式计算
        if basis_val is None and dom_price is not None:
            basis_val = round(spot_price - dom_price, 2)
        if basis_rate is None and basis_val is not None and dom_price is not None and dom_price > 0:
            basis_rate = round(basis_val / dom_price * 100.0, 2)

        unit = "元/㎡" if symbol == "FG" else "元/吨"

        records.append(
            ChemicalBasisRow(
                trade_date=trade_date,
                product_name=raw_name,
                symbol=symbol,
                spot_price_cny=spot_price,
                near_contract=near_contract,
                near_contract_price=near_price,
                dom_contract=dom_contract,
                dom_contract_price=dom_price,
                basis_cny=basis_val,
                basis_rate_pct=basis_rate,
                unit=unit,
            )
        )

    return records
