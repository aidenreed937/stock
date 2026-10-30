"""云厂商季度 CapEx 的历史回填、缓存与 RAW/Curated 契约测试。"""

from datetime import date

import polars as pl

from stock_data.fetcher.industry.cloud import (
    CLOUD_CAPEX_RAW_SCHEMA,
    CloudCapexCollector,
    CloudCapexRecord,
    build_cloud_capex_curated_frame,
    records_to_raw_cloud_capex_frame,
)
from stock_data.fetcher.industry.cloud.registry import ENDPOINT_SPECS
from stock_data.fetcher.industry.contracts import IndustryRunContext
from stock_data.fetcher.industry.runner import run_endpoint


def _record(report_quarter: str, value: float = 10.0) -> CloudCapexRecord:
    year, quarter = report_quarter.split("-Q")
    month = int(quarter) * 3
    trade_date = date(int(year), month, 30 if month in (6, 9) else 31)
    release_year = int(year) + 1 if month == 12 else int(year)
    release_month = 1 if month == 12 else month + 1
    return CloudCapexRecord(
        report_quarter=report_quarter,
        trade_date=trade_date,
        total_capex_billion_usd=value * 4,
        msft_capex_billion_usd=value,
        goog_capex_billion_usd=value,
        meta_capex_billion_usd=value,
        amzn_capex_billion_usd=value,
        release_date=date(release_year, release_month, 20),
        msft_release_date=date(release_year, release_month, 10),
        goog_release_date=date(release_year, release_month, 11),
        meta_release_date=date(release_year, release_month, 12),
        amzn_release_date=date(release_year, release_month, 20),
        raw_content_sha256="sha",
        raw_snapshot_path="cloud/sec_edgar/company.json.gz",
    )


def _records_from_2023_q1_to_2024_q1() -> list[CloudCapexRecord]:
    return [
        _record(f"{year}-Q{quarter}", value=float(index + 10))
        for index, (year, quarter) in enumerate(
            [
                (2023, 1),
                (2023, 2),
                (2023, 3),
                (2023, 4),
                (2024, 1),
            ]
        )
    ]


def test_cloud_capex_registry_declares_context_collection_and_raw_layer() -> None:
    assert len(ENDPOINT_SPECS) == 1
    spec = ENDPOINT_SPECS[0]
    assert spec.endpoint == "cloud_capex_quarterly"
    assert spec.raw_subdir == "cloud"


def test_cloud_capex_raw_transform_keeps_source_fields_only() -> None:
    raw = records_to_raw_cloud_capex_frame([_record("2024-Q1")])

    assert raw.schema == CLOUD_CAPEX_RAW_SCHEMA
    assert raw["msft_capex_raw"].to_list() == ["10.0"]
    assert raw["amzn_release_date"].to_list() == [date(2024, 4, 20)]
    assert raw["raw_content_sha256"].to_list() == ["sha"]
    assert "total_capex_billion_usd" not in raw.columns
    assert "yoy_growth" not in raw.columns
    assert "qoq_growth" not in raw.columns


def test_extract_sec_metric_converts_ytd_to_single_quarter() -> None:
    from stock_data.fetcher.industry.cloud.parser import (
        extract_sec_quarterly_metric_with_filing_dates,
    )

    facts = {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {
                                "form": "10-Q",
                                "start": "2026-01-01",
                                "end": "2026-03-31",
                                "filed": "2026-04-30",
                                "val": 100_000_000_000,
                            },
                            {
                                "form": "10-Q",
                                "start": "2026-01-01",
                                "end": "2026-06-30",
                                "filed": "2026-07-30",
                                "val": 250_000_000_000,
                            },
                        ]
                    }
                }
            }
        }
    }

    result = extract_sec_quarterly_metric_with_filing_dates(
        facts,
        "META",
        ("RevenueFromContractWithCustomerExcludingAssessedTax",),
        positive_only=True,
    )

    assert result["2026-Q1"] == (100.0, date(2026, 4, 30))
    assert result["2026-Q2"] == (150.0, date(2026, 7, 30))


