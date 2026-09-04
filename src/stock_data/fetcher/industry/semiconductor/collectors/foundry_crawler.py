"""全球晶圆代工 (TSMC / SMIC) 官方产能利用率在线采集爬虫。

数据源:
1. 台积电 (TSMC) 官方 IR 季度运营公报与管理层分析: https://investor.tsmc.com/english/quarterly-results
2. 中芯国际 (SMIC) 官方业绩公报 (HKEX / SSE): https://www.smics.com/site/news
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from curl_cffi import requests

from stock_data.fetcher.industry.common import save_raw_snapshot
from stock_data.fetcher.industry.semiconductor.lineage import (
    raw_content_sha256,
    raw_snapshot_content_bytes,
    raw_snapshot_path_value,
    response_content_bytes,
)
from stock_data.fetcher.industry.semiconductor.parsers import (
    extract_smic_announcement_targets,
    extract_smic_financial_report_links,
    extract_tsmc_quarterly_report_links,
    parse_smic_operating_pdf_bytes,
    parse_smic_operating_text,
    parse_tsmc_quarterly_report_pdf_bytes,
    parse_tsmc_quarterly_report_text,
)
from stock_data.fetcher.industry.semiconductor.paths import SemiconductorRawPaths

logger = logging.getLogger(__name__)

SMIC_NEWS_URL = "https://www.smics.com/site/news"
SMIC_FINANCIAL_SUMMARY_URL = "https://www.smics.com/en/site/company_financialSummary?year={year}"
TSMC_IR_URL = "https://investor.tsmc.com/english/quarterly-results"
TSMC_QUARTERLY_RESULTS_URL = f"{TSMC_IR_URL}/{{year}}/q{{quarter}}"

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class FoundryUtilizationCrawler:
    """晶圆代工官方产能利用率在线抓取器。"""

    def __init__(
        self,
        raw_dir: Path | str,
        timeout: int = 15,
        impersonate: str = "chrome120",
    ) -> None:
        self.paths = SemiconductorRawPaths(raw_dir)
        self.snapshot_dir = self.paths.foundry_dir
        self.timeout = timeout
        self.impersonate = impersonate

    def fetch_latest(self, force: bool = False) -> list[dict[str, Any]]:
        """在线抓取中芯国际官方最新季度公报。"""
        return self.fetch_latest_smic(force=force)

    def fetch_latest_smic(self, force: bool = False) -> list[dict[str, Any]]:
        """兼容旧入口，在线抓取 SMIC 与 TSMC 最新可用季度资料。"""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        if force:
            logger.debug("晶圆代工强制刷新: 跳过调度层缓存并重新访问线上源")

        return self._fetch_online(start_date=None, end_date=None)

    def fetch_latest_tsmc(self, force: bool = False) -> list[dict[str, Any]]:
        """只抓取 TSMC 最近一个已完成季度的管理报告。"""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        if force:
            logger.debug("TSMC 晶圆代工强制刷新: 跳过调度层缓存并重新访问线上源")
        return self._fetch_tsmc_online(
            start_date=None,
            end_date=None,
        )

    def fetch_range(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        """在线采集指定报告期范围内的 SMIC/TSMC 季度资料。"""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        if force:
            logger.debug("晶圆代工范围刷新: 跳过调度层缓存并重新访问线上源")
        return self._fetch_online(start_date=start_date, end_date=end_date)

    def _fetch_online(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
    ) -> list[dict[str, Any]]:
        smic_results = self._fetch_smic_online(start_date=start_date, end_date=end_date)
        tsmc_results = self._fetch_tsmc_online(start_date=start_date, end_date=end_date)
        return _merge_source_results(smic_results, tsmc_results)

    def _fetch_smic_online(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        try:
            resp = requests.get(
                SMIC_NEWS_URL,
                headers=HEADERS,
                timeout=self.timeout,
                impersonate=self.impersonate,
            )
            list_bytes = response_content_bytes(resp)
            if resp.status_code != 200 or not list_bytes:
                return results
            self._write_snapshot("smic_news_list.html", list_bytes)

            seen_urls: set[str] = set()
            for full_url, listing_release_date in extract_smic_announcement_targets(list_bytes):
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)
                try:
                    art_resp = requests.get(
                        full_url,
                        headers=HEADERS,
                        timeout=self.timeout,
                        impersonate=self.impersonate,
                    )
                    if art_resp.status_code == 200:
                        article_bytes = response_content_bytes(art_resp)
                        article_text = getattr(art_resp, "text", "") or article_bytes.decode(
                            "utf-8", errors="ignore"
                        )
                        content_hash, snapshot_ref = self._write_snapshot(
                            f"{_snapshot_stem(full_url)}.html", article_bytes
                        )
                        parsed = parse_smic_operating_text(
                            article_text,
                            default_date=listing_release_date,
                        )
                        if parsed is not None and _in_date_range(
                            parsed,
                            start_date=start_date,
                            end_date=end_date,
                        ):
                            results.append(
                                _tag_source_item(
                                    parsed,
                                    source="SMIC_IR",
                                    prefix="smic",
                                    source_url=full_url,
                                    content_hash=content_hash,
                                    snapshot_ref=snapshot_ref,
                                )
                            )
                except Exception as e:
                    logger.warning("抓取中芯国际公报失败 [%s]: %s", full_url, e)
        except Exception as exc:
            logger.warning("请求中芯国际新闻页面异常: %s", exc)

        results.extend(
            self._fetch_smic_financial_reports(
                start_date=start_date,
                end_date=end_date,
            )
        )
        return _dedupe_source_results(results, "smic")

    def _fetch_smic_financial_reports(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
    ) -> list[dict[str, Any]]:
        """从 SMIC 官方财务摘要页下载季度 Earnings Release PDF。"""
        results: list[dict[str, Any]] = []
        for year in _summary_year_targets(start_date=start_date, end_date=end_date):
            page_url = SMIC_FINANCIAL_SUMMARY_URL.format(year=year)
            try:
                response = requests.get(
                    page_url,
                    headers=HEADERS,
                    timeout=self.timeout,
                    impersonate=self.impersonate,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("请求 SMIC %s 财务摘要页异常: %s", year, exc)
                continue
            page_bytes = response_content_bytes(response)
            if response.status_code != 200 or not page_bytes:
                continue
            self._write_snapshot(f"smic_financial_summary_{year}.html", page_bytes)
            for report_url in extract_smic_financial_report_links(
                page_bytes,
                base_url=page_url,
            ):
                try:
                    report_response = requests.get(
                        report_url,
                        headers=HEADERS,
                        timeout=self.timeout,
                        impersonate=self.impersonate,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("下载 SMIC %s 财务报告异常: %s", year, exc)
                    continue
                report_bytes = response_content_bytes(report_response)
                if report_response.status_code != 200 or not report_bytes:
                    continue
                content_hash, snapshot_ref = self._write_snapshot(
                    f"smic_{year}_{_snapshot_stem(report_url)}.pdf",
                    report_bytes,
                    compress=False,
                )
                parsed = parse_smic_operating_pdf_bytes(report_bytes)
                if parsed is None or not _in_date_range(
                    parsed,
                    start_date=start_date,
                    end_date=end_date,
                ):
                    continue
                results.append(
                    _tag_source_item(
                        parsed,
                        source="SMIC_IR",
                        prefix="smic",
                        source_url=report_url,
                        content_hash=content_hash,
                        snapshot_ref=snapshot_ref,
                    )
                )
        return results

    def _fetch_tsmc_online(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for report_quarter in _quarter_targets(start_date=start_date, end_date=end_date):
            year = int(report_quarter[:4])
            quarter = int(report_quarter[-1])
            page_url = TSMC_QUARTERLY_RESULTS_URL.format(year=year, quarter=quarter)
            try:
                page_resp = self._get_tsmc(page_url)
            except Exception as exc:  # noqa: BLE001
                logger.warning("请求 TSMC %s 季度结果页异常: %s", report_quarter, exc)
                continue

            page_bytes = response_content_bytes(page_resp)
            if page_resp.status_code != 200 or not page_bytes:
                continue

            self._write_snapshot(f"tsmc_quarterly_{report_quarter}.html", page_bytes)
            page_text = getattr(page_resp, "text", "") or page_bytes.decode(
                "utf-8", errors="ignore"
            )
            report_links = extract_tsmc_quarterly_report_links(page_bytes, base_url=page_url)
            if not report_links:
                parsed_page = parse_tsmc_quarterly_report_text(
                    page_text,
                    default_quarter=report_quarter,
                )
                if parsed_page is not None:
                    results.append(
                        _tag_source_item(
                            parsed_page,
                            source="TSMC_IR",
                            prefix="tsmc",
                            source_url=page_url,
                            content_hash=raw_content_sha256(page_bytes),
                            snapshot_ref="",
                        )
                    )
                continue

            for report_url in report_links:
                try:
                    report_resp = self._get_tsmc(report_url)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("下载 TSMC %s 季度报告异常: %s", report_quarter, exc)
                    continue
                report_bytes = response_content_bytes(report_resp)
                if report_resp.status_code != 200 or not report_bytes:
                    continue

                content_hash, snapshot_ref = self._write_snapshot(
                    f"tsmc_{report_quarter}_{_snapshot_stem(report_url)}.pdf",
                    report_bytes,
                    compress=False,
                )
                parsed = parse_tsmc_quarterly_report_pdf_bytes(
                    report_bytes,
                    default_quarter=report_quarter,
                )
                if parsed is not None and _in_date_range(
                    parsed,
                    start_date=start_date,
                    end_date=end_date,
                ):
                    results.append(
                        _tag_source_item(
                            parsed,
                            source="TSMC_IR",
                            prefix="tsmc",
                            source_url=report_url,
                            content_hash=content_hash,
                            snapshot_ref=snapshot_ref,
                        )
                    )
                break

        return _dedupe_source_results(results, "tsmc")

    def _get_tsmc(self, url: str) -> Any:
        """访问 TSMC IR，并在偶发 Cloudflare 指纹拒绝时切换浏览器指纹。"""
        personas = list(dict.fromkeys((self.impersonate, "chrome136", "safari_ios")))
        last_response: Any = None
        for persona in personas:
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=self.timeout,
                impersonate=persona,
            )
            last_response = response
            if response.status_code not in {403, 429}:
                return response
        return last_response

    def replay_cached_snapshots(self) -> list[dict[str, Any]]:
        """从本地 HTML/PDF 快照离线重放两家公司的 RAW 字段。"""
        return _merge_source_results(
            self._parse_cached_article_snapshots(),
            self._parse_cached_smic_pdf_snapshots(),
            self._parse_cached_tsmc_snapshots(),
        )

    def _parse_cached_article_snapshots(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        html_files = sorted(self.snapshot_dir.rglob("*.html")) + sorted(
            self.snapshot_dir.rglob("*.html.gz")
        )
        for html_file in html_files:
            if html_file.name.endswith("_list.html") or html_file.name.endswith("_list.html.gz"):
                continue
            try:
                content_bytes = raw_snapshot_content_bytes(html_file)
                html_text = content_bytes.decode("utf-8", errors="ignore")
                parsed = parse_smic_operating_text(html_text)
                if parsed:
                    results.append(
                        _tag_source_item(
                            parsed,
                            source="SMIC_IR",
                            prefix="smic",
                            source_url=SMIC_NEWS_URL,
                            content_hash=raw_content_sha256(content_bytes),
                            snapshot_ref=raw_snapshot_path_value(html_file, self.paths.raw_root),
                        )
                    )
            except Exception as exc:
                logger.debug("解析 SMIC 本地 HTML 快照失败 [%s]: %s", html_file.name, exc)
        return _dedupe_source_results(results, "smic")

    def _parse_cached_tsmc_snapshots(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for pdf_file in sorted(self.snapshot_dir.rglob("*.pdf")):
            if not pdf_file.name.lower().startswith("tsmc"):
                continue
            try:
                content_bytes = raw_snapshot_content_bytes(pdf_file)
                parsed = parse_tsmc_quarterly_report_pdf_bytes(content_bytes)
                if parsed:
                    results.append(
                        _tag_source_item(
                            parsed,
                            source="TSMC_IR",
                            prefix="tsmc",
                            source_url=TSMC_IR_URL,
                            content_hash=raw_content_sha256(content_bytes),
                            snapshot_ref=raw_snapshot_path_value(pdf_file, self.paths.raw_root),
                        )
                    )
            except Exception as exc:
                logger.debug("解析 TSMC 本地 PDF 快照失败 [%s]: %s", pdf_file.name, exc)
        return _dedupe_source_results(results, "tsmc")

    def _parse_cached_smic_pdf_snapshots(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for pdf_file in sorted(self.snapshot_dir.rglob("*.pdf")):
            if pdf_file.name.lower().startswith("tsmc"):
                continue
            try:
                content_bytes = raw_snapshot_content_bytes(pdf_file)
                parsed = parse_smic_operating_pdf_bytes(content_bytes)
                if parsed:
                    results.append(
                        _tag_source_item(
                            parsed,
                            source="SMIC_IR",
                            prefix="smic",
                            source_url=SMIC_NEWS_URL,
                            content_hash=raw_content_sha256(content_bytes),
                            snapshot_ref=raw_snapshot_path_value(pdf_file, self.paths.raw_root),
                        )
                    )
            except Exception as exc:
                logger.debug("解析 SMIC 本地 PDF 快照失败 [%s]: %s", pdf_file.name, exc)
        return _dedupe_source_results(results, "smic")

    def _write_snapshot(
        self,
        filename: str,
        content: str | bytes,
        *,
        compress: bool = True,
    ) -> tuple[str, str]:
        content_bytes = content if isinstance(content, bytes) else content.encode("utf-8")
        try:
            snapshot_path = save_raw_snapshot(
                "foundry",
                filename,
                content_bytes,
                base_dir=self.paths.legacy_semiconductor_dir,
                compress=compress,
            )
            return (
                raw_content_sha256(content_bytes),
                raw_snapshot_path_value(snapshot_path, self.paths.raw_root),
            )
        except Exception as exc:
            logger.debug("保存 SMIC HTML 快照失败 [%s]: %s", filename, exc)
            return raw_content_sha256(content_bytes), ""


def _snapshot_stem(url: str) -> str:
    parsed = urlparse(url)
    raw_stem = f"{parsed.netloc}{parsed.path}" or "smic_snapshot"
    stem = re.sub(r"[^0-9A-Za-z]+", "-", raw_stem).strip("-").lower()
    return stem[:120] or "smic_snapshot"


def _in_date_range(
    item: dict[str, Any],
    *,
    start_date: date | None,
    end_date: date | None,
) -> bool:
    trade_date = item.get("trade_date")
    if not isinstance(trade_date, date):
        return False
    if start_date is not None and trade_date < start_date:
        return False
    return not (end_date is not None and trade_date > end_date)


def _quarter_targets(
    *,
    start_date: date | None,
    end_date: date | None,
) -> list[str]:
    if start_date is None and end_date is None:
        return [_latest_completed_quarter()]

    start = start_date or date(2000, 1, 1)
    end = end_date or date.today()
    start_index = start.year * 4 + (start.month - 1) // 3
    end_index = end.year * 4 + (end.month - 1) // 3
    return [f"{index // 4:04d}Q{index % 4 + 1}" for index in range(start_index, end_index + 1)]


def _latest_completed_quarter() -> str:
    today = date.today()
    quarter = (today.month - 1) // 3 + 1
    if quarter == 1:
        return f"{today.year - 1:04d}Q4"
    return f"{today.year:04d}Q{quarter - 1}"


def _summary_year_targets(
    *,
    start_date: date | None,
    end_date: date | None,
) -> list[int]:
    if start_date is None and end_date is None:
        latest = _latest_completed_quarter()
        year = int(latest[:4])
        years = [year]
        if not latest.endswith("Q4"):
            years.append(year - 1)
        return years
    start_year = (start_date or date(2000, 1, 1)).year
    end_year = (end_date or date.today()).year
    return list(range(start_year, end_year + 1))


def _tag_source_item(
    item: dict[str, Any],
    *,
    source: str,
    prefix: str,
    source_url: str,
    content_hash: str,
    snapshot_ref: str,
) -> dict[str, Any]:
    tagged = dict(item)
    release_date = tagged.get("release_date")
    tagged["source"] = source
    tagged["source_url"] = source_url
    tagged["raw_content_sha256"] = content_hash
    tagged["raw_snapshot_path"] = snapshot_ref
    tagged[f"{prefix}_source_url"] = source_url
    tagged[f"{prefix}_release_date"] = release_date
    tagged[f"{prefix}_raw_content_sha256"] = content_hash
    tagged[f"{prefix}_raw_snapshot_path"] = snapshot_ref
    if prefix == "smic":
        tagged["smic_utilization_status"] = (
            "reported" if tagged.get("smic_utilization_raw") is not None else "unavailable"
        )
    if prefix == "tsmc" and "tsmc_utilization_status" not in tagged:
        tagged["tsmc_utilization_status"] = (
            "reported" if tagged.get("tsmc_utilization_raw") is not None else "unavailable"
        )
    return tagged


def _dedupe_source_results(items: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    unique_items: dict[str, dict[str, Any]] = {}
    for item in items:
        key = str(item.get("report_quarter") or item.get("source_url") or len(unique_items))
        current = unique_items.get(key)
        if current is None:
            unique_items[key] = item
            continue
        current_release = current.get(f"{prefix}_release_date")
        incoming_release = item.get(f"{prefix}_release_date")
        if isinstance(incoming_release, date) and (
            not isinstance(current_release, date) or incoming_release >= current_release
        ):
            unique_items[key] = item
    return sorted(
        unique_items.values(),
        key=lambda item: (
            item["trade_date"] if isinstance(item.get("trade_date"), date) else date.min
        ),
    )


def _merge_source_results(*result_sets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for items in result_sets:
        for item in items:
            quarter = str(item.get("report_quarter") or "")
            if not quarter:
                continue
            current = merged.setdefault(quarter, {})
            for key, value in item.items():
                if value is not None and value != "":
                    current[key] = value

    results: list[dict[str, Any]] = []
    for item in merged.values():
        sources: list[str] = []
        urls: list[str] = []
        releases: list[date] = []
        for prefix, source in (("tsmc", "TSMC_IR"), ("smic", "SMIC_IR")):
            if item.get(f"{prefix}_source_url"):
                sources.append(source)
                urls.append(str(item[f"{prefix}_source_url"]))
            release = item.get(f"{prefix}_release_date")
            if isinstance(release, date):
                releases.append(release)
        if sources:
            item["source"] = "/".join(sources)
            item["source_url"] = ";".join(urls)
            if "TSMC_IR" in sources:
                item.setdefault("tsmc_utilization_raw", None)
                item.setdefault("tsmc_wafer_shipments_12in_kpcs_raw", None)
                item.setdefault("tsmc_capacity_12in_kpcs_raw", None)
                item.setdefault("tsmc_utilization_status", "unavailable")
            if "SMIC_IR" in sources:
                item.setdefault("smic_utilization_raw", None)
                item.setdefault("smic_monthly_capacity_raw", None)
                item.setdefault("smic_wafer_shipment_raw", None)
                item.setdefault("smic_utilization_status", "unavailable")
        if releases:
            item["release_date"] = max(releases)
        if len(sources) == 1:
            prefix = "tsmc" if sources[0] == "TSMC_IR" else "smic"
            item["raw_content_sha256"] = item.get(f"{prefix}_raw_content_sha256", "")
            item["raw_snapshot_path"] = item.get(f"{prefix}_raw_snapshot_path", "")
        else:
            item["raw_content_sha256"] = ""
            item["raw_snapshot_path"] = ""
        item["data_status"] = item.get("data_status") or "actual"
        results.append(item)
    return sorted(
        results,
        key=lambda item: (
            item["trade_date"] if isinstance(item.get("trade_date"), date) else date.min
        ),
    )
