"""SEAJ (日本半导体制造装置协会) 月度设备出货额在线采集爬虫。

数据源: SEAJ (https://www.seaj.or.jp/statistics/)
每月 20-25 日发布上月日本制造半导体制造装置出货额速报 (含 3MMA 出货额、环比与同比增幅)。
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from curl_cffi import requests

from stock_data.fetcher.industry.common import save_raw_snapshot
from stock_data.fetcher.industry.semiconductor.lineage import (
    raw_content_sha256,
    raw_snapshot_content_bytes,
    raw_snapshot_path_value,
    response_content_bytes,
)
from stock_data.fetcher.industry.semiconductor.parsers import (
    SeajPdfParser,
    parse_seaj_press_release_target,
    parse_seaj_release_calendar_pdf,
)
from stock_data.fetcher.industry.semiconductor.paths import SemiconductorRawPaths

logger = logging.getLogger(__name__)

SEAJ_BASE_URL = "https://www.seaj.or.jp/statistics/"
SEAJ_STATISTICS_URL = SEAJ_BASE_URL
SEAJ_RELEASE_DATES_URL = "https://www.seaj.or.jp/file/ReleaseDates.pdf"

SEAJ_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


class SeajCrawler:
    """SEAJ 官网在线采集爬虫。"""

    def __init__(self, raw_dir: Path | str) -> None:
        self.paths = SemiconductorRawPaths(raw_dir)
        self.snapshot_dir = self.paths.seaj_dir
        self.pdf_parser = SeajPdfParser()

    def fetch_latest(self, force: bool = False) -> list[dict[str, Any]]:
        """抓取并解析 SEAJ 官网最新半导体制造装置出货速报 PDF。"""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        pdf_snapshot_file = self.snapshot_dir / "latest_press_release.pdf"

        html_text = ""
        pdf_url = None
        rel_date: date | None = None
        pdf_content_hash = ""
        pdf_snapshot_ref = ""

        # 1. 在线抓取 statistics 首页并提取最新 PDF 链接
        try:
            resp = requests.get(
                SEAJ_BASE_URL,
                headers=SEAJ_HEADERS,
                timeout=15,
                impersonate="chrome120",
            )
            if resp.status_code == 200 and resp.content:
                html_bytes = response_content_bytes(resp)
                html_text = html_bytes.decode("shift_jis", errors="ignore")
                save_raw_snapshot(
                    "seaj",
                    "seaj_statistics_index.html",
                    html_bytes,
                    base_dir=self.paths.semiconductor_dir,
                    compress=True,
                )

                target = parse_seaj_press_release_target(html_text, base_url=SEAJ_BASE_URL)
                pdf_url = target.pdf_url
                rel_date = target.release_date
        except Exception as exc:
            logger.warning("请求 SEAJ statistics 首页失败: %s", exc)

        release_dates = self._load_release_dates(force=force)

        # 2. 抓取/读取最新 PDF 字节流并解析
        pdf_bytes = b""
        if pdf_url:
            try:
                pdf_resp = requests.get(
                    pdf_url, headers=SEAJ_HEADERS, timeout=15, impersonate="chrome120"
                )
                if pdf_resp.status_code == 200 and pdf_resp.content:
                    pdf_bytes = response_content_bytes(pdf_resp)
                    pdf_snapshot_path = save_raw_snapshot(
                        "seaj",
                        "latest_press_release.pdf",
                        pdf_bytes,
                        base_dir=self.paths.semiconductor_dir,
                    )
                    pdf_content_hash = raw_content_sha256(pdf_bytes)
                    pdf_snapshot_ref = raw_snapshot_path_value(
                        pdf_snapshot_path, self.paths.raw_root
                    )
                    logger.info("成功在线抓取并落盘 SEAJ 官方出货速报 PDF: %s", pdf_url)
            except Exception as exc:
                logger.warning("下载 SEAJ 官方速报 PDF 失败 (%s), 尝试读取本地快照", exc)

        if not pdf_bytes and pdf_snapshot_file.exists():
            try:
                pdf_bytes = raw_snapshot_content_bytes(pdf_snapshot_file)
                pdf_content_hash = raw_content_sha256(pdf_bytes)
                pdf_snapshot_ref = raw_snapshot_path_value(pdf_snapshot_file, self.paths.raw_root)
            except Exception:
                pass

        if not pdf_bytes:
            return []

        items = self.pdf_parser.parse_pdf_bytes(
            pdf_bytes,
            release_date=rel_date,
            release_dates=release_dates,
        )
        for item in items:
            item["raw_content_sha256"] = pdf_content_hash
            item["raw_snapshot_path"] = pdf_snapshot_ref
        return items

    def _load_release_dates(self, force: bool = False) -> dict[str, date]:
        """读取/归档 SEAJ 官方发布日期日历。"""
        calendar_file = self.snapshot_dir / "release_dates.pdf"
        if force or not calendar_file.exists():
            try:
                response = requests.get(
                    SEAJ_RELEASE_DATES_URL,
                    headers=SEAJ_HEADERS,
                    timeout=15,
                    impersonate="chrome120",
                )
                if response.status_code == 200 and response.content:
                    save_raw_snapshot(
                        "seaj",
                        "release_dates.pdf",
                        response_content_bytes(response),
                        base_dir=self.paths.semiconductor_dir,
                    )
            except Exception as exc:
                logger.warning("请求 SEAJ 发布日期日历失败: %s", exc)
        if not calendar_file.exists():
            return {}
        try:
            return parse_seaj_release_calendar_pdf(calendar_file.read_bytes())
        except OSError as exc:
            logger.warning("读取 SEAJ 发布日期日历失败: %s", exc)
            return {}
