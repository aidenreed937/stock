"""Mysteel (我的钢铁网 / 隆众能化) DOM 表格与文章智能解析器。

负责从 CDP 抓取的原始 HTML 网页中提取商品现货价格、规格、产地与发布日期。
支持两种互补解析模式：
1. 行情表格解析器 (Table Parser)：智能识别表头并解析多行品类报价明细；
2. 研报/周评文本解析器 (Article Parser)：针对无结构化表格的文章正文执行正则抽取。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MysteelParsedQuote:
    """Mysteel 现货价格抽取标准化记录。"""

    trade_date: date
    product_name: str
    symbol: str
    price: float
    spec: str = ""
    region: str = ""
    unit: str = "元/吨"
    source: str = "Mysteel"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "verified_industry_report"


@dataclass(frozen=True)
class MysteelArticleMeta:
    """Mysteel 资讯/周报文章元数据。"""

    title: str
    url: str
    publish_date: date | None = None
    summary: str = ""


def _clean_text(val: str | None) -> str:
    if not val:
        return ""
    return re.sub(r"\s+", " ", str(val)).strip()


def _parse_date_str(val: str, fallback_year: int | None = None) -> date | None:
    """从文本中解析标准日期。"""
    cleaned = _clean_text(val)
    m = re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", cleaned)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    # 短日期 MM-DD
    m_short = re.search(r"(\d{1,2})[-/.月](\d{1,2})", cleaned)
    if m_short:
        year = fallback_year or date.today().year
        try:
            return date(year, int(m_short.group(1)), int(m_short.group(2)))
        except ValueError:
            pass
    return None


def _parse_price_value(val_str: str) -> float | None:
    """从单元格文本中解析数值价格，支持中位数与万元折算。"""
    cleaned = _clean_text(val_str).replace(",", "").replace("，", "")
    # 范围区间: 45000-46000 或 4.3-4.5
    m_range = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*[-~～–—至到]\s*([0-9]+(?:\.[0-9]+)?)", cleaned)
    if m_range:
        p1 = float(m_range.group(1))
        p2 = float(m_range.group(2))
        avg = (p1 + p2) / 2.0
        if "万" in cleaned or avg < 200.0:
            avg = avg * 10000.0
        return round(avg, 1) if avg > 0 else None

    # 单点数值
    m_single = re.search(r"([0-9]+(?:\.[0-9]+)?)", cleaned)
    if m_single:
        val = float(m_single.group(1))
        if "万" in cleaned or (0 < val < 200.0 and "元" not in cleaned):
            val = val * 10000.0
        return round(val, 1) if val > 0 else None
    return None


def parse_mysteel_tables(
    html: str,
    target_product: str,
    symbol: str,
    default_unit: str = "元/吨",
    source_url: str = "",
    target_specs: list[str] | None = None,
) -> list[MysteelParsedQuote]:
    """从 HTML 中的所有 <table> 表格抽取指定品种报价。"""
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        return []

    # 尝试从页面提取发布日期
    page_date = _find_page_release_date(soup)
    results: list[MysteelParsedQuote] = []

    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        # 解析表头列索引
        header_row = rows[0]
        ths = [c.get_text(strip=True) for c in header_row.find_all(["th", "td"])]
        if not ths and len(rows) > 1:
            header_row = rows[1]
            ths = [c.get_text(strip=True) for c in header_row.find_all(["th", "td"])]

        col_map = _map_table_columns(ths)
        if "price" not in col_map:
            continue

        for r in rows[1:]:
            cells = r.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            texts = [_clean_text(c.get_text()) for c in cells]

            # 匹配品名
            prod_idx = col_map.get("product")
            row_prod = texts[prod_idx] if prod_idx is not None and prod_idx < len(texts) else ""
            if not row_prod or target_product not in row_prod:
                # 检查整行是否含品名
                if not any(target_product in t for t in texts):
                    continue

            # 匹配规格
            spec_idx = col_map.get("spec")
            spec_val = texts[spec_idx] if spec_idx is not None and spec_idx < len(texts) else ""
            if target_specs and spec_val:
                if not any(s in spec_val for s in target_specs):
                    continue

            # 产地/钢厂/区域
            region_idx = col_map.get("region")
            region_val = (
                texts[region_idx] if region_idx is not None and region_idx < len(texts) else ""
            )

            # 价格
            price_idx = col_map["price"]
            if price_idx >= len(texts):
                continue
            price_val = _parse_price_value(texts[price_idx])
            if price_val is None or price_val <= 0:
                continue

            # 日期
            date_idx = col_map.get("date")
            row_date_str = texts[date_idx] if date_idx is not None and date_idx < len(texts) else ""
            row_date = _parse_date_str(row_date_str) or page_date or date.today()

            results.append(
                MysteelParsedQuote(
                    trade_date=row_date,
                    product_name=target_product,
                    symbol=symbol,
                    price=price_val,
                    spec=spec_val or "标准品",
                    region=region_val or "国内主流",
                    unit=default_unit,
                    source="Mysteel",
                    source_url=source_url,
                    release_date=page_date or row_date,
                    data_status="verified_industry_report",
                )
            )

    return results


def _map_table_columns(headers: list[str]) -> dict[str, int]:
    """根据表头关键词智能映射列下标。"""
    col_map: dict[str, int] = {}
    for idx, h in enumerate(headers):
        if any(k in h for k in ["品名", "商品", "品种", "名称"]):
            col_map.setdefault("product", idx)
        elif any(k in h for k in ["规格", "型号", "牌号", "品级"]):
            col_map.setdefault("spec", idx)
        elif any(k in h for k in ["钢厂", "产地", "厂家", "区域", "市场", "地区"]):
            col_map.setdefault("region", idx)
        elif any(k in h for k in ["价格", "主流价", "出厂价", "均价", "现货价"]):
            col_map.setdefault("price", idx)
        elif any(k in h for k in ["日期", "发布日期", "时间"]):
            col_map.setdefault("date", idx)
    return col_map


def _find_page_release_date(soup: BeautifulSoup) -> date | None:
    """从页面文章头部或元数据抽取官方发布时间。"""
    for tag in soup.find_all(
        ["span", "div", "p"], class_=re.compile(r"time|date|pub|source", re.I)
    ):
        d = _parse_date_str(tag.get_text())
        if d:
            return d
    # 全局匹配正文中最早出现的完整时间戳
    text_snippet = soup.get_text()[:1500]
    m = re.search(r"(?:发布|时间|更新|日期)[:：\s]*(\d{4}-\d{2}-\d{2})", text_snippet)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            pass
    return None


def parse_mysteel_article_list(
    html: str,
    keywords: list[str] | None = None,
) -> list[MysteelArticleMeta]:
    """从周评/资讯列表页 HTML 解析匹配关键词的文章列表。"""
    soup = BeautifulSoup(html, "html.parser")
    articles: list[MysteelArticleMeta] = []
    seen_urls: set[str] = set()

    for a in soup.find_all("a"):
        title = _clean_text(a.get_text())
        href = str(a.get("href", "")).strip()
        if not title or not href or len(title) < 6:
            continue
        if href in seen_urls:
            continue
        if any(
            skip in title
            for skip in [
                "首页",
                "资讯",
                "客服",
                "注册",
                "登录",
                "意见反馈",
                "价格中心",
                "自媒体",
                "国家标准",
                "GB/T",
                "科普",
                "设备介绍",
                "应用",
            ]
        ):
            continue
        if keywords and not any(kw in title for kw in keywords):
            continue

        parent = a.parent
        parent_text = _clean_text(parent.get_text()) if parent else ""
        pub_date = _parse_date_str(parent_text) or _parse_date_str(title)

        seen_urls.add(href)
        articles.append(
            MysteelArticleMeta(
                title=title,
                url=href,
                publish_date=pub_date,
            )
        )
    return articles


def parse_mysteel_article(
    html: str,
    target_product: str,
    symbol: str,
    default_unit: str = "元/吨",
    source_url: str = "",
    target_specs: list[str] | None = None,
) -> list[MysteelParsedQuote]:
    """从无结构化表格的文章资讯正文执行智能正则抽取。"""
    soup = BeautifulSoup(html, "html.parser")
    page_date = _find_page_release_date(soup) or date.today()

    # 移除模态框/登录框以防止噪音污染
    for modal in soup.find_all(class_=re.compile(r"modal|dialog|login|passport", re.I)):
        modal.decompose()

    body_tag = soup.body if soup.body is not None else soup
    text = body_tag.get_text() if body_tag is not None else ""
    cleaned = _clean_text(text)

    # 抽取段落/句子中与 target_product 关联的报价
    results: list[MysteelParsedQuote] = []

    # 支持品类别名扩展 (尤其针对钛精矿多种表述)
    if symbol == "ilmenite" or "钛精矿" in target_product or "钛矿" in target_product:
        prod_pattern = r"(?:钛精矿|钛矿|攀枝花[0-9%品位]*矿|攀西[0-9%品位]*矿|国产[0-9%品位]*矿|进口[0-9%品位]*矿|莫桑比克[0-9%品位]*矿|尼日利亚[0-9%品位]*矿)"
    else:
        prod_pattern = re.escape(target_product)

    # 模式: 品名 ... 1180-1230 元/吨 或 1.2 万元/吨 (不跨越分号、句号、换行等截断符)
    pat = re.compile(
        prod_pattern
        + r"(?:[（(][^）)]*[）)])?[^；。!\n;?]{0,45}?(?:出厂|现货|在|为|报|：|:|已降至|降至|跌至|下调至|涨至|上调至|维持在)?\s*([0-9]+(?:\.[0-9]+)?)\s*[-~～–—至到]?\s*([0-9]+(?:\.[0-9]+)?)?\s*(?:元/吨|元|万元/吨|万元)",
    )

    for m in pat.finditer(cleaned):
        raw_p1 = m.group(1)
        raw_p2 = m.group(2)
        match_chunk = m.group(0)

        num_pos = match_chunk.find(raw_p1)
        between = match_chunk[:num_pos]
        preceding = cleaned[max(0, m.start() - 80) : m.start()]
        surrounding = cleaned[max(0, m.start() - 40) : min(len(cleaned), m.end() + 40)]

        # 1. 跨品种阻断 (若中间出现了其他主要品种名词，说明该价格属于后一个品种)
        other_commodities = ["钛渣", "海绵钛", "钛白粉", "钛铁", "高钛渣", "纯碱", "工业硅"]
        if any(c in between for c in other_commodities if c not in target_product):
            continue

        # 2. 标点阻断
        if any(punc in between for punc in ["；", "。", "！", ";", "\n"]):
            continue

        # 3. 变动量噪音过滤 (排除单纯的降幅/涨幅，但保留已降至/跌至/涨至等目标价)
        if any(bad in between for bad in ["跌幅", "涨幅", "环比", "同比", "成本", "费用"]):
            continue
        if any(bad in between for bad in ["跌", "降", "下调", "涨", "上调", "增"]):
            if not any(keep in between for keep in ["至", "到", "在"]):
                continue

        p1 = float(raw_p1)
        if raw_p2:
            p2 = float(raw_p2)
            avg = (p1 + p2) / 2.0
        else:
            avg = p1

        if "万" in match_chunk or (avg < 200.0 and "元" not in match_chunk):
            avg = avg * 10000.0

        if avg <= 0:
            continue

        # 4. 品种价格合理性门禁 (常识物理检验，杜绝交叉噪音)
        if symbol == "ilmenite" and not (500.0 <= avg <= 3000.0):
            continue
        if symbol == "Ti_sponge" and not (25000.0 <= avg <= 90000.0):
            continue

        # 从标题或前文上下文中抽取确切交易日期
        item_date = None
        # 匹配括号中的周范围结束日期，如 (8.28-9.4) -> 9月4日
        d_range = re.search(r"[-~～–—至到](\d{1,2})[./月](\d{1,2})", surrounding)
        if d_range:
            try:
                item_date = date(page_date.year, int(d_range.group(1)), int(d_range.group(2)))
            except ValueError:
                pass

        if not item_date:
            d_m1 = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", preceding)
            if d_m1:
                try:
                    item_date = date(int(d_m1.group(1)), int(d_m1.group(2)), int(d_m1.group(3)))
                except ValueError:
                    pass
        if not item_date:
            d_m2 = re.search(r"20\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])", preceding)
            if d_m2:
                s = d_m2.group(0)
                try:
                    item_date = date(int(s[:4]), int(s[4:6]), int(s[6:8]))
                except ValueError:
                    pass
        quote_date = item_date or page_date

        # 智能规格与区域判定
        spec_str = "标准品"
        region_str = "国内主流"

        if "46%" in surrounding:
            spec_str = "46%"
        elif "47%" in surrounding:
            spec_str = "47%"
        elif "50%" in surrounding:
            spec_str = "50%"
        elif target_specs:
            for s in target_specs:
                if s in surrounding:
                    spec_str = s
                    break

        if any(k in surrounding for k in ["攀枝花", "攀西"]):
            region_str = "攀西"
        elif "莫桑比克" in surrounding:
            region_str = "莫桑比克"
            spec_str = f"{spec_str}进口矿" if "进口" not in spec_str else spec_str
        elif "尼日利亚" in surrounding:
            region_str = "尼日利亚"
            spec_str = f"{spec_str}进口矿" if "进口" not in spec_str else spec_str
        elif "国产" in surrounding:
            region_str = "国产主流"

        results.append(
            MysteelParsedQuote(
                trade_date=quote_date,
                product_name=target_product,
                symbol=symbol,
                price=round(avg, 1),
                spec=spec_str,
                region=region_str,
                unit=default_unit,
                source="Mysteel",
                source_url=source_url,
                release_date=page_date if page_date >= quote_date else quote_date,
                data_status="verified_industry_report",
            )
        )

    return results


def parse_mysteel_html(
    html: str,
    product_meta: dict[str, Any] | str,
    source_url: str = "",
) -> list[MysteelParsedQuote]:
    """统一门面函数：优先表格抽取，次选文章正则抽取并去重。"""
    if isinstance(product_meta, dict):
        prod_name = product_meta.get("product_name", "")
        symbol = product_meta.get("symbol", "")
        specs = product_meta.get("target_specs")
        unit = product_meta.get("unit", "元/吨")
    else:
        prod_name = str(product_meta)
        symbol = str(product_meta)
        specs = None
        unit = "元/吨"

    # 1. 优先表格解析
    quotes = parse_mysteel_tables(
        html=html,
        target_product=prod_name,
        symbol=symbol,
        default_unit=unit,
        source_url=source_url,
        target_specs=specs,
    )

    # 2. 表格未提取到时回退到正文提取
    if not quotes:
        quotes = parse_mysteel_article(
            html=html,
            target_product=prod_name,
            symbol=symbol,
            default_unit=unit,
            source_url=source_url,
            target_specs=specs,
        )

    # 3. 按 (symbol, trade_date, spec) 幂等去重
    unique: dict[tuple[str, date, str], MysteelParsedQuote] = {}
    for q in quotes:
        key = (q.symbol, q.trade_date, q.spec)
        if key not in unique:
            unique[key] = q

    return list(unique.values())


__all__ = [
    "MysteelArticleMeta",
    "MysteelParsedQuote",
    "parse_mysteel_article",
    "parse_mysteel_article_list",
    "parse_mysteel_html",
    "parse_mysteel_tables",
]
