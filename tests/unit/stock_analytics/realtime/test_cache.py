"""实时快照缓存与留档测试。"""

from datetime import datetime, timedelta
from pathlib import Path

import polars as pl

from stock_analytics.realtime.cache import CacheFreshness, RealtimeSnapshotCache
from stock_data.fetcher.realtime.base import RealtimeQuote
from stock_data.fetcher.realtime.recorder import RealtimeSnapshotRecorder


def _quote(received_at: datetime, *, status: str = "valid") -> RealtimeQuote:
    return RealtimeQuote(
        symbol="600519.SH",
        provider_symbol="sh600519",
        received_at=received_at,
        status=status,  # type: ignore[arg-type]
        price=1307.88 if status == "valid" else None,
        pre_close=1297.99 if status == "valid" else None,
    )


def test_cache_has_fresh_stale_expired_and_date_boundary() -> None:
    received_at = datetime(2026, 8, 19, 10, 0, 0)
    cache = RealtimeSnapshotCache(fresh_ttl_seconds=2, max_age_seconds=60)
    cache.put(_quote(received_at))

    assert (
        cache.lookup("tencent", "600519.SH", now=received_at + timedelta(seconds=1)).freshness
        == CacheFreshness.FRESH
    )
    assert (
        cache.lookup("tencent", "600519.SH", now=received_at + timedelta(seconds=3)).freshness
        == CacheFreshness.STALE
    )
    assert (
        cache.lookup("tencent", "600519.SH", now=received_at + timedelta(seconds=61)).freshness
        == CacheFreshness.EXPIRED
    )
    assert cache.lookup("tencent", "600519.SH", now=datetime(2026, 8, 20, 10, 0, 0)) is None


def test_cache_does_not_store_missing_quote() -> None:
    received_at = datetime(2026, 8, 19, 10, 0, 0)
    cache = RealtimeSnapshotCache()

    cache.put(_quote(received_at, status="missing"))

    assert cache.lookup("tencent", "600519.SH", now=received_at) is None


def test_snapshot_recorder_writes_partitioned_parquet(tmp_path: Path) -> None:
    received_at = datetime(2026, 8, 19, 10, 0, 0)
    recorder = RealtimeSnapshotRecorder(root=tmp_path, flush_interval_seconds=30)

    target = recorder.append([_quote(received_at)], now=received_at)

    assert target is not None
    assert target.parent == tmp_path / "date=2026-08-19" / "hour=10"
    saved = pl.read_parquet(target)
    assert saved["symbol"].to_list() == ["600519.SH"]
    assert saved["source"].to_list() == ["tencent"]
