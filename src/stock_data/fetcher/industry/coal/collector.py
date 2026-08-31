"""煤炭行业动力煤平仓价与重点电厂日耗库存采集器 (CoalMarketCollector)。"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.coal.crawler import CoalMarketCrawler
from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.models import CoalMarketRecord

logger = logging.getLogger(__name__)

COAL_CSV_FIELDNAMES = [
    "report_date",
    "trade_date",
    "q5500_fob_price_cny",
    "coking_coal_price_cny",
    "power_plant_inventory_million_ton",
    "power_plant_daily_burn_ten_thousand_ton",
    "power_plant_available_days",
    "qinhuangdao_inventory_million_ton",
    "q5500_price_yoy",
    "q5500_price_mom",
    "unit",
    "source",
    "source_url",
    "release_date",
    "data_status",
    "collected_at",
]


def save_coal_raw_csv(file_path: Path | str, records: list[CoalMarketRecord]) -> None:
    """持久化标准化记录至 RAW CSV 快照。"""
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COAL_CSV_FIELDNAMES)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "report_date": r.report_date,
                    "trade_date": r.trade_date.isoformat(),
                    "q5500_fob_price_cny": r.q5500_fob_price_cny
                    if r.q5500_fob_price_cny is not None
                    else "",
                    "coking_coal_price_cny": r.coking_coal_price_cny
                    if r.coking_coal_price_cny is not None
                    else "",
                    "power_plant_inventory_million_ton": r.power_plant_inventory_million_ton
                    if r.power_plant_inventory_million_ton is not None
                    else "",
                    "power_plant_daily_burn_ten_thousand_ton": r.power_plant_daily_burn_ten_thousand_ton
                    if r.power_plant_daily_burn_ten_thousand_ton is not None
                    else "",
                    "power_plant_available_days": r.power_plant_available_days
                    if r.power_plant_available_days is not None
                    else "",
                    "qinhuangdao_inventory_million_ton": r.qinhuangdao_inventory_million_ton
                    if r.qinhuangdao_inventory_million_ton is not None
                    else "",
                    "q5500_price_yoy": r.q5500_price_yoy if r.q5500_price_yoy is not None else "",
                    "q5500_price_mom": r.q5500_price_mom if r.q5500_price_mom is not None else "",
                    "unit": r.unit or "cny_per_ton/million_tons/days",
                    "source": r.source or "CCTD/Sxcoal",
                    "source_url": r.source_url or "https://www.cctd.com.cn/",
                    "release_date": r.release_date.isoformat() if r.release_date else "",
                    "data_status": r.data_status or "actual",
                    "collected_at": r.collected_at or now_utc_iso(),
                }
            )


def load_coal_raw_csv(file_path: Path | str) -> list[CoalMarketRecord]:
    """从 RAW CSV 文件读取并标准化记录。"""
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

    records: list[CoalMarketRecord] = []
    with p.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rep_date_str = row["report_date"].strip()
            t_date = date.fromisoformat(row["trade_date"].strip() or rep_date_str)
            rel_d = None
            if row.get("release_date"):
                try:
                    rel_d = date.fromisoformat(row["release_date"].strip())
                except ValueError:
                    pass

            records.append(
                CoalMarketRecord(
                    report_date=rep_date_str,
                    trade_date=t_date,
                    q5500_fob_price_cny=_safe_float(row.get("q5500_fob_price_cny")),
                    coking_coal_price_cny=_safe_float(row.get("coking_coal_price_cny")),
                    power_plant_inventory_million_ton=_safe_float(
                        row.get("power_plant_inventory_million_ton")
                    ),
                    power_plant_daily_burn_ten_thousand_ton=_safe_float(
                        row.get("power_plant_daily_burn_ten_thousand_ton")
                    ),
                    power_plant_available_days=_safe_float(row.get("power_plant_available_days")),
                    qinhuangdao_inventory_million_ton=_safe_float(
                        row.get("qinhuangdao_inventory_million_ton")
                    ),
                    q5500_price_yoy=_safe_float(row.get("q5500_price_yoy")),
                    q5500_price_mom=_safe_float(row.get("q5500_price_mom")),
                    unit=row.get("unit") or "cny_per_ton/million_tons/days",
                    source=row.get("source") or "CCTD/Sxcoal",
                    source_url=row.get("source_url") or "https://www.cctd.com.cn/",
                    release_date=rel_d,
                    data_status=row.get("data_status") or "actual",
                    collected_at=row.get("collected_at") or now_utc_iso(),
                )
            )

    records.sort(key=lambda r: r.trade_date)
    return records


def compute_coal_price_derivatives(
    records: list[CoalMarketRecord],
) -> list[CoalMarketRecord]:
    """计算动力煤平仓价 4周环比与 52周同比特征。"""
    updated: list[CoalMarketRecord] = []
    for i, rec in enumerate(records):
        mom: float | None = None
        if (
            i >= 4
            and records[i - 4].q5500_fob_price_cny is not None
            and rec.q5500_fob_price_cny is not None
        ):
            prev_p = records[i - 4].q5500_fob_price_cny
            if prev_p and prev_p > 0:
                mom = round((rec.q5500_fob_price_cny - prev_p) / prev_p, 4)

        yoy: float | None = None
        if (
            i >= 52
            and records[i - 52].q5500_fob_price_cny is not None
            and rec.q5500_fob_price_cny is not None
        ):
            prev_y_p = records[i - 52].q5500_fob_price_cny
            if prev_y_p and prev_y_p > 0:
                yoy = round((rec.q5500_fob_price_cny - prev_y_p) / prev_y_p, 4)

        updated.append(
            CoalMarketRecord(
                report_date=rec.report_date,
                trade_date=rec.trade_date,
                q5500_fob_price_cny=rec.q5500_fob_price_cny,
                coking_coal_price_cny=rec.coking_coal_price_cny,
                power_plant_inventory_million_ton=rec.power_plant_inventory_million_ton,
                power_plant_daily_burn_ten_thousand_ton=rec.power_plant_daily_burn_ten_thousand_ton,
                power_plant_available_days=rec.power_plant_available_days,
                qinhuangdao_inventory_million_ton=rec.qinhuangdao_inventory_million_ton,
                q5500_price_yoy=yoy,
                q5500_price_mom=mom,
                unit=rec.unit,
                source=rec.source,
                source_url=rec.source_url,
                release_date=rec.release_date,
                data_status=rec.data_status,
                collected_at=rec.collected_at,
            )
        )
    return updated


class CoalMarketCollector:
    """煤炭行业动力煤平仓价与电厂库存日耗采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        if (self.raw_dir / "energy").exists():
            self.coal_raw_dir = self.raw_dir / "energy"
        elif (self.raw_dir / "coal").exists():
            self.coal_raw_dir = self.raw_dir / "coal"
        else:
            self.coal_raw_dir = self.raw_dir / "energy"
        self.crawler = CoalMarketCrawler(raw_dir=self.raw_dir)

    def collect(self, force: bool = False) -> list[CoalMarketRecord]:
        """执行煤炭数据采集: 抓取 CCTD 最新 Q5500 平仓价并落盘，以最新采集为准。"""
        self.coal_raw_dir.mkdir(parents=True, exist_ok=True)
        csv_file = self.coal_raw_dir / "coal_market_weekly.csv"
        if not csv_file.exists():
            for cand in [
                self.raw_dir / "coal" / "coal_market_weekly.csv",
                self.raw_dir / "energy" / "coal_market_weekly.csv",
            ]:
                if cand.exists():
                    csv_file = cand
                    break

        # 在线/本地快照抓取 CCTD 最新一期 Q5500 平仓价
        live_data = self.crawler.fetch_latest_q5500(force=force)
        if not live_data or not live_data.get("report_date"):
            logger.warning("在线抓取 CCTD Q5500 平仓价失败")
            return []

        d_key = str(live_data["report_date"])
        try:
            t_date = date.fromisoformat(d_key)
        except ValueError:
            t_date = date.today()
        rec_live = CoalMarketRecord(
            report_date=d_key,
            trade_date=t_date,
            q5500_fob_price_cny=live_data.get("q5500_fob_price_cny"),
            coking_coal_price_cny=None,
            power_plant_inventory_million_ton=None,
            power_plant_daily_burn_ten_thousand_ton=None,
            power_plant_available_days=None,
            qinhuangdao_inventory_million_ton=None,
            q5500_price_yoy=None,
            q5500_price_mom=None,
            unit="cny_per_ton/million_tons/days",
            source=live_data.get("source") or "CCTD",
            source_url=live_data.get("source_url") or "https://www.cctd.com.cn/",
            release_date=date.fromisoformat(live_data["release_date"])
            if live_data.get("release_date")
            else None,
            data_status=live_data.get("data_status") or "actual",
            collected_at=live_data.get("collected_at") or now_utc_iso(),
        )

        records = [rec_live]
        self.save_to_raw_csv(csv_file, records)
        return records

    def save_to_raw_csv(self, file_path: Path | str, records: list[CoalMarketRecord]) -> None:
        """持久化标准化记录至 RAW CSV 快照。"""
        save_coal_raw_csv(file_path, records)

    def load_from_raw_csv(self, file_path: Path | str) -> list[CoalMarketRecord]:
        """从 RAW CSV 文件读取并标准化记录。"""
        return load_coal_raw_csv(file_path)
