"""测试 TrendForce DataTrack 内存基准价格与台湾存储出货先导指标端点。"""

from __future__ import annotations

import json
from datetime import date

import polars as pl
import pytest

from stock_data.core.runtime import DataRuntimeContext
from stock_data.fetcher.industry.semiconductor.collectors.datatrack_memory import (
    DataTrackMemoryPriceCollector,
)
from stock_data.fetcher.industry.semiconductor.collectors.taiwan_memory import (
    TaiwanMemoryLeadCollector,
    _extract_mops_result_row,
)
from stock_data.fetcher.industry.semiconductor.parsers.datatrack_memory import (
    parse_datatrack_memory_price_json,
)
from stock_data.fetcher.industry.semiconductor.parsers.taiwan_memory import (
    parse_taiwan_memory_monthly_revenue_dict,
)
from stock_data.fetcher.industry.semiconductor.schemas import (
    MEMORY_BENCHMARK_CURATED_SCHEMA,
    MEMORY_BENCHMARK_RAW_SCHEMA,
    TAIWAN_MEMORY_LEAD_CURATED_SCHEMA,
    TAIWAN_MEMORY_LEAD_RAW_SCHEMA,
)
from stock_data.fetcher.industry.semiconductor.transforms import (
    records_to_memory_benchmark_frame,
    records_to_raw_memory_benchmark_frame,
    records_to_raw_taiwan_memory_lead_frame,
    records_to_taiwan_memory_lead_frame,
)
from stock_data.fetcher.industry.semiconductor.transforms.release_date import (
    require_raw_release_dates,
)
from stock_data.fetcher.industry.task_executor import execute_single_industry_task
from stock_data.governance.audit.backfill_acceptance import accept_backfill


def _sample_datatrack_payload() -> dict:
    return {
        "Mainstream DRAM Spot Price": {
            "indicator_id": 6105,
            "data": {
                "2023-01-31T16:00:00.000Z": "4.726",
                "2023-02-28T16:00:00.000Z": "4.190",
                "2024-01-31T16:00:00.000Z": "4.674",
            },
            "freq": "M",
            "data_source": "TrendForce",
            "inferenced": False,
            "unit": "USD",
        }
    }


def test_parse_datatrack_memory_price_json_keeps_raw_strings() -> None:
    records = parse_datatrack_memory_price_json(
        _sample_datatrack_payload(),
        source_url="https://datatrack-finwhale.trendforce.com:8000/api/v1/data/column?fields=6105",
        collected_at="2026-09-04T00:00:00+00:00",
        raw_content_sha256="sha-6105",
        raw_snapshot_path="semiconductor/datatrack/datatrack_memory_fields_6105.json.gz",
    )

    assert len(records) == 3
    first = records[0]
    assert first.report_month == "2023-01"
    assert first.trade_date == date(2023, 1, 31)
    assert first.product_family == "DRAM"
    assert first.indicator_id == 6105
    assert first.price_usd == 4.726
    # 严格检验 RAW 源字段优先
    assert first.indicator_id_raw == "6105"
    assert first.period_raw == "2023-01-31T16:00:00.000Z"
    assert first.value_raw == "4.726"
    assert first.raw_content_sha256 == "sha-6105"
    assert first.release_date is None
    assert first.release_date_status == "unavailable"


def test_memory_benchmark_curated_transforms_and_growth_calc() -> None:
    records = parse_datatrack_memory_price_json(
        _sample_datatrack_payload(),
        source_url="https://datatrack-finwhale.trendforce.com:8000/api/v1/data/column?fields=6105",
        collected_at="2026-09-04T00:00:00+00:00",
        raw_content_sha256="sha-6105",
        raw_snapshot_path="semiconductor/datatrack/datatrack_memory_fields_6105.json.gz",
    )

    raw_df = records_to_raw_memory_benchmark_frame(records)
    assert raw_df.columns == list(MEMORY_BENCHMARK_RAW_SCHEMA)
    assert raw_df["value_raw"].to_list()[0] == "4.726"
    assert "price_mom" not in raw_df.columns

    curated_df = records_to_memory_benchmark_frame(records)
    assert curated_df.columns == list(MEMORY_BENCHMARK_CURATED_SCHEMA)

    rows = curated_df.to_dicts()
    # 2023-02 的 MoM: 4.190 / 4.726 - 1.0 = -0.1134
    assert rows[1]["price_mom"] == -0.1134
    # 2024-01 的 YoY: 4.674 / 4.726 - 1.0 = -0.0110
    assert rows[2]["price_yoy"] == -0.0110


def test_memory_benchmark_incremental_transform_keeps_history_for_growth() -> None:
    records = parse_datatrack_memory_price_json(_sample_datatrack_payload())
    existing = records_to_memory_benchmark_frame(records)

    incremental = records_to_memory_benchmark_frame([records[-1]], existing_df=existing)

    assert len(incremental) == len(existing) == 3
    latest = incremental.filter(pl.col("report_month") == "2024-01").to_dicts()[0]
    assert latest["price_yoy"] == -0.0110


