"""GACC 批量回填调度器单元测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest
import yaml
from scripts.gacc_batch_scheduler import (
    inspect_curated_status,
    load_plan,
    run_batch,
    run_next_pending_batch,
    save_plan,
)


@pytest.fixture
def mock_plan_file(tmp_path: Path) -> Path:
    """生成测试用的 mock 排期计划文件。"""
    plan_data = {
        "version": "1.0",
        "meta": {"start_year": 2018, "end_year": 2026},
        "batches": [
            {
                "id": "2018H1",
                "year": 2018,
                "half": "H1",
                "start_month": 1,
                "end_month": 6,
                "status": "completed",
            },
            {
                "id": "2018H2",
                "year": 2018,
                "half": "H2",
                "start_month": 7,
                "end_month": 12,
                "status": "pending",
            },
        ],
    }
    plan_path = tmp_path / "test_plan.yaml"
    with open(plan_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(plan_data, f)
    return plan_path


def test_load_and_save_plan(mock_plan_file: Path) -> None:
    """验证排期文件的读取与保存。"""
    plan = load_plan(mock_plan_file)
    assert plan["version"] == "1.0"
    assert len(plan["batches"]) == 2
    assert plan["batches"][0]["id"] == "2018H1"

    # 修改并保存
    plan["batches"][1]["status"] = "completed"
    save_plan(plan, mock_plan_file)

    reloaded = load_plan(mock_plan_file)
    assert reloaded["batches"][1]["status"] == "completed"


def test_inspect_curated_status(tmp_path: Path) -> None:
    """验证从真实/模拟 Parquet 提取月份行数统计。"""
    df = pl.DataFrame(
        {
            "report_month": ["2018-01", "2018-01", "2018-02", "2018-07"],
            "goods_code": ["1", "2", "3", "4"],
        }
    )
    pq_path = tmp_path / "mock_curated.parquet"
    df.write_parquet(pq_path)

    stats = inspect_curated_status(pq_path)
    assert stats["2018-01"] == 2
    assert stats["2018-02"] == 1
    assert stats["2018-07"] == 1
    assert "2018-03" not in stats


@patch("scripts.gacc_batch_scheduler.run_automation")
def test_run_batch(mock_run: pytest.MagicMock, mock_plan_file: Path) -> None:
    """验证按指定 batch_id 执行。"""
    mock_run.return_value = 0

    code = run_batch("2018H2", plan_path=mock_plan_file)
    assert code == 0
    mock_run.assert_called_once_with(year=2018, start_month=7, end_month=12, auto_import=True)

    # 验证状态已被标记为 completed
    plan = load_plan(mock_plan_file)
    assert plan["batches"][1]["status"] == "completed"


@patch("scripts.gacc_batch_scheduler.run_automation")
def test_run_next_pending_batch(mock_run: pytest.MagicMock, mock_plan_file: Path) -> None:
    """验证自动查找并执行下一个 pending 批次。"""
    mock_run.return_value = 0

    code = run_next_pending_batch(plan_path=mock_plan_file)
    assert code == 0
    mock_run.assert_called_once_with(year=2018, start_month=7, end_month=12, auto_import=True)