def test_extract_sec_metric_uses_first_filing_for_repeated_comparative_period() -> None:
    from stock_data.fetcher.industry.cloud.parser import (
        extract_sec_quarterly_metric_with_filing_dates,
    )

    facts = {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {
                                "form": "10-Q",
                                "start": "2025-01-01",
                                "end": "2025-03-31",
                                "filed": "2025-04-30",
                                "val": 100_000_000_000,
                            },
                            {
                                "form": "10-Q",
                                "start": "2025-01-01",
                                "end": "2025-03-31",
                                "filed": "2026-04-29",
                                "val": 101_000_000_000,
                            },
                            {
                                "form": "10-Q",
                                "start": "2025-01-01",
                                "end": "2025-06-30",
                                "filed": "2025-07-30",
                                "val": 250_000_000_000,
                            },
                            {
                                "form": "10-Q",
                                "start": "2025-01-01",
                                "end": "2025-06-30",
                                "filed": "2026-07-29",
                                "val": 251_000_000_000,
                            },
                        ]
                    }
                }
            }
        }
    }

    result = extract_sec_quarterly_metric_with_filing_dates(
        facts,
        "GOOGL",
        ("RevenueFromContractWithCustomerExcludingAssessedTax",),
        positive_only=True,
    )

    assert result["2025-Q1"] == (100.0, date(2025, 4, 30))
    assert result["2025-Q2"] == (150.0, date(2025, 7, 30))


def test_extract_sec_metric_accepts_amended_filing_when_no_original_exists() -> None:
    from stock_data.fetcher.industry.cloud.parser import (
        extract_sec_quarterly_metric_with_filing_dates,
    )

    facts = {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {
                                "form": "10-Q/A",
                                "start": "2025-01-01",
                                "end": "2025-03-31",
                                "filed": "2025-05-05",
                                "val": 100_000_000_000,
                            }
                        ]
                    }
                }
            }
        }
    }

    result = extract_sec_quarterly_metric_with_filing_dates(
        facts,
        "META",
        ("RevenueFromContractWithCustomerExcludingAssessedTax",),
        positive_only=True,
    )

    assert result["2025-Q1"] == (100.0, date(2025, 5, 5))


def test_cloud_capex_range_keeps_four_quarters_for_growth_context(tmp_path) -> None:
    collector = CloudCapexCollector(tmp_path / "raw")
    calls: list[str] = []
    records = _records_from_2023_q1_to_2024_q1()
    by_ticker = {
        ticker: {
            record.report_quarter: (
                record.msft_capex_billion_usd or 0.0,
                record.msft_release_date,
            )
            for record in records
        }
        for ticker in ("MSFT", "GOOGL", "META", "AMZN")
    }

    def fake_fetch(ticker: str, _cik: str):
        calls.append(ticker)
        return by_ticker[ticker]

    collector._fetch_or_load_company = fake_fetch  # type: ignore[method-assign]
    raw = collector.collect_raw(
        start_date=date(2024, 1, 1),
        end_date=date(2024, 3, 31),
    )

    assert raw["report_quarter"].to_list() == [
        "2023-Q1",
        "2023-Q2",
        "2023-Q3",
        "2023-Q4",
        "2024-Q1",
    ]
    assert calls == ["MSFT", "GOOGL", "META", "AMZN"]
    curated = build_cloud_capex_curated_frame(raw)
    assert curated.filter(pl.col("report_quarter") == "2024-Q1")["yoy_growth"][0] is not None


def test_cloud_capex_non_force_reuses_complete_structured_raw_without_fetch(tmp_path) -> None:
    raw_dir = tmp_path / "raw"
    raw_path = raw_dir / "cloud" / "cloud_capex_quarterly.parquet"
    raw_path.parent.mkdir(parents=True)
    records_to_raw_cloud_capex_frame(_records_from_2023_q1_to_2024_q1()).write_parquet(raw_path)

    collector = CloudCapexCollector(raw_dir)

    def fail_fetch(*_args, **_kwargs):
        raise AssertionError("完整 RAW 缓存命中时不应请求 SEC")

    collector._fetch_or_load_company = fail_fetch  # type: ignore[method-assign]
    raw = collector.collect_raw(
        start_date=date(2024, 1, 1),
        end_date=date(2024, 3, 31),
    )

    assert raw.height == 5


