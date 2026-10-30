from datetime import date
from pathlib import Path

import polars as pl

from stock_data.core.task_resolution import resolve_task
from stock_data.fetcher.industry.semiconductor.schemas import (
    SEMICONDUCTOR_EQUIPMENT_GM_MULTI_SCHEMA,
    SEMICONDUCTOR_EQUIPMENT_GM_SCHEMA,
    TEL_GM_QUARTERLY_SCHEMA,
)
from stock_data.governance.quality.gate import QualityGate


def test_equipment_gm_tasks_have_explicit_keys_dates_and_scales() -> None:
    expected = {
        "semiconductor_equipment_gm": (("report_quarter",), ("trade_date", "release_date")),
        "semiconductor_equipment_gm_multi": (
            ("company", "report_quarter"),
            ("release_date",),
        ),
        "tel_gm_quarterly": (("report_quarter",), ("release_date", "period_end")),
    }

    for task_name, (keys, dates) in expected.items():
        task = resolve_task("industry", task_name)
        assert task.primary_keys == keys
        assert task.date_columns == dates
        assert task.units["gross_margin_pct"] == "percent_points"


def test_equipment_gm_atomic_tasks_use_release_watermarks() -> None:
    for task_name, company in (
        ("semiconductor_equipment_gm_amat", "AMAT"),
        ("semiconductor_equipment_gm_lrcx", "LRCX"),
        ("semiconductor_equipment_gm_klac", "KLAC"),
    ):
        task = resolve_task("industry", task_name)
        assert task.primary_keys == ("company", "report_quarter")
        assert task.watermark_column == "release_date"
        assert task.date_columns == ("release_date", "report_period_end")
        assert task.required_columns[0] == "company"
        assert company in task_name.upper()


def test_equipment_gm_bundle_contains_four_atomic_sources() -> None:
    from stock_data.core.task_bundles import resolve_bundle

    assert resolve_bundle("industry", "semiconductor_equipment_gm_bundle").tasks == (
        "semiconductor_equipment_gm_amat",
        "semiconductor_equipment_gm_lrcx",
        "semiconductor_equipment_gm_klac",
        "tel_gm_quarterly",
    )


def test_equipment_gm_schema_constants_match_manual_tables() -> None:
    assert list(SEMICONDUCTOR_EQUIPMENT_GM_SCHEMA) == [
        "report_quarter",
        "trade_date",
        "net_sales_eur_m",
        "gross_profit_eur_m",
        "gross_margin_pct",
        "net_income_eur_m",
        "ibm_sales_eur_m",
        "new_litho_units",
        "used_litho_units",
        "net_bookings_eur_m",
        "systems_backlog_eur_m",
        "gm_guidance_next_pct",
        "net_sales_guidance_next_eur_m",
        "release_date",
        "source",
        "source_url",
        "data_status",
        "collected_at",
    ]
    assert "company" in SEMICONDUCTOR_EQUIPMENT_GM_MULTI_SCHEMA
    assert "file" in TEL_GM_QUARTERLY_SCHEMA


def test_equipment_gm_quality_gate_checks_all_three_tables(tmp_path: Path) -> None:
    root = tmp_path / "curated" / "industry" / "semiconductor" / "equipment"
    root.mkdir(parents=True)
    release_date = date(2026, 7, 15)

    pl.DataFrame(
        {
            "report_quarter": ["2026-Q2"],
            "trade_date": [date(2026, 6, 28)],
            "gross_margin_pct": [54.0],
            "release_date": [release_date],
            "source": ["ASML_6K"],
            "data_status": ["actual"],
        }
    ).write_parquet(root / "semiconductor_equipment_gm.parquet")
    pl.DataFrame(
        {
            "company": ["AMAT"],
            "report_quarter": ["FY2026-Q2"],
            "release_date": [release_date],
            "gross_margin_pct": [47.0],
            "source": ["SEC_EDGAR"],
            "data_status": ["actual_10q"],
        }
    ).write_parquet(root / "semiconductor_equipment_gm_multi.parquet")
    pl.DataFrame(
        {
            "company": ["TEL"],
            "report_quarter": ["FY2026-Q2"],
            "gross_margin_pct": [45.0],
            "release_date": [release_date],
            "file": ["tel.pdf"],
        }
    ).write_parquet(root / "tel_gm_quarterly.parquet")

    gate = QualityGate(tmp_path / "curated")
    files = sorted(root.glob("*.parquet"))
    assert gate.assert_semiconductor_equipment_gm_quality(files) is True

    invalid = pl.read_parquet(root / "semiconductor_equipment_gm.parquet").with_columns(
        pl.lit(101.0).alias("gross_margin_pct")
    )
    invalid.write_parquet(root / "semiconductor_equipment_gm.parquet")
    assert gate.assert_semiconductor_equipment_gm_quality(files) is False


def test_semiconductor_ratio_scale_gate_distinguishes_ratio_and_percent_points(
    tmp_path: Path,
) -> None:
    root = tmp_path / "curated" / "industry" / "semiconductor" / "capacity"
    root.mkdir(parents=True)
    path = root / "tsmc_advanced_packaging_revenue.parquet"
    pl.DataFrame(
        {
            "advanced_wafer_pct": [0.74],
            "hpc_platform_pct": [0.53],
            "packaging_testing_others_pct": [0.08],
            "foundry_weighted_utilization_pct": [95.0],
        }
    ).write_parquet(path)
    gate = QualityGate(tmp_path / "curated")
    assert gate.assert_semiconductor_ratio_scale([path]) is True

    invalid = pl.read_parquet(path).with_columns(pl.lit(74.0).alias("advanced_wafer_pct"))
    invalid.write_parquet(path)
    assert gate.assert_semiconductor_ratio_scale([path]) is False