def test_taiwan_memory_incremental_transform_keeps_history_for_derived_fields(
    monkeypatch,
) -> None:
    rows = [
        {"report_month_raw": "113/01", "net_revenue_raw": "2,500,000"},
        {"report_month_raw": "113/02", "net_revenue_raw": "2,750,000"},
        {"report_month_raw": "113/03", "net_revenue_raw": "3,025,000"},
    ]
    records = parse_taiwan_memory_monthly_revenue_dict(rows, symbol="2408")
    monkeypatch.setattr(
        "stock_data.pipeline.normalizer.unit_normalizer.monthly_usdtwd_rate",
        lambda _month, runtime=None: 32.0,
    )
    existing = records_to_taiwan_memory_lead_frame(records)

    incremental = records_to_taiwan_memory_lead_frame(
        [records[-1]],
        existing_df=existing,
    )

    assert len(incremental) == len(existing) == 3
    latest = incremental.filter(pl.col("report_month") == "2024-03").to_dicts()[0]
    assert latest["revenue_mom"] == 0.1
    assert latest["revenue_3mma_usd"] == 86.2


def test_memory_benchmark_endpoint_writes_raw_and_curated(tmp_path, monkeypatch) -> None:
    class DummyResp:
        status_code = 200
        content = json.dumps(_sample_datatrack_payload()).encode("utf-8")
        text = json.dumps(_sample_datatrack_payload())

    monkeypatch.setattr("curl_cffi.requests.get", lambda *args, **kwargs: DummyResp())

    collector = DataTrackMemoryPriceCollector(raw_dir=tmp_path / "raw")
    direct_records = collector.collect()
    assert len(direct_records) > 0

    count = execute_single_industry_task(
        endpoint="semiconductor_memory_benchmark",
        raw_dir=tmp_path / "raw",
        curated_dir=tmp_path / "curated",
    )

    # 2 个字段 fields=6105 和 fields=6106 各产出 3 行，去重后为相应行数
    assert count > 0
    raw_path = (
        tmp_path / "raw" / "semiconductor" / "price" / "semiconductor_memory_benchmark.parquet"
    )
    curated_path = (
        tmp_path / "curated" / "semiconductor" / "price" / "semiconductor_memory_benchmark.parquet"
    )
    assert raw_path.exists()
    assert curated_path.exists()

    raw = pl.read_parquet(raw_path)
    curated = pl.read_parquet(curated_path)
    assert raw.columns == list(MEMORY_BENCHMARK_RAW_SCHEMA)
    assert curated.columns == list(MEMORY_BENCHMARK_CURATED_SCHEMA)


def test_taiwan_memory_lead_endpoint_and_transforms(tmp_path, monkeypatch) -> None:
    sample_mops_rows = [
        {
            "report_month_raw": "113/01",
            "net_revenue_raw": "2,500,000",
            "last_year_revenue_raw": "2,000,000",
            "yoy_change_raw": "25.00%",
            "mom_change_raw": "-5.00%",
            "release_date_raw": "115/09/04 20:31:43",
        },
        {
            "report_month_raw": "113/02",
            "net_revenue_raw": "2,750,000",
            "last_year_revenue_raw": "2,200,000",
            "yoy_change_raw": "25.00%",
            "mom_change_raw": "10.00%",
            "release_date_raw": "115/09/04 20:31:43",
        },
    ]

    records = parse_taiwan_memory_monthly_revenue_dict(
        sample_mops_rows,
        symbol="2408",
        source_url="https://mops.twse.com.tw",
        collected_at="2026-09-04T00:00:00+00:00",
        raw_content_sha256="sha-2408",
        raw_snapshot_path="semiconductor/taiwan_memory/2408.html.gz",
    )

    assert len(records) == 2
    rec = records[0]
    assert rec.report_month == "2024-01"
    assert rec.symbol == "2408"
    assert rec.company_name == "南亚科技"
    assert rec.revenue_ntd_thousand == 2500000.0
    assert rec.revenue_ntd_million is None
    assert rec.revenue_yoy == 0.25
    assert rec.net_revenue_raw == "2,500,000"

    raw_df = records_to_raw_taiwan_memory_lead_frame(records)
    curated_df = records_to_taiwan_memory_lead_frame(records)
    assert raw_df.columns == list(TAIWAN_MEMORY_LEAD_RAW_SCHEMA)
    assert curated_df.columns == list(TAIWAN_MEMORY_LEAD_CURATED_SCHEMA)
    assert curated_df["revenue_ntd_million"].to_list()[1] == 2750.0

    # 模拟端点调度执行
    monkeypatch.setattr(
        TaiwanMemoryLeadCollector,
        "_collect_company",
        lambda self, target, start_year, end_year: records,
    )

    count = execute_single_industry_task(
        endpoint="semiconductor_memory_taiwan_lead",
        raw_dir=tmp_path / "raw",
        curated_dir=tmp_path / "curated",
    )
    assert count == 2
    assert (
        tmp_path
        / "curated"
        / "semiconductor"
        / "price"
        / "semiconductor_memory_taiwan_lead.parquet"
    ).exists()


