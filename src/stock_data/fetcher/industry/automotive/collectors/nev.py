"""新能源汽车多源月度采集协调器。"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.automotive.collectors.cabia import CabiaCollector
from stock_data.fetcher.industry.automotive.collectors.cpca import CpcaCollector
from stock_data.fetcher.industry.automotive.merger import (
    merge_record,
    month_keys,
    record_in_range,
)
from stock_data.fetcher.industry.automotive.models import NevMonthlyRecord
from stock_data.fetcher.industry.automotive.paths import AutomotiveRawPaths
from stock_data.fetcher.industry.contracts import IndustryCollectionResult

logger = logging.getLogger(__name__)


class NevCollector:
    """协调 CPCA、CABIA 两个源，并维护新能源汽车统一 RAW 水位。"""

    def __init__(self, *, raw_dir: Path | str) -> None:
        self.raw_dir = Path(raw_dir)
        self.paths = AutomotiveRawPaths(self.raw_dir)
        self.cpca_source = CpcaCollector(raw_dir=self.raw_dir)
        self.cabia_source = CabiaCollector(raw_dir=self.raw_dir)
        # 保留旧属性，供历史脚本和调试调用方继续访问。
        self.cpca_crawler = self.cpca_source.crawler
        self.cabia_crawler = self.cabia_source.crawler

    def collect(
        self,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> IndustryCollectionResult:
        """按 RAW 水位和请求窗口采集并返回完整历史记录。"""
        requested_periods = set(month_keys(start_date, end_date))
        errors: list[str] = []
        existing_by_month: dict[str, NevMonthlyRecord] = {}
        for incoming in self._collect_sources(
            start_date=start_date,
            end_date=end_date,
            force=force,
            errors=errors,
        ):
            previous = existing_by_month.get(incoming.report_month)
            merged = merge_record(previous, incoming)
            existing_by_month[incoming.report_month] = merged

        fetched_periods = set(self.cpca_source.last_fetched_periods)
        fetched_periods.update(self.cabia_source.last_fetched_periods)

        records = sorted(existing_by_month.values(), key=lambda record: record.trade_date)
        if not records:
            logger.warning("未找到新能源汽车 CPCA/CABIA RAW 数据")
            return IndustryCollectionResult(
                [],
                status="FAILED",
                missing_periods=sorted(requested_periods),
                errors=(*errors, "未找到 CPCA/CABIA RAW 或在线数据"),
            )

        available_periods = {
            record.report_month
            for record in records
            if record_in_range(record, start_date, end_date)
        }
        missing_periods = sorted(requested_periods - available_periods)
        if missing_periods:
            errors.append(f"未覆盖请求月份:{','.join(missing_periods)}")
        if (errors and records and (force or not requested_periods)) or (
            missing_periods and fetched_periods
        ):
            status = "PARTIAL"
        elif missing_periods:
            status = "FAILED"
        elif fetched_periods:
            status = "SUCCESS"
        else:
            status = "NO_CHANGE"
        return IndustryCollectionResult(
            records,
            status=status,
            fetched_periods=sorted(fetched_periods),
            cached_periods=sorted(requested_periods - fetched_periods - set(missing_periods)),
            missing_periods=missing_periods,
            errors=errors,
            updated=bool(fetched_periods),
        )

    def _collect_sources(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
        force: bool,
        errors: list[str],
    ) -> list[NevMonthlyRecord]:
        cpca_records = self.cpca_source.collect(
            start_date=start_date,
            end_date=end_date,
            force=force,
        )
        errors.extend(self.cpca_source.last_errors)
        cabia_records = self.cabia_source.collect(
            start_date=start_date,
            end_date=end_date,
            force=force,
        )
        errors.extend(self.cabia_source.last_errors)
        return [*cpca_records, *cabia_records]

    def replay_cached_snapshots(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[NevMonthlyRecord]:
        """仅从 CPCA/CABIA RAW 快照离线重放，不触发网络请求。"""
        records_by_month: dict[str, NevMonthlyRecord] = {}
        for incoming in (
            *self.cpca_source.replay_cached_snapshots(
                start_date=start_date,
                end_date=end_date,
            ),
            *self.cabia_source.replay_cached_snapshots(
                start_date=start_date,
                end_date=end_date,
            ),
        ):
            records_by_month[incoming.report_month] = merge_record(
                records_by_month.get(incoming.report_month), incoming
            )
        return sorted(records_by_month.values(), key=lambda record: record.trade_date)


__all__ = ["NevCollector"]
