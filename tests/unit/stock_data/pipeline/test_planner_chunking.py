"""单元测试：BackfillPlanner 全市场跨年任务分块拆解与调度。"""

from datetime import date
from unittest.mock import MagicMock

from stock_data.core.settings import data_settings
from stock_data.pipeline.planner import (
    BackfillPlanner,
    _has_curated_range,
    _split_date_range_by_year,
)


def test_split_date_range_by_year_same_year() -> None:
    """测试同年日期区间不拆分。"""
    chunks = _split_date_range_by_year(date(2021, 3, 1), date(2021, 10, 15))
    assert chunks == [(date(2021, 3, 1), date(2021, 10, 15))]


def test_split_date_range_by_year_multi_year() -> None:
    """测试跨多年日期区间按日历年拆分。"""
    chunks = _split_date_range_by_year(date(2018, 5, 20), date(2021, 8, 14))
    assert len(chunks) == 4
    assert chunks[0] == (date(2018, 5, 20), date(2018, 12, 31))
    assert chunks[1] == (date(2019, 1, 1), date(2019, 12, 31))
    assert chunks[2] == (date(2020, 1, 1), date(2020, 12, 31))
    assert chunks[3] == (date(2021, 1, 1), date(2021, 8, 14))


def test_plan_tasks_chunking_market_wide_event() -> None:
    """测试全市场跨年事件任务 (如 share_float) 自动拆解为年度子任务。"""
    mock_cfg = MagicMock()
    mock_cfg.watchlists = None
    mock_cfg.endpoint_start_date_overrides = {}

    tasks = BackfillPlanner.plan_tasks(
        data_source="tushare",
        endpoints=["share_float"],
        symbol=None,
        start_date=date(2018, 1, 1),
        end_date=date(2021, 12, 31),
        start_specified=True,
        data_cfg=mock_cfg,
    )
    assert len(tasks) == 4
    assert [t.start_date for t in tasks] == [
        date(2018, 1, 1),
        date(2019, 1, 1),
        date(2020, 1, 1),
        date(2021, 1, 1),
    ]
    assert [t.end_date for t in tasks] == [
        date(2018, 12, 31),
        date(2019, 12, 31),
        date(2020, 12, 31),
        date(2021, 12, 31),
    ]
    for t in tasks:
        assert t.endpoint == "share_float"
        assert t.symbol == ""
        assert t.is_chunked is True
        assert t.chunk_count == 4


def test_plan_tasks_force_refresh_disables_existing_chunk_skip() -> None:
    """测试强制刷新时年度任务不会标记为跳过。"""
    mock_cfg = MagicMock()
    mock_cfg.watchlists = None
    mock_cfg.endpoint_start_date_overrides = {}

    tasks = BackfillPlanner.plan_tasks(
        data_source="tushare",
        endpoints=["share_float"],
        symbol=None,
        start_date=date(2018, 1, 1),
        end_date=date(2019, 12, 31),
        start_specified=True,
        data_cfg=mock_cfg,
        force_refresh=True,
    )

    assert len(tasks) == 2
    assert all(task.skip_existing is False for task in tasks)


def test_has_curated_range_requires_every_month(tmp_path, monkeypatch) -> None:
    """测试年度跳过检查不会把缺失月份误判为完整。"""
    curated_root = tmp_path / "curated"
    monkeypatch.setattr(data_settings, "curated_data_dir", curated_root)
    dataset_root = curated_root / "tushare" / "market=CN" / "share_float" / "year=2018"
    for month in range(1, 13):
        month_dir = dataset_root / f"month={month:02d}"
        month_dir.mkdir(parents=True)
        (month_dir / "data.parquet").touch()

    assert _has_curated_range("tushare", "share_float", date(2018, 1, 1), date(2018, 12, 31))
    (dataset_root / "month=12" / "data.parquet").unlink()
    assert not _has_curated_range("tushare", "share_float", date(2018, 1, 1), date(2018, 12, 31))


def test_plan_tasks_per_symbol_no_chunking() -> None:
    """测试按标的任务 (per_symbol) 不按年拆分，保持完整区间。"""
    mock_cfg = MagicMock()
    mock_cfg.watchlists = None
    mock_cfg.endpoint_start_date_overrides = {}

    tasks = BackfillPlanner.plan_tasks(
        data_source="tushare",
        endpoints=["stock_daily_bar"],
        symbol="000001.SZ",
        start_date=date(2018, 1, 1),
        end_date=date(2021, 12, 31),
        start_specified=True,
        data_cfg=mock_cfg,
    )
    assert len(tasks) == 1
    assert tasks[0].start_date == date(2018, 1, 1)
    assert tasks[0].end_date == date(2021, 12, 31)
    assert tasks[0].symbol == "000001.SZ"
