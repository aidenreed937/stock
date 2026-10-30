"""AkShare 航运指数采集器。"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.shipping.models import ShippingIndicesRecord
from stock_data.fetcher.industry.shipping.parsers import save_shipping_raw_csv

logger = logging.getLogger(__name__)


def fetch_akshare_shipping_data() -> list[ShippingIndicesRecord]:
    """从 AkShare 在线抓取 BDI、BDTI、BCTI 与集装箱运价。"""
    try:
        import akshare as ak
    except ImportError:
        logger.error("未安装 akshare，跳过航运运价抓取")
        return []

    bdi_map: dict[str, float] = {}
    bdti_map: dict[str, float] = {}
    bcti_map: dict[str, float] = {}
    scfi_map: dict[str, float] = {}

    try:
        logger.info("正在从官方接口在线抓取综合航运运价指数 (BDI/BDTI/BCTI)...")
        df_freight = ak.macro_china_freight_index()
        if df_freight is not None and not df_freight.empty:
            for _, row in df_freight.iterrows():
                d_str = str(row["截止日期"]).strip().split(" ")[0].replace("/", "-")
                if row.get("波罗的海综合运价指数BDI") is not None:
                    val = float(row["波罗的海综合运价指数BDI"])
                    if val > 0:
                        bdi_map[d_str] = val
                if row.get("油轮运价指数原油运价指数BDTI") is not None:
                    val = float(row["油轮运价指数原油运价指数BDTI"])
                    if val > 0:
                        bdti_map[d_str] = val
                if row.get("油轮运价指数成品油运价指数BCTI") is not None:
                    val = float(row["油轮运价指数成品油运价指数BCTI"])
                    if val > 0:
                        bcti_map[d_str] = val
                if row.get("HRCI国际集装箱租船指数") is not None:
                    val = float(row["HRCI国际集装箱租船指数"])
                    if val > 0:
                        scfi_map[d_str] = val
    except Exception as e:
        logger.warning("抓取综合航运指数异常: %s", e)

    if not bdi_map:
        try:
            df_bdi = ak.macro_shipping_bdi()
            if df_bdi is not None and not df_bdi.empty:
                for _, row in df_bdi.iterrows():
                    d_str = str(row["日期"]).strip().split(" ")[0].replace("/", "-")
                    val = float(row["最新值"])
                    if val > 0:
                        bdi_map[d_str] = val
        except Exception as e:
            logger.warning("兜底抓取 BDI 异常: %s", e)

    if not bcti_map:
        try:
            df_bcti = ak.macro_shipping_bcti()
            if df_bcti is not None and not df_bcti.empty:
                for _, row in df_bcti.iterrows():
                    d_str = str(row["日期"]).strip().split(" ")[0].replace("/", "-")
                    val = float(row["最新值"])
                    if val > 0:
                        bcti_map[d_str] = val
        except Exception as e:
            logger.warning("兜底抓取 BCTI 异常: %s", e)

    try:
        df_wci = ak.drewry_wci_index()
        if df_wci is not None and not df_wci.empty:
            for _, row in df_wci.iterrows():
                d_str = str(row["date"]).strip().split(" ")[0].replace("/", "-")
                if row.get("wci") is not None:
                    val = float(row["wci"])
                    if val > 0:
                        scfi_map[d_str] = val
    except Exception as e:
        logger.warning("抓取 Drewry 集装箱运价指数异常: %s", e)

    if not bdi_map and not bdti_map:
        logger.warning("未抓取到有效航运运价数据")
        return []

    all_dates = sorted(
        list(
            set(bdi_map.keys()) | set(bdti_map.keys()) | set(bcti_map.keys()) | set(scfi_map.keys())
        )
    )
    now_iso = now_utc_iso()
    records: list[ShippingIndicesRecord] = []

    for d_str in all_dates:
        if d_str < "2016-01-01":
            continue
        try:
            t_date = date.fromisoformat(d_str)
        except ValueError:
            continue

        bdi_val = bdi_map.get(d_str)
        bdti_val = bdti_map.get(d_str)
        bcti_val = bcti_map.get(d_str)
        scfi_val = scfi_map.get(d_str)

        if bdi_val is None and bdti_val is None and bcti_val is None and scfi_val is None:
            continue

        records.append(
            ShippingIndicesRecord(
                trade_date=t_date,
                bdi_index=bdi_val,
                bdti_index=bdti_val,
                bcti_index=bcti_val,
                scfi_index=scfi_val,
                bdi_ma200_bias=None,
                bdti_ma200_bias=None,
                unit="index_points",
                source="BalticExchange/SSE/Drewry",
                source_url="https://www.balticexchange.com/",
                release_date=t_date,
                data_status="actual",
                collected_at=now_iso,
            )
        )

    records.sort(key=lambda r: r.trade_date)
    return records


class ShippingCollector:
    """全球海运与油运日频运价指数采集适配器。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.shipping_dir = self.raw_dir / "shipping"

    def collect(self) -> list[ShippingIndicesRecord]:
        """执行航运运价数据采集: 在线抓取最新真实数据并落盘快照。"""
        self.shipping_dir.mkdir(parents=True, exist_ok=True)
        records = fetch_akshare_shipping_data()
        if records:
            save_shipping_raw_csv(records, self.shipping_dir / "freight_indices_real.csv")
            save_shipping_raw_csv(records, self.shipping_dir / "freight_indices.csv")
        else:
            logger.warning("在线抓取航运运价指数失败")
        return records

    def fetch_from_akshare(self) -> list[ShippingIndicesRecord]:
        """在线抓取航运运价记录。"""
        return self.collect()


__all__ = ["ShippingCollector", "fetch_akshare_shipping_data"]
