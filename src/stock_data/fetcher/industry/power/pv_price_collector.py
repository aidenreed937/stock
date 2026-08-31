"""光伏全产业链 (多晶硅/硅片/电池片/组件) InfoLink 官方周度现货价格采集适配器 (PvPriceChainCollector)。"""

from __future__ import annotations

import csv
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from curl_cffi import requests

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.models import SolarPriceChainRecord

logger = logging.getLogger(__name__)

INFOLINK_SPOT_PRICE_URL = "https://www.infolink-group.com/spot-price/cn/"
INFOLINK_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

PV_PRICE_FIELDNAMES = [
    "report_date",
    "trade_date",
    "polysilicon_price_cny_kg",
    "wafer_price_cny_piece",
    "cell_price_cny_watt",
    "module_price_cny_watt",
    "module_price_yoy",
    "module_price_mom",
    "price_cycle_stage",
    "unit",
    "source",
    "source_url",
    "release_date",
    "data_status",
    "collected_at",
]


def parse_infolink_spot_price_html(html_text: str, source_url: str = "") -> dict[str, Any] | None:
    """从 InfoLink Consulting 官方光伏现货报价页面 HTML 中高精度抽取各环节均价与发布日期。"""
    if "多晶硅" not in html_text and "硅片" not in html_text and "组件" not in html_text:
        return None

    soup = BeautifulSoup(html_text, "html.parser")

    # 1. 解析日期
    trade_d: date | None = None
    rep_date: str | None = None
    curr_yr = date.today().year

    match_range = re.search(r"\((\d{1,2})\.(\d{1,2})-(\d{1,2})\.(\d{1,2})\)", html_text)
    if match_range:
        _, _, m2, d2 = [int(x) for x in match_range.groups()]
        try:
            trade_d = date(curr_yr, m2, d2)
            rep_date = trade_d.isoformat()
        except ValueError:
            pass
    else:
        match_art_date = re.search(r"(20\d\d)[年\-/](\d{1,2})[月\-/](\d{1,2})", html_text)
        if match_art_date:
            y, m, d = [int(x) for x in match_art_date.groups()]
            try:
                trade_d = date(y, m, d)
                rep_date = trade_d.isoformat()
            except ValueError:
                pass

    if trade_d is None or rep_date is None:
        logger.warning("InfoLink 报价页未解析出有效发布日期，放弃本次抓取")
        return None

    results: dict[str, Any] = {
        "report_date": rep_date,
        "trade_date": trade_d,
        "polysilicon_price_cny_kg": None,
        "wafer_price_cny_piece": None,
        "cell_price_cny_watt": None,
        "module_price_cny_watt": None,
        "price_cycle_stage": "bottom_rebound",
        "source": "InfoLink Consulting",
        "source_url": source_url or INFOLINK_SPOT_PRICE_URL,
        "data_status": "actual",
        "collected_at": now_utc_iso(),
    }

    tables = soup.find_all("table")
    for tb in tables:
        rows = tb.find_all("tr")
        for r in rows:
            cells = [td.get_text().strip() for td in r.find_all(["td", "th"])]
            if len(cells) >= 4:
                item_name = cells[0]
                avg_str = cells[3].replace(",", "").strip()
                try:
                    avg_val = float(avg_str)
                except (ValueError, TypeError):
                    continue
                if "多晶硅" in item_name and "致密料" in item_name and "(RMB)" in item_name:
                    results["polysilicon_price_cny_kg"] = avg_val
                elif "硅片" in item_name and "182" in item_name and "(RMB)" in item_name:
                    if results["wafer_price_cny_piece"] is None:
                        results["wafer_price_cny_piece"] = avg_val
                elif (
                    "电池片" in item_name
                    and ("TOPCon" in item_name or "182" in item_name)
                    and "(RMB)" in item_name
                ):
                    if results["cell_price_cny_watt"] is None:
                        results["cell_price_cny_watt"] = avg_val
                elif (
                    "组件" in item_name
                    and ("TOPCon" in item_name or "182" in item_name)
                    and "(RMB)" in item_name
                ):
                    if results["module_price_cny_watt"] is None:
                        results["module_price_cny_watt"] = avg_val

    if (
        results["polysilicon_price_cny_kg"] is None
        and results["wafer_price_cny_piece"] is None
        and results["cell_price_cny_watt"] is None
        and results["module_price_cny_watt"] is None
    ):
        return None

    return results