def test_mops_row_preserves_response_datetime_and_duplicate_percentages() -> None:
    row = _extract_mops_result_row(
        {
            "companyAbbreviation": "威剛",
            "yymm": "11507",
            "data": [
                ["本月", "18,379,079"],
                ["去年同期", "4,261,406"],
                ["增減百分比", "331.29"],
                ["本年累計", "82,650,603"],
                ["增減百分比", "206.73"],
            ],
        },
        symbol="3260",
        response_datetime_raw="115/09/04 20:31:44",
    )

    assert row is not None
    assert row["yoy_change_raw"] == "331.29"
    assert row["cumulative_yoy_raw"] == "206.73"
    assert row["source_response_datetime_raw"] == "115/09/04 20:31:44"
    records = parse_taiwan_memory_monthly_revenue_dict([row], symbol="3260")
    assert records[0].release_date is None
    assert records[0].release_date_status == "unavailable"
    assert records[0].source_response_datetime_raw == "115/09/04 20:31:44"
    assert records[0].revenue_ntd_thousand == 18379079.0
    assert records[0].revenue_ntd_million is None
    assert records[0].revenue_yoy == 3.3129


def test_datatrack_collector_limits_requested_window(tmp_path, monkeypatch) -> None:
    collector = DataTrackMemoryPriceCollector(raw_dir=tmp_path / "raw")
    calls: list[tuple[int, date | None, date | None]] = []

    def collect_field(field_id: int, *, start_date=None, end_date=None):
        calls.append((field_id, start_date, end_date))
        return []

    monkeypatch.setattr(collector, "_collect_field", collect_field)
    assert (
        collector.collect(
            force=True,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
        )
        == []
    )
    assert calls == [
        (6105, date(2026, 7, 1), date(2026, 7, 31)),
        (6106, date(2026, 7, 1), date(2026, 7, 31)),
    ]


def test_taiwan_collector_limits_requested_year_and_month_window(tmp_path, monkeypatch) -> None:
    collector = TaiwanMemoryLeadCollector(raw_dir=tmp_path / "raw")
    calls: list[tuple[str, int, int, date | None, date | None]] = []

    def collect_company(
        self,
        target,
        *,
        start_year,
        end_year,
        start_date=None,
        end_date=None,
    ):
        del self
        calls.append((target["symbol"], start_year, end_year, start_date, end_date))
        return []

    monkeypatch.setattr(TaiwanMemoryLeadCollector, "_collect_company", collect_company)
    assert (
        collector.collect(
            force=True,
            start_date=date(2025, 2, 1),
            end_date=date(2025, 3, 15),
        )
        == []
    )
    assert calls == [
        ("2408", 2025, 2025, date(2025, 2, 1), date(2025, 3, 15)),
        ("3260", 2025, 2025, date(2025, 2, 1), date(2025, 3, 15)),
    ]

    calls.clear()
    assert collector.collect(force=True) == []
    assert calls[0][1] == 2016
    assert calls[1][1] == 2016


def test_industry_runtime_controls_semiconductor_storage_paths(tmp_path, monkeypatch) -> None:
    records = parse_datatrack_memory_price_json(_sample_datatrack_payload())
    runtime = DataRuntimeContext.from_root(tmp_path / "runtime")
    calls: dict[str, object] = {}

    def collect(self, force=False, start_date=None, end_date=None):
        del self
        calls.update(force=force, start_date=start_date, end_date=end_date)
        return records

    monkeypatch.setattr(DataTrackMemoryPriceCollector, "collect", collect)
    count = execute_single_industry_task(
        endpoint="semiconductor_memory_benchmark",
        start_date=date(2023, 1, 1),
        end_date=date(2024, 1, 31),
        force_refresh=True,
        raw_dir=tmp_path / "ignored-raw",
        curated_dir=tmp_path / "ignored-curated",
        runtime=runtime,
    )

    assert count == len(records)
    assert calls == {
        "force": True,
        "start_date": date(2023, 1, 1),
        "end_date": date(2024, 1, 31),
    }
    assert (
        runtime.raw_root / "industry/semiconductor/price/semiconductor_memory_benchmark.parquet"
    ).exists()
    assert (
        runtime.curated_root / "industry/semiconductor/price/semiconductor_memory_benchmark.parquet"
    ).exists()
    assert not (tmp_path / "ignored-raw").exists()


