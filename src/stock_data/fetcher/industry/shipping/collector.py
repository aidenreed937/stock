"""全球海运与油运日频运价指数官方采集器 (ShippingCollector)。"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.models import ShippingIndicesRecord

logger = logging.getLogger(__name__)


def fetch_akshare_shipping_data() -> list[ShippingIndicesRecord]:
    """从 AkShare 在线抓取波罗的海干散货 (BDI)、原油运价 (BDTI)、成品油 (BCTI) 与集装箱运价 (SCFI/WCI)。"""
    try:
        import akshare as ak
    except ImportError:
        logger.error("未安装 akshare，跳过航运运价抓取")
        return []

    bdi_map: dict[str, float] = {}
    bdti_map: dict[str, float] = {}
    bcti_map: dict[str, float] = {}
    scfi_map: dict[str, float] = {}

    # 1. 优先从综合航运运价接口抓取 (BDI, BDTI, BCTI, HRCI)
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

    # 2. 若 BDI 或 BCTI 缺失，使用单项接口兜底补充
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

    # 3. 抓取集装箱运价 (Drewry World Container Index) 补充集运腿
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
                bdi_index=bdi_val if bdi_val is not None else 0.0,
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


def save_shipping_raw_csv(records: list[ShippingIndicesRecord], path: Path) -> None:
    """持久化 RAW 快照 CSV。"""
    fieldnames = [
        "trade_date",
        "bdi_index",
        "bdti_index",
        "bcti_index",
        "scfi_index",
        "bdi_ma200_bias",
        "bdti_ma200_bias",
        "unit",
        "source",
        "source_url",
        "release_date",
        "data_status",
        "collected_at",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "trade_date": r.trade_date.isoformat(),
                    "bdi_index": r.bdi_index if r.bdi_index is not None else "",
                    "bdti_index": r.bdti_index if r.bdti_index is not None else "",
                    "bcti_index": r.bcti_index if r.bcti_index is not None else "",
                    "scfi_index": r.scfi_index if r.scfi_index is not None else "",
                    "bdi_ma200_bias": r.bdi_ma200_bias if r.bdi_ma200_bias is not None else "",
                    "bdti_ma200_bias": r.bdti_ma200_bias if r.bdti_ma200_bias is not None else "",
                    "unit": r.unit,
                    "source": r.source,
                    "source_url": r.source_url,
                    "release_date": r.release_date.isoformat() if r.release_date else "",
                    "data_status": r.data_status,
                    "collected_at": r.collected_at,
                }
            )
    logger.info("已保存真实航运运价 RAW 快照: %s (共 %d 行)", path, len(records))


def load_shipping_raw_records(file_path: Path | str) -> list[ShippingIndicesRecord]:
    """从航运 RAW 快照 CSV 中读取并标准化。"""
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

    records: list[ShippingIndicesRecord] = []
    with p.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            t_date = date.fromisoformat(row["trade_date"].strip())
            records.append(
                ShippingIndicesRecord(
                    trade_date=t_date,
                    bdi_index=float(row["bdi_index"]) if row.get("bdi_index") else 0.0,
                    bdti_index=_safe_float(row.get("bdti_index")),
                    bcti_index=_safe_float(row.get("bcti_index")),
                    scfi_index=_safe_float(row.get("scfi_index")),
                    bdi_ma200_bias=_safe_float(row.get("bdi_ma200_bias")),
                    bdti_ma200_bias=_safe_float(row.get("bdti_ma200_bias")),
                    unit=row.get("unit") or "index_points",
                    source=row.get("source") or "Baltic_Exchange",
                    source_url=row.get("source_url") or "",
                    release_date=date.fromisoformat(row["release_date"])
                    if row.get("release_date")
                    else None,
                    data_status=row.get("data_status") or "actual",
                    collected_at=row.get("collected_at") or now_utc_iso(),
                )
            )
    records.sort(key=lambda r: r.trade_date)
    return records


class ShippingCollector:
    """全球海运与油运日频运价指数 (BDI/BDTI/BCTI/SCFI) 采集适配器。"""

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

    def load_from_raw_csv(self, file_path: Path | str) -> list[ShippingIndicesRecord]:
        """从航运 RAW 快照 CSV 中读取记录。"""
        return load_shipping_raw_records(file_path)
