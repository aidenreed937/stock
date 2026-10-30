"""化工周报网页与 RAW CSV 解析。"""

from __future__ import annotations

import csv
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from stock_data.fetcher.industry.common import now_utc_iso


def load_weekly_survey_raw_csv(
    survey_dir: Path, strict_snapshot: bool = True
) -> dict[tuple[str, str, str], dict[str, Any]]:
    """读取周度化工调查 RAW CSV。

    严格遵循 Ground Truth First 铁律：
    若 strict_snapshot 为 True，凡缺少 raw_content_sha256 或 raw_snapshot_path 的记录直接丢弃，杜绝无源孤儿数据入库。
    """
    csv_file = survey_dir / "weekly_survey.csv"
    if not csv_file.exists():
        return {}

    records: dict[tuple[str, str, str], dict[str, Any]] = {}
    with csv_file.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            d_str = row["report_date"].strip()
            product = row["product_name"].strip()
            source = (row.get("source") or "").strip()
            if not product or not source:
                continue
            content_hash = (row.get("raw_content_sha256") or "").strip()
            snapshot_path = (row.get("raw_snapshot_path") or "").strip()
            if strict_snapshot and (not content_hash or not snapshot_path):
                continue
            release_date = _safe_date(row.get("release_date"))
            records[(product, d_str, source)] = {
                "trade_date": date.fromisoformat(d_str),
                "report_date": date.fromisoformat(d_str),
                "product_name": product,
                "symbol": row.get("symbol") or "",
                "operating_rate_pct": _float_from_row("operating_rate_pct", row),
                "weekly_output_w_tons": _float_from_row("weekly_output_w_tons", row),
                "factory_inventory_w_tons": _float_from_row("factory_inventory_w_tons", row),
                "shipment_rate_pct": _float_from_row("shipment_rate_pct", row),
                "source": source,
                "source_url": row.get("source_url") or "",
                "release_date": release_date,
                "data_status": (row.get("data_status") or "actual").strip(),
                "collected_at": row.get("collected_at") or now_utc_iso(),
                "raw_content_sha256": content_hash,
                "raw_snapshot_path": snapshot_path,
            }
    return records


def save_weekly_survey_raw_csv(
    survey_dir: Path, records: dict[tuple[str, str, str], dict[str, Any]]
) -> None:
    """保存周度化工调查 RAW CSV。"""
    csv_file = survey_dir / "weekly_survey.csv"
    rows = sorted(
        records.values(), key=lambda row: (row["product_name"], row["report_date"], row["source"])
    )
    fieldnames = [
        "trade_date",
        "report_date",
        "product_name",
        "symbol",
        "operating_rate_pct",
        "weekly_output_w_tons",
        "factory_inventory_w_tons",
        "shipment_rate_pct",
        "source",
        "source_url",
        "release_date",
        "data_status",
        "collected_at",
        "raw_content_sha256",
        "raw_snapshot_path",
    ]
    survey_dir.mkdir(parents=True, exist_ok=True)
    with csv_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(_weekly_survey_row_to_csv(row))


def collect_100ppi_weekly_records(
    records: dict[tuple[str, str, str], dict[str, Any]],
    fetch_html: Callable[[str], str],
    current_year: int,
    now_iso: str,
    start_date: date | None = None,
    end_date: date | None = None,
    raw_content_sha256_value: str = "",
    raw_snapshot_path: str = "",
) -> None:
    """解析生意社官方纯碱情报站周度开工、库存与出货率。"""
    soda_qb_url = "https://www.100ppi.com/qb/?pid=533"
    html_100ppi = fetch_html(soda_qb_url)
    if not html_100ppi:
        return

    text = BeautifulSoup(html_100ppi, "html.parser").get_text()
    page_release_date = parse_page_release_date(html_100ppi)
    pat_rate = re.findall(
        r"(\d{1,2})月(\d{1,2})日(?:当周)?[，,\s]*纯碱(?:装置|整体|行业)?(?:开工率|产能利用率|开工负荷)[为\s]*([\d.]+)%(?:[，,\s]*较上周[增加减少]+[\d.]+%[；;])?(?:[，,\s]*纯碱产量[为\s]*([\d.]+)万吨)?",
        text,
    )
    for month_s, day_s, rate_s, output_s in pat_rate:
        record = _get_100ppi_record(
            records,
            current_year,
            int(month_s),
            int(day_s),
            soda_qb_url,
            now_iso,
            start_date=start_date,
            end_date=end_date,
            raw_content_sha256_value=raw_content_sha256_value,
            raw_snapshot_path=raw_snapshot_path,
            release_date=page_release_date,
        )
        if record is None:
            continue
        record["operating_rate_pct"] = float(rate_s)
        if output_s:
            record["weekly_output_w_tons"] = float(output_s)

    pat_inventory = re.findall(
        r"(\d{1,2})月(\d{1,2})日[，,\s]*(?:周初|本周)?国内纯碱(?:库存|厂家总库存)[为\s]*([\d.]+)万吨",
        text,
    )
    for month_s, day_s, inventory_s in pat_inventory:
        record = _get_100ppi_record(
            records,
            current_year,
            int(month_s),
            int(day_s),
            soda_qb_url,
            now_iso,
            start_date=start_date,
            end_date=end_date,
            raw_content_sha256_value=raw_content_sha256_value,
            raw_snapshot_path=raw_snapshot_path,
            release_date=page_release_date,
        )
        if record is not None:
            record["factory_inventory_w_tons"] = float(inventory_s)

    pat_shipment = re.findall(
        r"(\d{1,2})月(\d{1,2})日[，,\s]*本周中国纯碱企业出货量[为\s]*([\d.]+)万吨[^\n]*?纯碱(?:整体)?出货率在[为\s]*([\d.]+)%",
        text,
    )
    for month_s, day_s, _output_s, shipment_s in pat_shipment:
        record = _get_100ppi_record(
            records,
            current_year,
            int(month_s),
            int(day_s),
            soda_qb_url,
            now_iso,
            start_date=start_date,
            end_date=end_date,
            raw_content_sha256_value=raw_content_sha256_value,
            raw_snapshot_path=raw_snapshot_path,
            release_date=page_release_date,
        )
        if record is not None:
            record["shipment_rate_pct"] = float(shipment_s)


