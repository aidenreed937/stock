"""半导体产业端点 RAW/Curated 两层落盘契约测试。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.contracts import IndustryRunContext
from stock_data.fetcher.industry.runner import (
    context_collector,
    frame_endpoint,
    record_endpoint,
    run_endpoint,
)
from stock_data.fetcher.industry.semiconductor.models import (
    ChipLeadTimeRecord,
    SemiconductorEquipmentRecord,
    SemiconductorSalesRecord,
)
from stock_data.fetcher.industry.semiconductor.registry import ENDPOINT_SPECS
from stock_data.fetcher.industry.semiconductor.schemas import (
    CHANNEL_INVENTORY_RAW_SCHEMA,
    CHIP_LEAD_TIME_RAW_SCHEMA,
    FOUNDRY_RAW_SCHEMA,
    INVENTORY_RAW_SCHEMA,
    MEMORY_PRICE_RAW_SCHEMA,
    SEMI_EQUIPMENT_RAW_SCHEMA,
    SEMICONDUCTOR_EQUIPMENT_RAW_SCHEMA,
    SEMICONDUCTOR_LEAD_RAW_SCHEMA,
    SEMICONDUCTOR_SALES_RAW_SCHEMA,
)
from stock_data.fetcher.industry.semiconductor.transforms import (
    build_inventory_raw_frame,
    build_semi_equipment_curated_frame,
    records_to_chip_lead_time_frame,
    records_to_raw_chip_lead_time_frame,
    records_to_raw_semiconductor_equipment_frame,
    records_to_raw_semiconductor_frame,
    records_to_semiconductor_frame,
)


def test_semiconductor_endpoints_declare_shared_raw_subdir() -> None:
    specs = {spec.endpoint: spec for spec in ENDPOINT_SPECS}

    assert set(specs) == {
        "semiconductor_sales",
        "semiconductor_equipment",
        "semiconductor_lead",
        "chip_lead_time",
        "semiconductor_equipment_semi",
        "foundry_capacity_utilization",
        "semiconductor_inventory_days",
        "semiconductor_channel_inventory",
        "semiconductor_memory_price",
        "semiconductor_memory_benchmark",
        "semiconductor_memory_taiwan_lead",
        "tsmc_advanced_packaging_revenue",
        "tsmc_cowos_capacity_estimates",
        "semiconductor_equipment_gm_amat",
        "semiconductor_equipment_gm_lrcx",
        "semiconductor_equipment_gm_klac",
        "tel_gm_quarterly",
    }
    core_specs = {
        endpoint: spec
        for endpoint, spec in specs.items()
        if endpoint
        not in {
            "semiconductor_equipment_gm_amat",
            "semiconductor_equipment_gm_lrcx",
            "semiconductor_equipment_gm_klac",
            "tel_gm_quarterly",
        }
    }
    assert all(spec.raw_subdir.startswith("semiconductor/") for spec in core_specs.values())
    assert {spec.raw_subdir for spec in core_specs.values()} == {
        "semiconductor/sales",
        "semiconductor/equipment",
        "semiconductor/capacity",
        "semiconductor/inventory",
        "semiconductor/price",
    }
    assert {spec.target_file for spec in specs.values()} == {
        "semiconductor/sales/semiconductor_sales.parquet",
        "semiconductor/equipment/semiconductor_equipment.parquet",
        "semiconductor/sales/semiconductor_lead.parquet",
        "semiconductor/capacity/chip_lead_time.parquet",
        "semiconductor/equipment/semiconductor_equipment_semi.parquet",
        "semiconductor/capacity/foundry_capacity_utilization.parquet",
        "semiconductor/inventory/semiconductor_inventory_days.parquet",
        "semiconductor/inventory/semiconductor_channel_inventory.parquet",
        "semiconductor/price/semiconductor_memory_price.parquet",
        "semiconductor/price/semiconductor_memory_benchmark.parquet",
        "semiconductor/price/semiconductor_memory_taiwan_lead.parquet",
        "semiconductor/capacity/tsmc_advanced_packaging_revenue.parquet",
        "semiconductor/capacity/tsmc_cowos_capacity_estimates.parquet",
        "semiconductor/equipment/semiconductor_equipment_gm_amat.parquet",
        "semiconductor/equipment/semiconductor_equipment_gm_lrcx.parquet",
        "semiconductor/equipment/semiconductor_equipment_gm_klac.parquet",
        "semiconductor/equipment/tel_gm_quarterly.parquet",
    }


def test_online_semiconductor_raw_business_fields_are_source_strings() -> None:
    raw_business_fields = {
        **{
            name: dtype
            for name, dtype in SEMICONDUCTOR_SALES_RAW_SCHEMA.items()
            if name.endswith("_raw")
        },
        **{
            name: dtype
            for name, dtype in SEMICONDUCTOR_LEAD_RAW_SCHEMA.items()
            if name.endswith("_raw")
        },
        **{
            name: dtype
            for name, dtype in CHIP_LEAD_TIME_RAW_SCHEMA.items()
            if name.endswith("_raw")
        },
        **{
            name: dtype
            for name, dtype in SEMICONDUCTOR_EQUIPMENT_RAW_SCHEMA.items()
            if name.endswith("_raw")
        },
        **{
            name: dtype
            for name, dtype in SEMI_EQUIPMENT_RAW_SCHEMA.items()
            if name.endswith("_raw")
        },
        **{name: dtype for name, dtype in FOUNDRY_RAW_SCHEMA.items() if name.endswith("_raw")},
        **{name: dtype for name, dtype in INVENTORY_RAW_SCHEMA.items() if name.endswith("_raw")},
        **{
            name: dtype
            for name, dtype in CHANNEL_INVENTORY_RAW_SCHEMA.items()
            if name.endswith("_raw")
        },
        **{name: dtype for name, dtype in MEMORY_PRICE_RAW_SCHEMA.items() if name.endswith("_raw")},
    }

    assert raw_business_fields
    assert set(raw_business_fields.values()) == {pl.String}


def test_sales_raw_transform_keeps_source_strings_and_curated_derives_growth() -> None:
    records = [
        SemiconductorSalesRecord(
            report_month="2025-06",
            trade_date=date(2025, 6, 30),
            global_sales_usd=40.0,
            release_date=date(2025, 8, 1),
            raw_content_sha256="sha-2025-06",
            raw_snapshot_path="sia/WSTS-Historical-Billings-Report-Jun_2026.xlsx",
            worldwide_raw="40,000,000",
            americas_raw="12,000,000",
            europe_raw="8,000,000",
            japan_raw="7,000,000",
            asia_pacific_raw="13,000,000",
            china_sales_raw="$12.00 billion",
            china_yoy_growth_raw="10.0%",
            china_mom_growth_raw="2.0%",
        ),
        SemiconductorSalesRecord(
            report_month="2026-06",
            trade_date=date(2026, 6, 30),
            global_sales_usd=999.0,
            release_date=date(2026, 8, 6),
            raw_content_sha256="sha-2026-06",
            raw_snapshot_path="sia/WSTS-Historical-Billings-Report-Jun_2026.xlsx",
            worldwide_raw="51,000,000",
            americas_raw="15,000,000",
            europe_raw="9,000,000",
            japan_raw="8,000,000",
            asia_pacific_raw="19,000,000",
            china_sales_raw="$15.00 billion",
            china_yoy_growth_raw="28.8%",
            china_mom_growth_raw="10.4%",
        ),
    ]

    raw = records_to_raw_semiconductor_frame(records)
    assert raw.columns == list(SEMICONDUCTOR_SALES_RAW_SCHEMA)
    assert raw["worldwide_raw"].to_list() == ["40,000,000", "51,000,000"]
    assert raw["china_sales_raw"].to_list() == ["$12.00 billion", "$15.00 billion"]
    assert raw["raw_content_sha256"].to_list() == ["sha-2025-06", "sha-2026-06"]
    assert "global_sales_usd" not in raw.columns
    assert "yoy_growth" not in raw.columns
    assert "mom_growth" not in raw.columns

    curated = records_to_semiconductor_frame(records)
    latest = curated.filter(pl.col("report_month") == "2026-06").to_dicts()[0]
    assert latest["global_sales_usd"] == 51.0
    assert latest["china_sales_usd"] == 15.0
    assert latest["china_yoy_growth"] == 0.288
    assert latest["china_mom_growth"] == 0.104
    assert latest["yoy_growth"] == 0.275


def test_sales_raw_transform_preserves_unknown_wsts_release_date_as_null() -> None:
    record = SemiconductorSalesRecord(
        report_month="1986-01",
        trade_date=date(1986, 1, 31),
        global_sales_usd=1.724,
        worldwide_raw="1724274.6666666667",
    )

    raw = records_to_raw_semiconductor_frame([record])

    assert raw.height == 1
    assert raw["release_date"].null_count() == 1
    assert raw["worldwide_raw"][0] == "1724274.6666666667"


def test_sales_curated_preserves_negative_sia_growth_context() -> None:
    record = SemiconductorSalesRecord(
        report_month="2019-01",
        trade_date=date(2019, 1, 31),
        global_sales_usd=25.0,
        china_yoy_growth=-0.105,
        china_yoy_growth_raw="10.5%",
    )

    curated = records_to_semiconductor_frame([record])

    assert curated["china_yoy_growth"][0] == -0.105


def test_record_endpoint_writes_raw_before_curated(tmp_path) -> None:
    record = ChipLeadTimeRecord(
        report_month="2026-07",
        trade_date=date(2026, 7, 31),
        avg_lead_time_weeks=21.0,
        mcu_lead_time_weeks=20.0,
        analog_lead_time_weeks=22.0,
        release_date=date(2026, 8, 20),
    )
    spec = record_endpoint(
        endpoint="chip_lead_time",
        domain="semiconductor",
        collect=lambda _raw_dir, _force: [record],
        raw_transform=records_to_raw_chip_lead_time_frame,
        transform=records_to_chip_lead_time_frame,
        target_file="chip_lead_time.parquet",
        primary_keys=["report_month"],
        raw_subdir="semiconductor",
    )

    count = run_endpoint(
        spec,
        IndustryRunContext(
            endpoint=spec.endpoint,
            raw_dir=tmp_path / "raw",
            curated_dir=tmp_path / "curated",
        ),
    )

    assert count == 1
    raw = pl.read_parquet(tmp_path / "raw" / "semiconductor" / "chip_lead_time.parquet")
    curated = pl.read_parquet(tmp_path / "curated" / "chip_lead_time.parquet")
    assert "lead_time_raw" in raw.columns
    assert "avg_lead_time_weeks" not in raw.columns
    assert "mcu_lead_time_weeks" not in raw.columns
    assert "lead_time_status" not in raw.columns
    assert "lead_time_mom_weeks" not in raw.columns
    assert "lead_time_status" in curated.columns


def test_frame_endpoint_writes_raw_frame_without_curated_columns(tmp_path) -> None:
    raw = pl.DataFrame(
        [
            {
                "report_quarter": "2024-Q1",
                "trade_date": date(2024, 3, 31),
                "global_billings_raw": "US$27.10 billion",
                "china_billings_raw": "$9.00 billion",
                "yoy_growth_raw": None,
                "qoq_growth_raw": None,
                "source": "SEMI_WWSEMS",
                "source_url": "https://www.semi.org/test",
                "release_date": date(2024, 6, 3),
                "data_status": "actual",
                "collected_at": "2024-06-03T00:00:00Z",
                "raw_content_sha256": "sha-q1",
                "raw_snapshot_path": "semiconductor/semi/q1.html.gz",
            },
            {
                "report_quarter": "2024-Q2",
                "trade_date": date(2024, 6, 30),
                "global_billings_raw": "US$26.88 billion",
                "china_billings_raw": "$9.15 billion",
                "yoy_growth_raw": None,
                "qoq_growth_raw": None,
                "source": "SEMI_WWSEMS",
                "source_url": "https://www.semi.org/test",
                "release_date": date(2024, 9, 2),
                "data_status": "actual",
                "collected_at": "2024-09-02T00:00:00Z",
                "raw_content_sha256": "sha-q2",
                "raw_snapshot_path": "semiconductor/semi/q2.html.gz",
            },
        ],
        schema=SEMI_EQUIPMENT_RAW_SCHEMA,
    )
    spec = frame_endpoint(
        endpoint="semiconductor_equipment_semi",
        domain="semiconductor",
        collect=lambda _raw_dir, _force: raw,
        transform=build_semi_equipment_curated_frame,
        target_file="semiconductor_equipment_semi.parquet",
        primary_keys=["report_quarter"],
        raw_subdir="semiconductor",
        raw_transform=lambda frame: frame,
    )

    run_endpoint(
        spec,
        IndustryRunContext(
            endpoint=spec.endpoint,
            raw_dir=tmp_path / "raw",
            curated_dir=tmp_path / "curated",
        ),
    )

    raw_saved = pl.read_parquet(
        tmp_path / "raw" / "semiconductor" / "semiconductor_equipment_semi.parquet"
    )
    curated_saved = pl.read_parquet(tmp_path / "curated" / "semiconductor_equipment_semi.parquet")
    assert raw_saved.columns == list(SEMI_EQUIPMENT_RAW_SCHEMA)
    assert raw_saved["global_billings_raw"].to_list() == ["US$27.10 billion", "US$26.88 billion"]
    assert "global_billings_billion_usd" not in raw_saved.columns
    assert raw_saved["raw_content_sha256"].to_list() == ["sha-q1", "sha-q2"]
    assert "china_share_pct" not in raw_saved.columns
    assert "china_share_pct" in curated_saved.columns
    assert "raw_content_sha256" not in curated_saved.columns
    assert "raw_snapshot_path" not in curated_saved.columns


def test_frame_endpoint_context_collector_receives_run_window(tmp_path) -> None:
    class RangeCollector:
        calls: list[tuple[bool, date | None, date | None]] = []

        def __init__(self, raw_dir) -> None:
            self.raw_dir = raw_dir

        def collect_raw(
            self,
            force: bool = False,
            start_date: date | None = None,
            end_date: date | None = None,
        ) -> pl.DataFrame:
            self.calls.append((force, start_date, end_date))
            return pl.DataFrame(
                [
                    {
                        "report_quarter": "2025-Q2",
                        "trade_date": date(2025, 6, 30),
                        "global_billings_raw": "US$33.07 billion",
                        "china_billings_raw": None,
                        "yoy_growth_raw": None,
                        "qoq_growth_raw": None,
                        "source": "SEMI_WWSEMS",
                        "source_url": "https://www.semi.org/q2-2025",
                        "release_date": date(2025, 9, 2),
                        "data_status": "actual",
                        "collected_at": "2025-09-02T00:00:00Z",
                        "raw_content_sha256": "sha-q2",
                        "raw_snapshot_path": "semiconductor/semi/q2.html.gz",
                    }
                ],
                schema=SEMI_EQUIPMENT_RAW_SCHEMA,
            )

    spec = frame_endpoint(
        endpoint="semiconductor_equipment_semi",
        domain="semiconductor",
        context_collect=context_collector(RangeCollector, "collect_raw"),
        transform=build_semi_equipment_curated_frame,
        target_file="semiconductor_equipment_semi.parquet",
        primary_keys=["report_quarter"],
        raw_subdir="semiconductor",
        raw_transform=lambda frame: frame,
    )

    run_endpoint(
        spec,
        IndustryRunContext(
            endpoint=spec.endpoint,
            raw_dir=tmp_path / "raw",
            curated_dir=tmp_path / "curated",
            start_date=date(2025, 4, 1),
            end_date=date(2025, 6, 30),
            force_refresh=True,
        ),
    )

    assert RangeCollector.calls == [(True, date(2025, 4, 1), date(2025, 6, 30))]


def test_context_collector_passes_constructor_kwargs() -> None:
    class ConfiguredCollector:
        enabled: bool

        def __init__(self, raw_dir, *, enable_online: bool) -> None:
            self.raw_dir = raw_dir
            self.enabled = enable_online

        def collect_raw(self, force: bool = False) -> pl.DataFrame:
            assert force is True
            assert self.enabled is True
            return pl.DataFrame()

    collect = context_collector(
        ConfiguredCollector,
        "collect_raw",
        constructor_kwargs={"enable_online": True},
    )
    result = collect(
        IndustryRunContext(
            endpoint="test",
            raw_dir=Path("data/raw"),
            curated_dir=Path("data/curated"),
            force_refresh=True,
        )
    )

    assert result.is_empty()


def test_equipment_raw_transform_keeps_source_values_only() -> None:
    record = SemiconductorEquipmentRecord(
        report_month="2026-07",
        trade_date=date(2026, 7, 31),
        billings_3mma_jpy=556.22,
        billings_jpy_raw="556,220",
        yoy_reported="35.4%",
        mom_growth_3mma=0.083,
        mom_reported="8.3%",
        release_date=date(2026, 8, 21),
    )

    raw = records_to_raw_semiconductor_equipment_frame([record])

    assert raw["sales_3mma_raw"][0] == "556,220"
    assert raw["yoy_growth_3mma_raw"][0] == "35.4%"
    assert raw["mom_growth_3mma_raw"][0] == "8.3%"
    assert "raw_content_sha256" in raw.columns
    assert "raw_snapshot_path" in raw.columns
    assert "billings_jpy_raw" not in raw.columns
    assert "billings_3mma_jpy" not in raw.columns
    assert "yoy_growth_3mma" not in raw.columns
    assert "mom_growth_3mma" not in raw.columns


def test_inventory_raw_transform_drops_derived_columns() -> None:
    raw = build_inventory_raw_frame(
        pl.DataFrame(
            {
                "symbol": ["TXN"],
                "report_quarter": ["2026Q1"],
                "trade_date": [date(2026, 3, 31)],
                "inventory_usd_raw": ["3910.0"],
                "cost_of_revenue_usd_raw": ["1840.0"],
                "release_date": [date(2026, 4, 30)],
                "doi_days": [191.2],
                "idm_weighted_doi_days": [158.0],
                "inventory_regime": ["high_overstocked"],
            }
        )
    )

    assert raw.columns == list(INVENTORY_RAW_SCHEMA)
    assert raw["inventory_usd_raw"][0] == "3910.0"
    assert "inventory_usd_million" not in raw.columns
    assert "cost_of_revenue_usd_million" not in raw.columns
    assert "doi_days" not in raw.columns
    assert "idm_weighted_doi_days" not in raw.columns
    assert "inventory_regime" not in raw.columns
