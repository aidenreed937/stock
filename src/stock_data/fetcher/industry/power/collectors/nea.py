"""国家能源局 (NEA) / 中电联 (CEC) 光伏月度新增与累计装机容量官方采集器 (SolarCollector)。"""

from __future__ import annotations

import logging
from datetime import date
from inspect import Parameter, signature
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
)
from stock_data.fetcher.industry.contracts import IndustryCollectionResult
from stock_data.fetcher.industry.power.collectors.nea_crawler import NeaBulletinCrawler
from stock_data.fetcher.industry.power.collectors.nea_storage import (
    _safe_float,
    load_solar_capacity_raw_csv,
    save_solar_capacity_raw_csv,
)
from stock_data.fetcher.industry.power.lineage import file_lineage
from stock_data.fetcher.industry.power.models import SolarCapacityRecord
from stock_data.fetcher.industry.power.paths import PowerRawPaths

logger = logging.getLogger(__name__)


class SolarCollector:
    """国家能源局 (NEA) 光伏装机月度统计采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.paths = PowerRawPaths(self.raw_dir)
        self.nea_dir = self.paths.nea_dir
        self.crawler = NeaBulletinCrawler(raw_dir=self.raw_dir)

    def collect(
        self,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> IndustryCollectionResult:
        """执行光伏装机数据采集: 在线抓取国家能源局通报并落盘，以最新采集为准。"""
        self.nea_dir.mkdir(parents=True, exist_ok=True)
        csv_file = self.paths.solar_capacity_csv

        existing_records = self.load_from_raw_csv(csv_file)
        existing_by_month = {r.report_month: r for r in existing_records}
        requested_periods = set(_month_keys(start_date, end_date))
        if requested_periods and not force and requested_periods <= set(existing_by_month):
            return IndustryCollectionResult(
                existing_records,
                status="NO_CHANGE",
                cached_periods=sorted(requested_periods),
            )

        # 在线抓取国家能源局官网通报
        fetch_method = self.crawler.fetch_latest_bulletins
        parameters = signature(fetch_method).parameters
        accepts_kwargs = any(param.kind == Parameter.VAR_KEYWORD for param in parameters.values())
        kwargs: dict[str, Any] = {}
        for name, value in (
            ("start_date", start_date),
            ("end_date", end_date),
            ("force", force),
        ):
            if accepts_kwargs or name in parameters:
                kwargs[name] = value
        bulletins = fetch_method(**kwargs) if kwargs else fetch_method()
        if not bulletins and not existing_records:
            logger.warning("在线抓取国家能源局光伏装机通报失败")
            return IndustryCollectionResult([], status="FAILED")

        now_iso = now_utc_iso()
        for m_str, info in bulletins.items():
            cum_gw = info.get("cumulative_gw")
            if cum_gw is None:
                continue
            yr, mo = parse_month_string(m_str)
            t_date = get_month_end_date(yr, mo)
            rel_d = date.fromisoformat(info["release_date"]) if info.get("release_date") else None
            content_hash, snapshot_ref = _resolve_bulletin_lineage(
                info, m_str, self.paths, self.raw_dir
            )
            previous = existing_by_month.get(m_str)
            content_hash = content_hash or (previous.raw_content_sha256 if previous else "")
            snapshot_ref = snapshot_ref or (previous.raw_snapshot_path if previous else "")
            existing_by_month[m_str] = SolarCapacityRecord(
                report_month=m_str,
                trade_date=t_date,
                monthly_new_capacity_gw=info.get("monthly_new_capacity_gw"),
                cumulative_capacity_gw=float(cum_gw),
                yoy_growth=info.get("yoy_growth"),
                unit="gw",
                source="NEA",
                source_url=info.get("url") or "http://www.nea.gov.cn/",
                release_date=rel_d,
                data_status="actual",
                collected_at=info.get("collected_at") or now_iso,
                monthly_new_capacity_gw_raw=(
                    str(info["monthly_new_capacity_gw"])
                    if info.get("monthly_new_capacity_gw") is not None
                    else None
                ),
                cumulative_capacity_gw_raw=str(cum_gw),
                yoy_growth_raw=(
                    str(info["yoy_growth"]) if info.get("yoy_growth") is not None else None
                ),
                raw_content_sha256=str(info.get("raw_content_sha256") or content_hash),
                raw_snapshot_path=str(info.get("raw_snapshot_path") or snapshot_ref),
            )

        if not existing_by_month:
            return IndustryCollectionResult(
                [], status="FAILED" if getattr(self.crawler, "last_errors", ()) else "EMPTY"
            )

        # 按月份排序并重新计算差分单月新增
        months_sorted = sorted(existing_by_month.keys())
        records: list[SolarCapacityRecord] = []
        prev_cum: float | None = None

        for m_str in months_sorted:
            r = existing_by_month[m_str]
            cum_gw = r.cumulative_capacity_gw

            source_new_gw = _safe_float(r.monthly_new_capacity_gw_raw)
            if source_new_gw is not None:
                new_gw = source_new_gw
            elif cum_gw is not None:
                if prev_cum is None:
                    new_gw = None
                else:
                    diff = cum_gw - prev_cum
                    new_gw = round(diff, 2) if diff >= 0 else None
            else:
                new_gw = r.monthly_new_capacity_gw

            if cum_gw is not None:
                prev_cum = cum_gw

            records.append(
                SolarCapacityRecord(
                    report_month=r.report_month,
                    trade_date=r.trade_date,
                    monthly_new_capacity_gw=new_gw,
                    cumulative_capacity_gw=cum_gw,
                    yoy_growth=r.yoy_growth,
                    unit=r.unit,
                    source=r.source,
                    source_url=r.source_url,
                    release_date=r.release_date,
                    data_status=r.data_status,
                    collected_at=r.collected_at,
                    raw_content_sha256=r.raw_content_sha256,
                    raw_snapshot_path=r.raw_snapshot_path,
                    monthly_new_capacity_gw_raw=r.monthly_new_capacity_gw_raw,
                    cumulative_capacity_gw_raw=r.cumulative_capacity_gw_raw,
                    yoy_growth_raw=r.yoy_growth_raw,
                )
            )

        records.sort(key=lambda r: r.trade_date)
        self.save_to_raw_csv(self.paths.nea_dir / "solar_capacity.csv", records)
        period_keys = {
            record.report_month
            for record in records
            if (start_date is None or record.trade_date >= start_date)
            and (end_date is None or record.trade_date <= end_date)
        }
        fetched_periods = set(getattr(self.crawler, "last_fetched_periods", ()))
        if not fetched_periods:
            fetched_periods = set(existing_by_month) - {r.report_month for r in existing_records}
        errors = tuple(getattr(self.crawler, "last_errors", ()))
        missing_periods = sorted(requested_periods - period_keys)
        status = "SUCCESS"
        if errors and not fetched_periods:
            status = "FAILED" if not period_keys else "PARTIAL"
        elif missing_periods:
            status = "PARTIAL"
        elif not fetched_periods and requested_periods:
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

    def save_to_raw_csv(self, file_path: Path | str, records: list[SolarCapacityRecord]) -> None:
        """持久化标准化记录至 RAW CSV 快照。"""
        save_solar_capacity_raw_csv(file_path, records)
        logger.info("已保存 NEA 光伏装机 RAW 快照: %s (共 %d 行)", file_path, len(records))

    def load_from_raw_csv(self, file_path: Path | str) -> list[SolarCapacityRecord]:
        """从 NEA RAW 快照 CSV 中读取并标准化。"""
        return load_solar_capacity_raw_csv(file_path, self.raw_dir)


def _month_keys(start_date: date | None, end_date: date | None) -> list[str]:
    """生成包含边界月份的 YYYY-MM 列表。"""
    if start_date is None and end_date is None:
        return []
    cursor = (start_date or end_date).replace(day=1)  # type: ignore[union-attr]
    end = (end_date or start_date).replace(day=1)  # type: ignore[union-attr]
    result: list[str] = []
    while cursor <= end:
        result.append(cursor.strftime("%Y-%m"))
        cursor = date(
            cursor.year + (cursor.month == 12),
            1 if cursor.month == 12 else cursor.month + 1,
            1,
        )
    return result


def _resolve_bulletin_lineage(
    info: dict[str, Any],
    report_month: str,
    paths: PowerRawPaths,
    raw_dir: Path,
) -> tuple[str, str]:
    """为历史 manifest 记录补齐详情 HTML 的真实血缘。"""
    raw_hash = str(info.get("raw_content_sha256") or "")
    raw_ref = str(info.get("raw_snapshot_path") or "")
    if raw_hash and raw_ref:
        return raw_hash, raw_ref
    filename = str(info.get("filename") or "")
    candidates = [
        paths.nea_dir / filename
        if filename
        else paths.nea_dir / f"power_stats_{report_month.replace('-', '_')}.html",
        *(directory / filename for directory in paths.legacy_nea_dirs if filename),
    ]
    for candidate in candidates:
        if candidate.exists():
            return file_lineage(candidate, raw_dir)
    return raw_hash, raw_ref


__all__ = ["SolarCollector"]
