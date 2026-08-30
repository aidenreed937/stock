"""北美四大云厂商 (CSP) 季度 AI 资本开支采集器 (CloudCapexCollector)。"""

import csv
import logging
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
)
from stock_data.fetcher.industry.models import CloudCapexRecord

logger = logging.getLogger(__name__)


def _quarter_to_month_end(quarter_str: str) -> tuple[str, date]:
    """将 YYYY-Q1/Q2/Q3/Q4 转换为季度末自然日。"""
    parts = quarter_str.strip().split("-")
    year = int(parts[0])
    q = parts[1].upper()
    month_map = {"Q1": 3, "Q2": 6, "Q3": 9, "Q4": 12}
    month = month_map.get(q, 12)
    return quarter_str, get_month_end_date(year, month)


class CloudCapexCollector:
    """北美四大云厂商 (MSFT/GOOG/META/AMZN) 季度 CapEx 采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)

    def collect(self) -> list[CloudCapexRecord]:
        """执行云厂商季度 CapEx 数据采集: 检查 RAW 快照 -> 校验落盘。"""
        raw_csv = self.raw_dir / "cloud_capex" / "csp_capex_quarterly.csv"
        if raw_csv.exists():
            return self.load_from_raw_csv(raw_csv)

        logger.warning("未找到云厂商季度 CapEx RAW 快照: %s", raw_csv)
        return []

    def load_from_raw_csv(self, file_path: Path | str) -> list[CloudCapexRecord]:
        """从云厂商 CapEx RAW 快照 CSV 中读取并标准化。"""
        p = Path(file_path)
        if not p.exists():
            return []

        records: list[CloudCapexRecord] = []
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                q_str = row["report_quarter"].strip()
                _, t_date = _quarter_to_month_end(q_str)
                records.append(
                    CloudCapexRecord(
                        report_quarter=q_str,
                        trade_date=t_date,
                        total_capex_billion_usd=float(row["total_capex_billion_usd"]),
                        msft_capex_billion_usd=float(row["msft_capex_billion_usd"])
                        if row.get("msft_capex_billion_usd")
                        else None,
                        goog_capex_billion_usd=float(row["goog_capex_billion_usd"])
                        if row.get("goog_capex_billion_usd")
                        else None,
                        meta_capex_billion_usd=float(row["meta_capex_billion_usd"])
                        if row.get("meta_capex_billion_usd")
                        else None,
                        amzn_capex_billion_usd=float(row["amzn_capex_billion_usd"])
                        if row.get("amzn_capex_billion_usd")
                        else None,
                        yoy_growth=float(row["yoy_growth"]) if row.get("yoy_growth") else None,
                        qoq_growth=float(row["qoq_growth"]) if row.get("qoq_growth") else None,
                        unit=row.get("unit") or "billion_usd",
                        source=row.get("source") or "Company Filings (10-Q/10-K)",
                        source_url=row.get("source_url") or "",
                        release_date=date.fromisoformat(row["release_date"])
                        if row.get("release_date")
                        else None,
                        data_status=row.get("data_status") or "actual",
                        collected_at=row.get("collected_at") or now_utc_iso(),
                    )
                )
        records.sort(key=lambda r: r.trade_date)
        logger.info("云厂商季度 CapEx RAW 快照加载成功: 共 %d 个季度记录", len(records))
        return records
