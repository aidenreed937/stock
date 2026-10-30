"""全品种化工高频周度产业调查快讯采集器 (ChemicalWeeklySurveyCollector)。

数据属性与多源 2-Tier ETL 架构:
1. 覆盖 4 大核心链主大宗化工品种:
   - 纯碱 (SA): 36 家样本综合产能利用率、实物产量、厂家总库存、出货率;
   - 烧碱 (SH): 113 家样本企业 (4429 万吨有效产能) 平均产能利用率、厂家库存、氧化铝开工率;
   - PTA (TA): 27 家样本企业 (9330 万吨有效产能) 周度产能利用率、周产量、聚酯开工率、社会库存;
   - 甲醇 (MA): 183 家样本企业周度产能利用率、周产量、下游 MTO 烯烃开工率;
2. 真实来源:
   - 生意社 (100ppi): 官方商品情报站与每周四快报;
   - 隆众资讯 (Longzhong / Mysteel 能化): 官方一手统计周报;
3. 2-Tier 存储: 物理 RAW CSV 保存在 data/raw/industry/chemicals/operating_rates/weekly_survey.csv;
4. 消除前视偏差: release_date 为文章官方发布日 (工作日每周四/周五生效);
5. 双周提取机制: 充分利用周报中同时披露的【当周真实值】与【上周真实值】。
"""

from __future__ import annotations

import csv
import logging
import re
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl
from curl_cffi import requests

from stock_data.fetcher.industry.chemicals.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
)
from stock_data.fetcher.industry.chemicals.parsers.weekly_survey import (
    collect_100ppi_weekly_records,
    has_weekly_metrics,
    load_weekly_survey_raw_csv,
    parse_commodity_weekly_metrics,
    parse_page_release_date,
    save_weekly_survey_raw_csv,
)
from stock_data.fetcher.industry.chemicals.schemas import (
    WEEKLY_SURVEY_COLLECTION_SCHEMA,
    WEEKLY_SURVEY_RAW_SCHEMA,
    WEEKLY_SURVEY_SCHEMA,
)
from stock_data.fetcher.industry.chemicals.transforms.weekly_survey import (
    build_weekly_survey_curated_frame,
    build_weekly_survey_raw_frame,
)
from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.contracts import IndustryFrameResult

logger = logging.getLogger(__name__)