def test_cloud_capex_force_refresh_bypasses_structured_raw_cache(tmp_path) -> None:
    raw_dir = tmp_path / "raw"
    raw_path = raw_dir / "cloud" / "cloud_capex_quarterly.parquet"
    raw_path.parent.mkdir(parents=True)
    records_to_raw_cloud_capex_frame(_records_from_2023_q1_to_2024_q1()).write_parquet(raw_path)

    collector = CloudCapexCollector(raw_dir)
    calls: list[str] = []
    records = _records_from_2023_q1_to_2024_q1()
    company_data = {
        record.report_quarter: (record.msft_capex_billion_usd or 0.0, record.msft_release_date)
        for record in records
    }

    def fake_fetch(ticker: str, _cik: str):
        calls.append(ticker)
        return company_data

    collector._fetch_or_load_company = fake_fetch  # type: ignore[method-assign]
    raw = collector.collect_raw(
        force=True,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 3, 31),
    )

    assert raw.height == 5
    assert calls == ["MSFT", "GOOGL", "META", "AMZN"]


def test_cloud_capex_endpoint_writes_separate_raw_and_curated_layers(tmp_path, monkeypatch) -> None:
    records = _records_from_2023_q1_to_2024_q1()
    raw = records_to_raw_cloud_capex_frame(records)
    monkeypatch.setattr(CloudCapexCollector, "collect_raw", lambda self, **_kwargs: raw)

    spec = ENDPOINT_SPECS[0]
    count = run_endpoint(
        spec,
        IndustryRunContext(
            endpoint=spec.endpoint,
            raw_dir=tmp_path / "raw",
            curated_dir=tmp_path / "curated",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 3, 31),
        ),
    )

    assert count == 5
    raw_saved = pl.read_parquet(tmp_path / "raw" / "cloud" / "cloud_capex_quarterly.parquet")
    curated_saved = pl.read_parquet(tmp_path / "curated" / "cloud_capex_quarterly.parquet")
    assert raw_saved.schema == CLOUD_CAPEX_RAW_SCHEMA
    assert "total_capex_billion_usd" not in raw_saved.columns
    assert "yoy_growth" in curated_saved.columns
    assert "msft_capex_raw" not in curated_saved.columns


def test_cloud_capex_incremental_run_preserves_historical_growth(tmp_path, monkeypatch) -> None:
    # 1. 预置包含 2023-Q1 ~ 2024-Q1 的既有黄金表
    records_initial = _records_from_2023_q1_to_2024_q1()
    curated_dir = tmp_path / "curated"
    curated_dir.mkdir(parents=True, exist_ok=True)
    curated_path = curated_dir / "cloud_capex_quarterly.parquet"
    build_cloud_capex_curated_frame(records_initial).write_parquet(curated_path)

    # 验证初始状态下 2024-Q1 有 yoy
    initial_df = pl.read_parquet(curated_path)
    assert initial_df.filter(pl.col("report_quarter") == "2024-Q1")["yoy_growth"][0] is not None

    # 2. 模拟增量同步 2024-Q2：collect_raw 仅返回 2023-Q2 ~ 2024-Q2 切片（前4季上下文+目标季）
    q2_record = _record("2024-Q2", value=15.0)
    incremental_records = records_initial[1:] + [q2_record]
    incremental_raw = records_to_raw_cloud_capex_frame(incremental_records)
    monkeypatch.setattr(CloudCapexCollector, "collect_raw", lambda self, **_kwargs: incremental_raw)

    spec = ENDPOINT_SPECS[0]
    run_endpoint(
        spec,
        IndustryRunContext(
            endpoint=spec.endpoint,
            raw_dir=tmp_path / "raw",
            curated_dir=curated_dir,
            start_date=date(2024, 4, 1),
            end_date=date(2024, 6, 30),
        ),
    )

    # 3. 验证落盘黄金表：既有的 2024-Q1 以及新增的 2024-Q2 的同比与环比均健康完整，未被污染为 None
    updated_curated = pl.read_parquet(curated_path)
    assert updated_curated.height == 6
    assert updated_curated["report_quarter"].to_list() == [
        "2023-Q1",
        "2023-Q2",
        "2023-Q3",
        "2023-Q4",
        "2024-Q1",
        "2024-Q2",
    ]
    assert (
        updated_curated.filter(pl.col("report_quarter") == "2024-Q1")["yoy_growth"][0] is not None
    )
    assert (
        updated_curated.filter(pl.col("report_quarter") == "2024-Q2")["yoy_growth"][0] is not None
    )
    assert (
        updated_curated.filter(pl.col("report_quarter") == "2024-Q1")["qoq_growth"][0] is not None
    )
    assert (
        updated_curated.filter(pl.col("report_quarter") == "2024-Q2")["qoq_growth"][0] is not None
    )
