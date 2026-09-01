"""芯片交付周期 (Chip Lead Time) 采集器、数据模型与任务包测试 (纯 Mock/无硬编码事实)。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import polars as pl

from stock_data.core.task_bundles import expand_task_targets
from stock_data.fetcher.industry import (
    CHIP_LEAD_TIME_SCHEMA,
    ChipLeadTimeCollector,
    empty_chip_lead_time,
    execute_single_industry_task,
    records_to_chip_lead_time_frame,
)
from stock_data.fetcher.industry.models import ChipLeadTimeRecord
from stock_data.fetcher.industry.semiconductor.lead_time_collector import (
    _parse_lead_time_string_to_weeks,
)


def test_parse_lead_time_string() -> None:
    """验证分销商交期字符串解析。"""
    assert _parse_lead_time_string_to_weeks("18 Weeks") == 18.0
    assert _parse_lead_time_string_to_weeks("24.5 weeks") == 24.5
    assert _parse_lead_time_string_to_weeks("70 Days") == 10.0
    assert _parse_lead_time_string_to_weeks("12 周") == 12.0
    assert _parse_lead_time_string_to_weeks("") is None


def test_chip_lead_time_collector_live_mock(tmp_path: Path, monkeypatch) -> None:
    """验证配置 API Key 时在线抓取、加权计算及 RAW 快照落盘。"""
    monkeypatch.setenv("MOUSER_SEARCH_API_KEY", "mock-test-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "SearchResults": {"Parts": [{"LeadTime": "20 Weeks", "Manufacturer": "STMicroelectronics"}]}
    }

    with patch("requests.post", return_value=mock_resp):
        collector = ChipLeadTimeCollector(raw_dir=tmp_path / "raw")
        records = collector.collect()

    assert len(records) == 1
    r = records[0]
    assert r.avg_lead_time_weeks == 20.0
    assert r.mcu_lead_time_weeks == 20.0
    assert r.analog_lead_time_weeks == 20.0
    assert r.lead_time_status == "tight"
    assert r.unit == "weeks"
    assert r.source == "Mouser/Distributor"

    # 验证 RAW 快照文件已创建在 data/raw/lead_time/
    raw_files = list((tmp_path / "raw" / "lead_time").glob("*.json"))
    assert len(raw_files) == 1
    saved_data = json.loads(raw_files[0].read_text(encoding="utf-8"))
    assert saved_data["avg_lead_time_weeks"] == 20.0


def test_chip_lead_time_collector_from_raw_snapshots(tmp_path: Path, monkeypatch) -> None:
    """验证未配置 API Key 时自动回退读取本地 RAW 快照。"""
    monkeypatch.delenv("MOUSER_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("MOUSER_API_KEY", raising=False)
    monkeypatch.setattr("stock_data.core.settings.data_settings.mouser_search_api_key", None)
    monkeypatch.setattr("stock_data.core.settings.data_settings.mouser_api_key", None)

    lead_dir = tmp_path / "raw" / "lead_time"
    lead_dir.mkdir(parents=True, exist_ok=True)

    # 写入 2 个月度真实快照
    (lead_dir / "chip_lead_time_2026-05.json").write_text(
        json.dumps(
            {
                "report_month": "2026-05",
                "avg_lead_time_weeks": 21.0,
                "category_averages": {
                    "mcu": 20.0,
                    "analog": 18.0,
                    "discrete": 16.0,
                    "compute": 30.0,
                },
            }
        ),
        encoding="utf-8",
    )
    (lead_dir / "chip_lead_time_2026-06.json").write_text(
        json.dumps(
            {
                "report_month": "2026-06",
                "avg_lead_time_weeks": 21.5,
                "category_averages": {
                    "mcu": 20.5,
                    "analog": 18.5,
                    "discrete": 16.5,
                    "compute": 30.5,
                },
            }
        ),
        encoding="utf-8",
    )

    collector = ChipLeadTimeCollector(raw_dir=tmp_path / "raw")
    records = collector.collect()

    assert len(records) == 2
    assert records[0].report_month == "2026-05"
    assert records[0].avg_lead_time_weeks == 21.0
    assert records[1].report_month == "2026-06"
    assert records[1].avg_lead_time_weeks == 21.5


def test_chip_lead_time_collector_empty_when_no_key_and_no_raw(tmp_path: Path, monkeypatch) -> None:
    """验证未配置 Key 且本地无 RAW 快照时安全返回空列表。"""
    monkeypatch.delenv("MOUSER_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("MOUSER_API_KEY", raising=False)
    monkeypatch.setattr("stock_data.core.settings.data_settings.mouser_search_api_key", None)
    monkeypatch.setattr("stock_data.core.settings.data_settings.mouser_api_key", None)

    collector = ChipLeadTimeCollector(raw_dir=tmp_path / "raw")
    records = collector.collect()
    assert records == []


def test_chip_lead_time_transform_and_empty() -> None:
    """验证 DataFrame 转换与空表骨架。"""
    df_empty = empty_chip_lead_time()
    assert df_empty.schema == CHIP_LEAD_TIME_SCHEMA
    assert df_empty.height == 0

    records = [
        ChipLeadTimeRecord(
            report_month="2026-07",
            trade_date=date(2026, 7, 31),
            avg_lead_time_weeks=21.32,
            mcu_lead_time_weeks=19.5,
            analog_lead_time_weeks=18.0,
            discrete_lead_time_weeks=16.5,
            compute_lead_time_weeks=31.0,
            lead_time_status="tight",
        )
    ]
    df = records_to_chip_lead_time_frame(records)
    assert df.height == 1
    assert df["avg_lead_time_weeks"][0] == 21.32


def test_execute_single_industry_task_chip_lead_time(tmp_path: Path, monkeypatch) -> None:
    """验证 execute_single_industry_task 分发 chip_lead_time 并生成 parquet。"""
    monkeypatch.setenv("MOUSER_SEARCH_API_KEY", "mock-test-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"SearchResults": {"Parts": [{"LeadTime": "19 Weeks"}]}}

    with patch("requests.post", return_value=mock_resp):
        count = execute_single_industry_task(
            endpoint="chip_lead_time",
            raw_dir=tmp_path / "raw",
            curated_dir=tmp_path / "curated",
        )

    assert count == 1
    parquet_path = tmp_path / "curated" / "chip_lead_time.parquet"
    assert parquet_path.exists()
    df = pl.read_parquet(parquet_path)
    assert df.height == 1
    assert df["avg_lead_time_weeks"][0] == 19.0


def test_task_bundles_includes_chip_lead_time() -> None:
    """验证 task_bundles 中 industry_tech 与 industry_all 包含 chip_lead_time。"""
    tech_tasks = expand_task_targets("industry", ["industry_tech"])
    assert "chip_lead_time" in tech_tasks

    all_tasks = expand_task_targets("industry", ["industry_all"])
    assert "chip_lead_time" in all_tasks
