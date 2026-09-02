"""全球晶圆代工 (TSMC / SMIC) 官方产能利用率在线采集爬虫与公告解析器。

数据源:
1. 台积电 (TSMC) 官方 IR 季度运营公报与管理层分析: https://investor.tsmc.com/chinese/quarterly-results
2. 中芯国际 (SMIC) 官方业绩公报 (HKEX / SSE): https://www.smics.com/site/news
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag
from curl_cffi import requests

logger = logging.getLogger(__name__)

SMIC_NEWS_URL = "https://www.smics.com/site/news"
TSMC_IR_URL = "https://investor.tsmc.com/chinese/quarterly-results"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class FoundryUtilizationCrawler:
    """晶圆代工官方产能利用率在线抓取与解析器。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.snapshot_dir = self.raw_dir / "semiconductors" / "foundry"

    def parse_smic_operating_text(
        self, text: str, default_quarter: str | None = None, default_date: date | None = None
    ) -> dict[str, Any] | None:
        """从中芯国际季度业绩公报文本中解析产能利用率、月产能与出货量。"""
        if not text:
            return None

        # 1. 匹配报告季度: 例如 "二零二四年第三季", "2024年第三季度", "2024Q3", "third quarter of 2024"
        q_str = default_quarter
        ch_year_map = {
            "零": "0",
            "〇": "0",
            "○": "0",
            "一": "1",
            "二": "2",
            "三": "3",
            "四": "4",
            "五": "5",
            "六": "6",
            "七": "7",
            "八": "8",
            "九": "9",
        }
        q_map = {"一": 1, "二": 2, "三": 3, "四": 4, "1": 1, "2": 2, "3": 3, "4": 4}

        # 匹配中文大写年份: 二零二四年第三季
        ch_match = re.search(r"([零〇○一二三四五六七八九]{4})年?\s*第([一二三四1-4])季", text)
        if ch_match:
            ch_yr, ch_q = ch_match.groups()
            yr_str = "".join(ch_year_map.get(c, c) for c in ch_yr)
            q_idx = q_map.get(ch_q, 1)
            q_str = f"{yr_str}Q{q_idx}"
        else:
            q_match = re.search(r"(\d{4})年?\s*(?:第([一二三四1-4])季|Q([1-4]))", text)
            if q_match:
                yr_str, ch_q, num_q = q_match.groups()
                q_idx = q_map.get(ch_q) or (int(num_q) if num_q else 1)
                q_str = f"{yr_str}Q{q_idx}"

        # 2. 匹配产能利用率: 例如 "產能利用率為85.2%", "产能利用率为 85.2%", "capacity utilization rate of 80.8%"
        util_match = re.search(
            r"(?:產能利用率|产能利用率|capacity utilization rate)[^\d%]{0,15}(\d{1,2}(?:\.\d+)?)\s*%",
            text,
            re.IGNORECASE,
        )
        smic_util = float(util_match.group(1)) if util_match else None

        # 3. 匹配月产能 (折合 8 英寸千片/月): 例如 "增加至二零二四年第三季的884.25千片", "月产能为 814.5 千片"
        cap_match = re.search(
            r"(?:月產能|月产能)[^。\n]*?(?:增加至|增加到|上升至|至)\s*(?:[^。\n]*?的)?\s*([\d\.]+)\s*(?:千片|k)",
            text,
            re.IGNORECASE,
        )
        smic_cap: float | None
        if cap_match:
            smic_cap = float(cap_match.group(1))
        else:
            cap_simple = re.search(
                r"(?:月產能|月产能)[^。\n]*?([0-9]+(?:\.[0-9]+)?)\s*(?:千片|k)", text, re.IGNORECASE
            )
            smic_cap = float(cap_simple.group(1)) if cap_simple else None

        # 4. 匹配晶圆出货量 (千片): 例如 "晶圓出貨量為1,790千片", "晶圆出货量为 1,920 千片"
        ship_match = re.search(
            r"(?:晶圓出貨量|晶圆出货量|wafer shipments)[^\d]{0,15}([\d,]+(?:\.\d+)?)\s*(?:千片|k)",
            text,
            re.IGNORECASE,
        )
        smic_ship = float(ship_match.group(1).replace(",", "")) if ship_match else None

        if not q_str or smic_util is None:
            return None

        yr = int(q_str[:4])
        q_idx = int(q_str[-1])
        m_end = q_idx * 3
        d_end = 31 if m_end in (3, 12) else 30
        t_date = date(yr, m_end, d_end)

        return {
            "report_quarter": q_str,
            "trade_date": t_date,
            "smic_utilization_pct": smic_util,
            "smic_monthly_capacity_8inch_kw": smic_cap,
            "smic_wafer_shipment_kw": smic_ship,
            "release_date": default_date or t_date,
        }

    def fetch_latest_smic(self) -> list[dict[str, Any]]:
        """在线抓取中芯国际官方最新季度公报。"""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        results: list[dict[str, Any]] = []

        try:
            resp = requests.get(SMIC_NEWS_URL, headers=HEADERS, timeout=15, impersonate="chrome120")
            if resp.status_code != 200 or not resp.content:
                return results

            soup = BeautifulSoup(resp.content, "html.parser")
            for a_tag in soup.find_all("a", href=True):
                if not isinstance(a_tag, Tag):
                    continue
                t = a_tag.get_text(strip=True)
                if any(kw in t for kw in ["业绩公布", "季度业绩", "Results Announcement"]):
                    href = a_tag.get("href")
                    if not isinstance(href, str):
                        continue
                    full_url = href if href.startswith("http") else f"https://www.smics.com{href}"
                    try:
                        art_resp = requests.get(
                            full_url, headers=HEADERS, timeout=15, impersonate="chrome120"
                        )
                        if art_resp.status_code == 200:
                            parsed = self.parse_smic_operating_text(art_resp.text)
                            if parsed:
                                results.append(parsed)
                    except Exception as e:
                        logger.warning("抓取中芯国际公报失败 [%s]: %s", full_url, e)
        except Exception as exc:
            logger.warning("请求中芯国际新闻页面异常: %s", exc)

        return results
