"""高端名优白酒 (飞天茅台/五粮液/国窖1573) 周度一批价采集器 (LiquorWholesaleCollector)。"""

from __future__ import annotations

import csv
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

from curl_cffi import requests

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.models import LiquorWholesaleRecord

logger = logging.getLogger(__name__)

LIQUOR_PRICE_FIELDNAMES = [
    "report_date",
    "trade_date",
    "moutai_loose_price_cny",
    "moutai_boxed_price_cny",
    "wuliangye_puwu_price_cny",
    "guojiao1573_price_cny",
    "moutai_loose_price_yoy",
    "moutai_loose_price_mom",
    "unit",
    "source",
    "source_url",
    "release_date",
    "data_status",
    "collected_at",
]

JINRIJIA_URL = "https://www.jinrijia.com/"


def parse_liquor_price_text(text: str) -> dict[str, Any] | None:
    """从白酒批价通报文本中高精度提取茅五泸核心批价。"""
    clean_text = text.replace(" ", "").replace("\t", "")

    # 1. 散瓶与原箱茅台批价 (飞天 53度 500ml)
    m_loose = re.search(r"(?:散瓶|散飞|飞天散)[^\d]*(\d{4})", clean_text)
    m_boxed = re.search(r"(?:原箱|原箱飞天|整箱)[^\d]*(\d{4})", clean_text)
    m_wly = re.search(r"(?:普五|第八代五粮液|五粮液)[^\d]*(\d{3,4})", clean_text)
    m_gj = re.search(r"(?:国窖1573|国窖)[^\d]*(\d{3,4})", clean_text)

    loose_p = float(m_loose.group(1)) if m_loose else None
    boxed_p = float(m_boxed.group(1)) if m_boxed else None
    wly_p = float(m_wly.group(1)) if m_wly else None
    gj_p = float(m_gj.group(1)) if m_gj else None

    if loose_p is None and wly_p is None:
        return None

    return {
        "moutai_loose_price_cny": loose_p,
        "moutai_boxed_price_cny": boxed_p,
        "wuliangye_puwu_price_cny": wly_p,
        "guojiao1573_price_cny": gj_p,
        "source": "TodayLiquorPrice",
        "source_url": JINRIJIA_URL,
        "data_status": "actual",
        "collected_at": now_utc_iso(),
    }


