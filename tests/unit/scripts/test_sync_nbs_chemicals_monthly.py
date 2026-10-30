"""scripts/sync_nbs_chemicals_monthly.py 单元测试。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest
from scripts.sync_nbs_chemicals_monthly import main

from stock_data.fetcher.industry.chemicals.collectors.capacity import (
    ChemicalCapacityUtilization10Y,
)
from stock_data.fetcher.industry.contracts import IndustryFrameResult


def test_sync_nbs_chemicals_monthly_main_mock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证 sync_nbs_chemicals_monthly 脚本通过 ChemicalCapacityUtilization10Y 完成增量物化。"""
    raw_dir = tmp_path / "raw" / "industry"
    raw_dir.mkdir(parents=True)
    chem_dir = raw_dir / "chemicals"
    chem_dir.mkdir(parents=True)

    # 模拟命令行参数
    test_args = [
        "sync_nbs_chemicals_monthly.py",
        "--month",
        "2026-08",
        "--products",
        "纯碱",
        "--raw-dir",
        str(raw_dir),
    ]
    monkeypatch.setattr("sys.argv", test_args)

    mock_frame = pl.DataFrame(
        [
            {
                "product_name": "纯碱",
                "symbol": "SA",
                "report_month": "2026-08",
                "trade_date": date(2026, 8, 1),
                "output_current_raw": "334.4",
                "output_cumulative_raw": "2568.1",
                "output_yoy_raw": "3.0",
                "output_cum_yoy_raw": "4.2",
                "annual_capacity_raw": "4900.0",
                "capacity_source": "CPCIF",
                "unit": "万吨",
                "source": "NBS_Official",
                "release_date": date(2026, 9, 18),
                "collected_at": "2026-10-10T00:00:00Z",
            }
        ]
    )
    mock_curated = pl.DataFrame(
        [
            {
                "product_name": "纯碱",
                "symbol": "SA",
                "year": 2026,
                "month": 8,
                "trade_date": date(2026, 8, 1),
                "actual_output_w_tons": 334.4,
                "implied_capacity_utilization_pct": 80.35,
            }
        ]
    )

    mock_raw_result = IndustryFrameResult(
        frame=mock_frame,
        status="SUCCESS",
        fetched_periods=("2026-08",),
        cached_periods=(),
        errors=(),
        updated=True,
    )

    with patch.object(
        ChemicalCapacityUtilization10Y,
        "sync_and_curate",
        return_value=(mock_raw_result, mock_curated),
    ) as mock_sync:
        exit_code = main()
        assert exit_code == 0
        mock_sync.assert_called_once_with(
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1),
            force=False,
            product_names=["纯碱"],
        )
