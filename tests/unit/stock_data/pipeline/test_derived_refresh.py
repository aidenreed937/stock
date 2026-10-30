"""Curated 派生表自动刷新测试。"""

from datetime import date
from unittest.mock import patch

import polars as pl

from stock_data.pipeline.derived_refresh import refresh_sw_2021_industry_golden
from stock_data.pipeline.sw_industry_golden import SWIndustryGoldenFrames
from stock_data.pipeline.sync_models import SyncExecutionResult, SyncTaskItem


def test_lixinger_constituent_success_refreshes_cross_source_golden() -> None:
    day = date(2026, 9, 4)
    plan = [
        SyncTaskItem(
            data_source="lixinger",
            endpoint="sw_2021_constituents",
            dataset="sw_2021_constituents",
            start_date=day,
            end_date=day,
            watermark=None,
            status="PENDING",
            is_ready=True,
        )
    ]
    results = [
        SyncExecutionResult(
            data_source="lixinger",
            endpoint="sw_2021_constituents",
            start_date=day,
            end_date=day,
            records=10,
            duration_s=0.1,
            status="SUCCESS",
        )
    ]
    materialized = SWIndustryGoldenFrames(
        dimension=pl.DataFrame({"industry_code": ["110000"]}),
        members=pl.DataFrame({"symbol": ["000001"]}),
        snapshot_date=day,
        request_id="request",
    )

    with patch(
        "stock_data.pipeline.derived_refresh.materialize_sw_2021_industry_golden",
        return_value=materialized,
    ) as materialize:
        result = refresh_sw_2021_industry_golden("lixinger", plan, results)

    materialize.assert_called_once_with(runtime=None, dry_run=False)
    assert result is not None
    assert result.data_source == "derived"
    assert result.endpoint == "sw_2021_industry_member_golden"
    assert result.status == "SUCCESS"
    assert result.records == 1
