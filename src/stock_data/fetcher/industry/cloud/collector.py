"""北美四大云厂商季度 AI 资本开支 (10-Q) 官方 SEC EDGAR 采集器 (CloudCapexCollector)。"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
from curl_cffi import requests

from stock_data.fetcher.industry.cloud.models import CloudCapexRecord
from stock_data.fetcher.industry.cloud.parser import (
    extract_sec_quarterly_capex_with_filing_dates,
)
from stock_data.fetcher.industry.cloud.paths import (
    CLOUD_RAW_SUBDIR,
    SEC_EDGAR_RAW_SUBDIR,
    CloudRawPaths,
)
from stock_data.fetcher.industry.cloud.transform import build_cloud_capex_raw_frame
from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    save_raw_snapshot,
)
from stock_data.fetcher.industry.semiconductor.lineage import (
    raw_content_sha256,
    raw_snapshot_content_bytes,
    raw_snapshot_path_value,
    response_content_bytes,
)

logger = logging.getLogger(__name__)

# SEC EDGAR 官方 CIK 字典
CSP_CIK_MAP: dict[str, str] = {
    "MSFT": "0000789019",
    "GOOGL": "0001652044",
    "META": "0001326801",
    "AMZN": "0001018724",
}

SEC_HEADERS = {
    "User-Agent": os.getenv("SEC_USER_AGENT", "stock-data-cloud/1.0 (contact@example.com)"),
    "Accept": "application/json",
}
CLOUD_CAPEX_START_DATE = date(2018, 1, 1)
_RAW_COMPONENTS = (
    "msft_capex_raw",
    "goog_capex_raw",
    "meta_capex_raw",
    "amzn_capex_raw",
)
_RAW_RELEASE_DATES = (
    "msft_release_date",
    "goog_release_date",
    "meta_release_date",
    "amzn_release_date",
)


class CloudCapexCollector:
    """北美四大云厂商 (MSFT/GOOGL/META/AMZN) 季度 10-Q CapEx 官方采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.paths = CloudRawPaths(raw_dir)
        self.raw_dir = self.paths.raw_root
        self.sec_raw_dir = self.paths.sec_edgar_dir
        self.raw_parquet = self.paths.cloud_capex_raw
        self._force_refresh = False
        self._allow_network = True
        self._company_lineage: dict[str, dict[str, str]] = {}

    def collect(
        self,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[CloudCapexRecord]:
        """兼容旧入口，返回指定报告期范围内的季度记录。"""
        return self._collect_records(
            force=force,
            start_date=start_date,
            end_date=end_date,
            allow_network=True,
        )

    def collect_raw(
        self,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pl.DataFrame:
        """按运行窗口采集云 CapEx RAW，优先复用结构化 RAW 与 SEC 快照。"""
        self._validate_range(start_date, end_date)
        local = self._load_structured_raw(start_date=None, end_date=None)
        targets = _target_quarters(start_date=start_date, end_date=end_date)
        required = _context_quarters(targets)
        has_window = start_date is not None or end_date is not None

        if not force:
            if targets and _contains_all_targets(local, required):
                return _select_quarters(local, required)
            if not has_window and not local.is_empty():
                return local
            if has_window and not targets:
                return build_cloud_capex_raw_frame(pl.DataFrame())

        collection_start = _quarter_end(min(required)) if required else None

        records = self._collect_records(
            force=force,
            start_date=collection_start,
            end_date=end_date,
            allow_network=True,
        )
        collected = build_cloud_capex_raw_frame(records)
        if local.is_empty():
            return collected
        if collected.is_empty():
            if has_window and not required:
                return build_cloud_capex_raw_frame(pl.DataFrame())
            return _select_quarters(local, required) if required else local
        merged = build_cloud_capex_raw_frame(pl.concat([local, collected], how="diagonal_relaxed"))
        return _select_quarters(merged, required) if required else merged

    def load_from_raw_snapshots(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pl.DataFrame:
        """离线读取结构化 RAW 或 SEC JSON 快照，不触发网络请求。"""
        self._validate_range(start_date, end_date)
        local = self._load_structured_raw(start_date=None, end_date=None)
        targets = _target_quarters(start_date=start_date, end_date=end_date)
        required = _context_quarters(targets)
        has_window = start_date is not None or end_date is not None
        collection_start = _quarter_end(min(required)) if required else None
        records = self._collect_records(
            force=False,
            start_date=collection_start,
            end_date=end_date,
            allow_network=False,
        )
        snapshots = build_cloud_capex_raw_frame(records)
        if local.is_empty():
            return snapshots
        if snapshots.is_empty():
            if has_window and not required:
                return build_cloud_capex_raw_frame(pl.DataFrame())
            return _select_quarters(local, required) if required else local
        merged = build_cloud_capex_raw_frame(pl.concat([local, snapshots], how="diagonal_relaxed"))
        return _select_quarters(merged, required) if required else merged

    def _collect_records(
        self,
        *,
        force: bool,
        start_date: date | None,
        end_date: date | None,
        allow_network: bool,
    ) -> list[CloudCapexRecord]:
        self._validate_range(start_date, end_date)
        targets = _target_quarters(start_date=start_date, end_date=end_date)
        previous_force = self._force_refresh
        previous_allow_network = self._allow_network
        previous_lineage = self._company_lineage
        self._force_refresh = force
        self._allow_network = allow_network
        self._company_lineage = {}

        try:
            company_data: dict[str, dict[str, float]] = {}
            company_filing_dates: dict[str, dict[str, date | None]] = {}
            cached_company_files = {
                ticker: (self.sec_raw_dir / f"{ticker}.json.gz").exists() for ticker in CSP_CIK_MAP
            }
            for ticker, cik in CSP_CIK_MAP.items():
                quarterly_facts = self._fetch_or_load_company(ticker, cik)
                company_data[ticker] = {
                    quarter: value for quarter, (value, _filing_date) in quarterly_facts.items()
                }
                company_filing_dates[ticker] = {
                    quarter: filing_date
                    for quarter, (_value, filing_date) in quarterly_facts.items()
                }

            # 本地 CompanyFacts 快照存在但尚未覆盖目标期时，只刷新缺口对应的公司。
            if targets and not force and allow_network:
                for ticker, cik in CSP_CIK_MAP.items():
                    if not cached_company_files[ticker] or _contains_quarters(
                        company_data[ticker], targets
                    ):
                        continue
                    refreshed = self._fetch_company_with_options(
                        ticker,
                        cik,
                        force=True,
                        allow_network=True,
                    )
                    if refreshed:
                        company_data[ticker] = {
                            quarter: value for quarter, (value, _date) in refreshed.items()
                        }
                        company_filing_dates[ticker] = {
                            quarter: filing_date
                            for quarter, (_value, filing_date) in refreshed.items()
                        }

            return self._build_records(
                company_data,
                company_filing_dates,
                start_date=start_date,
                end_date=end_date,
            )
        finally:
            self._force_refresh = previous_force
            self._allow_network = previous_allow_network
            self._company_lineage = previous_lineage

    def _build_records(
        self,
        company_data: dict[str, dict[str, float]],
        company_filing_dates: dict[str, dict[str, date | None]],
        *,
        start_date: date | None,
        end_date: date | None,
    ) -> list[CloudCapexRecord]:
        if not company_data:
            return []

        all_quarters = sorted(
            {
                quarter
                for data in company_data.values()
                for quarter, value in data.items()
                if value > 0 and quarter >= "2018-Q1"
            }
        )
        if start_date is not None or end_date is not None:
            targets = _target_quarters(start_date=start_date, end_date=end_date)
            all_quarters = [quarter for quarter in all_quarters if quarter in targets]
        if not all_quarters:
            return []

        records: list[CloudCapexRecord] = []
        now_iso = now_utc_iso()
        for q_str in all_quarters:
            year, q_num = int(q_str.split("-Q")[0]), int(q_str.split("-Q")[1])
            t_date = get_month_end_date(year, q_num * 3)
            component_values = [company_data.get(ticker, {}).get(q_str) for ticker in CSP_CIK_MAP]
            has_complete_components = all(
                value is not None and value > 0 for value in component_values
            )
            total = sum(value for value in component_values if value is not None)
            component_filing_dates = [
                company_filing_dates.get(ticker, {}).get(q_str) for ticker in CSP_CIK_MAP
            ]
            known_filing_dates = [
                filing_date for filing_date in component_filing_dates if filing_date is not None
            ]
            release_date = (
                max(known_filing_dates)
                if has_complete_components and len(known_filing_dates) == len(component_values)
                else None
            )
            lineage = {
                ticker: self._company_lineage[ticker]
                for ticker in CSP_CIK_MAP
                if ticker in self._company_lineage
            }
            records.append(
                CloudCapexRecord(
                    report_quarter=q_str,
                    trade_date=t_date,
                    total_capex_billion_usd=round(total, 3) if has_complete_components else None,
                    msft_capex_billion_usd=_positive_value(component_values[0]),
                    goog_capex_billion_usd=_positive_value(component_values[1]),
                    meta_capex_billion_usd=_positive_value(component_values[2]),
                    amzn_capex_billion_usd=_positive_value(component_values[3]),
                    unit="billion_usd",
                    source="SEC_EDGAR_10Q",
                    source_url="https://www.sec.gov/edgar/",
                    release_date=release_date,
                    data_status="actual" if has_complete_components else "partial_actual",
                    collected_at=now_iso,
                    raw_content_sha256=json.dumps(
                        {
                            ticker: info.get("raw_content_sha256", "")
                            for ticker, info in lineage.items()
                        },
                        sort_keys=True,
                    ),
                    raw_snapshot_path=json.dumps(
                        {
                            ticker: info.get("raw_snapshot_path", "")
                            for ticker, info in lineage.items()
                        },
                        sort_keys=True,
                    ),
                    msft_capex_raw=_raw_number(component_values[0]),
                    goog_capex_raw=_raw_number(component_values[1]),
                    meta_capex_raw=_raw_number(component_values[2]),
                    amzn_capex_raw=_raw_number(component_values[3]),
                    msft_release_date=component_filing_dates[0],
                    goog_release_date=component_filing_dates[1],
                    meta_release_date=component_filing_dates[2],
                    amzn_release_date=component_filing_dates[3],
                )
            )
        return records

    def _fetch_company_with_options(
        self,
        ticker: str,
        cik: str,
        *,
        force: bool,
        allow_network: bool,
    ) -> dict[str, tuple[float, date | None]]:
        previous_force = self._force_refresh
        previous_allow_network = self._allow_network
        self._force_refresh = force
        self._allow_network = allow_network
        try:
            return self._fetch_or_load_company(ticker, cik)
        finally:
            self._force_refresh = previous_force
            self._allow_network = previous_allow_network

    def _load_structured_raw(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
    ) -> pl.DataFrame:
        if not self.raw_parquet.exists():
            return build_cloud_capex_raw_frame(pl.DataFrame())
        try:
            frame = build_cloud_capex_raw_frame(pl.read_parquet(self.raw_parquet))
        except (OSError, pl.exceptions.PolarsError, ValueError) as exc:
            logger.warning("读取云 CapEx RAW Parquet 失败 [%s]: %s", self.raw_parquet, exc)
            return build_cloud_capex_raw_frame(pl.DataFrame())
        return _filter_date_range(frame, start_date=start_date, end_date=end_date)

    def _load_company_facts(self, ticker: str, cik: str) -> dict[str, Any]:
        """读取 SEC CompanyFacts 快照；按 force/allow_network 控制缓存与网络。"""
        raw_file = self.sec_raw_dir / f"{ticker}.json.gz"
        if raw_file.exists() and not self._force_refresh:
            facts = self._read_company_snapshot(raw_file, ticker)
            if facts:
                return facts

        if not self._allow_network:
            return {}

        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        logger.info("正在从 SEC EDGAR 获取 %s (CIK %s) 真实 10-Q 财报...", ticker, cik)
        try:
            response = requests.get(
                url,
                headers=SEC_HEADERS,
                timeout=20,
                impersonate="chrome120",
            )
            content = response_content_bytes(response)
            if response.status_code != 200 or not content:
                logger.warning("SEC EDGAR 请求失败 [%s]: HTTP %s", ticker, response.status_code)
                return {} if self._force_refresh else self._read_company_snapshot(raw_file, ticker)
            snapshot_path = save_raw_snapshot(
                SEC_EDGAR_RAW_SUBDIR,
                f"{ticker}.json",
                content,
                base_dir=self.raw_dir / CLOUD_RAW_SUBDIR,
                compress=True,
            )
            self._company_lineage[ticker] = {
                "raw_content_sha256": raw_content_sha256(content),
                "raw_snapshot_path": raw_snapshot_path_value(snapshot_path, self.raw_dir),
            }
            payload = json.loads(content.decode("utf-8"))
            if not isinstance(payload, dict) or not _company_facts_matches_identity(payload, cik):
                logger.warning("SEC CompanyFacts 响应 CIK 不匹配，拒绝复用 [%s]", ticker)
                return {}
            return payload
        except Exception as exc:  # noqa: BLE001
            logger.warning("SEC EDGAR 在线拉取异常 [%s]: %s", ticker, exc)
            return {} if self._force_refresh else self._read_company_snapshot(raw_file, ticker)

    def _read_company_snapshot(self, raw_file: Path, ticker: str) -> dict[str, Any]:
        try:
            content = raw_snapshot_content_bytes(raw_file)
            payload = json.loads(content.decode("utf-8"))
            if not isinstance(payload, dict) or not _company_facts_matches_identity(
                payload,
                CSP_CIK_MAP[ticker],
            ):
                logger.warning("本地 SEC CompanyFacts CIK 不匹配，拒绝复用 [%s]", ticker)
                return {}
            self._company_lineage[ticker] = {
                "raw_content_sha256": raw_content_sha256(content),
                "raw_snapshot_path": raw_snapshot_path_value(raw_file, self.raw_dir),
            }
            return payload
        except (OSError, EOFError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("读取本地 SEC 快照失败 [%s]: %s", raw_file, exc)
            return {}

    def _fetch_or_load_company(self, ticker: str, cik: str) -> dict[str, tuple[float, date | None]]:
        """加载单家公司的季度 CapEx 事实及 filing date。"""
        return extract_sec_quarterly_capex_with_filing_dates(
            self._load_company_facts(ticker, cik), ticker
        )

    @staticmethod
    def _validate_range(start_date: date | None, end_date: date | None) -> None:
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError(f"云 CapEx 日期范围无效: {start_date} > {end_date}")


def _positive_value(value: float | None) -> float | None:
    return round(value, 3) if value is not None and value > 0 else None


def _raw_number(value: float | None) -> str | None:
    return str(value) if value is not None and value > 0 else None


def _company_facts_matches_identity(payload: dict[str, Any], expected_cik: str) -> bool:
    raw_cik = str(payload.get("cik") or "").strip()
    if not raw_cik:
        return True
    return (raw_cik.lstrip("0") or "0") == (expected_cik.lstrip("0") or "0")


def _target_quarters(
    *,
    start_date: date | None,
    end_date: date | None,
) -> set[str]:
    if start_date is None and end_date is None:
        return set()
    lower = max(start_date or CLOUD_CAPEX_START_DATE, CLOUD_CAPEX_START_DATE)
    upper = end_date or date.today()
    if lower > upper:
        return set()

    year = lower.year
    quarter = (lower.month - 1) // 3 + 1
    targets: set[str] = set()
    while True:
        quarter_end = get_month_end_date(year, quarter * 3)
        if quarter_end > upper:
            break
        if quarter_end >= lower:
            targets.add(f"{year}-Q{quarter}")
        quarter += 1
        if quarter == 5:
            year += 1
            quarter = 1
    return targets


def _contains_quarters(data: dict[str, float], targets: set[str]) -> bool:
    return targets.issubset({quarter for quarter, value in data.items() if value > 0})


def _contains_all_targets(frame: pl.DataFrame, targets: set[str]) -> bool:
    required_columns = set(_RAW_COMPONENTS) | set(_RAW_RELEASE_DATES)
    if not targets or frame.is_empty() or not required_columns.issubset(frame.columns):
        return False
    target_rows = frame.filter(pl.col("report_quarter").is_in(sorted(targets)))
    if target_rows.select("report_quarter").n_unique() != len(targets):
        return False
    values_complete = pl.all_horizontal(
        [
            pl.col(column)
            .cast(pl.String)
            .str.replace_all(r"[^\d.eE+-]", "")
            .cast(pl.Float64, strict=False)
            .is_not_null()
            & (
                pl.col(column)
                .cast(pl.String)
                .str.replace_all(r"[^\d.eE+-]", "")
                .cast(pl.Float64, strict=False)
                > 0
            )
            for column in _RAW_COMPONENTS
        ]
    )
    dates_complete = pl.all_horizontal(
        [pl.col(column).is_not_null() for column in _RAW_RELEASE_DATES]
    )
    return target_rows.select(values_complete & dates_complete).to_series().all()


def _context_quarters(targets: set[str]) -> set[str]:
    """为同比计算补入目标期前四个季度的最小上下文窗口。"""
    if not targets:
        return set()
    first = min(targets)
    year, quarter = _parse_quarter(first)
    context: set[str] = set()
    for offset in range(-4, 1):
        context_year, context_quarter = _shift_quarter(year, quarter, offset)
        if context_year >= CLOUD_CAPEX_START_DATE.year:
            context.add(f"{context_year}-Q{context_quarter}")
    return context | targets


def _select_quarters(frame: pl.DataFrame, quarters: set[str]) -> pl.DataFrame:
    if not quarters:
        return frame
    return frame.filter(pl.col("report_quarter").is_in(sorted(quarters))).sort("trade_date")


def _parse_quarter(value: str) -> tuple[int, int]:
    year, quarter = value.split("-Q")
    return int(year), int(quarter)


def _shift_quarter(year: int, quarter: int, offset: int) -> tuple[int, int]:
    index = year * 4 + quarter - 1 + offset
    return index // 4, index % 4 + 1


def _quarter_end(value: str) -> date:
    year, quarter = _parse_quarter(value)
    return get_month_end_date(year, quarter * 3)


def _filter_date_range(
    frame: pl.DataFrame,
    *,
    start_date: date | None,
    end_date: date | None,
) -> pl.DataFrame:
    condition = pl.lit(True)
    if start_date is not None:
        condition = condition & (pl.col("trade_date") >= start_date)
    if end_date is not None:
        condition = condition & (pl.col("trade_date") <= end_date)
    return frame.filter(condition)
