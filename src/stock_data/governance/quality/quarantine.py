"""保留清洗阶段被拒绝的数据，避免静默丢弃导致无法审计。"""

import threading
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

_quarantine_lock = threading.Lock()


class QuarantineStore:
    """以 Parquet 追加方式保存异常记录及其处理上下文。"""

    def __init__(self, root: str | Path = "data/quarantine") -> None:
        self.root = Path(root)

    def write(
        self,
        frame: pl.DataFrame,
        *,
        endpoint: str,
        reason: str,
        request_id: str = "",
        data_source: str = "",
    ) -> Path:
        if frame.is_empty():
            return self.root / f"{endpoint}.parquet"
        target = self.root / f"endpoint={endpoint}" / "records.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        enriched = frame.with_columns(
            pl.lit(reason).alias("quarantine_reason"),
            pl.lit(endpoint).alias("source_endpoint"),
            pl.lit(request_id).alias("request_id"),
            pl.lit(data_source).alias("data_source"),
            pl.lit(datetime.now(UTC)).alias("quarantined_at"),
        )
        with _quarantine_lock:
            if target.exists():
                try:
                    existing = pl.read_parquet(target)
                    enriched = pl.concat([existing, enriched], how="diagonal_relaxed")
                except Exception:
                    pass
            tmp_target = target.with_suffix(".tmp")
            enriched.write_parquet(tmp_target)
            tmp_target.replace(target)
        return target

    def write_file(
        self,
        frame: pl.DataFrame,
        *,
        endpoint: str,
        reason: str,
        request_id: str = "",
        data_source: str = "",
    ) -> Path:
        """以独立文件记录一次历史治理结果，避免与运行时隔离批次混写。"""
        target = self.root / f"endpoint={endpoint}" / "history_repair.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        enriched = frame.with_columns(
            pl.lit(reason).alias("quarantine_reason"),
            pl.lit(endpoint).alias("source_endpoint"),
            pl.lit(request_id).alias("request_id"),
            pl.lit(data_source).alias("data_source"),
            pl.lit(datetime.now(UTC)).alias("quarantined_at"),
        )
        enriched.write_parquet(target)
        return target