class ChemicalWeeklySurveyCollector:
    """全品种周度化工高频产业调查快讯采集器 (支持 纯碱/烧碱/PTA/甲醇 多源并行)。"""

    def __init__(self, raw_dir: Path | str, enable_online: bool = False) -> None:
        self.raw_dir = Path(raw_dir)
        self.survey_dir = self.raw_dir / "chemicals" / "operating_rates"
        self.source_manifest = self.survey_dir / "mysteel_weekly_sources.csv"
        self.survey_dir.mkdir(parents=True, exist_ok=True)
        self.enable_online = enable_online
        self.session: Any = requests.Session(impersonate="chrome120")
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        self.collection_errors: list[str] = []
        self.missing_periods: set[str] = set()
        self.fetched_periods: set[str] = set()
        self.cached_periods: set[str] = set()

    def _request(self, url: str) -> Any | None:
        """以有限重试请求网页，避免把一次 WAF/网络抖动误判为永久缺数。"""
        if not self.enable_online:
            logger.debug("ChemicalWeeklySurveyCollector 处于离线安全模式，跳过请求: %s", url)
            return None
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self.session.get(url, headers=self.headers, timeout=10)
                if response.status_code == 403:
                    logger.debug("周报源请求被拦截 (403 Forbidden) [%s]", url)
                    return None
                if response.status_code != 200:
                    raise RuntimeError(f"HTTP {response.status_code}")
                response.encoding = "utf-8"
                if not str(response.text).strip():
                    raise RuntimeError("空响应")
                return response
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.25 * (2**attempt))
        logger.debug("请求失败 [%s]: %s", url, last_error)
        return None

    def _fetch_html_with_cookie_bypass(self, url: str) -> str:
        response = self._request(url)
        if response is None:
            return ""
        first_text = str(response.text)
        match = re.search(r'var _0x2 = "([a-f0-9]+)";', first_text)
        if match:
            token = match.group(1)
            self.session.cookies.set("HW_CHECK", token, domain="100ppi.com")
            response = self._request(url)
            if response is None:
                return ""
        return str(response.text)

    def _load_raw_csv(self) -> dict[tuple[str, str, str], dict[str, Any]]:
        return load_weekly_survey_raw_csv(self.survey_dir)

    def _save_raw_csv(self, records: dict[tuple[str, str, str], dict[str, Any]]) -> None:
        save_weekly_survey_raw_csv(self.survey_dir, records)

    def _save_html_snapshot(self, name: str, html_text: str) -> tuple[str, str]:
        """保存网页原文并返回相对 RAW 路径与内容哈希。"""
        snapshot_dir = self.survey_dir / "snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        content_hash = raw_content_sha256(html_text.encode("utf-8"))
        snapshot_path = snapshot_dir / f"{name}_{content_hash[:16]}.html"
        if not snapshot_path.exists():
            snapshot_path.write_text(html_text, encoding="utf-8")
        return (
            content_hash,
            raw_snapshot_path_value(snapshot_path, self.raw_dir),
        )

    def _load_mysteel_sources(self) -> list[tuple[str, str, str, str]]:
        """从 RAW manifest 读取待抓取的 Mysteel 周报 URL。"""
        manifest_paths = (
            self.source_manifest,
            Path("config/data_sources/chemicals_weekly_sources.csv"),
        )
        for manifest_path in manifest_paths:
            if not manifest_path.exists():
                continue
            with manifest_path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                return [
                    (
                        str(row["product_name"]),
                        str(row["symbol"]),
                        str(row["report_date"]),
                        str(row["source_url"]),
                    )
                    for row in reader
                    if row.get("product_name")
                    and row.get("symbol")
                    and row.get("report_date")
                    and row.get("source_url")
                ]
        return []

    def collect(
        self,
        current_year: int | None = None,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pl.DataFrame:
        """执行全品种周度快讯解析与 2-Tier Upsert。"""
        return _collect_weekly_survey(
            self,
            current_year=current_year,
            force=force,
            start_date=start_date,
            end_date=end_date,
        )

    def collect_result(
        self,
        current_year: int | None = None,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> IndustryFrameResult:
        """采集周报并返回可供调度器判断的覆盖、缓存和错误状态。"""
        frame = self.collect(
            current_year=current_year,
            force=force,
            start_date=start_date,
            end_date=end_date,
        )
        missing = tuple(sorted(self.missing_periods))
        errors = tuple(self.collection_errors)
        if frame.is_empty() and missing:
            status = "MISSING_RANGE"
        elif errors and frame.is_empty():
            status = "FAILED"
        elif errors or missing:
            status = "PARTIAL"
        elif frame.is_empty():
            status = "EMPTY"
        else:
            status = "SUCCESS"
        return IndustryFrameResult(
            frame=frame,
            status=status,
            fetched_periods=tuple(sorted(self.fetched_periods)),
            cached_periods=tuple(sorted(self.cached_periods)),
            missing_periods=missing,
            errors=errors,
            updated=bool(self.fetched_periods),
        )

    def load_from_raw(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pl.DataFrame:
        """离线读取周报 RAW，不触发上游请求。"""
        records = self._load_raw_csv()
        if not records:
            return pl.DataFrame(schema=WEEKLY_SURVEY_SCHEMA)
        df = (
            pl.DataFrame(list(records.values()), schema=WEEKLY_SURVEY_COLLECTION_SCHEMA)
            .sort(["product_name", "report_date", "source"])
            .select(list(WEEKLY_SURVEY_SCHEMA))
        )
        if start_date is not None:
            df = df.filter(pl.col("report_date") >= pl.lit(start_date))
        if end_date is not None:
            df = df.filter(pl.col("report_date") <= pl.lit(end_date))
        return df


def _collect_weekly_survey(
    collector: ChemicalWeeklySurveyCollector,
    *,
    current_year: int | None,
    force: bool,
    start_date: date | None,
    end_date: date | None,
) -> pl.DataFrame:
    """执行周报两路采集，保持 Collector 只负责资源生命周期。"""
    collector.collection_errors = []
    collector.missing_periods = set()
    collector.fetched_periods = set()
    collector.cached_periods = set()
    current_year = current_year or (end_date or date.today()).year
    records = collector._load_raw_csv()
    now_iso = now_utc_iso()

    if not collector.enable_online:
        for row in records.values():
            r_date = row.get("report_date")
            if (
                r_date is not None
                and (start_date is None or r_date >= start_date)
                and (end_date is None or r_date <= end_date)
                and has_weekly_metrics(row)
            ):
                src = str(row.get("source") or "WeeklySurvey")
                sym = str(row.get("symbol") or "")
                collector.cached_periods.add(f"{src}:{sym}:{r_date.isoformat()}")
    else:
        soda_qb_url = "https://www.100ppi.com/qb/?pid=533"
        reference_date = end_date or date.today()
        recent_cutoff = reference_date - timedelta(days=7)
        has_recent_100ppi = any(
            row.get("source") == "100ppi_Weekly"
            and row.get("report_date") is not None
            and row["report_date"] >= recent_cutoff
            and (start_date is None or row["report_date"] >= start_date)
            and row["report_date"] <= reference_date
            and has_weekly_metrics(row)
            for row in records.values()
        )
        html_100ppi = ""
        if force or not has_recent_100ppi:
            html_100ppi = collector._fetch_html_with_cookie_bypass(soda_qb_url)
            if not html_100ppi:
                collector.collection_errors.append("100ppi 周报请求失败或返回空页面")
        if html_100ppi:
            try:
                content_hash, snapshot_path = collector._save_html_snapshot(
                    f"100ppi_weekly_{current_year}", html_100ppi
                )
            except OSError as exc:
                logger.warning("保存生意社周报 RAW 快照失败: %s", exc)
                content_hash, snapshot_path = "", ""
            collect_100ppi_weekly_records(
                records,
                fetch_html=lambda _url: html_100ppi,
                current_year=current_year,
                now_iso=now_iso,
                start_date=start_date,
                end_date=end_date,
                raw_content_sha256_value=content_hash,
                raw_snapshot_path=snapshot_path,
            )
            collector.fetched_periods.update(
                f"100ppi_Weekly:{row['report_date'].isoformat()}"
                for row in records.values()
                if row.get("source") == "100ppi_Weekly"
                and row.get("report_date") is not None
                and row["report_date"] >= (start_date or date.min)
                and row["report_date"] <= (end_date or date.max)
            )
        elif has_recent_100ppi:
            collector.cached_periods.add("100ppi_Weekly")

        for prod_name, sym, d_str, url_lz in collector._load_mysteel_sources():
            report_date = date.fromisoformat(d_str)
            if start_date is not None and report_date < start_date:
                continue
            if end_date is not None and report_date > end_date:
                continue
            key = (prod_name, d_str, "Longzhong_Oilchem")
            if not force and key in records and has_weekly_metrics(records[key]):
                collector.cached_periods.add(f"Longzhong_Oilchem:{sym}:{d_str}")
                continue
            try:
                response = collector._request(url_lz)
                if response is None:
                    collector.missing_periods.add(f"{sym}:{d_str}")
                    collector.collection_errors.append(f"{sym}:{d_str}: 隆众周报请求失败")
                    continue
                html_text = response.text
                try:
                    content_hash, snapshot_path = collector._save_html_snapshot(
                        f"mysteel_{sym}_{d_str}", html_text
                    )
                except OSError as exc:
                    logger.warning("保存隆众周报 RAW 快照失败 [%s]: %s", url_lz, exc)
                    content_hash, snapshot_path = "", ""

                metrics = parse_commodity_weekly_metrics(html_text, prod_name, sym)
                report_day = date.fromisoformat(d_str)
                record = records.get(
                    key,
                    {
                        "trade_date": report_day,
                        "report_date": report_day,
                        "product_name": prod_name,
                        "symbol": sym,
                        "operating_rate_pct": None,
                        "weekly_output_w_tons": None,
                        "factory_inventory_w_tons": None,
                        "shipment_rate_pct": None,
                        "source": "Longzhong_Oilchem",
                        "source_url": url_lz,
                        "release_date": None,
                        "data_status": "actual",
                        "collected_at": now_iso,
                        "raw_content_sha256": content_hash,
                        "raw_snapshot_path": snapshot_path,
                    },
                )
                record["raw_content_sha256"] = content_hash
                record["raw_snapshot_path"] = snapshot_path
                record["release_date"] = parse_page_release_date(html_text)
                if "data_status" not in record:
                    record["data_status"] = "actual"
                if metrics.get("operating_rate_pct") is not None:
                    record["operating_rate_pct"] = metrics["operating_rate_pct"]
                if metrics.get("weekly_output_w_tons") is not None:
                    record["weekly_output_w_tons"] = metrics["weekly_output_w_tons"]
                if metrics.get("factory_inventory_w_tons") is not None:
                    record["factory_inventory_w_tons"] = metrics["factory_inventory_w_tons"]
                if metrics.get("shipment_rate_pct") is not None:
                    record["shipment_rate_pct"] = metrics["shipment_rate_pct"]
                if has_weekly_metrics(record):
                    records[key] = record
                    collector.fetched_periods.add(f"Longzhong_Oilchem:{sym}:{d_str}")
                else:
                    records.pop(key, None)
                    collector.missing_periods.add(f"{sym}:{d_str}")
                    collector.collection_errors.append(f"{sym}:{d_str}: 周报未解析出有效指标")

                previous_util = re.search(r"上周\s*([4-9]\d(?:\.\d+)?)%", html_text)
                if previous_util:
                    previous_day = report_day - timedelta(days=7)
                    previous_key = (prod_name, previous_day.isoformat(), "Longzhong_Oilchem")
                    previous = records.get(
                        previous_key,
                        {
                            "trade_date": previous_day,
                            "report_date": previous_day,
                            "product_name": prod_name,
                            "symbol": sym,
                            "operating_rate_pct": float(previous_util.group(1)),
                            "weekly_output_w_tons": None,
                            "factory_inventory_w_tons": None,
                            "shipment_rate_pct": None,
                            "source": "Longzhong_Oilchem",
                            "source_url": url_lz,
                            "release_date": None,
                            "data_status": "actual",
                            "collected_at": now_iso,
                            "raw_content_sha256": content_hash,
                            "raw_snapshot_path": snapshot_path,
                        },
                    )
                    previous["operating_rate_pct"] = float(previous_util.group(1))
                    previous["raw_content_sha256"] = content_hash
                    previous["raw_snapshot_path"] = snapshot_path
                    previous["release_date"] = parse_page_release_date(html_text)
                    if "data_status" not in previous:
                        previous["data_status"] = "actual"
                    records[previous_key] = previous
            except Exception as exc:
                logger.warning("隆众周报解析失败 [%s]: %s", url_lz, exc)
                collector.missing_periods.add(f"{sym}:{d_str}")
                collector.collection_errors.append(f"{sym}:{d_str}: {exc}")

    if records:
        collector._save_raw_csv(records)
    if not records:
        return pl.DataFrame(schema=WEEKLY_SURVEY_SCHEMA)

    frame = pl.DataFrame(list(records.values()), schema=WEEKLY_SURVEY_COLLECTION_SCHEMA).sort(
        ["product_name", "report_date", "source"]
    )
    if start_date is not None:
        frame = frame.filter(pl.col("report_date") >= pl.lit(start_date))
    if end_date is not None:
        frame = frame.filter(pl.col("report_date") <= pl.lit(end_date))
    return frame


__all__ = [
    "WEEKLY_SURVEY_RAW_SCHEMA",
    "WEEKLY_SURVEY_SCHEMA",
    "ChemicalWeeklySurveyCollector",
    "build_weekly_survey_curated_frame",
    "build_weekly_survey_raw_frame",
]