class LiquorPriceCrawler:
    """白酒行业渠道批发参考价轻量在线采集器。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.consumer_dir = self.raw_dir / "consumer"

    def fetch_latest_liquor_price(self) -> dict[str, Any] | None:
        """在线抓取白酒最新批价快照。"""
        self.consumer_dir.mkdir(parents=True, exist_ok=True)
        try:
            logger.info("正在抓取白酒批发参考价发布源: %s", JINRIJIA_URL)
            resp = requests.get(
                JINRIJIA_URL,
                headers={"User-Agent": "Mozilla/5.0"},
                impersonate="chrome120",
                timeout=12,
            )
            if resp.status_code == 200:
                parsed = parse_liquor_price_text(resp.text)
                if parsed:
                    parsed["report_date"] = date.today().isoformat()
                    parsed["trade_date"] = date.today()
                    parsed["release_date"] = date.today()
                    return parsed
        except Exception as e:
            logger.debug("抓取白酒批价异常: %s", e)

        return None


def save_liquor_raw_csv(file_path: Path | str, records: list[LiquorWholesaleRecord]) -> None:
    """持久化标准化记录至 RAW CSV 快照。"""
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LIQUOR_PRICE_FIELDNAMES)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "report_date": r.report_date,
                    "trade_date": r.trade_date.isoformat(),
                    "moutai_loose_price_cny": r.moutai_loose_price_cny
                    if r.moutai_loose_price_cny is not None
                    else "",
                    "moutai_boxed_price_cny": r.moutai_boxed_price_cny
                    if r.moutai_boxed_price_cny is not None
                    else "",
                    "wuliangye_puwu_price_cny": r.wuliangye_puwu_price_cny
                    if r.wuliangye_puwu_price_cny is not None
                    else "",
                    "guojiao1573_price_cny": r.guojiao1573_price_cny
                    if r.guojiao1573_price_cny is not None
                    else "",
                    "moutai_loose_price_yoy": r.moutai_loose_price_yoy
                    if r.moutai_loose_price_yoy is not None
                    else "",
                    "moutai_loose_price_mom": r.moutai_loose_price_mom
                    if r.moutai_loose_price_mom is not None
                    else "",
                    "unit": r.unit or "cny_per_bottle",
                    "source": r.source or "TodayLiquorPrice",
                    "source_url": r.source_url or "",
                    "release_date": r.release_date.isoformat() if r.release_date else "",
                    "data_status": r.data_status or "actual",
                    "collected_at": r.collected_at or now_utc_iso(),
                }
            )


def load_liquor_raw_csv(file_path: Path | str) -> list[LiquorWholesaleRecord]:
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

    records: list[LiquorWholesaleRecord] = []
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
                LiquorWholesaleRecord(
                    report_date=rep_date_str,
                    trade_date=t_date,
                    moutai_loose_price_cny=_safe_float(row.get("moutai_loose_price_cny")),
                    moutai_boxed_price_cny=_safe_float(row.get("moutai_boxed_price_cny")),
                    wuliangye_puwu_price_cny=_safe_float(row.get("wuliangye_puwu_price_cny")),
                    guojiao1573_price_cny=_safe_float(row.get("guojiao1573_price_cny")),
                    moutai_loose_price_yoy=_safe_float(row.get("moutai_loose_price_yoy")),
                    moutai_loose_price_mom=_safe_float(row.get("moutai_loose_price_mom")),
                    unit=row.get("unit") or "cny_per_bottle",
                    source=row.get("source") or "TodayLiquorPrice",
                    source_url=row.get("source_url") or "",
                    release_date=rel_d,
                    data_status=row.get("data_status") or "actual",
                    collected_at=row.get("collected_at") or now_utc_iso(),
                )
            )

    records.sort(key=lambda r: r.trade_date)
    return records


def compute_liquor_price_derivatives(
    records: list[LiquorWholesaleRecord],
) -> list[LiquorWholesaleRecord]:
    """计算飞天茅台散瓶批价的 4周环比与 52周同比特征。"""
    updated: list[LiquorWholesaleRecord] = []
    for i, rec in enumerate(records):
        mom: float | None = None
        if (
            i >= 4
            and records[i - 4].moutai_loose_price_cny is not None
            and rec.moutai_loose_price_cny is not None
        ):
            prev_p = records[i - 4].moutai_loose_price_cny
            if prev_p and prev_p > 0:
                mom = round((rec.moutai_loose_price_cny - prev_p) / prev_p, 4)

        yoy: float | None = None
        if (
            i >= 52
            and records[i - 52].moutai_loose_price_cny is not None
            and rec.moutai_loose_price_cny is not None
        ):
            prev_y_p = records[i - 52].moutai_loose_price_cny
            if prev_y_p and prev_y_p > 0:
                yoy = round((rec.moutai_loose_price_cny - prev_y_p) / prev_y_p, 4)

        updated.append(
            LiquorWholesaleRecord(
                report_date=rec.report_date,
                trade_date=rec.trade_date,
                moutai_loose_price_cny=rec.moutai_loose_price_cny,
                moutai_boxed_price_cny=rec.moutai_boxed_price_cny,
                wuliangye_puwu_price_cny=rec.wuliangye_puwu_price_cny,
                guojiao1573_price_cny=rec.guojiao1573_price_cny,
                moutai_loose_price_yoy=yoy,
                moutai_loose_price_mom=mom,
                unit=rec.unit,
                source=rec.source,
                source_url=rec.source_url,
                release_date=rec.release_date,
                data_status=rec.data_status,
                collected_at=rec.collected_at,
            )
        )
    return updated


class LiquorWholesaleCollector:
    """高端白酒周度渠道一批价与动销采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.consumer_raw_dir = self.raw_dir / "consumer"
        self.crawler = LiquorPriceCrawler(raw_dir=self.raw_dir)

    def collect(self) -> list[LiquorWholesaleRecord]:
        """执行白酒一批价采集: 在线抓取最新周度批价并落盘，以最新采集为准。"""
        self.consumer_raw_dir.mkdir(parents=True, exist_ok=True)
        csv_file = self.consumer_raw_dir / "liquor_wholesale_weekly.csv"

        # 在线抓取最新白酒批价
        live_data = self.crawler.fetch_latest_liquor_price()
        if not live_data or not live_data.get("report_date"):
            logger.warning("在线抓取白酒批价失败")
            return []

        d_key = str(live_data["report_date"])
        rec_live = LiquorWholesaleRecord(
            report_date=d_key,
            trade_date=live_data["trade_date"],
            moutai_loose_price_cny=live_data.get("moutai_loose_price_cny"),
            moutai_boxed_price_cny=live_data.get("moutai_boxed_price_cny"),
            wuliangye_puwu_price_cny=live_data.get("wuliangye_puwu_price_cny"),
            guojiao1573_price_cny=live_data.get("guojiao1573_price_cny"),
            moutai_loose_price_yoy=None,
            moutai_loose_price_mom=None,
            unit="cny_per_bottle",
            source=live_data.get("source") or "TodayLiquorPrice",
            source_url=live_data.get("source_url") or JINRIJIA_URL,
            release_date=live_data.get("release_date"),
            data_status="actual",
            collected_at=live_data.get("collected_at") or now_utc_iso(),
        )

        records = [rec_live]
        self.save_to_raw_csv(csv_file, records)
        return records

    def save_to_raw_csv(self, file_path: Path | str, records: list[LiquorWholesaleRecord]) -> None:
        """持久化标准化记录至 RAW CSV 快照。"""
        save_liquor_raw_csv(file_path, records)

    def load_from_raw_csv(self, file_path: Path | str) -> list[LiquorWholesaleRecord]:
        """从 RAW CSV 文件读取并标准化记录。"""
        return load_liquor_raw_csv(file_path)
