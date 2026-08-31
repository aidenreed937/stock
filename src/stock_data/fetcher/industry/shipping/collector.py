"""全球海运与油运日频运价指数官方采集器 (ShippingCollector)。"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.models import ShippingIndicesRecord

logger = logging.getLogger(__name__)


class ShippingCollector:
    """全球海运与油运日频运价指数 (BDI/BCTI) 采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.shipping_dir = self.raw_dir / "shipping"

    def collect(self) -> list[ShippingIndicesRecord]:
        """执行航运运价数据采集: 在线抓取最新真实数据并落盘快照，以最新采集为准。"""
        self.shipping_dir.mkdir(parents=True, exist_ok=True)

        # 在线获取最新真实数据并保存快照
        live_records = self.fetch_from_akshare()
        if not live_records:
            logger.warning("在线抓取航运运价指数失败")
        return live_records

    def fetch_from_akshare(self) -> list[ShippingIndicesRecord]:
        """从 AkShare 在线抓取波罗的海干散货运价 (BDI) 与成品油运价 (BCTI)。"""
        try:
            import akshare as ak
        except ImportError:
            logger.error("未安装 akshare，跳过航运运价抓取")
            return []

        logger.info("正在从官方接口在线抓取波罗的海干散货指数 (BDI)...")
        bdi_map: dict[str, float] = {}
        try:
            df_bdi = ak.macro_shipping_bdi()
            if df_bdi is not None and not df_bdi.empty:
                for _, row in df_bdi.iterrows():
                    d_str = str(row["日期"]).strip().split(" ")[0].replace("/", "-")
                    val = float(row["最新值"])
                    if val > 0:
                        bdi_map[d_str] = val
        except Exception as e:
            logger.warning("抓取 BDI 指数异常: %s", e)

        logger.info("正在从官方接口在线抓取波罗的海成品油运价指数 (BCTI)...")
        bcti_map: dict[str, float] = {}
        try:
            df_bcti = ak.macro_shipping_bcti()
            if df_bcti is not None and not df_bcti.empty:
                for _, row in df_bcti.iterrows():
                    d_str = str(row["日期"]).strip().split(" ")[0].replace("/", "-")
                    val = float(row["最新值"])
                    if val > 0:
                        bcti_map[d_str] = val
        except Exception as e:
            logger.warning("抓取 BCTI 指数异常: %s", e)

        if not bdi_map:
            logger.warning("未抓取到有效 BDI 数据")
            return []

        all_dates = sorted(list(set(bdi_map.keys()) | set(bcti_map.keys())))
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
            if bdi_val is None:
                continue
            bcti_val = bcti_map.get(d_str)

            records.append(
                ShippingIndicesRecord(
                    trade_date=t_date,
                    bdi_index=bdi_val,
                    bdti_index=None,
                    bcti_index=bcti_val,
                    scfi_index=None,
                    bdi_ma200_bias=None,  # transform 层自动滚动计算 MA200 乖离率
                    bdti_ma200_bias=None,
                    unit="index_points",
                    source="Baltic_Exchange",
                    source_url="https://www.balticexchange.com/",
                    release_date=t_date,
                    data_status="actual",
                    collected_at=now_iso,
                )
            )

        records.sort(key=lambda r: r.trade_date)
        if records:
            self._save_raw_csv(records, self.shipping_dir / "freight_indices_real.csv")
            self._save_raw_csv(records, self.shipping_dir / "freight_indices.csv")
        return records

    def _save_raw_csv(self, records: list[ShippingIndicesRecord], path: Path) -> None:
        """持久化 RAW 快照 CSV。"""
        fieldnames = [
            "trade_date",
            "bdi_index",
            "bcti_index",
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
                        "bdi_index": r.bdi_index,
                        "bcti_index": r.bcti_index,
                        "source": r.source,
                        "source_url": r.source_url,
                        "release_date": r.release_date.isoformat() if r.release_date else "",
                        "data_status": r.data_status,
                        "collected_at": r.collected_at,
                    }
                )
        logger.info("已保存真实航运运价 RAW 快照: %s (共 %d 行)", path, len(records))

    def load_from_raw_csv(self, file_path: Path | str) -> list[ShippingIndicesRecord]:
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
                        bdi_index=float(row["bdi_index"]),
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
