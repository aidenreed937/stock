"""硅业分会月度硅料/硅片标准端点 Collector。"""

from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.common import parse_month_string
from stock_data.fetcher.industry.contracts import IndustryCollectionResult, as_collection_result
from stock_data.fetcher.industry.power.collectors.silicon_crawler import (
    SOLARBE_HEADERS,
    SOLARBE_SILICON_SEARCH_URL,
    SOLARBE_SILICON_SOURCE,
    SiliconBranchCrawler,
    month_keys,
    requests,
)
from stock_data.fetcher.industry.power.collectors.silicon_storage import (
    ACTUAL_SILICON_DATA_STATUSES,
    get_polysilicon_annual_capacity,
    get_wafer_annual_capacity,
    load_capacity_row,
    load_silicon_records_from_raw_csv,
    records_from_online,
    safe_float,
    save_silicon_records_to_raw_csv,
)
from stock_data.fetcher.industry.power.lineage import file_lineage
from stock_data.fetcher.industry.power.models import (
    PolysiliconInventoryMonthlyRecord,
    PolysiliconSupplyMonthlyRecord,
    PvWaferMonthlyRecord,
    SiliconWaferMonthlyRecord,
)
from stock_data.fetcher.industry.power.parsers.silicon import parse_silicon_branch_bulletin_text
from stock_data.fetcher.industry.power.paths import PowerRawPaths


