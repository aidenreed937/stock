"""AkShare 有色金属行情采集器。"""

import logging
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.metals.models import NonFerrousMetalsRecord
from stock_data.fetcher.industry.metals.parsers import save_metals_raw_csv

logger = logging.getLogger(__name__)


def fetch_akshare_metals_data() -> list[NonFerrousMetalsRecord]:
    """通过 AkShare 接口在线抓取有色大宗核心期货、现货与库存数据。"""
    try:
        import akshare as ak
    except ImportError:
        logger.warning("未安装 akshare，跳过在线抓取")
        return []

    logger.info("开始通过 AkShare 在线抓取有色大宗核心期货与库存行情...")
    merged: dict[str, dict[str, float | None]] = {}

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
    """有色大宗金属采集适配器。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.metals_dir = self.raw_dir / "metals"

    def collect(self) -> list[NonFerrousMetalsRecord]:
        """执行有色大宗数据采集: 在线抓取 AkShare 最新真实行情并落盘。"""
        self.metals_dir.mkdir(parents=True, exist_ok=True)
        live_records = self.fetch_from_akshare()
        if not live_records:
            logger.warning("在线抓取有色金属行情失败")
        return live_records

    def _save_raw_csv(self, records: list[NonFerrousMetalsRecord], path: Path) -> None:
        """持久化 RAW 快照 CSV。"""
        save_metals_raw_csv(records, path)

    def fetch_from_akshare(self) -> list[NonFerrousMetalsRecord]:
        """通过 AkShare 接口在线抓取有色大宗核心期货、现货与库存数据。"""
        records = fetch_akshare_metals_data()
        if records:
            self._save_raw_csv(records, self.metals_dir / "commodity_prices.csv")
        return records


__all__ = ["NonFerrousCollector", "fetch_akshare_metals_data"]