def load_pv_price_raw_csv(file_path: Path | str) -> list[SolarPriceChainRecord]:
    """从 RAW CSV 文件读取并标准化记录。"""
    p = Path(file_path)
    if not p.exists():
        return []

    def _safe_float(val: str | None) -> float | None:
        if not val or not str(val).strip() or str(val).strip() in ("nan", "None", ""):
            return None
        try:
            return float(str(val).strip())
        except (ValueError, TypeError):
            return None

    records: list[SolarPriceChainRecord] = []
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
                SolarPriceChainRecord(
                    report_date=rep_date_str,
                    trade_date=t_date,
                    polysilicon_price_cny_kg=_safe_float(row.get("polysilicon_price_cny_kg")),
                    wafer_price_cny_piece=_safe_float(row.get("wafer_price_cny_piece")),
                    cell_price_cny_watt=_safe_float(row.get("cell_price_cny_watt")),
                    module_price_cny_watt=_safe_float(row.get("module_price_cny_watt")),
                    module_price_yoy=_safe_float(row.get("module_price_yoy")),
                    module_price_mom=_safe_float(row.get("module_price_mom")),
                    price_cycle_stage=row.get("price_cycle_stage") or "bottom_rebound",
                    unit=row.get("unit") or "cny_per_unit",
                    source=row.get("source") or "InfoLink Consulting",
                    source_url=row.get("source_url") or INFOLINK_SPOT_PRICE_URL,
                    release_date=rel_d,
                    data_status=row.get("data_status") or "actual",
                    collected_at=row.get("collected_at") or now_utc_iso(),
                )
            )

    records.sort(key=lambda r: r.trade_date)
    return records


def save_pv_price_raw_csv(file_path: Path | str, records: list[SolarPriceChainRecord]) -> None:
    """持久化标准化记录至 RAW CSV 快照。"""
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PV_PRICE_FIELDNAMES)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "report_date": r.report_date,
                    "trade_date": r.trade_date.isoformat(),
                    "polysilicon_price_cny_kg": r.polysilicon_price_cny_kg
                    if r.polysilicon_price_cny_kg is not None
                    else "",
                    "wafer_price_cny_piece": r.wafer_price_cny_piece
                    if r.wafer_price_cny_piece is not None
                    else "",
                    "cell_price_cny_watt": r.cell_price_cny_watt
                    if r.cell_price_cny_watt is not None
                    else "",
                    "module_price_cny_watt": r.module_price_cny_watt
                    if r.module_price_cny_watt is not None
                    else "",
                    "module_price_yoy": r.module_price_yoy
                    if r.module_price_yoy is not None
                    else "",
                    "module_price_mom": r.module_price_mom
                    if r.module_price_mom is not None
                    else "",
                    "price_cycle_stage": r.price_cycle_stage or "bottom_rebound",
                    "unit": r.unit or "cny_per_unit",
                    "source": r.source or "InfoLink Consulting",
                    "source_url": r.source_url or INFOLINK_SPOT_PRICE_URL,
                    "release_date": r.release_date.isoformat() if r.release_date else "",
                    "data_status": r.data_status or "actual",
                    "collected_at": r.collected_at or now_utc_iso(),
                }
            )


def compute_pv_price_derivatives(
    records: list[SolarPriceChainRecord],
) -> list[SolarPriceChainRecord]:
    """计算组件价格周环比与52周同比派生特征。"""
    updated: list[SolarPriceChainRecord] = []
    for i, rec in enumerate(records):
        mom: float | None = None
        if (
            i > 0
            and records[i - 1].module_price_cny_watt is not None
            and rec.module_price_cny_watt is not None
        ):
            prev_p = records[i - 1].module_price_cny_watt
            if prev_p and prev_p > 0:
                mom = round((rec.module_price_cny_watt - prev_p) / prev_p, 4)

        yoy: float | None = None
        if (
            i >= 52
            and records[i - 52].module_price_cny_watt is not None
            and rec.module_price_cny_watt is not None
        ):
            prev_y_p = records[i - 52].module_price_cny_watt
            if prev_y_p and prev_y_p > 0:
                yoy = round((rec.module_price_cny_watt - prev_y_p) / prev_y_p, 4)

        updated.append(
            SolarPriceChainRecord(
                report_date=rec.report_date,
                trade_date=rec.trade_date,
                polysilicon_price_cny_kg=rec.polysilicon_price_cny_kg,
                wafer_price_cny_piece=rec.wafer_price_cny_piece,
                cell_price_cny_watt=rec.cell_price_cny_watt,
                module_price_cny_watt=rec.module_price_cny_watt,
                module_price_yoy=yoy,
                module_price_mom=mom,
                price_cycle_stage=rec.price_cycle_stage,
                unit=rec.unit,
                source=rec.source,
                source_url=rec.source_url,
                release_date=rec.release_date,
                data_status=rec.data_status,
                collected_at=rec.collected_at,
            )
        )
    return updated