class SiliconBranchCollector:
    """硅业分会多晶硅与单晶硅片月度基本面数据采集器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
        crawler: SiliconBranchCrawler | None = None,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.paths = PowerRawPaths(self.raw_dir)
        self.csv_file = self.paths.silicon_wafer_monthly_csv
        self.crawler = crawler or SiliconBranchCrawler(raw_dir=self.raw_dir)

    def collect(
        self,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> IndustryCollectionResult:
        """智能读取本地覆盖并在线补齐硅业分会月度缺口。"""
        raw_existing_records = self.load_from_raw_csv(self.csv_file, include_unverified=True)
        existing_records = [
            record
            for record in raw_existing_records
            if record.data_status in ACTUAL_SILICON_DATA_STATUSES
        ]
        no_range = start_date is None and end_date is None
        existing_by_month = {record.report_month: record for record in existing_records}
        raw_by_month = {record.report_month: record for record in raw_existing_records}
        covered = set(existing_by_month)
        if no_range:
            requested: list[str] = []
            fetch_latest = getattr(self.crawler, "fetch_latest", None)
            online_result = (
                as_collection_result(fetch_latest(force=force))
                if callable(fetch_latest)
                else IndustryCollectionResult([], status="EMPTY")
            )
            online_records = self._records_from_online(online_result.records)
            for record in online_records:
                previous = existing_by_month.get(record.report_month)
                if (
                    previous is not None
                    and record.raw_content_sha256
                    and record.raw_content_sha256 == previous.raw_content_sha256
                ):
                    record = replace(record, collected_at=previous.collected_at)
                existing_by_month[record.report_month] = record
                raw_by_month[record.report_month] = record
        else:
            start = (start_date or end_date).replace(day=1)  # type: ignore[union-attr]
            end = (end_date or start_date).replace(day=1)  # type: ignore[union-attr]
            requested = month_keys(start, end)
            fetch_periods = (
                requested if force else [period for period in requested if period not in covered]
            )
            online_result = as_collection_result(
                self.crawler.fetch_range(
                    start_date=start,
                    end_date=end,
                    periods=fetch_periods,
                    force=force,
                )
            )
            online_records = self._records_from_online(online_result.records)
            for record in online_records:
                existing_by_month[record.report_month] = record
                raw_by_month[record.report_month] = record

        records = sorted(existing_by_month.values(), key=lambda record: record.trade_date)
        if online_records:
            self.save_to_raw_csv(
                self.paths.silicon_branch_dir / "silicon_wafer_monthly.csv",
                sorted(raw_by_month.values(), key=lambda record: record.trade_date),
            )
        enriched: list[SiliconWaferMonthlyRecord] = []
        for record in records:
            year, _ = parse_month_string(record.report_month)
            capacity_row, capacity_file = load_capacity_row(year, self.raw_dir)
            poly_capacity = (
                safe_float(capacity_row.get("polysilicon_capacity_w_tons"))
                if capacity_row
                else None
            )
            wafer_capacity = (
                safe_float(capacity_row.get("wafer_capacity_gw")) if capacity_row else None
            )
            poly_capacity = poly_capacity or record.polysilicon_capacity_annual_w_tons
            wafer_capacity = wafer_capacity or record.wafer_capacity_annual_gw
            capacity_hash, capacity_ref = (
                file_lineage(capacity_file, self.raw_dir)
                if capacity_file is not None
                else (
                    record.capacity_raw_content_sha256,
                    record.capacity_raw_snapshot_path,
                )
            )
            enriched.append(
                replace(
                    record,
                    polysilicon_capacity_annual_w_tons=poly_capacity,
                    wafer_capacity_annual_gw=wafer_capacity,
                    polysilicon_capacity_annual_w_tons_raw=(
                        str(poly_capacity)
                        if poly_capacity is not None
                        else record.polysilicon_capacity_annual_w_tons_raw
                    ),
                    wafer_capacity_annual_gw_raw=(
                        str(wafer_capacity)
                        if wafer_capacity is not None
                        else record.wafer_capacity_annual_gw_raw
                    ),
                    capacity_raw_content_sha256=capacity_hash,
                    capacity_raw_snapshot_path=capacity_ref,
                )
            )
        available = {record.report_month for record in enriched}
        missing = sorted(set(requested) - available)
        errors = tuple(online_result.errors)
        if no_range:
            if online_result.errors:
                status = online_result.status
            elif online_records:
                status = online_result.status if online_result.status != "EMPTY" else "SUCCESS"
            else:
                status = "NO_CHANGE" if existing_records else online_result.status
        else:
            status = online_result.status
        if missing and status == "SUCCESS":
            status = "UNSUPPORTED_RANGE"
        elif missing and status == "PARTIAL":
            status = "PARTIAL"
        elif not online_records and not errors and not no_range:
            status = "NO_CHANGE"
        return IndustryCollectionResult(
            enriched,
            status=status,
            fetched_periods=sorted({record.report_month for record in online_records}),
            cached_periods=sorted(covered & set(requested)),
            missing_periods=missing,
            errors=errors,
            updated=bool(online_records),
        )

    @staticmethod
    def _records_from_online(rows: list[Any]) -> list[SiliconWaferMonthlyRecord]:
        return records_from_online(rows)

    def load_from_raw_csv(
        self,
        file_path: Path | str,
        *,
        include_unverified: bool = False,
    ) -> list[SiliconWaferMonthlyRecord]:
        """从 RAW 快照 CSV 读取并解析为 SiliconWaferMonthlyRecord 列表。"""
        return load_silicon_records_from_raw_csv(
            file_path,
            self.raw_dir,
            include_unverified=include_unverified,
        )

    def save_to_raw_csv(
        self,
        file_path: Path | str,
        records: list[SiliconWaferMonthlyRecord],
    ) -> None:
        """持久化标准化记录至 RAW CSV 快照。"""
        save_silicon_records_to_raw_csv(file_path, records)

    def collect_supply(self) -> list[PolysiliconSupplyMonthlyRecord]:
        """提取标准化多晶硅供给事实记录列表。"""
        return _collect_supply(self)

    def collect_inventory(self) -> list[PolysiliconInventoryMonthlyRecord]:
        """提取标准化多晶硅库存事实记录列表。"""
        return _collect_inventory(self)

    def collect_wafer(self) -> list[PvWaferMonthlyRecord]:
        """提取标准化单晶硅片产出与折算需求事实记录列表。"""
        return _collect_wafer(self)


def _collect_supply(
    collector: SiliconBranchCollector,
) -> list[PolysiliconSupplyMonthlyRecord]:
    records = collector.collect()
    supply_records: list[PolysiliconSupplyMonthlyRecord] = []
    for record in records:
        year, _ = parse_month_string(record.report_month)
        capacity = get_polysilicon_annual_capacity(year, raw_dir=collector.raw_dir)
        capacity = capacity or record.polysilicon_capacity_annual_w_tons
        supply_records.append(
            PolysiliconSupplyMonthlyRecord(
                report_month=record.report_month,
                trade_date=record.trade_date,
                production_w_tons=record.polysilicon_output_w_tons,
                production_yoy=record.polysilicon_output_yoy,
                production_mom=None,
                capacity_annual_w_tons=capacity,
                operating_rate=record.polysilicon_operating_rate,
                derived_utilization_rate=None,
                unit="ten_thousand_tons",
                source=record.source,
                source_url=record.source_url,
                release_date=record.release_date,
                data_status=record.data_status,
                collected_at=record.collected_at,
            )
        )
    return supply_records


def _collect_inventory(
    collector: SiliconBranchCollector,
) -> list[PolysiliconInventoryMonthlyRecord]:
    records = collector.collect()
    inventory_records: list[PolysiliconInventoryMonthlyRecord] = []
    for record in records:
        if record.polysilicon_inventory_w_tons is not None:
            inventory_records.append(
                PolysiliconInventoryMonthlyRecord(
                    report_month=record.report_month,
                    trade_date=record.trade_date,
                    inventory_w_tons=record.polysilicon_inventory_w_tons,
                    inventory_change_w_tons=None,
                    inventory_weeks=None,
                    inventory_status=None,
                    unit="ten_thousand_tons",
                    source=record.source,
                    source_url=record.source_url,
                    release_date=record.release_date,
                    data_status=record.data_status,
                    collected_at=record.collected_at,
                )
            )
    return inventory_records


def _collect_wafer(collector: SiliconBranchCollector) -> list[PvWaferMonthlyRecord]:
    records = collector.collect()
    return [
        PvWaferMonthlyRecord(
            report_month=record.report_month,
            trade_date=record.trade_date,
            wafer_output_gw=record.wafer_output_gw,
            wafer_output_yoy=record.wafer_output_yoy,
            wafer_operating_rate=record.wafer_operating_rate,
            derived_wafer_utilization_rate=record.derived_wafer_utilization_rate,
            silicon_consumption_ratio=None,
            implied_silicon_demand_w_tons=None,
            unit="gw/ten_thousand_tons",
            source=record.source,
            source_url=record.source_url,
            release_date=record.release_date,
            data_status=record.data_status,
            collected_at=record.collected_at,
        )
        for record in records
    ]


__all__ = [
    "SOLARBE_HEADERS",
    "SOLARBE_SILICON_SEARCH_URL",
    "SOLARBE_SILICON_SOURCE",
    "SiliconBranchCollector",
    "SiliconBranchCrawler",
    "get_polysilicon_annual_capacity",
    "get_wafer_annual_capacity",
    "parse_silicon_branch_bulletin_text",
    "requests",
    "save_silicon_records_to_raw_csv",
]
