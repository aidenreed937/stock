"""光伏产业链 InfoLink 价格端点 Collector。"""

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.base_parser import HtmlParserProtocol
from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.contracts import IndustryCollectionResult, as_collection_result
from stock_data.fetcher.industry.power.collectors.infolink_crawler import (
    INFOLINK_HEADERS,
    INFOLINK_HISTORY_URL,
    InfoLinkPvPriceCrawler,
)
from stock_data.fetcher.industry.power.collectors.infolink_crawler import (
    requests as _requests,
)
from stock_data.fetcher.industry.power.collectors.infolink_storage import (
    compute_pv_price_derivatives,
    load_pv_price_raw_csv,
    save_pv_price_raw_csv,
)
from stock_data.fetcher.industry.power.models import SolarPriceChainRecord
from stock_data.fetcher.industry.power.parsers.infolink import (
    INFOLINK_SPOT_PRICE_URL,
    InfoLinkSpotPriceHtmlParser,
)
from stock_data.fetcher.industry.power.paths import PowerRawPaths

# 保持旧测试和外部调用方从本模块 patch 网络客户端的兼容性。
requests = _requests


class PvPriceChainCollector:
    """光伏产业链各环节周度真实价格采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
        crawler: InfoLinkPvPriceCrawler | None = None,
        parser: HtmlParserProtocol[dict[str, Any]] | None = None,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.paths = PowerRawPaths(self.raw_dir)
        self.energy_raw_dir = self.paths.infolink_dir
        self.crawler = crawler or InfoLinkPvPriceCrawler(raw_dir=self.raw_dir, parser=parser)

    def collect(
        self,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> IndustryCollectionResult:
        """执行光伏价格链条采集并合并到 RAW CSV。"""
        self.energy_raw_dir.mkdir(parents=True, exist_ok=True)
        source_csv = self.paths.pv_price_chain_csv
        canonical_csv = self.energy_raw_dir / "pv_price_chain_weekly.csv"
        existing_records = self.load_from_raw_csv(source_csv)

        if start_date is not None or end_date is not None:
            range_start = start_date or end_date
            range_end = end_date or start_date
            if range_start is None or range_end is None:
                return IndustryCollectionResult([], status="EMPTY")
            range_start = range_start - timedelta(days=range_start.weekday())
            range_end = range_end + timedelta(days=6 - range_end.weekday())
            covered_weeks = {
                record.trade_date - timedelta(days=record.trade_date.weekday())
                for record in existing_records
                if range_start <= record.trade_date <= range_end
            }
            requested_weeks = set()
            cursor = range_start
            while cursor <= range_end:
                requested_weeks.add(cursor)
                cursor += timedelta(days=7)
            if not force and requested_weeks <= covered_weeks:
                return IndustryCollectionResult(
                    existing_records,
                    status="NO_CHANGE",
                    cached_periods=sorted(record.report_date for record in existing_records),
                )
            range_result = as_collection_result(
                self.crawler.fetch_range(range_start, range_end, force=force)
            )
            live_rows = range_result.records
            errors = range_result.errors
            fetched_periods = list(range_result.fetched_periods)
            missing_periods = list(range_result.missing_periods)
        else:
            live_data = self.crawler.fetch_live_spot_prices(force=force)
            live_rows = (
                [live_data] if isinstance(live_data, dict) and live_data.get("report_date") else []
            )
            errors = () if live_rows else ("在线抓取 InfoLink 光伏现货价格失败",)
            fetched_periods = (
                [str(live_data["report_date"])]
                if isinstance(live_data, dict) and live_data.get("report_date")
                else []
            )
            missing_periods = []

        if not live_rows:
            if existing_records and not force:
                self.save_to_raw_csv(canonical_csv, existing_records)
                return IndustryCollectionResult(
                    existing_records,
                    status="FAILED"
                    if start_date is not None or end_date is not None
                    else "NO_CHANGE",
                    cached_periods=[record.report_date for record in existing_records],
                    missing_periods=missing_periods,
                    errors=errors,
                )
            return IndustryCollectionResult([], status="FAILED", errors=errors)

        live_records = [self._record_from_live_data(live_data) for live_data in live_rows]
        records_by_date = {record.report_date: record for record in existing_records}
        records_by_date.update({record.report_date: record for record in live_records})
        records = sorted(records_by_date.values(), key=lambda record: record.trade_date)
        records = compute_pv_price_derivatives(records)
        self.save_to_raw_csv(canonical_csv, records)
        requested = {
            record.report_date
            for record in records
            if (start_date is None or record.trade_date >= start_date)
            and (end_date is None or record.trade_date <= end_date)
        }
        missing = missing_periods
        if start_date is not None and not requested:
            missing = missing or [start_date.isoformat()]
        return IndustryCollectionResult(
            records,
            status="PARTIAL" if errors or missing else "SUCCESS",
            fetched_periods=sorted(set(fetched_periods)),
            cached_periods=sorted({record.report_date for record in existing_records} & requested),
            missing_periods=missing,
            errors=errors,
            updated=bool(live_records),
        )

    @staticmethod
    def _record_from_live_data(live_data: dict[str, Any]) -> SolarPriceChainRecord:
        return SolarPriceChainRecord(
            report_date=str(live_data["report_date"]),
            trade_date=live_data["trade_date"],
            polysilicon_price_cny_kg=live_data.get("polysilicon_price_cny_kg"),
            wafer_price_cny_piece=live_data.get("wafer_price_cny_piece"),
            cell_price_cny_watt=live_data.get("cell_price_cny_watt"),
            module_price_cny_watt=live_data.get("module_price_cny_watt"),
            module_price_yoy=None,
            module_price_mom=None,
            price_cycle_stage=live_data.get("price_cycle_stage"),
            unit="cny_per_unit",
            source=live_data.get("source") or "InfoLink Consulting",
            source_url=live_data.get("source_url") or INFOLINK_SPOT_PRICE_URL,
            release_date=live_data.get("release_date"),
            data_status="actual",
            collected_at=str(live_data.get("collected_at") or now_utc_iso()),
            polysilicon_price_cny_kg_raw=(
                str(live_data["polysilicon_price_cny_kg"])
                if live_data.get("polysilicon_price_cny_kg") is not None
                else None
            ),
            wafer_price_cny_piece_raw=(
                str(live_data["wafer_price_cny_piece"])
                if live_data.get("wafer_price_cny_piece") is not None
                else None
            ),
            cell_price_cny_watt_raw=(
                str(live_data["cell_price_cny_watt"])
                if live_data.get("cell_price_cny_watt") is not None
                else None
            ),
            module_price_cny_watt_raw=(
                str(live_data["module_price_cny_watt"])
                if live_data.get("module_price_cny_watt") is not None
                else None
            ),
            raw_content_sha256=live_data.get("raw_content_sha256") or "",
            raw_snapshot_path=live_data.get("raw_snapshot_path") or "",
        )

    def save_to_raw_csv(self, file_path: Path | str, records: list[SolarPriceChainRecord]) -> None:
        """持久化标准化记录至 RAW CSV 快照。"""
        save_pv_price_raw_csv(file_path, records)

    def load_from_raw_csv(self, file_path: Path | str) -> list[SolarPriceChainRecord]:
        """从 RAW CSV 文件读取并标准化记录。"""
        return load_pv_price_raw_csv(file_path)


__all__ = [
    "INFOLINK_HEADERS",
    "INFOLINK_HISTORY_URL",
    "INFOLINK_SPOT_PRICE_URL",
    "InfoLinkPvPriceCrawler",
    "InfoLinkSpotPriceHtmlParser",
    "PvPriceChainCollector",
    "compute_pv_price_derivatives",
    "load_pv_price_raw_csv",
    "requests",
    "save_pv_price_raw_csv",
]
