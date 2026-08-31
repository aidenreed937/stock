"""消费电子终端季度出货 (IDC) 官方公开源在线采集爬虫 (ConsumerElectronicsCrawler)。

数据源与口径:
- IDC Press Release (my.idc.com/getdoc.jsp): 全球智能手机 / 全球 PC / 中国市场季度出货量
  (branded sell-in 口径), 免费静态 HTML, 正文含总量、同比与 Top 厂商表格;
- AI 手机 / AI PC 渗透率仅有年度预测 (IDC GenAI / Canalys AI-capable), 无稳定免费季度序列,
  本采集器不自动填充, 保留本地快照历史值;
- Canalys 已并入 Omdia, 旧 canalys.com 新闻稿 URL 失效, 本采集器固定 IDC 单一机构口径。
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from stock_data.fetcher.industry.common import now_utc_iso

logger = logging.getLogger(__name__)

IDC_GETDOC_URL = "https://my.idc.com/getdoc.jsp?containerId={cid}"
IDC_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# 最新一期 IDC Press Release containerId (随季度发布人工更新; 新编号可从 IDC 新闻室/搜索发现)
IDC_PR_IDS: dict[str, str] = {
    "smartphone_global": "prUS53868725",  # 3Q25 全球智能手机出货
    "pc_global": "prUS53855725",  # 3Q25 全球 PC 出货
    "china": "prAP53871825",  # 3Q25 中国市场智能手机出货
}

_QUARTER_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4}


def extract_idc_quarter(text: str) -> str | None:
    """从 IDC PR 正文提取报告季度 (如 '3Q25' / 'third quarter of 2025' -> '2025-Q3')。"""
    m = re.search(r"([1-4])Q\s*(\d{2})\b", text)
    if m:
        return f"20{m.group(2)}-Q{m.group(1)}"
    m2 = re.search(r"(first|second|third|fourth)\s+quarter\s+of\s+(20\d\d)", text, re.IGNORECASE)
    if m2:
        return f"{m2.group(2)}-Q{_QUARTER_WORDS[m2.group(1).lower()]}"
    return None


def extract_total_million_units(text: str) -> float | None:
    """提取 'reached 322.7 million units' 类出货总量 (百万台)。"""
    m = re.search(r"([\d,]+\.?\d*)\s*million\s+units", text, re.IGNORECASE)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def extract_yoy_growth(text: str) -> float | None:
    """提取同比增速 (如 'increased 2.6% year-over-year' / 'declined 0.6%' 等 IDC 句式)。"""
    m = re.search(
        r"(?:increased|grew|rose|grew by|up)\s+([\d.]+)\s*%\s*(?:year-over-year|YoY|from the prior year)",
        text,
        re.IGNORECASE,
    )
    if m:
        return round(float(m.group(1)) / 100.0, 4)
    m = re.search(
        r"(?:declined|fell|dipped|down)\s+([\d.]+)\s*%\s*(?:year-over-year|YoY|from the prior year)",
        text,
        re.IGNORECASE,
    )
    if m:
        return round(-float(m.group(1)) / 100.0, 4)
    m = re.search(
        r"decline\s+(?:easing to|of|to)\s+([\d.]+)\s*%",
        text,
        re.IGNORECASE,
    )
    if m:
        return round(-float(m.group(1)) / 100.0, 4)
    return None


def _to_float(val: str) -> float | None:
    cleaned = val.replace(",", "").strip()
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def parse_idc_vendor_table(html_text: str) -> dict[str, float]:
    """从 IDC PR 厂商表格提取 Apple 与 Transsion 季度出货量 (百万台)。

    表格列序: Company | 本期出货 | 本期份额 | 上期出货 | 上期份额 | YoY。
    """
    soup = BeautifulSoup(html_text, "html.parser")
    result: dict[str, float] = {}
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            row_label = cells[0]
            if "apple" in row_label.lower():
                val = _to_float(cells[1])
                if val is not None:
                    result["apple_shipments_million"] = val
            elif "transsion" in row_label.lower():
                val = _to_float(cells[1])
                if val is not None:
                    result["transsion_shipments_million"] = val
    return result


def parse_idc_smartphone_pr(html_text: str) -> dict[str, Any] | None:
    """解析 IDC 全球智能手机季度 PR。"""
    quarter = extract_idc_quarter(html_text)
    if quarter is None:
        return None
    result: dict[str, Any] = {
        "report_quarter": quarter,
        "global_smartphone_shipments_million": extract_total_million_units(html_text),
        "smartphone_yoy_growth": extract_yoy_growth(html_text),
    }
    result.update(parse_idc_vendor_table(html_text))
    if result["global_smartphone_shipments_million"] is None:
        return None
    return result


def parse_idc_pc_pr(html_text: str) -> dict[str, Any] | None:
    """解析 IDC 全球 PC 季度 PR。"""
    quarter = extract_idc_quarter(html_text)
    if quarter is None:
        return None
    return {
        "report_quarter": quarter,
        "global_pc_shipments_million": extract_total_million_units(html_text),
        "pc_yoy_growth": extract_yoy_growth(html_text),
    }


def parse_idc_china_pr(html_text: str) -> dict[str, Any] | None:
    """解析 IDC 中国市场智能手机季度 PR。"""
    quarter = extract_idc_quarter(html_text)
    if quarter is None:
        return None
    return {
        "report_quarter": quarter,
        "china_smartphone_shipments_million": extract_total_million_units(html_text),
        "smartphone_yoy_growth": extract_yoy_growth(html_text),
    }


class ConsumerElectronicsCrawler:
    """IDC 官方 Press Release 克制爬虫 (每季度 3 个 PR, 单次轻量请求)。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.snapshot_dir = self.raw_dir / "electronics" / "idc"

    def fetch_latest_quarter(self) -> dict[str, Any] | None:
        """抓取最新一期 IDC 全球手机 / PC / 中国 PR 并合并为单季度记录。"""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        merged: dict[str, Any] | None = None

        for key, cid in IDC_PR_IDS.items():
            url = IDC_GETDOC_URL.format(cid=cid)
            try:
                logger.info("正在抓取 IDC Press Release: %s", url)
                resp = requests.get(url, headers=IDC_HEADERS, timeout=15)
                if resp.status_code != 200:
                    logger.warning("IDC %s 返回 HTTP %d", key, resp.status_code)
                    continue
                resp.encoding = "utf-8"
                html_text = resp.text
                # 保存 RAW 原始快照
                snapshot_file = self.snapshot_dir / f"idc_{key}_{cid}.html"
                try:
                    snapshot_file.write_text(html_text, encoding="utf-8")
                except Exception as e:
                    logger.debug("保存 IDC 快照失败: %s", e)

                if key == "smartphone_global":
                    parsed = parse_idc_smartphone_pr(html_text)
                elif key == "pc_global":
                    parsed = parse_idc_pc_pr(html_text)
                else:
                    parsed = parse_idc_china_pr(html_text)

                if not parsed:
                    logger.warning("IDC %s PR 解析失败，跳过", key)
                    continue
                if merged is None:
                    merged = dict(parsed)
                else:
                    if merged.get("report_quarter") != parsed.get("report_quarter"):
                        logger.warning(
                            "IDC PR 季度不一致 [%s vs %s]，以首次解析季度为准",
                            merged.get("report_quarter"),
                            parsed.get("report_quarter"),
                        )
                        continue
                    for k, v in parsed.items():
                        if v is not None:
                            merged[k] = v
            except Exception as e:
                logger.warning("抓取 IDC %s 异常: %s", key, e)

        if merged:
            merged["source"] = "IDC"
            merged["source_url"] = IDC_GETDOC_URL.format(cid=IDC_PR_IDS["smartphone_global"])
            merged["release_date"] = date.today().isoformat()
            merged["data_status"] = "actual"
            merged["collected_at"] = now_utc_iso()
        return merged
