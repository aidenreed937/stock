"""SIA / WSTS 全球半导体月度销售额协同采集器 (SemiconductorCollector)。

双源协同架构:
1. 主源 (WSTS Historical Billings): 负责 1986 ~ 至今 40 年连续无缺口的全球及四大区域 3MMA 销售额底表;
2. 补充源 (SIA Monthly News): 负责补充 China 销售额、官方新闻发布日期 (release_date) 及最新月份校验。
"""

import logging
import time
from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

from curl_cffi import requests

from stock_data.fetcher.industry.common import (
    now_utc_iso,
    save_raw_snapshot,
)
from stock_data.fetcher.industry.semiconductor.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
    response_content_bytes,
)
from stock_data.fetcher.industry.semiconductor.models import SemiconductorSalesRecord
from stock_data.fetcher.industry.semiconductor.parsers import (
    extract_sia_sales_article_links,
    load_sia_news_enrichments,
    parse_sia_china_and_date,
    parse_wsts_excel_file,
)
from stock_data.fetcher.industry.semiconductor.paths import SemiconductorRawPaths

logger = logging.getLogger(__name__)

WSTS_EXCEL_URL = "https://www.wsts.org/esraCMS/extension/media/f/WST/7735/WSTS-Historical-Billings-Report-Jun_2026.xlsx"