def _get_100ppi_record(
    records: dict[tuple[str, str, str], dict[str, Any]],
    current_year: int,
    month: int,
    day: int,
    source_url: str,
    now_iso: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    raw_content_sha256_value: str = "",
    raw_snapshot_path: str = "",
    release_date: date | None = None,
) -> dict[str, Any] | None:
    report_date = date(current_year, month, day)
    if start_date is not None and report_date < start_date:
        return None
    if end_date is not None and report_date > end_date:
        return None
    date_text = report_date.isoformat()
    key = ("纯碱", date_text, "100ppi_Weekly")
    record = records.get(
        key,
        {
            "trade_date": report_date,
            "report_date": report_date,
            "product_name": "纯碱",
            "symbol": "SA",
            "operating_rate_pct": None,
            "weekly_output_w_tons": None,
            "factory_inventory_w_tons": None,
            "shipment_rate_pct": None,
            "source": "100ppi_Weekly",
            "source_url": source_url,
            "release_date": None,
            "data_status": "actual",
            "collected_at": now_iso,
            "raw_content_sha256": raw_content_sha256_value,
            "raw_snapshot_path": raw_snapshot_path,
        },
    )
    record["raw_content_sha256"] = raw_content_sha256_value
    record["raw_snapshot_path"] = raw_snapshot_path
    record["release_date"] = release_date
    if "data_status" not in record:
        record["data_status"] = "actual"
    records[key] = record
    return record


def _float_from_row(key: str, row: dict[str, str]) -> float | None:
    value = row.get(key)
    return float(value) if value and value.strip() else None


def _safe_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def parse_page_release_date(html_text: str) -> date | None:
    """提取网页显式发布时间（支持结构化标签、正文首部时间戳与属性前缀）。"""
    soup = BeautifulSoup(html_text, "html.parser")
    # 1. 优先提取结构化 DOM 标签 (如 Mysteel 的 <span class="publish-time">)
    span = soup.find("span", class_=re.compile(r"publish-time|content-info-text"))
    if span:
        m_span = re.search(r"(20\d{2}[-/年]\d{1,2}[-/月]\d{1,2})", span.get_text())
        if m_span:
            d_str = m_span.group(1).replace("/", "-").replace("年", "-").replace("月", "-")
            return _safe_date(d_str)

    # 2. 检索网页前 2000 字符内的标准时间戳 (如 2025-10-23 16:43，排除底部版权年限)
    m_top = re.search(r"(20\d{2}-\d{2}-\d{2})\s+\d{1,2}:\d{2}", html_text[:2000])
    if m_top:
        return _safe_date(m_top.group(1))

    # 3. 既有带关键字前缀的模式兜底
    patterns = (
        r"(?:datePublished|published_time|发布时间|发布日期)[^0-9]{0,30}(20\d{2}-\d{2}-\d{2})",
        r"(?:datePublished|published_time|发布时间|发布日期)[^0-9]{0,30}(20\d{2}/\d{2}/\d{2})",
    )
    for pattern in patterns:
        match = re.search(pattern, html_text, flags=re.IGNORECASE)
        if match:
            return _safe_date(match.group(1).replace("/", "-"))
    return None


def has_weekly_metrics(record: dict[str, Any]) -> bool:
    """判断一条周报记录是否至少包含一个可验证指标。"""
    return any(
        record.get(key) is not None
        for key in (
            "operating_rate_pct",
            "weekly_output_w_tons",
            "factory_inventory_w_tons",
            "shipment_rate_pct",
        )
    )


