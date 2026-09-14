"""智库 CoWoS 产能预测与供需推演 RAW 解析器 (CowosEstimatesParser).

解析 cowos_capacity_estimates_raw.csv，校验智库公报 SHA-256、发布日期与预测状态，
严格禁止标注为 actual，实现预测数据物理隔离。
"""

from __future__ import annotations

import csv
import hashlib
import logging
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.semiconductor.models import CowosCapacityEstimateRecord

logger = logging.getLogger(__name__)


def load_cowos_capacity_estimates_raw_csv(
    file_path: Path | str,
    project_root: Path | str | None = None,
    verify_hash: bool = True,
) -> list[CowosCapacityEstimateRecord]:
    """从 CSV 加载智库 CoWoS 产能测算原始记录并严格核验时态。"""
    csv_path = Path(file_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"未找到 CoWoS 智库测算 RAW 文件: {csv_path}")

    root = Path(project_root) if project_root else csv_path.parent.parent.parent.parent.parent
    records: list[CowosCapacityEstimateRecord] = []

    with csv_path.open(mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row_idx, row in enumerate(reader, start=2):
            symbol = row["symbol"].strip()
            report_quarter = row["report_quarter"].strip()
            trade_date_val = date.fromisoformat(row["trade_date"].strip())
            agency = row["agency"].strip()
            published_date_val = date.fromisoformat(row["published_date"].strip())
            monthly_capacity = float(row["monthly_capacity_kwpm"])
            lead_time = float(row["lead_time_months"]) if row.get("lead_time_months") else None
            data_status = row.get("data_status", "forecast").strip()
            source = row.get("source", "TrendForce_Press_Release").strip()
            source_url = row.get("source_url", "").strip()
            collected_at = row.get("collected_at", "").strip()
            raw_sha256 = row.get("raw_content_sha256", "").strip()
            raw_path = row.get("raw_snapshot_path", "").strip()

            # 绝对红线：智库预测表严禁标记为 actual
            if data_status == "actual":
                raise ValueError(
                    f"第 {row_idx} 行违规: 智库测算表绝对禁止标记为 actual! 必须为 estimate 或 forecast"
                )

            # 严格时态红线：如果 trade_date 在 published_date 之后，必须强制为 forecast
            if trade_date_val > published_date_val and data_status != "forecast":
                raise ValueError(
                    f"第 {row_idx} 行时态违规: 报告期 {trade_date_val} 晚于发布日 {published_date_val}，"
                    f"必须为 forecast, 实际为 {data_status}"
                )

            # 校验快照真实文件与 SHA-256
            if verify_hash and raw_path and raw_sha256:
                target_file = (
                    root / raw_path if not Path(raw_path).is_absolute() else Path(raw_path)
                )
                if target_file.exists():
                    actual_sha = hashlib.sha256(target_file.read_bytes()).hexdigest()
                    if actual_sha != raw_sha256:
                        raise ValueError(
                            f"第 {row_idx} 行快照哈希不一致! 期望 {raw_sha256[:12]}, 实际 {actual_sha[:12]}"
                        )

            record = CowosCapacityEstimateRecord(
                symbol=symbol,
                report_quarter=report_quarter,
                trade_date=trade_date_val,
                agency=agency,
                published_date=published_date_val,
                monthly_capacity_kwpm=monthly_capacity,
                lead_time_months=lead_time,
                data_status=data_status,
                source=source,
                source_url=source_url,
                collected_at=collected_at,
                raw_content_sha256=raw_sha256,
                raw_snapshot_path=raw_path,
            )
            records.append(record)

    return sorted(records, key=lambda r: (r.agency, r.published_date, r.trade_date))
