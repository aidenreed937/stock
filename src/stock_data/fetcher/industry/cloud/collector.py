"""北美四大云厂商季度 AI 资本开支 (10-Q) 官方 SEC EDGAR 采集器 (CloudCapexCollector)。"""

from __future__ import annotations

import csv
import gzip
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any, cast

import requests

from stock_data.fetcher.industry.cloud.parser import extract_sec_quarterly_capex
from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
)
from stock_data.fetcher.industry.models import CloudCapexRecord

logger = logging.getLogger(__name__)

# SEC EDGAR 官方 CIK 字典
CSP_CIK_MAP: dict[str, str] = {
    "MSFT": "0000789019",
    "GOOGL": "0001652044",
    "META": "0001326801",
    "AMZN": "0001018724",
}

SEC_HEADERS = {
    "User-Agent": "AntigravityResearch/1.0 (contact@research.antigravity.org)",
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov",
}


class CloudCapexCollector:
    """北美四大云厂商 (MSFT/GOOGL/META/AMZN) 季度 10-Q CapEx 官方采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.sec_raw_dir = self.raw_dir / "cloud" / "sec_edgar"

    def collect(self) -> list[CloudCapexRecord]:
        """执行数据采集: 扫描/拉取 SEC EDGAR 官方 10-Q -> 差分计算单季发生额 -> 汇总构建事实。"""
        # 兼容测试用例的旧 CSV 快照
        legacy_csv = self.raw_dir / "cloud_capex" / "csp_capex_quarterly.csv"
        if legacy_csv.exists():
            legacy_records = self._load_from_legacy_csv(legacy_csv)
            if legacy_records:
                return legacy_records

        self.sec_raw_dir.mkdir(parents=True, exist_ok=True)
        company_data: dict[str, dict[str, float]] = {}

        for ticker, cik in CSP_CIK_MAP.items():
            quarterly_capex = self._fetch_or_load_company(ticker, cik)
            company_data[ticker] = quarterly_capex

        if not company_data:
            return []

        all_quarters = sorted(
            list(
                {
                    q
                    for data in company_data.values()
                    for q, v in data.items()
                    if v > 0 and q >= "2018-Q1"
                }
            )
        )
        if not all_quarters:
            return []

        records: list[CloudCapexRecord] = []
        now_iso = now_utc_iso()

        for q_str in all_quarters:
            year, q_num = int(q_str.split("-Q")[0]), int(q_str.split("-Q")[1])
            month = q_num * 3
            t_date = get_month_end_date(year, month)

            msft = company_data.get("MSFT", {}).get(q_str, 0.0)
            goog = company_data.get("GOOGL", {}).get(q_str, 0.0)
            meta = company_data.get("META", {}).get(q_str, 0.0)
            amzn = company_data.get("AMZN", {}).get(q_str, 0.0)
            tot = msft + goog + meta + amzn

            # 财报通常在季度结束后 1 个月内发布
            rel_year = year if month < 12 else year + 1
            rel_month = month + 1 if month < 12 else 1
            rel_date = date(rel_year, rel_month, 28)

            records.append(
                CloudCapexRecord(
                    report_quarter=q_str,
                    trade_date=t_date,
                    total_capex_billion_usd=round(tot, 3),
                    msft_capex_billion_usd=round(msft, 3) if msft > 0 else None,
                    goog_capex_billion_usd=round(goog, 3) if goog > 0 else None,
                    meta_capex_billion_usd=round(meta, 3) if meta > 0 else None,
                    amzn_capex_billion_usd=round(amzn, 3) if amzn > 0 else None,
                    yoy_growth=None,  # 由 transform 层计算
                    qoq_growth=None,
                    unit="billion_usd",
                    source="SEC_EDGAR_10Q",
                    source_url="https://www.sec.gov/edgar/",
                    release_date=rel_date,
                    data_status="actual",
                    collected_at=now_iso,
                )
            )

        records.sort(key=lambda r: r.trade_date)
        return records

    def _fetch_or_load_company(self, ticker: str, cik: str) -> dict[str, float]:
        """加载或从 SEC EDGAR 在线抓取单家公司的 CapEx 事实。"""
        raw_file = self.sec_raw_dir / f"{ticker}.json.gz"
        facts: dict[str, Any] = {}

        if raw_file.exists():
            try:
                with gzip.open(raw_file, "rt", encoding="utf-8") as f:
                    facts = json.load(f)
            except Exception as e:
                logger.warning("读取本地 SEC 快照失败 [%s]: %s", raw_file, e)

        if not facts:
            url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
            logger.info("正在从 SEC EDGAR 获取 %s (CIK %s) 真实 10-Q 财报...", ticker, cik)
            try:
                r = requests.get(url, headers=SEC_HEADERS, timeout=15)
                if r.status_code == 200:
                    facts = cast("dict[str, Any]", r.json())
                    with gzip.open(raw_file, "wt", encoding="utf-8") as f:
                        json.dump(facts, f, ensure_ascii=False)
                else:
                    logger.warning("SEC EDGAR 请求失败 [%s]: HTTP %d", ticker, r.status_code)
                    return {}
            except Exception as e:
                logger.error("SEC EDGAR 在线拉取异常 [%s]: %s", ticker, e)
                return {}

        return extract_sec_quarterly_capex(facts, ticker)

    def _load_from_legacy_csv(self, file_path: Path) -> list[CloudCapexRecord]:
        """从旧 CSV 快照中读取云厂商 CapEx 记录。"""

        def _safe_float(val: str | None) -> float | None:
            if not val or not val.strip():
                return None
            try:
                return float(val.strip())
            except (ValueError, TypeError):
                return None

        records: list[CloudCapexRecord] = []
        with file_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                q_str = row["report_quarter"].strip()
                t_date = date.fromisoformat(row["trade_date"].strip())
                records.append(
                    CloudCapexRecord(
                        report_quarter=q_str,
                        trade_date=t_date,
                        total_capex_billion_usd=float(row["total_capex_billion_usd"]),
                        msft_capex_billion_usd=_safe_float(row.get("msft_capex_billion_usd")),
                        goog_capex_billion_usd=_safe_float(row.get("goog_capex_billion_usd")),
                        meta_capex_billion_usd=_safe_float(row.get("meta_capex_billion_usd")),
                        amzn_capex_billion_usd=_safe_float(row.get("amzn_capex_billion_usd")),
                        yoy_growth=_safe_float(row.get("yoy_growth")),
                        qoq_growth=_safe_float(row.get("qoq_growth")),
                        unit=row.get("unit") or "billion_usd",
                        source=row.get("source") or "10-Q",
                        source_url=row.get("source_url") or "",
                        release_date=date.fromisoformat(row["release_date"])
                        if row.get("release_date")
                        else None,
                        data_status=row.get("data_status") or "actual",
                        collected_at=row.get("collected_at") or now_utc_iso(),
                    )
                )
        records.sort(key=lambda r: r.trade_date)
        return records
