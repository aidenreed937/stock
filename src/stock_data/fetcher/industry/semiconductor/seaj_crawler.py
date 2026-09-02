"""SEAJ (日本半导体制造装置协会) 月度设备出货额在线采集爬虫与 PDF/HTML 解析器。

数据源: SEAJ (https://www.seaj.or.jp/statistics/)
每月 20-25 日发布上月日本制造半导体制造装置出货额速报 (含 3MMA 出货额、环比与同比增幅)。
"""

from __future__ import annotations

import io
import logging
import re
import urllib.parse
from datetime import date
from pathlib import Path
from typing import Any

import pypdf
from bs4 import BeautifulSoup
from bs4.element import Tag
from curl_cffi import requests

logger = logging.getLogger(__name__)

SEAJ_BASE_URL = "https://www.seaj.or.jp/statistics/"
SEAJ_STATISTICS_URL = SEAJ_BASE_URL

SEAJ_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


class SeajPdfParser:
    """SEAJ 官方速报 PDF 结构化解析器。"""

    def parse_pdf_bytes(
        self, pdf_bytes: bytes, release_date: date | None = None
    ) -> list[dict[str, Any]]:
        """从 SEAJ 出货速报 PDF 字节流中解析历史月份 3MMA 出货额与同比/环比增速。"""
        results: list[dict[str, Any]] = []
        if not pdf_bytes:
            return results

        try:
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
            full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            logger.warning("解析 SEAJ PDF 失败: %s", exc)
            return results

        # 匹配 PDF 中的表格行:
        # 例: 2026/7(暫定値) 556,220 8.3% 35.4%
        # 例: 2026/6(確定値) 513,610 -2.4% 26.9%
        # 例: 2026/2 423,103 -1.0% 2.7%
        table_pattern = re.compile(
            r"(\d{4})/(\d{1,2})(?:\([^\)]*\))?\s+([\d,]+)\s+([+\-]?[\d\.]+)%?\s+([+\-]?[\d\.]+)%?",
            re.MULTILINE,
        )

        # 找到 PDF 中最新月份
        matches = list(table_pattern.finditer(full_text))
        latest_ym = None
        if matches:
            latest_ym = f"{int(matches[0].group(1)):04d}-{int(matches[0].group(2)):02d}"

        for match in matches:
            yr_str, mo_str, bill_str, mom_str, yoy_str = match.groups()
            try:
                yr = int(yr_str)
                mo = int(mo_str)
                report_month = f"{yr:04d}-{mo:02d}"

                # 单位为百万円 (Million JPY), 折算为 十億円 (Billion JPY, 1 十亿 = 1,000 百万)
                bill_raw = float(bill_str.replace(",", ""))
                b_3mma = round(bill_raw / 1000.0, 2)

                mom = round(float(mom_str.replace(",", "").replace("%", "")) / 100.0, 4)
                yoy = round(float(yoy_str.replace(",", "").replace("%", "")) / 100.0, 4)

                # 发布日对齐: 最新月份使用实际公报日, 历史月份对齐次月 25 日法定速报发布日
                if report_month == latest_ym and release_date is not None:
                    row_rel_date = release_date
                else:
                    next_yr, next_mo = (yr + 1, 1) if mo == 12 else (yr, mo + 1)
                    row_rel_date = date(next_yr, next_mo, 25)

                results.append(
                    {
                        "report_month": report_month,
                        "billings_jpy_billion": b_3mma,
                        "billings_3mma_jpy": b_3mma,
                        "mom_growth_3mma": mom,
                        "yoy_growth_3mma": yoy,
                        "yoy_growth": yoy,
                        "release_date": row_rel_date,
                    }
                )
            except (ValueError, TypeError):
                continue

        return results


class SeajCrawler:
    """SEAJ 官网在线采集爬虫。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.snapshot_dir = self.raw_dir / "semiconductor" / "seaj"
        self.pdf_parser = SeajPdfParser()

    def fetch_latest(self, force: bool = False) -> list[dict[str, Any]]:
        """抓取并解析 SEAJ 官网最新半导体制造装置出货速报 PDF。"""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        html_snapshot_file = self.snapshot_dir / "seaj_statistics_index.html"
        pdf_snapshot_file = self.snapshot_dir / "latest_press_release.pdf"

        html_text = ""
        pdf_url = None
        rel_date: date | None = None

        # 1. 在线抓取 statistics 首页并提取最新 PDF 链接
        try:
            resp = requests.get(
                SEAJ_BASE_URL,
                headers=SEAJ_HEADERS,
                timeout=15,
                impersonate="chrome120",
            )
            if resp.status_code == 200 and resp.content:
                html_text = resp.content.decode("shift_jis", errors="ignore")
                html_snapshot_file.write_text(html_text, encoding="utf-8")

                soup = BeautifulSoup(html_text, "html.parser")
                for tr in soup.find_all("tr"):
                    t = tr.get_text(separator=" ", strip=True)
                    if "半導体製造装置（日本製）" in t and "販売高速報値" in t:
                        # 提取发布日期: 如 2026年8月21日
                        m_date = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", t)
                        if m_date:
                            rel_date = date(
                                int(m_date.group(1)), int(m_date.group(2)), int(m_date.group(3))
                            )

                        a = tr.find("a", href=True)
                        if isinstance(a, Tag):
                            href = a.get("href")
                            if isinstance(href, str):
                                pdf_url = urllib.parse.urljoin(SEAJ_BASE_URL, href)
                        break
        except Exception as exc:
            logger.warning("请求 SEAJ statistics 首页失败: %s", exc)

        # 2. 抓取/读取最新 PDF 字节流并解析
        pdf_bytes = b""
        if pdf_url:
            try:
                pdf_resp = requests.get(
                    pdf_url, headers=SEAJ_HEADERS, timeout=15, impersonate="chrome120"
                )
                if pdf_resp.status_code == 200 and pdf_resp.content:
                    pdf_bytes = pdf_resp.content
                    pdf_snapshot_file.write_bytes(pdf_bytes)
                    logger.info("成功在线抓取并落盘 SEAJ 官方出货速报 PDF: %s", pdf_url)
            except Exception as exc:
                logger.warning("下载 SEAJ 官方速报 PDF 失败 (%s), 尝试读取本地快照", exc)

        if not pdf_bytes and pdf_snapshot_file.exists():
            try:
                pdf_bytes = pdf_snapshot_file.read_bytes()
            except Exception:
                pass

        if not pdf_bytes:
            return []

        return self.pdf_parser.parse_pdf_bytes(pdf_bytes, release_date=rel_date)
