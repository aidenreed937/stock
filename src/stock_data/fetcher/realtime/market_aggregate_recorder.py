"""市场聚合快照的可选 RAW 留档器。"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import polars as pl

from stock_data.core.runtime import DataRuntimeContext
from stock_data.fetcher.realtime.market_aggregate import MarketAggregateSnapshot


class MarketAggregateSnapshotRecorder:
    """按日期/小时追加一行聚合快照，不写入 Curated 黄金表。"""

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        runtime: DataRuntimeContext | None = None,
        source: str = "eastmoney",
        flush_interval_seconds: float = 60.0,
    ) -> None:
        if runtime is None:
            from stock_data.core.settings import data_settings

            context = data_settings.runtime_context
        else:
            context = runtime
        self.root = (
            Path(root)
            if root is not None
            else context.raw_root / "realtime" / "market_aggregate" / source
        )
        self.flush_interval_seconds = max(0.0, flush_interval_seconds)
        self._pending: list[dict[str, object]] = []
        self._last_flush_at: datetime | None = None

    def append(
        self,
        snapshots: Iterable[MarketAggregateSnapshot],
        *,
        now: datetime,
        force: bool = False,
    ) -> Path | None:
        """追加聚合快照；达到间隔或 force 时写入 Parquet。"""
        self._pending.extend(snapshot.model_dump() for snapshot in snapshots)
        should_flush = force or (
            self._last_flush_at is None
            or (now - self._last_flush_at).total_seconds() >= self.flush_interval_seconds
        )
        return self.flush(now=now) if should_flush else None

    def flush(self, *, now: datetime) -> Path | None:
        """将待写聚合快照作为新的 Parquet part 文件落盘。"""
        if not self._pending:
            return None
        target_dir = self.root / f"date={now.date().isoformat()}" / f"hour={now.hour:02d}"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"part-{now.strftime('%H%M%S')}-{uuid4().hex[:10]}.parquet"
        frame = pl.DataFrame(self._pending)
        temporary = target.with_name(f".{target.name}.tmp")
        frame.write_parquet(temporary, compression="zstd")
        temporary.replace(target)
        self._pending.clear()
        self._last_flush_at = now
        return target

    def prune(self, *, now: datetime, retention_days: int = 10) -> int:
        """显式清理超过保留期的聚合快照分区，默认不自动执行。"""
        cutoff = now.date() - timedelta(days=max(0, retention_days))
        removed = 0
        if not self.root.exists():
            return removed
        for directory in self.root.glob("date=*"):
            try:
                partition_date = datetime.strptime(
                    directory.name.removeprefix("date="), "%Y-%m-%d"
                ).date()
            except ValueError:
                continue
            if partition_date >= cutoff:
                continue
            for file_path in directory.rglob("*.parquet"):
                file_path.unlink()
                removed += 1
            for empty_dir in sorted(directory.rglob("*"), reverse=True):
                if empty_dir.is_dir() and not any(empty_dir.iterdir()):
                    empty_dir.rmdir()
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        return removed


__all__ = ["MarketAggregateSnapshotRecorder"]
