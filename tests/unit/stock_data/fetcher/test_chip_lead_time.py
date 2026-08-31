"""芯片交付周期 (Chip Lead Time) 采集器、数据模型与任务包测试。"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from stock_data.core.task_bundles import expand_task_targets
from stock_data.fetcher.industry import (
    CHIP_LEAD_TIME_SCHEMA,
    ChipLeadTimeCollector,
    empty_chip_lead_time,
    execute_single_industry_task,
    records_to_chip_lead_time_frame,
)


def test_chip_lead_time_collector_collect(tmp_path: Path) -> None:
    """验证 ChipLeadTimeCollector 采集与加权计算。"""
    collector = ChipLeadTimeCollector(raw_dir=tmp_path / "raw")
    records = collector.collect()

    assert len(records) >= 100
    r0 = records[0]
    assert r0.report_month == "2018-01"
    assert r0.avg_lead_time_weeks > 0
    assert r0.mcu_lead_time_weeks is not None
    assert r0.analog_lead_time_weeks is not None
    assert r0.discrete_lead_time_weeks is not None
    assert r0.compute_lead_time_weeks is not None
    assert r0.unit == "weeks"
    assert r0.lead_time_status in ("normal", "tight", "overheating", "easing")

    # 检查 2022 缺芯极值年份状态
    rec_2022 = next(r for r in records if r.report_month == "2022-05")
    assert rec_2022.avg_lead_time_weeks >= 26.0
    assert rec_2022.lead_time_status == "overheating"

    # 检查 2026 最新月份状态
    rec_2026 = next(r for r in records if r.report_month == "2026-07")
    assert rec_2026.avg_lead_time_weeks >= 18.0
    assert rec_2026.lead_time_status == "tight"
    assert rec_2026.lead_time_mom_weeks is not None


def test_chip_lead_time_transform_and_empty() -> None:
    """验证 DataFrame 转换与空表骨架。"""
    df_empty = empty_chip_lead_time()
    assert df_empty.schema == CHIP_LEAD_TIME_SCHEMA
    assert df_empty.height == 0

    collector = ChipLeadTimeCollector()
    records = collector.collect()
    df = records_to_chip_lead_time_frame(records)

    assert df.height == len(records)
    assert "report_month" in df.columns
    assert "avg_lead_time_weeks" in df.columns
    assert "lead_time_status" in df.columns
    assert df["avg_lead_time_weeks"].is_not_null().all()


def test_execute_single_industry_task_chip_lead_time(tmp_path: Path) -> None:
    """验证 execute_single_industry_task 分发 chip_lead_time 并生成 parquet。"""
    count = execute_single_industry_task(
        endpoint="chip_lead_time",
        raw_dir=tmp_path / "raw",
        curated_dir=tmp_path / "curated",
    )
    assert count >= 100
    parquet_path = tmp_path / "curated" / "chip_lead_time.parquet"
    assert parquet_path.exists()

    df = pl.read_parquet(parquet_path)
    assert df.height == count
    assert "avg_lead_time_weeks" in df.columns


def test_task_bundles_includes_chip_lead_time() -> None:
    """验证 task_bundles 中 industry_tech 与 industry_all 包含 chip_lead_time。"""
    tech_tasks = expand_task_targets("industry", ["industry_tech"])
    assert "chip_lead_time" in tech_tasks

    all_tasks = expand_task_targets("industry", ["industry_all"])
    assert "chip_lead_time" in all_tasks
    assert len(all_tasks) == 17  # 16 + 1