def test_memory_benchmark_acceptance_maps_raw_indicator_key(tmp_path) -> None:
    records = parse_datatrack_memory_price_json(_sample_datatrack_payload())
    raw_root = tmp_path / "raw"
    curated_root = tmp_path / "curated"
    raw_path = (
        raw_root / "industry" / "semiconductor" / "price" / "semiconductor_memory_benchmark.parquet"
    )
    curated_path = (
        curated_root
        / "industry"
        / "semiconductor"
        / "price"
        / "semiconductor_memory_benchmark.parquet"
    )
    raw_path.parent.mkdir(parents=True)
    curated_path.parent.mkdir(parents=True)
    records_to_raw_memory_benchmark_frame(records).write_parquet(raw_path)
    records_to_memory_benchmark_frame(records).write_parquet(curated_path)

    result = accept_backfill(
        root=str(curated_root),
        raw_root=str(raw_root),
        endpoint="semiconductor_memory_benchmark",
        data_source="industry",
    )

    assert result["status"] == "PASSED"
    assert result["raw_curated_status"] == "PASSED"
    assert result["raw_key_count"] == result["curated_key_count"] == 3


def test_release_date_gate_requires_explicit_status_and_source_date() -> None:
    unavailable = pl.DataFrame(
        {
            "release_date": [None],
            "release_date_raw": [None],
            "release_date_status": ["unavailable"],
        },
        schema={
            "release_date": pl.Date,
            "release_date_raw": pl.String,
            "release_date_status": pl.String,
        },
    )
    assert require_raw_release_dates(
        unavailable,
        "semiconductor_memory_benchmark",
        allow_unavailable=True,
    ).equals(unavailable)
    assert require_raw_release_dates(
        unavailable,
        "semiconductor_memory_taiwan_lead",
        allow_unavailable=True,
    ).equals(unavailable)

    reported_without_raw = pl.DataFrame(
        {
            "release_date": [date(2026, 9, 4)],
            "release_date_raw": [None],
            "release_date_status": ["reported"],
        },
        schema={
            "release_date": pl.Date,
            "release_date_raw": pl.String,
            "release_date_status": pl.String,
        },
    )
    with pytest.raises(ValueError, match="release_date_raw"):
        require_raw_release_dates(reported_without_raw, "semiconductor_memory_taiwan_lead")


def test_datatrack_release_calendar_loader() -> None:
    from stock_data.fetcher.industry.semiconductor.datatrack_calendar import (
        load_datatrack_release_calendar,
    )

    calendar = load_datatrack_release_calendar()
    assert len(calendar) == 61
    assert "2021-08" in calendar
    assert calendar["2021-08"] == date(2021, 9, 3)
    assert "2022-12" in calendar
    assert calendar["2022-12"] == date(2023, 1, 4)
    assert "2026-07" in calendar
    assert calendar["2026-07"] == date(2026, 8, 5)
    assert "2026-08" in calendar
    assert calendar["2026-08"] == date(2026, 9, 3)
    for _m, d in calendar.items():
        assert isinstance(d, date)
        assert d.weekday() < 5  # 周一至周五平日


def test_memory_benchmark_curated_proxy_calendar_mapping() -> None:
    records = parse_datatrack_memory_price_json(_sample_datatrack_payload())
    curated_df = records_to_memory_benchmark_frame(records)

    # 2023-01 应被映射为 2023-02-03, 状态为 proxy_calendar
    jan = curated_df.filter(pl.col("report_month") == "2023-01").to_dicts()[0]
    assert jan["release_date"] == date(2023, 2, 3)
    assert jan["release_date_status"] == "proxy_calendar"

    # 2023-02 应被映射为 2023-03-03
    feb = curated_df.filter(pl.col("report_month") == "2023-02").to_dicts()[0]
    assert feb["release_date"] == date(2023, 3, 3)
    assert feb["release_date_status"] == "proxy_calendar"

    # 2024-01 应被映射为 2024-02-05
    jan24 = curated_df.filter(pl.col("report_month") == "2024-01").to_dicts()[0]
    assert jan24["release_date"] == date(2024, 2, 5)
    assert jan24["release_date_status"] == "proxy_calendar"

    # 若记录本身已有 reported release_date，优先保留
    reported_record = records[0].__class__(
        report_month="2023-01",
        trade_date=date(2023, 1, 31),
        product_family="DRAM",
        indicator_id=6105,
        indicator_name="Mainstream DRAM Spot Price",
        price_usd=4.726,
        release_date=date(2023, 2, 1),
        release_date_status="reported",
    )
    custom_df = records_to_memory_benchmark_frame([reported_record])
    assert custom_df["release_date"][0] == date(2023, 2, 1)
    assert custom_df["release_date_status"][0] == "reported"