class InfoLinkPvPriceCrawler:
    """InfoLink Consulting 官方光伏现货价格周度在线爬虫。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.energy_dir = self.raw_dir / "energy"

    def fetch_live_spot_prices(self) -> dict[str, Any] | None:
        """从 InfoLink 官方发布页抓取最新周度现货报价。"""
        self.energy_dir.mkdir(parents=True, exist_ok=True)
        try:
            logger.info("正在在线抓取 InfoLink 官方光伏现货价格发布页: %s", INFOLINK_SPOT_PRICE_URL)
            resp = requests.get(
                INFOLINK_SPOT_PRICE_URL,
                headers=INFOLINK_HEADERS,
                impersonate="chrome120",
                timeout=15,
            )
            if resp.status_code != 200:
                logger.warning("访问 InfoLink 返回 HTTP %d", resp.status_code)
                return None

            html_text = resp.text
            parsed = parse_infolink_spot_price_html(html_text, INFOLINK_SPOT_PRICE_URL)
            if parsed:
                snapshot_file = self.energy_dir / "infolink_live_spot_price.html"
                try:
                    snapshot_file.write_text(html_text, encoding="utf-8")
                except Exception as e:
                    logger.debug("保存 InfoLink 快照失败: %s", e)
                return parsed
        except Exception as e:
            logger.warning("在线抓取 InfoLink 价格异常: %s", e)

        return None


class PvPriceChainCollector:
    """光伏产业链各环节周度真实价格与拐点采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.energy_raw_dir = self.raw_dir / "energy"
        self.crawler = InfoLinkPvPriceCrawler(raw_dir=self.raw_dir)

    def collect(self) -> list[SolarPriceChainRecord]:
        """执行光伏价格链条采集: 在线抓取 InfoLink 最新周度价格并落盘，以最新采集为准。"""
        self.energy_raw_dir.mkdir(parents=True, exist_ok=True)
        csv_file = self.energy_raw_dir / "pv_price_chain_weekly.csv"

        # 在线抓取 InfoLink 最新周度现货价格
        live_data = self.crawler.fetch_live_spot_prices()
        if not live_data or not live_data.get("report_date"):
            logger.warning("在线抓取 InfoLink 光伏现货价格失败")
            return []

        d_key = str(live_data["report_date"])
        rec_live = SolarPriceChainRecord(
            report_date=d_key,
            trade_date=live_data["trade_date"],
            polysilicon_price_cny_kg=live_data["polysilicon_price_cny_kg"],
            wafer_price_cny_piece=live_data["wafer_price_cny_piece"],
            cell_price_cny_watt=live_data["cell_price_cny_watt"],
            module_price_cny_watt=live_data["module_price_cny_watt"],
            module_price_yoy=None,
            module_price_mom=None,
            price_cycle_stage=live_data.get("price_cycle_stage") or "bottom_rebound",
            unit="cny_per_unit",
            source=live_data.get("source") or "InfoLink Consulting",
            source_url=live_data.get("source_url") or INFOLINK_SPOT_PRICE_URL,
            release_date=live_data["trade_date"],
            data_status="actual",
            collected_at=live_data.get("collected_at") or now_utc_iso(),
        )

        records = [rec_live]
        self.save_to_raw_csv(csv_file, records)
        return records

    def save_to_raw_csv(self, file_path: Path | str, records: list[SolarPriceChainRecord]) -> None:
        """持久化标准化记录至 RAW CSV 快照。"""
        save_pv_price_raw_csv(file_path, records)

    def load_from_raw_csv(self, file_path: Path | str) -> list[SolarPriceChainRecord]:
        """从 RAW CSV 文件读取并标准化记录。"""
        return load_pv_price_raw_csv(file_path)
