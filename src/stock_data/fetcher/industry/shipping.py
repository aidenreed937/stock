"""全球海运与油运日频运价指数采集器 (ShippingCollector)。"""

import csv
import logging
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.models import ShippingIndicesRecord

logger = logging.getLogger(__name__)


class ShippingCollector:
    """全球海运与油运日频运价指数 (BDI/BDTI/BCTI/SCFI) 采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)

    def collect(self) -> list[ShippingIndicesRecord]:
        """执行航运运价数据采集: 检查 RAW 快照 -> 校验落盘。"""
        raw_csv = self.raw_dir / "shipping" / "freight_indices.csv"
        if raw_csv.exists():
            return self.load_from_raw_csv(raw_csv)

        logger.warning("未找到全球航运运价指数 RAW 快照: %s", raw_csv)
        return []

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
                        source=row.get("source") or "BalticExchange/SSE",
                        source_url=row.get("source_url") or "",
                        release_date=date.fromisoformat(row["release_date"])
                        if row.get("release_date")
                        else None,
                        data_status=row.get("data_status") or "actual",
                        collected_at=row.get("collected_at") or now_utc_iso(),
                    )
                )
        records.sort(key=lambda r: r.trade_date)
        logger.info("全球海运与油运日频运价 RAW 快照加载成功: 共 %d 个交易日记录", len(records))
        return records
