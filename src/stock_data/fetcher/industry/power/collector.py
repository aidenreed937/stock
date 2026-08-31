"""国家能源局 (NEA) / 中电联 (CEC) 光伏月度新增与累计装机容量官方采集器 (SolarCollector)。"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
)
from stock_data.fetcher.industry.models import SolarCapacityRecord
from stock_data.fetcher.industry.power.crawler import NeaBulletinCrawler

logger = logging.getLogger(__name__)


class SolarCollector:
    """国家能源局 (NEA) 光伏装机月度统计采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        if (self.raw_dir / "energy" / "cn_nea").exists():
            self.nea_dir = self.raw_dir / "energy" / "cn_nea"
        elif (self.raw_dir / "cn_nea").exists():
            self.nea_dir = self.raw_dir / "cn_nea"
        elif (self.raw_dir / "nea").exists():
            self.nea_dir = self.raw_dir / "nea"
        else:
            self.nea_dir = self.raw_dir / "energy" / "cn_nea"
        self.crawler = NeaBulletinCrawler(raw_dir=self.raw_dir)

    def collect(self, force: bool = False) -> list[SolarCapacityRecord]:
        """执行光伏装机数据采集: 在线抓取国家能源局通报并落盘，以最新采集为准。"""
        self.nea_dir.mkdir(parents=True, exist_ok=True)
        csv_file = self.nea_dir / "solar_capacity.csv"

        existing_records = self.load_from_raw_csv(csv_file)
        existing_by_month = {r.report_month: r for r in existing_records}

        if not force and existing_records:
            return existing_records

        # 在线抓取国家能源局官网通报
        bulletins = self.crawler.fetch_latest_bulletins()
        if not bulletins and not existing_records:
            logger.warning("在线抓取国家能源局光伏装机通报失败")
            return []

        now_iso = now_utc_iso()
        for m_str, info in bulletins.items():
            cum_gw = info.get("cumulative_gw")
            if cum_gw is None:
                continue
            yr, mo = parse_month_string(m_str)
            t_date = get_month_end_date(yr, mo)
            rel_d = date.fromisoformat(info["release_date"]) if info.get("release_date") else None
            existing_by_month[m_str] = SolarCapacityRecord(
                report_month=m_str,
                trade_date=t_date,
                monthly_new_capacity_gw=0.0,
                cumulative_capacity_gw=float(cum_gw),
                yoy_growth=info.get("yoy_growth"),
                unit="gw",
                source="NEA",
                source_url=info.get("url") or "http://www.nea.gov.cn/",
                release_date=rel_d,
                data_status="actual",
                collected_at=info.get("collected_at") or now_iso,
            )

        if not existing_by_month:
            return []

        # 按月份排序并重新计算差分单月新增
        months_sorted = sorted(existing_by_month.keys())
        records: list[SolarCapacityRecord] = []
        prev_cum: float | None = None

        for m_str in months_sorted:
            r = existing_by_month[m_str]
            cum_gw = r.cumulative_capacity_gw
            yr, mo = parse_month_string(m_str)

            if cum_gw is not None:
                if mo == 1 or prev_cum is None:
                    new_gw = cum_gw if cum_gw < 50 else round(cum_gw * 0.1, 2)
                else:
                    diff = cum_gw - prev_cum
                    new_gw = round(diff, 2) if diff > 0 else 0.0
                prev_cum = cum_gw
            else:
                new_gw = r.monthly_new_capacity_gw

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
                )
            )

        records.sort(key=lambda r: r.trade_date)
        self.save_to_raw_csv(csv_file, records)
        return records

    def save_to_raw_csv(self, file_path: Path | str, records: list[SolarCapacityRecord]) -> None:
        """持久化标准化记录至 RAW CSV 快照。"""
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "report_month",
            "trade_date",
            "monthly_new_capacity_gw",
            "cumulative_capacity_gw",
            "yoy_growth",
            "unit",
            "source",
            "source_url",
            "release_date",
            "data_status",
            "collected_at",
        ]
        with p.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in records:
                writer.writerow(
                    {
                        "report_month": r.report_month,
                        "trade_date": r.trade_date.isoformat(),
                        "monthly_new_capacity_gw": r.monthly_new_capacity_gw,
                        "cumulative_capacity_gw": r.cumulative_capacity_gw
                        if r.cumulative_capacity_gw is not None
                        else "",
                        "yoy_growth": r.yoy_growth if r.yoy_growth is not None else "",
                        "unit": r.unit or "gw",
                        "source": r.source or "NEA",
                        "source_url": r.source_url or "",
                        "release_date": r.release_date.isoformat() if r.release_date else "",
                        "data_status": r.data_status or "actual",
                        "collected_at": r.collected_at or now_utc_iso(),
                    }
                )
        logger.info("已保存 NEA 光伏装机 RAW 快照: %s (共 %d 行)", p, len(records))

    def load_from_raw_csv(self, file_path: Path | str) -> list[SolarCapacityRecord]:
        """从 NEA RAW 快照 CSV 中读取并标准化。"""
        p = Path(file_path)
        if not p.exists():
            return []

        def _safe_float(val: str | None) -> float | None:
            if not val or not val.strip():
                return None
            try:
                return float(val.strip())
            except (ValueError, TypeError):
                return None

        records: list[SolarCapacityRecord] = []
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                month_str = row["report_month"].strip()
                year, month = parse_month_string(month_str)
                t_date = get_month_end_date(year, month)
                records.append(
                    SolarCapacityRecord(
                        report_month=month_str,
                        trade_date=t_date,
                        monthly_new_capacity_gw=float(row["monthly_new_capacity_gw"]),
                        cumulative_capacity_gw=_safe_float(row.get("cumulative_capacity_gw")),
                        yoy_growth=_safe_float(row.get("yoy_growth")),
                        unit=row.get("unit") or "gw",
                        source=row.get("source") or "NEA",
                        source_url=row.get("source_url") or "http://www.nea.gov.cn/",
                        release_date=date.fromisoformat(row["release_date"])
                        if row.get("release_date")
                        else None,
                        data_status=row.get("data_status") or "actual",
                        collected_at=row.get("collected_at") or now_utc_iso(),
                    )
                )
        records.sort(key=lambda r: r.trade_date)
        return records