# 物理学常识守恒与合理区间门禁（超出者视为口径错位或非单周指标，坚决置为 None）
CHEMICAL_PHYSICAL_BOUNDS: dict[str, dict[str, tuple[float, float]]] = {
    "TA": {
        "operating_rate_pct": (50.0, 95.0),
        "weekly_output_w_tons": (80.0, 160.0),
        "factory_inventory_w_tons": (20.0, 450.0),
    },
    "MEG": {
        "operating_rate_pct": (40.0, 85.0),
        "weekly_output_w_tons": (20.0, 55.0),
        "factory_inventory_w_tons": (5.0, 160.0),
    },
    "MA": {
        "operating_rate_pct": (50.0, 92.0),
        "weekly_output_w_tons": (100.0, 230.0),
        "factory_inventory_w_tons": (15.0, 180.0),
    },
    "V": {
        "operating_rate_pct": (55.0, 92.0),
        "weekly_output_w_tons": (30.0, 65.0),
        "factory_inventory_w_tons": (15.0, 120.0),
    },
    "TIO2": {
        "operating_rate_pct": (40.0, 95.0),
        "weekly_output_w_tons": (4.0, 18.0),
        "factory_inventory_w_tons": (5.0, 35.0),
    },
    "SA": {
        "operating_rate_pct": (50.0, 100.0),
        "weekly_output_w_tons": (40.0, 90.0),
        "factory_inventory_w_tons": (10.0, 220.0),
    },
    "UR": {
        "operating_rate_pct": (55.0, 95.0),
        "weekly_output_w_tons": (70.0, 160.0),
        "factory_inventory_w_tons": (15.0, 160.0),
    },
    "SH": {
        "operating_rate_pct": (65.0, 92.0),
        "weekly_output_w_tons": (50.0, 100.0),
        "factory_inventory_w_tons": (15.0, 85.0),
    },
    "EB": {
        "operating_rate_pct": (45.0, 95.0),
        "weekly_output_w_tons": (20.0, 48.0),
        "factory_inventory_w_tons": (3.0, 40.0),
    },
    "PP": {
        "operating_rate_pct": (50.0, 95.0),
        "weekly_output_w_tons": (40.0, 85.0),
        "factory_inventory_w_tons": (10.0, 95.0),
    },
    "PX": {
        "operating_rate_pct": (50.0, 95.0),
        "weekly_output_w_tons": (45.0, 90.0),
        "factory_inventory_w_tons": (5.0, 60.0),
    },
}

DOWNSTREAM_EXCLUDES: dict[str, list[str]] = {
    "TA": ["聚酯", "涤纶", "PX", "对二甲苯", "长丝", "短纤", "织造", "织机", "切片", "瓶片"],
    "MEG": ["聚酯", "长丝", "短纤", "织造", "织机", "棉花"],
    "MA": ["醋酸", "甲醛", "MTBE", "二甲醚", "烯烃", "MTO"],
    "V": ["管材", "型材", "下游", "地板", "薄膜"],
    "TIO2": ["涂料", "造纸", "塑料", "钛矿"],
    "SA": ["浮法玻璃", "光伏玻璃", "重碱下游", "平板玻璃"],
    "UR": ["复合肥", "三聚氰胺", "车用尿素", "下游"],
    "SH": ["氧化铝", "印染", "造纸", "化纤", "下游"],
    "EB": ["PS", "EPS", "ABS", "UPR", "SBR", "下游", "树脂"],
    "PP": ["编织袋", "BOPP", "注塑", "纤维", "下游", "制品", "无纺布"],
    "PX": ["PTA", "聚酯", "长丝", "短纤", "织造", "下游"],
}

PERIOD_EXCLUDES: list[str] = [
    r"202\d年",
    r"年度",
    r"全年",
    r"累计",
    r"月度",
    r"\d{1,2}月(?:国内)?(?:产量|累|共计)",
    r"日产",
    r"日均",
    r"装置(?:年)?产能",
    r"单套装置",
    r"某厂",
]


