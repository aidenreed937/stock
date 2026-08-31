"""有色大宗金属价格与显性库存采集器 (NonFerrousCollector)。"""

import csv
import logging
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.models import NonFerrousMetalsRecord

logger = logging.getLogger(__name__)

METALS_CSV_FIELDNAMES = [
    "report_date",
    "trade_date",
    "lithium_carbonate_price",
    "shfe_copper_price",
    "shfe_aluminum_price",
    "sge_gold_price",
    "copper_inventory_ton",
    "unit",
    "source",
    "source_url",
    "release_date",
    "data_status",
    "collected_at",
]


def save_metals_raw_csv(records: list[NonFerrousMetalsRecord], path: Path) -> None:
    """持久化 RAW 快照 CSV。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=METALS_CSV_FIELDNAMES)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "report_date": r.report_date,
                    "trade_date": r.trade_date.isoformat(),
                    "lithium_carbonate_price": r.lithium_carbonate_price
                    if r.lithium_carbonate_price is not None
                    else "",
                    "shfe_copper_price": r.shfe_copper_price
                    if r.shfe_copper_price is not None
                    else "",
                    "shfe_aluminum_price": r.shfe_aluminum_price
                    if r.shfe_aluminum_price is not None
                    else "",
                    "sge_gold_price": r.sge_gold_price if r.sge_gold_price is not None else "",
                    "copper_inventory_ton": r.copper_inventory_ton
                    if r.copper_inventory_ton is not None
                    else "",
                    "unit": r.unit,
                    "source": r.source,
                    "source_url": r.source_url,
                    "release_date": r.release_date.isoformat() if r.release_date else "",
                    "data_status": r.data_status,
                    "collected_at": r.collected_at,
                }
            )
    logger.info("已保存真实有色大宗 RAW 快照: %s (共 %d 行)", path, len(records))


def load_metals_raw_csv(file_path: Path | str) -> list[NonFerrousMetalsRecord]:
    """从 RAW 快照 CSV 中读取并标准化。"""
    p = Path(file_path)
    if not p.exists():
        return []

    records: list[NonFerrousMetalsRecord] = []
    with p.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            r_date_str = row["report_date"].strip()
            t_date = date.fromisoformat(
                row["trade_date"].strip() if row.get("trade_date") else r_date_str
            )
            records.append(
                NonFerrousMetalsRecord(
                    report_date=r_date_str,
                    trade_date=t_date,
                    lithium_carbonate_price=float(row["lithium_carbonate_price"])
                    if row.get("lithium_carbonate_price")
                    else None,
                    shfe_copper_price=float(row["shfe_copper_price"])
                    if row.get("shfe_copper_price")
                    else None,
                    shfe_aluminum_price=float(row["shfe_aluminum_price"])
                    if row.get("shfe_aluminum_price")
                    else None,
                    sge_gold_price=float(row["sge_gold_price"])
                    if row.get("sge_gold_price")
                    else None,
                    copper_inventory_ton=float(row["copper_inventory_ton"])
                    if row.get("copper_inventory_ton")
                    else None,
                    unit=row.get("unit") or "mixed",
                    source=row.get("source") or "AkShare",
                    source_url=row.get("source_url") or "",
                    release_date=date.fromisoformat(row["release_date"].strip())
                    if row.get("release_date")
                    else t_date,
                    data_status=row.get("data_status") or "actual",
                    collected_at=row.get("collected_at") or now_utc_iso(),
                )
            )
    records.sort(key=lambda r: r.trade_date)
    return records


def fetch_akshare_metals_data() -> list[NonFerrousMetalsRecord]:
    """通过 AkShare 接口在线抓取有色大宗核心期货、现货与库存数据。"""
    try:
        import akshare as ak
    except ImportError:
        logger.warning("未安装 akshare，跳过在线抓取")
        return []

    logger.info("开始通过 AkShare 在线抓取有色大宗核心期货与库存行情...")
    merged: dict[str, dict[str, float | None]] = {}

    # 1. 上期所铜期货主力 (CU0)
    try:
        df_cu = ak.futures_main_sina(symbol="CU0")
        if df_cu is not None and not df_cu.empty:
            d_col = "日期" if "日期" in df_cu.columns else "date"
            c_col = "收盘价" if "收盘价" in df_cu.columns else "close"
            for _, row in df_cu.iterrows():
                d_str = str(row[d_col]).split(" ")[0].replace("/", "-")
                merged.setdefault(d_str, {})["shfe_copper_price"] = float(row[c_col])
    except Exception as exc:
        logger.warning("AkShare 抓取沪铜主力 CU0 异常: %s", exc)

    # 2. 上期所铝期货主力 (AL0)
    try:
        df_al = ak.futures_main_sina(symbol="AL0")
        if df_al is not None and not df_al.empty:
            d_col = "日期" if "日期" in df_al.columns else "date"
            c_col = "收盘价" if "收盘价" in df_al.columns else "close"
            for _, row in df_al.iterrows():
                d_str = str(row[d_col]).split(" ")[0].replace("/", "-")
                merged.setdefault(d_str, {})["shfe_aluminum_price"] = float(row[c_col])
    except Exception as exc:
        logger.warning("AkShare 抓取沪铝主力 AL0 异常: %s", exc)

    # 3. 广期所碳酸锂期货主力 (LC0)
    try:
        df_lc = ak.futures_main_sina(symbol="LC0")
        if df_lc is not None and not df_lc.empty:
            d_col = "日期" if "日期" in df_lc.columns else "date"
            c_col = "收盘价" if "收盘价" in df_lc.columns else "close"
            for _, row in df_lc.iterrows():
                d_str = str(row[d_col]).split(" ")[0].replace("/", "-")
                merged.setdefault(d_str, {})["lithium_carbonate_price"] = float(row[c_col])
    except Exception as exc:
        logger.warning("AkShare 抓取碳酸锂主力 LC0 异常: %s", exc)

    # 4. 上海黄金交易所现货 (Au99.99)
    try:
        df_sge = ak.spot_hist_sge(symbol="Au99.99")
        if df_sge is not None and not df_sge.empty:
            d_col = "date" if "date" in df_sge.columns else "日期"
            c_col = "close" if "close" in df_sge.columns else "收盘价"
            for _, row in df_sge.iterrows():
                d_str = str(row[d_col]).split(" ")[0].replace("/", "-")
                merged.setdefault(d_str, {})["sge_gold_price"] = float(row[c_col])
    except Exception as exc:
        logger.warning("AkShare 抓取上海金 Au99.99 异常: %s", exc)

    # 5. 上期所铜显性库存 (沪铜)
    try:
        df_inv = ak.futures_inventory_em(symbol="沪铜")
        if df_inv is not None and not df_inv.empty:
            date_col = (
                "日期"
                if "日期" in df_inv.columns
                else ("TRADE_DATE" if "TRADE_DATE" in df_inv.columns else df_inv.columns[0])
            )
            inv_col = (
                "库存"
                if "库存" in df_inv.columns
                else ("ON_WARRANT_NUM" if "ON_WARRANT_NUM" in df_inv.columns else df_inv.columns[1])
            )
            for _, row in df_inv.iterrows():
                d_str = str(row[date_col]).split(" ")[0].replace("/", "-")
                merged.setdefault(d_str, {})["copper_inventory_ton"] = float(row[inv_col])
    except Exception as exc:
        logger.warning("AkShare 抓取沪铜库存异常: %s", exc)

    if not merged:
        return []

    now_iso = now_utc_iso()
    records: list[NonFerrousMetalsRecord] = []
    for d_str in sorted(merged.keys()):
        try:
            t_date = date.fromisoformat(d_str)
        except ValueError:
            continue
        item = merged[d_str]
        records.append(
            NonFerrousMetalsRecord(
                report_date=d_str,
                trade_date=t_date,
                lithium_carbonate_price=item.get("lithium_carbonate_price"),
                shfe_copper_price=item.get("shfe_copper_price"),
                shfe_aluminum_price=item.get("shfe_aluminum_price"),
                sge_gold_price=item.get("sge_gold_price"),
                copper_inventory_ton=item.get("copper_inventory_ton"),
                unit="mixed",
                source="AkShare",
                source_url="https://akshare.akfamily.xyz/",
                release_date=t_date,
                data_status="actual",
                collected_at=now_iso,
            )
        )

    return records


class NonFerrousCollector:
    """有色大宗金属 (碳酸锂/铜/铝/金/库存) 采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.metals_dir = self.raw_dir / "metals"

    def collect(self) -> list[NonFerrousMetalsRecord]:
        """执行有色大宗数据采集: 在线抓取 AkShare 最新真实行情并落盘，以最新采集为准。"""
        self.metals_dir.mkdir(parents=True, exist_ok=True)
        live_records = self.fetch_from_akshare()
        if not live_records:
            logger.warning("在线抓取有色金属行情失败")
        return live_records

    def _save_raw_csv(self, records: list[NonFerrousMetalsRecord], path: Path) -> None:
        """持久化 RAW 快照 CSV。"""
        save_metals_raw_csv(records, path)

    def load_from_raw_csv(self, file_path: Path | str) -> list[NonFerrousMetalsRecord]:
        """从 RAW 快照 CSV 中读取并标准化。"""
        return load_metals_raw_csv(file_path)

    def fetch_from_akshare(self) -> list[NonFerrousMetalsRecord]:
        """通过 AkShare 接口在线抓取有色大宗核心期货、现货与库存数据。"""
        records = fetch_akshare_metals_data()
        if records:
            self._save_raw_csv(records, self.metals_dir / "commodity_prices.csv")
        return records
