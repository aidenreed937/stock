"""核心观察池实时监控应用 Facade。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import polars as pl

from stock_analytics.realtime.monitor import RealtimeMonitor
from stock_core.config.loader import load_watchlist_config
from stock_data.catalog import DataCatalog
from stock_data.core.settings import data_settings
from stock_data.fetcher.realtime import RealtimeSnapshotRecorder, TencentRealtimeFetcher


class RealtimeSession:
    """封装观察池装配、单次运行和 RAW 留档收尾。"""

    def __init__(
        self,
        monitor: RealtimeMonitor,
        symbols_by_dataset: dict[str, tuple[str, ...]],
        configured_count: int,
        recorder: RealtimeSnapshotRecorder | None = None,
    ) -> None:
        self.monitor = monitor
        self.symbols_by_dataset = symbols_by_dataset
        self.configured_count = configured_count
        self.recorder = recorder

    def run_once(self) -> pl.DataFrame:
        """执行一次观察池实时体检。"""
        return self.monitor.run(self.symbols_by_dataset)

    def flush(self, *, now: datetime) -> None:
        """结束运行时将待留档快照刷新到 RAW。"""
        if self.recorder is not None:
            self.recorder.flush(now=now)


def create_realtime_session(
    *,
    storage_dir: str | Path | None = None,
    raw_root: str | Path | None = None,
    record: bool = False,
) -> RealtimeSession:
    """从观察池配置创建实时监控会话。"""
    watchlist = load_watchlist_config().tushare
    symbols_by_dataset = {
        "stock_daily_bar": tuple(watchlist.stocks),
        "index_daily_bar": tuple(watchlist.indices),
        "fund_daily": tuple(watchlist.funds),
    }
    configured_count = sum(len(symbols) for symbols in symbols_by_dataset.values())
    if configured_count == 0:
        raise FileNotFoundError("watchlist.yaml 未加载到 A 股核心观察池")

    recorder: RealtimeSnapshotRecorder | None = None
    if record:
        runtime = data_settings.runtime_context
        recorder_path = (
            Path(raw_root) if raw_root is not None else runtime.raw_root / "realtime" / "tencent"
        )
        recorder = RealtimeSnapshotRecorder(root=recorder_path)
    catalog = DataCatalog(data_source="tushare", storage_dir=storage_dir)
    monitor = RealtimeMonitor(TencentRealtimeFetcher(), catalog, recorder=recorder)
    return RealtimeSession(
        monitor,
        symbols_by_dataset,
        configured_count,
        recorder,
    )


__all__ = ["RealtimeSession", "create_realtime_session"]