def parse_commodity_weekly_metrics(
    html_text: str, product_name: str, symbol: str
) -> dict[str, float | None]:
    """针对不同大宗化工品种（纯碱、PTA、乙二醇、甲醇、PVC、钛白粉、苯乙烯、聚丙烯、对二甲苯等）专属提取周度开工率、周产量与库存。

    严守以下三原则：
    1. 强制绑定主体并排除下游衍生品；
    2. 严格排除年度、月度、日均、累计及单装置指标，只采集明确的周度数据；
    3. 严禁无主语全文盲扫兜底，引入产业物理守恒门禁，超限数据坚决置空。
    """
    util: float | None = None
    output: float | None = None
    inv: float | None = None
    shipment: float | None = None

    p_norm = (product_name or "").strip()
    sym_norm = (symbol or "").strip().upper()
    if sym_norm in ("EG", "MEG") or "乙二醇" in p_norm:
        sym_key = "MEG"
    elif sym_norm in ("PTA", "TA") or "对苯二甲酸" in p_norm:
        sym_key = "TA"
    elif sym_norm in ("PVC", "V") or "聚氯乙烯" in p_norm:
        sym_key = "V"
    elif sym_norm in ("MA",) or "甲醇" in p_norm:
        sym_key = "MA"
    elif sym_norm in ("TIO2", "TI") or "钛白粉" in p_norm:
        sym_key = "TIO2"
    elif sym_norm in ("SA",) or "纯碱" in p_norm:
        sym_key = "SA"
    elif sym_norm in ("UR",) or "尿素" in p_norm:
        sym_key = "UR"
    elif sym_norm in ("SH",) or "烧碱" in p_norm:
        sym_key = "SH"
    elif sym_norm in ("EB",) or "苯乙烯" in p_norm:
        sym_key = "EB"
    elif sym_norm in ("PP",) or "聚丙烯" in p_norm:
        sym_key = "PP"
    elif sym_norm in ("PX",) or "对二甲苯" in p_norm:
        sym_key = "PX"
    else:
        sym_key = sym_norm

    # 若为 HTML 文本，先剔除内联标签干扰并保留块级换行
    if "<html" in html_text.lower() or "<body" in html_text.lower() or "<div" in html_text.lower():
        soup = BeautifulSoup(html_text, "html.parser")
        for tag in soup(["script", "style"]):
            tag.extract()
        for blk in soup.find_all(["p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4"]):
            blk.append("\n")
        raw_clean = soup.get_text()
    else:
        raw_clean = html_text

    sentences = re.split(r"[\n;。；➢◆\t]", raw_clean)
    downstream_kw = DOWNSTREAM_EXCLUDES.get(sym_key, [])

    for s in sentences:
        s_clean = re.sub(r"\s+", " ", s).strip()
        if not s_clean or len(s_clean) < 4:
            continue

        has_downstream = any(dk in s_clean for dk in downstream_kw)

        # 1. 开工率 / 产能利用率（必须包含主体，排除下游）
        if util is None and not has_downstream:
            if sym_key == "TA" and ("PTA" in s_clean or "对苯二甲酸" in s_clean):
                m_util = re.search(
                    r"(?:PTA|精对苯二甲酸)(?:整体|国内|行业|装置|周均|周度|周)?[^\d%]{0,10}?(?:产能利用率|开工率|负荷|开工)[^\d%]{0,15}?(?:为|至|在|达|:|：)?\s*([4-9]\d(?:\.\d+)?)%",
                    s_clean,
                    re.IGNORECASE,
                )
                if not m_util:
                    m_util = re.search(
                        r"(?:国内PTA开工率|国内PTA负荷|PTA周均产能利用率|PTA周产能利用率)[^\d%]{0,15}?(?:为|至|在|达|:|：)?\s*([4-9]\d(?:\.\d+)?)%",
                        s_clean,
                        re.IGNORECASE,
                    )
                if m_util:
                    util = float(m_util.group(1))
            elif sym_key == "MEG" and ("乙二醇" in s_clean or "MEG" in s_clean):
                m_util = re.search(
                    r"(?:乙二醇|MEG)(?:综合|整体|全国|装置|行业|煤制|乙烯法|周均|企业)?(?:产能利用率|开工率|负荷|开工)[^\d%]{0,20}?(?:为|至|在|达|:|：)?\s*([3-9]\d(?:\.\d+)?)%",
                    s_clean,
                    re.IGNORECASE,
                )
                if not m_util:
                    m_util = re.search(
                        r"(?:乙二醇开工率|煤制乙二醇装置产能利用率|乙烯法乙二醇企业产能利用率)[^\d%]{0,25}?(?:为|至|在|达|:|：)?(?:一体化开)?\s*([3-9]\d(?:\.\d+)?)%",
                        s_clean,
                        re.IGNORECASE,
                    )
                if m_util:
                    util = float(m_util.group(1))
            elif sym_key == "MA":
                if "甲醇" in s_clean or "装置产能利用率" in s_clean or "开工负荷" in s_clean:
                    m_util = re.search(
                        r"(?:甲醇|全国甲醇|装置)?(?:整体|装置|行业|全国)?(?:产能利用率|开工负荷|开工率|负荷)[^\d%]{0,20}?(?:为|至|在|达|:|：)?\s*([4-9]\d(?:\.\d+)?)%",
                        s_clean,
                        re.IGNORECASE,
                    )
                    if m_util:
                        util = float(m_util.group(1))
            elif sym_key == "V" and ("PVC" in s_clean or "聚氯乙烯" in s_clean):
                m_util = re.search(
                    r"(?:PVC|聚氯乙烯)(?:装置|企业|生产企业|综合|行业|整体)?(?:开工负荷率|产能利用率|开工率|负荷)[^\d%]{0,20}?(?:为|至|在|达|:|：)?\s*([4-9]\d(?:\.\d+)?)%",
                    s_clean,
                    re.IGNORECASE,
                )
                if m_util:
                    util = float(m_util.group(1))
            elif sym_key == "TIO2" and (
                "钛白粉" in s_clean or "TIO2" in s_clean.upper() or "钛企" in s_clean
            ):
                m_util = re.search(
                    r"(?:钛白粉|TiO2|钛企|国内钛企样本)[^\d%]{0,25}?(?:开工率|产能利用率|开工负荷|负荷)[^\d%]{0,15}?(?:为|至|在|达|:|：)?\s*([3-9]\d(?:\.\d+)?)%",
                    s_clean,
                    re.IGNORECASE,
                )
                if not m_util and ("钛白粉" in s_clean or "钛企" in s_clean or "钛白" in s_clean):
                    m_util = re.search(
                        r"(?:产能利用率|开工率|开工负荷)[^\d%]{0,15}?(?:为|至|在|达|:|：)?\s*([3-9]\d(?:\.\d+)?)%",
                        s_clean,
                        re.IGNORECASE,
                    )
                if not m_util and ("钛白粉开工率" in s_clean or "钛白粉产能利用率" in s_clean):
                    m_util = re.search(
                        r"钛白粉(?:开工率|产能利用率)[^\d%]{0,25}?([3-9]\d(?:\.\d+)?)%", s_clean
                    )
                if m_util:
                    util = float(m_util.group(1))
            elif sym_key == "SA" and ("纯碱" in s_clean):
                m_util = re.search(
                    r"(?:纯碱|国内纯碱)(?:装置|行业|综合|整体)?(?:开工率|产能利用率|开工负荷|负荷)[^\d%]{0,20}?(?:为|至|在|达|:|：)?\s*([3-9]\d(?:\.\d+)?)%",
                    s_clean,
                    re.IGNORECASE,
                )
                if m_util:
                    util = float(m_util.group(1))
            elif sym_key == "UR" and ("尿素" in s_clean):
                m_util = re.search(
                    r"(?:尿素|国内尿素)(?:装置|行业|综合|整体)?(?:开工率|产能利用率|开工负荷|负荷)[^\d%]{0,20}?(?:为|至|在|达|:|：)?\s*([4-9]\d(?:\.\d+)?)%",
                    s_clean,
                    re.IGNORECASE,
                )
                if m_util:
                    util = float(m_util.group(1))
            elif sym_key == "SH" and (
                "烧碱" in s_clean or "氯碱" in s_clean or "离子膜" in s_clean
            ):
                m_util = re.search(
                    r"(?:烧碱|离子膜烧碱|氯碱|国内烧碱)(?:装置|企业|综合|整体)?(?:开工负荷率|产能利用率|开工率|负荷)[^\d%]{0,20}?(?:为|至|在|达|:|：)?\s*([5-9]\d(?:\.\d+)?)%",
                    s_clean,
                    re.IGNORECASE,
                )
                if m_util:
                    util = float(m_util.group(1))
            elif sym_key == "EB" and (
                "苯乙烯" in s_clean
                or "EB" in s_clean
                or "行业整体产能利用率" in s_clean
                or "国内开工率" in s_clean
            ):
                m_util = re.search(
                    r"(?:苯乙烯|国内苯乙烯)(?:行业|整体|装置|工厂|企业|周均)?[^\d%]{0,20}?(?:产能利用率|开工率|开工负荷|负荷)[^\d%]{0,20}?(?:为|至|在|达|:|：)?\s*([4-9]\d(?:\.\d+)?)%",
                    s_clean,
                    re.IGNORECASE,
                )
                if not m_util and ("行业整体产能利用率" in s_clean or "苯乙烯开工率" in s_clean):
                    m_util = re.search(
                        r"(?:行业整体产能利用率|装置开工率|国内开工率)[^\d%]{0,15}?(?:为|至|在|达|:|：)?\s*([4-9]\d(?:\.\d+)?)%",
                        s_clean,
                    )
                if m_util:
                    util = float(m_util.group(1))
            elif sym_key == "PP" and (
                "聚丙烯" in s_clean
                or "PP" in s_clean
                or "平均产能利用率" in s_clean
                or "装置产能利用率" in s_clean
                or "总体开工率" in s_clean
                or "整体负荷" in s_clean
            ):
                m_util = re.search(
                    r"(?:聚丙烯|PP|中国聚丙烯|总体|行业整体)?(?:装置|企业|生产企业|周均|整体|平均)?[^\d%]{0,20}?(?:产能利用率|开工率|开工负荷|负荷)(?:[^\d%]{0,15}?(?:较|环比)[^，,。；;\n]+?至)?(?:为|至|在|达|接近|:|：)?\s*([4-9]\d(?:\.\d+)?)%",
                    s_clean,
                    re.IGNORECASE,
                )
                if not m_util and (
                    "产能利用率" in s_clean
                    or "装置平均开工率" in s_clean
                    or "平均产能利用率" in s_clean
                    or "总体开工率" in s_clean
                    or "整体负荷" in s_clean
                ):
                    m_util = re.search(
                        r"(?:平均产能利用率|装置产能利用率|装置平均开工率|总体开工率|整体负荷)(?:[^\d%]{0,15}?(?:较|环比)[^，,。；;\n]+?至)?(?:为|至|在|达|接近|:|：)?\s*(?:至|为|在)?\s*([4-9]\d(?:\.\d+)?)%",
                        s_clean,
                    )
                if m_util:
                    util = float(m_util.group(1))
            elif sym_key == "PX" and ("PX" in s_clean or "对二甲苯" in s_clean):
                m_util = re.search(
                    r"(?:PX|对二甲苯|国内PX)(?:装置|行业|整体|国内|周均|周度)?[^\d%]{0,20}?(?:产能利用率|开工率|开工负荷|负荷)[^\d%]{0,20}?(?:为|至|在|达|:|：)?\s*([4-9]\d(?:\.\d+)?)%",
                    s_clean,
                    re.IGNORECASE,
                )
                if not m_util:
                    m_util = re.search(
                        r"PX周均产能利用率[^\d%]{0,15}?(?:为|至|在|达|:|：)?\s*([4-9]\d(?:\.\d+)?)%",
                        s_clean,
                    )
                if m_util:
                    util = float(m_util.group(1))

        # 2. 周度产量（必须包含周度修饰词，排除年、月、累计、单装置）
        if output is None and not has_downstream:
            has_long_period = any(re.search(pk, s_clean) for pk in PERIOD_EXCLUDES)
            has_weekly_ctx = any(
                wk in s_clean
                for wk in [
                    "周度产量",
                    "周产量",
                    "当周产量",
                    "本周产量",
                    "周产",
                    "上周产量",
                    "较上周",
                    "周均产量",
                    "周数据预计：产量",
                    "本期钛白粉产量",
                    "较上期",
                ]
            ) or (
                "产量" in s_clean
                and any(k in s_clean for k in ["国内", "中国", "本周", "周期", "本期"])
            )
            if has_weekly_ctx and not has_long_period:
                if sym_key == "TA" and ("PTA" in s_clean or "对苯二甲酸" in s_clean):
                    m_out = re.search(
                        r"(?:PTA|精对苯二甲酸)[^\d]{0,10}?(?:周度产量|周产量|当周产量|本周产量|周产|产量)[^\d]{0,10}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                        s_clean,
                        re.IGNORECASE,
                    )
                    if m_out:
                        output = float(m_out.group(1))
                elif sym_key == "MEG" and ("乙二醇" in s_clean or "MEG" in s_clean):
                    m_out = re.search(
                        r"(?:乙二醇|MEG)[^\d]{0,10}?(?:周度产量|周产量|当周产量|本周产量|产量)[^\d]{0,10}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                        s_clean,
                        re.IGNORECASE,
                    )
                    if m_out:
                        output = float(m_out.group(1))
                elif sym_key == "MA" and ("甲醇" in s_clean):
                    m_out = re.search(
                        r"(?:甲醇|全国甲醇)[^\d]{0,10}?(?:周度产量|周产量|当周产量|本周产量|产量)[^\d]{0,10}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                        s_clean,
                        re.IGNORECASE,
                    )
                    if not m_out:
                        m_out_ton = re.search(
                            r"(?:甲醇|全国甲醇)[^\d]{0,10}?(?:周度产量|周产量|当周产量|本周产量|产量)[^\d]{0,10}?([1-9]\d{5,7})\s*吨",
                            s_clean,
                            re.IGNORECASE,
                        )
                        if m_out_ton:
                            output = round(float(m_out_ton.group(1)) / 10000.0, 2)
                    if not m_out and "周数据预计：产量" in s_clean:
                        m_out = re.search(r"产量([1-9]\d*(?:\.\d+)?)\s*万吨", s_clean)
                    if m_out and output is None:
                        output = float(m_out.group(1))
                elif sym_key == "V" and ("PVC" in s_clean or "聚氯乙烯" in s_clean):
                    m_out = re.search(
                        r"(?:PVC|聚氯乙烯)[^\d]{0,10}?(?:周度产量|周产量|当周产量|本周产量|产量)[^\d]{0,10}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                        s_clean,
                        re.IGNORECASE,
                    )
                    if m_out:
                        output = float(m_out.group(1))
                elif sym_key == "TIO2" and (
                    "钛白粉" in s_clean or "TIO2" in s_clean.upper() or "钛企" in s_clean
                ):
                    m_out = re.search(
                        r"(?:钛白粉|TiO2|本期钛白粉|国内钛白粉)[^\d]{0,15}?(?:周度产量|周产量|当周产量|本周产量|产量)[^\d]{0,15}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                        s_clean,
                        re.IGNORECASE,
                    )
                    if not m_out:
                        m_out = re.search(
                            r"(?:本期钛白粉产量|本周钛白粉产量|本期产量|周度产量|周产量|当周产量)[^\d]{0,15}?(?:在|为|约|约为)?\s*([1-9]\d*(?:\.\d+)?)\s*万吨",
                            s_clean,
                            re.IGNORECASE,
                        )
                    if m_out:
                        output = float(m_out.group(1))
                elif sym_key == "SA" and ("纯碱" in s_clean):
                    m_out = re.search(
                        r"(?:纯碱|国内纯碱)[^\d]{0,10}?(?:周度产量|周产量|当周产量|本周产量|产量)[^\d]{0,10}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                        s_clean,
                        re.IGNORECASE,
                    )
                    if m_out:
                        output = float(m_out.group(1))
                elif sym_key == "UR" and ("尿素" in s_clean):
                    m_out = re.search(
                        r"(?:尿素|国内尿素)[^\d]{0,10}?(?:周度产量|周产量|当周产量|本周产量|产量)[^\d]{0,10}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                        s_clean,
                        re.IGNORECASE,
                    )
                    if m_out:
                        output = float(m_out.group(1))
                elif sym_key == "SH" and ("烧碱" in s_clean or "离子膜" in s_clean):
                    m_out = re.search(
                        r"(?:烧碱|国内烧碱|离子膜烧碱)[^\d]{0,10}?(?:周度产量|周产量|当周产量|本周产量|产量)[^\d]{0,10}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                        s_clean,
                        re.IGNORECASE,
                    )
                    if m_out:
                        output = float(m_out.group(1))
                elif sym_key == "EB" and ("苯乙烯" in s_clean or "EB" in s_clean):
                    m_out = re.search(
                        r"(?:苯乙烯|国内苯乙烯)(?:企业)?(?:总产量|周度产量|周产量|当周产量|本周产量|产出|产量)[^\d]{0,10}?(?:为|至|约)?\s*([1-9]\d*(?:\.\d+)?)\s*万吨",
                        s_clean,
                        re.IGNORECASE,
                    )
                    if not m_out:
                        m_out = re.search(r"总产量[^\d]{0,10}?([1-9]\d*(?:\.\d+)?)\s*万吨", s_clean)
                    if m_out:
                        output = float(m_out.group(1))
                elif sym_key == "PP" and (
                    "聚丙烯" in s_clean or "PP" in s_clean or "周均产量" in s_clean
                ):
                    m_out = re.search(
                        r"(?:聚丙烯|PP|中国聚丙烯)?(?:企业)?(?:周度总产量|总产量|周度产量|周产量|当周产量|本周产量|周均产量|产量)[^\d]{0,10}?(?:为|至|约|在|仍在)?\s*([1-9]\d*(?:\.\d+)?)\s*万吨",
                        s_clean,
                        re.IGNORECASE,
                    )
                    if m_out:
                        output = float(m_out.group(1))
                elif sym_key == "PX" and ("PX" in s_clean or "对二甲苯" in s_clean):
                    m_out = re.search(
                        r"(?:PX|对二甲苯|国内PX)(?:企业)?(?:周度产量|周产量|当周产量|本周产量|产量)[^\d]{0,10}?(?:为|至|约)?\s*([1-9]\d*(?:\.\d+)?)\s*万吨",
                        s_clean,
                        re.IGNORECASE,
                    )
                    if m_out:
                        output = float(m_out.group(1))

        # 3. 库存（企业库存 / 港口库存 / 社会库存）
        is_downstream_inv = any(f"{dk}库存" in s_clean for dk in downstream_kw)
        allow_inv = not is_downstream_inv and (
            not has_downstream
            or f"{p_norm}厂家库存" in s_clean
            or f"{p_norm}企业库存" in s_clean
            or f"{p_norm}库存" in s_clean
            or f"{sym_key}工厂库存" in s_clean
        )
        if inv is None and allow_inv:
            if sym_key == "TA" and (
                "PTA" in s_clean or "社会库存" in s_clean or "工厂库存" in s_clean
            ):
                m_inv = re.search(
                    r"(?:PTA工厂库存|PTA社会库存|PTA企业库存|PTA厂家库存|PTA社会库存量)[^\d]{0,15}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                    s_clean,
                    re.IGNORECASE,
                )
                if not m_inv:
                    m_inv = re.search(
                        r"PTA[^\d]{0,10}?(?:社会库存|工厂库存|企业库存|厂家库存)[^\d]{0,15}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                        s_clean,
                        re.IGNORECASE,
                    )
                if m_inv:
                    inv = float(m_inv.group(1))
            elif sym_key == "MEG" and (
                "主港" in s_clean or "乙二醇" in s_clean or "MEG" in s_clean
            ):
                m_inv = re.search(
                    r"(?:华东主港库存|乙二醇主港库存|乙二醇港口库存|MEG主港库存|MEG港口库存|主港库存|港口库存|华东主港地区G库存总量)[^\d]{0,15}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                    s_clean,
                    re.IGNORECASE,
                )
                if not m_inv:
                    m_inv = re.search(
                        r"(?:乙二醇|MEG)[^\d]{0,15}?(?:主港库存|港口库存|库存)[^\d]{0,15}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                        s_clean,
                        re.IGNORECASE,
                    )
                if m_inv:
                    inv = float(m_inv.group(1))
            elif sym_key == "MA" and (
                "甲醇" in s_clean or "港口" in s_clean or "企业库存" in s_clean
            ):
                m_inv = re.search(
                    r"(?:甲醇港口库存|甲醇港口样本库存|甲醇企业库存|生产企业库存|港口库存|港口总库存)[^\d]{0,15}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                    s_clean,
                    re.IGNORECASE,
                )
                if m_inv:
                    inv = float(m_inv.group(1))
            elif sym_key == "V" and (
                "PVC" in s_clean
                or "聚氯乙烯" in s_clean
                or "社会库存" in s_clean
                or "厂区库存" in s_clean
                or "第三方库存" in s_clean
            ):
                m_inv = re.search(
                    r"(?:PVC|聚氯乙烯)?[^\d]{0,15}?(?:社会库存|企业厂区库存|厂区库存|生产企业库存|仓库库存|企业库存|第三方库存量)[^\d]{0,15}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                    s_clean,
                    re.IGNORECASE,
                )
                if m_inv:
                    inv = float(m_inv.group(1))
            elif sym_key == "TIO2" and ("钛白粉" in s_clean or "TIO2" in s_clean.upper()):
                m_inv = re.search(
                    r"(?:钛白粉)?(?:厂家库存|企业库存|生产厂家库存|成品库存)[^\d]{0,15}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                    s_clean,
                    re.IGNORECASE,
                )
                if m_inv:
                    inv = float(m_inv.group(1))
            elif sym_key == "SA" and ("纯碱" in s_clean or "厂家库存" in s_clean):
                m_inv = re.search(
                    r"(?:厂家总库存|国内纯碱厂家总库存|碱厂总库存|纯碱企业库存|企业总库存)[^\d]{0,15}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                    s_clean,
                    re.IGNORECASE,
                )
                if m_inv:
                    inv = float(m_inv.group(1))
            elif sym_key == "UR" and ("尿素" in s_clean or "企业库存" in s_clean):
                m_inv = re.search(
                    r"(?:尿素企业库存|企业库存|厂家库存|尿素库存)[^\d]{0,15}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                    s_clean,
                    re.IGNORECASE,
                )
                if m_inv:
                    inv = float(m_inv.group(1))
            elif sym_key == "SH" and (
                "烧碱" in s_clean or "企业库存" in s_clean or "厂内库存" in s_clean
            ):
                m_inv = re.search(
                    r"(?:烧碱企业库存|企业库存|厂内库存|烧碱库存)[^\d]{0,15}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                    s_clean,
                    re.IGNORECASE,
                )
                if m_inv:
                    inv = float(m_inv.group(1))
            elif sym_key == "EB" and (
                "苯乙烯" in s_clean
                or "主流库区" in s_clean
                or "港口库存" in s_clean
                or "主港" in s_clean
                or "样本库存" in s_clean
            ):
                m_inv = re.search(
                    r"(?:苯乙烯华东主港库存|江苏苯乙烯主流库区总库存|华东主港库存|江苏主流库区总库存|样本库存|港口库存|主流库区总库存|企业库存)[^\d]{0,15}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                    s_clean,
                    re.IGNORECASE,
                )
                if not m_inv:
                    m_inv = re.search(
                        r"(?:苯乙烯|EB)[^\d]{0,10}?(?:库存|库区总库存)[^\d]{0,15}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                        s_clean,
                    )
                if m_inv:
                    inv = float(m_inv.group(1))
            elif sym_key == "PP" and (
                "聚丙烯" in s_clean
                or "生产企业" in s_clean
                or "两油" in s_clean
                or "企业库存" in s_clean
                or "主要生产企业" in s_clean
                or "库存位置" in s_clean
            ):
                m_inv = re.search(
                    r"(?:中国聚丙烯主要生产企业总库存|主要生产企业总库存|生产企业总库存|聚丙烯企业库存|企业库存|两油库存|库存位置接近|库存位置)[^\d]{0,15}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                    s_clean,
                    re.IGNORECASE,
                )
                if not m_inv:
                    m_inv = re.search(
                        r"(?:聚丙烯|PP)[^\d]{0,10}?(?:库存|总库存)[^\d]{0,15}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                        s_clean,
                    )
                if m_inv:
                    inv = float(m_inv.group(1))
            elif sym_key == "PX" and (
                "PX" in s_clean
                or "对二甲苯" in s_clean
                or "主港库存" in s_clean
                or "港口库存" in s_clean
                or "企业库存" in s_clean
            ):
                m_inv = re.search(
                    r"(?:国内PX库存|PX企业库存|PX主港库存|PX港口库存|港口库存|企业库存)[^\d]{0,15}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                    s_clean,
                    re.IGNORECASE,
                )
                if not m_inv:
                    m_inv = re.search(
                        r"(?:对二甲苯|PX)[^\d]{0,10}?(?:库存|总库存)[^\d]{0,15}?([1-9]\d*(?:\.\d+)?)\s*万吨",
                        s_clean,
                    )
                if m_inv:
                    inv = float(m_inv.group(1))

        # 4. 出货率 / 产销率
        if shipment is None and ("出货率" in s_clean or "产销率" in s_clean):
            m_ship = re.search(
                r"(?:出货率|产销率)[^\d%]{0,15}?(?:在|为|达)?\s*([1-9]\d*(?:\.\d+)?)%",
                s_clean,
            )
            if m_ship:
                shipment = float(m_ship.group(1))

    # 5. 严格物理常识守恒门禁过滤（超出物理合理区间的坚决置空）
    bounds = CHEMICAL_PHYSICAL_BOUNDS.get(sym_key, {})
    if util is not None:
        min_u, max_u = bounds.get("operating_rate_pct", (40.0, 100.0))
        if not (min_u <= util <= max_u):
            util = None

    if output is not None:
        min_o, max_o = bounds.get("weekly_output_w_tons", (1.0, 500.0))
        if not (min_o <= output <= max_o):
            output = None

    if inv is not None:
        min_i, max_i = bounds.get("factory_inventory_w_tons", (1.0, 500.0))
        if not (min_i <= inv <= max_i):
            inv = None

    if shipment is not None and not (10.0 <= shipment <= 200.0):
        shipment = None

    return {
        "operating_rate_pct": util,
        "weekly_output_w_tons": output,
        "factory_inventory_w_tons": inv,
        "shipment_rate_pct": shipment,
    }


