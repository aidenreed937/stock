"""台积电月度营运营收先导指标采集器 (TsmcLeadCollector)。

数据源: https://investor.tsmc.com/english/monthly-revenue/{year}
TSMC 每月 10 日前后披露上月合并营收，比 SIA 全球销售额提前约 25 天，是全球晶圆代工与
AI 算力最高频、最前瞻的景气指标。采集时逐年拉取英文投资者年度页面，得到全年 12 个月
营收与 YoY；原始 HTML 以 Gzip 归档仅作对账校验，不以快照作为解析来源 (2-Tier ETL)。
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from curl_cffi import requests

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
    save_raw_snapshot,
)
from stock_data.fetcher.industry.semiconductor.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
    response_content_bytes,
)
from stock_data.fetcher.industry.semiconductor.models import SemiconductorLeadRecord
from stock_data.fetcher.industry.semiconductor.parsers import parse_tsmc_monthly_revenue_html
from stock_data.fetcher.industry.semiconductor.paths import SemiconductorRawPaths

logger = logging.getLogger(__name__)

TSMC_MONTHLY_REVENUE_URL = "https://investor.tsmc.com/english/monthly-revenue/{year}"
TSMC_SOURCE_NAME = "tsmc"
START_YEAR = 2014


def _next_month_release_date(report_month: str) -> date:
    """台积电在每月 10 日前后披露上月营收，故 release_date 采用下月 10 日。"""
    year, month = parse_month_string(report_month)
    next_year = year + 1 if month == 12 else year
    next_month = 1 if month == 12 else month + 1
    return date(next_year, next_month, 10)


class TsmcLeadCollector:
    """台积电月度营运营收景气采集适配器。

    逐年拉取英文投资者年度页面 (START_YEAR ~ 当前年)，解析官方月度营收与 YoY，
    并将原始 HTML Gzip 归档供对账校验。USD、MoM 和 3MMA 在 Curated 转换阶段计算。
    """

    def __init__(
        self,
        raw_dir: Path | str,
        timeout: int = 20,
        impersonate: str = "chrome120",
    ) -> None:
        self.paths = SemiconductorRawPaths(raw_dir)
        self.raw_root = self.paths.raw_root
        self.timeout = timeout
        self.impersonate = impersonate

    def collect(self) -> list[SemiconductorLeadRecord]:
        """在线采集台积电英文年度月度营收原始记录。"""
        self.paths.semiconductor_dir.mkdir(parents=True, exist_ok=True)

        current_year = date.today().year
        records: list[SemiconductorLeadRecord] = []
        for year in range(START_YEAR, current_year + 1):
            records.extend(self._collect_year(year))

        if not records:
            logger.info("未抓取到任何台积电月度营收数据")
            return []

        logger.info("TSMC 英文投资者月度营收采集完成: 共 %d 个月度记录", len(records))
        return sorted(records, key=lambda r: r.report_month)

    def _collect_year(self, year: int) -> list[SemiconductorLeadRecord]:
        url = TSMC_MONTHLY_REVENUE_URL.format(year=year)
        try:
            resp = requests.get(url, impersonate=self.impersonate, timeout=self.timeout)
            if resp.status_code != 200:
                logger.warning("抓取 TSMC %d 年度营收页返回 HTTP %d", year, resp.status_code)
                return []
        except Exception as exc:  # noqa: BLE001
            logger.warning("抓取 TSMC %d 年度营收页异常: %s", year, exc)
            return []

        content_bytes = response_content_bytes(resp)

        # 原始 HTML Gzip 归档，仅作对账校验
        snapshot_path = save_raw_snapshot(
            TSMC_SOURCE_NAME,
            f"tsmc_monthly_revenue_{year}.html.gz",
            content_bytes,
            base_dir=self.raw_root,
            compress=True,
        )
        content_hash = raw_content_sha256(content_bytes)
        snapshot_ref = raw_snapshot_path_value(snapshot_path, self.raw_root)
        html_text = getattr(resp, "text", "") or content_bytes.decode("utf-8", errors="ignore")

        rows = parse_tsmc_monthly_revenue_html(html_text, year=year)
        collected_at = now_utc_iso()
        year_records: list[SemiconductorLeadRecord] = []
        for row in rows:
            report_month = str(row["report_month"])
            yr, mo = parse_month_string(report_month)
            ntd = float(row["tsmc_revenue_ntd_million"])
            yoy = row["tsmc_revenue_yoy"]
            year_records.append(
                SemiconductorLeadRecord(
                    report_month=report_month,
                    trade_date=get_month_end_date(yr, mo),
                    tsmc_revenue_ntd_million=ntd,
                    tsmc_revenue_yoy=float(yoy) if yoy is not None else None,
                    unit="million_ntd/usd",
                    source="TSMC",
                    source_url=url,
                    release_date=_next_month_release_date(report_month),
                    data_status="actual",
                    collected_at=collected_at,
                    raw_content_sha256=content_hash,
                    raw_snapshot_path=snapshot_ref,
                    tsmc_month_raw=str(row.get("month_raw") or ""),
                    tsmc_revenue_raw=str(row.get("net_revenue_raw") or ""),
                    tsmc_revenue_yoy_raw=str(row.get("yoy_change_raw") or ""),
                )
            )

        logger.info("成功抓取 TSMC %d 年度月度营收: 共 %d 个月", year, len(year_records))
        return year_records
