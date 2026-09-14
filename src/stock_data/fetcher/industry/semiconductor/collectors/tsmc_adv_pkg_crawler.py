"""台积电官方先进封装与财务拆解在线爬虫 (TsmcAdvPkgRevenueCrawler).

功能：
1. 在线探测台积电官方 IR 季度公报与法说会管理报告；
2. 自动下载原生 Management Report PDF 存证至 data/raw/industry/semiconductor/tsmc_filings/；
3. 严格验签计算 SHA-256 指纹；
4. 解析结构化财务拆解数据（新台币/美元营收、3/5/7nm先进技术占比、HPC平台占比、法说会日期）；
5. 追加记录至 tsmc_adv_pkg_revenue_raw.csv 并保证数据按季度升序有序。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from curl_cffi import requests

from stock_data.fetcher.industry.semiconductor.lineage import (
    raw_content_sha256,
    response_content_bytes,
)
from stock_data.fetcher.industry.semiconductor.parsers.adv_pkg_revenue import (
    append_tsmc_adv_pkg_revenue_raw_record,
    parse_tsmc_management_report_pdf,
)
from stock_data.fetcher.industry.semiconductor.parsers.tsmc_foundry import (
    extract_tsmc_quarterly_report_links,
)
from stock_data.fetcher.industry.semiconductor.paths import SemiconductorRawPaths

logger = logging.getLogger(__name__)

TSMC_IR_URL = "https://investor.tsmc.com/english/quarterly-results"
TSMC_QUARTERLY_RESULTS_URL = f"{TSMC_IR_URL}/{{year}}/q{{quarter}}"

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _next_candidate_quarters(current_max: str, count: int = 4) -> list[str]:
    """生成已有最大季度之后连续若干个候选季度。"""
    try:
        year = int(current_max[:4])
        q = int(current_max[-1])
    except (ValueError, IndexError):
        return []

    candidates: list[str] = []
    for _ in range(count):
        if q == 4:
            year += 1
            q = 1
        else:
            q += 1
        candidates.append(f"{year}Q{q}")
    return candidates


class TsmcAdvPkgRevenueCrawler:
    """台积电官方财务拆解报告在线探测与存证采集器。"""

    def __init__(
        self,
        raw_dir: Path | str,
        timeout: float = 30.0,
        impersonate: str = "chrome120",
    ) -> None:
        self.paths = SemiconductorRawPaths(raw_dir)
        self.filings_dir = self.paths.tsmc_filings_dir
        self.csv_path = self.paths.tsmc_adv_pkg_revenue_csv
        self.timeout = timeout
        self.impersonate = impersonate

    def _get_tsmc(self, url: str) -> Any:
        """访问 TSMC 页面并在 Cloudflare 拦截时轮换浏览器指纹。"""
        personas = list(dict.fromkeys((self.impersonate, "chrome136", "safari_ios")))
        last_response: Any = None
        for persona in personas:
            try:
                response = requests.get(
                    url,
                    headers=HEADERS,
                    timeout=self.timeout,
                    impersonate=persona,
                )
                last_response = response
                if response.status_code not in {403, 429}:
                    return response
            except Exception as exc:  # noqa: BLE001
                logger.debug("请求 %s (指纹 %s) 失败: %s", url, persona, exc)
                continue
        return last_response

    def fetch_quarter_pdf_and_parse(
        self,
        year: int,
        quarter: int,
        fallback_pkg_pct: float | None = None,
    ) -> dict[str, Any] | None:
        """在线抓取指定年份季度的台积电官方管理报告 PDF 并解析。"""
        report_quarter = f"{year}Q{quarter}"
        page_url = TSMC_QUARTERLY_RESULTS_URL.format(year=year, quarter=quarter)

        try:
            page_resp = self._get_tsmc(page_url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("请求 TSMC %s 结果页面异常: %s", report_quarter, exc)
            return None

        if page_resp is None or page_resp.status_code != 200:
            return None

        page_bytes = response_content_bytes(page_resp)
        if not page_bytes:
            return None

        report_links = extract_tsmc_quarterly_report_links(page_bytes, base_url=page_url)
        if not report_links:
            logger.debug("TSMC %s 页面未找到 Management Report PDF 链接", report_quarter)
            return None

        report_url = report_links[0]
        try:
            pdf_resp = self._get_tsmc(report_url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("下载 TSMC %s 管理报告 PDF 异常: %s", report_quarter, exc)
            return None

        if pdf_resp is None or pdf_resp.status_code != 200:
            return None

        pdf_bytes = response_content_bytes(pdf_resp)
        if not pdf_bytes:
            return None

        # 存证保存
        self.filings_dir.mkdir(parents=True, exist_ok=True)
        pdf_filename = f"tsmc_{report_quarter}_management_report.pdf"
        target_file = self.filings_dir / pdf_filename
        target_file.write_bytes(pdf_bytes)

        sha256_hash = raw_content_sha256(pdf_bytes)
        relative_snapshot_path = f"data/raw/industry/semiconductor/tsmc_filings/{pdf_filename}"

        # 结构化解析
        parsed = parse_tsmc_management_report_pdf(pdf_bytes, default_quarter=report_quarter)
        if parsed is None:
            logger.warning("解析 TSMC %s 管理报告 PDF 失败", report_quarter)
            return None

        now_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        parsed["packaging_testing_others_pct"] = fallback_pkg_pct
        parsed["data_status"] = "actual"
        parsed["source"] = "TSMC_OFFICIAL_MANAGEMENT_REPORT"
        parsed["source_url"] = TSMC_IR_URL
        parsed["collected_at"] = now_utc
        parsed["raw_content_sha256"] = sha256_hash
        parsed["raw_snapshot_path"] = relative_snapshot_path

        logger.info(
            "成功抓取并解析 TSMC %s: NT$%.2fB, US$%.2fB, 7nm及以下=%.2f%%",
            report_quarter,
            parsed.get("net_revenue_ntd_bn", 0.0),
            parsed.get("net_revenue_usd_bn", 0.0) or 0.0,
            (parsed.get("advanced_wafer_pct", 0.0) or 0.0) * 100,
        )
        return parsed

    def sync_incremental(
        self,
        current_max_quarter: str | None = None,
        fallback_pkg_pct: float | None = 0.1000,
    ) -> list[dict[str, Any]]:
        """在线探测新季度公报并执行增量追加。

        Args:
            current_max_quarter: 本地已有最新报告季度，如 '2026Q2'。若为空则不限制。
            fallback_pkg_pct: 当管理报告中未显式披露封测比例时沿用的基准值。

        Returns:
            新抓取并写入 RAW CSV 的记录字典列表。
        """
        if not current_max_quarter:
            logger.info("未提供已有最新季度，跳过在线增量嗅探")
            return []

        candidates = _next_candidate_quarters(current_max_quarter, count=4)
        if not candidates:
            return []

        newly_collected: list[dict[str, Any]] = []
        for candidate_q in candidates:
            yr = int(candidate_q[:4])
            q_num = int(candidate_q[-1])
            record = self.fetch_quarter_pdf_and_parse(
                year=yr,
                quarter=q_num,
                fallback_pkg_pct=fallback_pkg_pct,
            )
            if record is not None:
                newly_collected.append(record)
            else:
                # 季度报告按序发布，一旦候选季度不存在则终止后续探测
                break

        if newly_collected:
            append_tsmc_adv_pkg_revenue_raw_record(self.csv_path, newly_collected)
            logger.info("TSMC 官方财务拆解已增量同步 %d 个新季度", len(newly_collected))
        else:
            logger.info("TSMC 官方财务拆解已是最新状态 (%s)，未探测到新报告", current_max_quarter)

        return newly_collected