def _weekly_survey_row_to_csv(row: dict[str, Any]) -> dict[str, object]:
    return {
        "trade_date": row["trade_date"].isoformat(),
        "report_date": row["report_date"].isoformat(),
        "product_name": row["product_name"],
        "symbol": row["symbol"],
        "operating_rate_pct": row["operating_rate_pct"]
        if row["operating_rate_pct"] is not None
        else "",
        "weekly_output_w_tons": row["weekly_output_w_tons"]
        if row["weekly_output_w_tons"] is not None
        else "",
        "factory_inventory_w_tons": row["factory_inventory_w_tons"]
        if row["factory_inventory_w_tons"] is not None
        else "",
        "shipment_rate_pct": row["shipment_rate_pct"]
        if row["shipment_rate_pct"] is not None
        else "",
        "source": row["source"],
        "source_url": row["source_url"],
        "release_date": row["release_date"].isoformat() if row.get("release_date") else "",
        "data_status": row.get("data_status") or "actual",
        "collected_at": row["collected_at"],
        "raw_content_sha256": row.get("raw_content_sha256") or "",
        "raw_snapshot_path": row.get("raw_snapshot_path") or "",
    }


__all__ = [
    "collect_100ppi_weekly_records",
    "has_weekly_metrics",
    "load_weekly_survey_raw_csv",
    "parse_commodity_weekly_metrics",
    "parse_page_release_date",
    "save_weekly_survey_raw_csv",
]