class SemiconductorCollector:
    """WSTS / SIA 全球及中国半导体月度销售额双源协同采集适配器。"""

    def __init__(
        self,
        timeout: int = 20,
        impersonate: str = "chrome120",
        *,
        raw_dir: Path | str,
    ) -> None:
        self.timeout = timeout
        self.impersonate = impersonate
        self.paths = SemiconductorRawPaths(raw_dir)
        self.sia_raw_dir = self.paths.sia_dir

    def collect(self, force: bool = False) -> list[SemiconductorSalesRecord]:
        """执行 WSTS 历史底表与 SIA 最新月报的双源协同采集。"""
        sia_enrichments = self._fetch_sia_news_enrichments()
        release_dates = {
            month: value["release_date"]
            for month, value in sia_enrichments.items()
            if isinstance(value.get("release_date"), date)
        }
        wsts_records = self._fetch_and_parse_wsts_history(
            release_dates=release_dates,
            force=force,
        )

        final_records: list[SemiconductorSalesRecord] = []
        for r in wsts_records:
            release_date = r.release_date or release_dates.get(r.report_month)
            enrich = sia_enrichments.get(r.report_month)
            if enrich:
                china_sales = enrich.get("china_sales_usd")
                c_yoy = enrich.get("china_yoy_growth")
                c_mom = enrich.get("china_mom_growth")
                rel_d = enrich.get("release_date")
                rec = SemiconductorSalesRecord(
                    report_month=r.report_month,
                    trade_date=r.trade_date,
                    global_sales_usd=r.global_sales_usd,
                    china_sales_usd=float(china_sales) if china_sales is not None else None,
                    china_yoy_growth=float(c_yoy) if c_yoy is not None else None,
                    china_mom_growth=float(c_mom) if c_mom is not None else None,
                    americas_sales_usd=r.americas_sales_usd,
                    europe_sales_usd=r.europe_sales_usd,
                    japan_sales_usd=r.japan_sales_usd,
                    asia_pacific_sales_usd=r.asia_pacific_sales_usd,
                    yoy_growth=None,
                    mom_growth=None,
                    unit="billion_usd",
                    source="WSTS/SIA",
                    # WSTS 是全球主表，保留其 URL 与快照血缘；SIA 原文另存于 sia/ 目录。
                    source_url=r.source_url,
                    release_date=rel_d if isinstance(rel_d, date) else release_date,
                    data_status="actual",
                    collected_at=now_utc_iso(),
                    raw_content_sha256=r.raw_content_sha256,
                    raw_snapshot_path=r.raw_snapshot_path,
                    worldwide_raw=r.worldwide_raw,
                    americas_raw=r.americas_raw,
                    europe_raw=r.europe_raw,
                    japan_raw=r.japan_raw,
                    asia_pacific_raw=r.asia_pacific_raw,
                    china_sales_raw=(
                        str(enrich["china_sales_raw"])
                        if enrich.get("china_sales_raw") is not None
                        else None
                    ),
                    china_yoy_growth_raw=(
                        str(enrich["china_yoy_growth_raw"])
                        if enrich.get("china_yoy_growth_raw") is not None
                        else None
                    ),
                    china_mom_growth_raw=(
                        str(enrich["china_mom_growth_raw"])
                        if enrich.get("china_mom_growth_raw") is not None
                        else None
                    ),
                )
            else:
                rec = replace(r, release_date=release_date, yoy_growth=None, mom_growth=None)
            final_records.append(rec)

        final_records.sort(key=lambda x: x.trade_date)
        logger.info("WSTS/SIA 半导体协同采集完成: 共 %d 个月度连续数据", len(final_records))
        return final_records

    def _fetch_and_parse_wsts_history(
        self,
        *,
        release_dates: Mapping[str, date] | None = None,
        force: bool = False,
    ) -> list[SemiconductorSalesRecord]:
        """下载并解析 WSTS 官方 Historical Billings Report。"""
        excel_path = self.sia_raw_dir / "WSTS-Historical-Billings-Report-Jun_2026.xlsx"
        if force or not excel_path.exists():
            try:
                resp = requests.get(
                    WSTS_EXCEL_URL, impersonate=self.impersonate, timeout=self.timeout
                )
                if resp.status_code == 200 and response_content_bytes(resp):
                    content_bytes = response_content_bytes(resp)
                    self.sia_raw_dir.mkdir(parents=True, exist_ok=True)
                    save_raw_snapshot(
                        "sia",
                        excel_path.name,
                        content_bytes,
                        base_dir=self.paths.raw_root,
                    )
            except Exception as exc:
                logger.warning("下载 WSTS 官方 Excel 失败: %s", exc)

        if not excel_path.exists():
            logger.error("未找到 WSTS 官方历史 Excel 文件: %s", excel_path)
            return []

        content_bytes = excel_path.read_bytes()
        content_hash = raw_content_sha256(content_bytes)
        snapshot_ref = raw_snapshot_path_value(excel_path, self.paths.raw_root)
        return [
            replace(r, raw_content_sha256=content_hash, raw_snapshot_path=snapshot_ref)
            for r in parse_wsts_excel_file(excel_path, release_dates=release_dates)
        ]

    def _fetch_sia_news_enrichments(self) -> dict[str, dict[str, Any]]:
        """在线抓取 SIA 官网最新月度新闻，解析 China 销售数据与 release_date。"""
        enrichments = load_sia_news_enrichments(self.sia_raw_dir)

        # 在线获取最新发布的月报公报
        list_url = "https://www.semiconductors.org/news-events/latest-news/"
        try:
            resp = requests.get(list_url, impersonate=self.impersonate, timeout=self.timeout)
            if resp.status_code == 200:
                list_bytes = response_content_bytes(resp)
                list_text = getattr(resp, "text", "") or list_bytes.decode("utf-8", errors="ignore")
                save_raw_snapshot(
                    "sia",
                    "latest_news_list.html",
                    list_bytes,
                    base_dir=self.paths.raw_root,
                    compress=True,
                )
                for link in extract_sia_sales_article_links(list_text)[:10]:
                    try:
                        r_art = requests.get(
                            link, impersonate=self.impersonate, timeout=self.timeout
                        )
                        if r_art.status_code == 200:
                            slug = link.rstrip("/").split("/")[-1]
                            article_bytes = response_content_bytes(r_art)
                            article_text = getattr(r_art, "text", "") or article_bytes.decode(
                                "utf-8", errors="ignore"
                            )
                            snapshot_path = save_raw_snapshot(
                                "sia",
                                f"{slug}.html",
                                article_bytes,
                                base_dir=self.paths.raw_root,
                                compress=True,
                            )
                            parsed = parse_sia_china_and_date(article_text, link)
                            if parsed and parsed.get("report_month"):
                                parsed["raw_content_sha256"] = raw_content_sha256(article_bytes)
                                parsed["raw_snapshot_path"] = raw_snapshot_path_value(
                                    snapshot_path, self.paths.raw_root
                                )
                                enrichments[str(parsed["report_month"])] = parsed
                        time.sleep(0.1)
                    except Exception as e:
                        logger.debug("SIA 文章补充解析失败 [%s]: %s", link, e)
        except Exception as exc:
            logger.debug("抓取 SIA 新闻列表异常: %s", exc)

        return enrichments
