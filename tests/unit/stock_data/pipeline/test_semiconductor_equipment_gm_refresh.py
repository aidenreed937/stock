from datetime import date

import polars as pl

from stock_data.core.runtime import DataRuntimeContext
from stock_data.pipeline.derived_refresh import refresh_semiconductor_equipment_gm_multi
from stock_data.pipeline.sync_models import SyncExecutionResult, SyncTaskItem

_SOURCE_TASKS = (
    "semiconductor_equipment_gm_amat",
    "semiconductor_equipment_gm_lrcx",
    "semiconductor_equipment_gm_klac",
    "tel_gm_quarterly",
)


def _plan(status: str = "PENDING") -> list[SyncTaskItem]:
    return [
        SyncTaskItem(
            data_source="industry",
            endpoint=endpoint,
            dataset=endpoint,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 9, 30),
            watermark=None,
            status=status,
            is_ready=True,
        )
        for endpoint in _SOURCE_TASKS
    ]


def _results(status: str = "SUCCESS") -> list[SyncExecutionResult]:
    return [
        SyncExecutionResult(
            data_source="industry",
            endpoint=endpoint,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 9, 30),
            records=1 if status == "SUCCESS" else 0,
            duration_s=0.1,
            status=status,
        )
        for endpoint in _SOURCE_TASKS
    ]


def _write_atomic_inputs(runtime: DataRuntimeContext) -> None:
    root = runtime.curated_root / "industry" / "semiconductor" / "equipment"
    root.mkdir(parents=True, exist_ok=True)
    for endpoint, company in (
        ("semiconductor_equipment_gm_amat", "AMAT"),
        ("semiconductor_equipment_gm_lrcx", "LRCX"),
        ("semiconductor_equipment_gm_klac", "KLAC"),
    ):
        pl.DataFrame(
            {
                "company": [company],
                "report_quarter": ["2026-Q3"],
                "report_period_end": [date(2026, 7, 31)],
                "release_date": [date(2026, 8, 10)],
                "gross_margin_pct": [50.0],
                "gm_guidance_next_pct": [51.0],
                "services_share_pct": [20.0],
                "source": ["SEC_EDGAR"],
                "data_status": ["actual"],
            }
        ).write_parquet(root / f"{endpoint}.parquet")
    pl.DataFrame(
        {
            "company": ["TEL"],
            "report_quarter": ["FY2027-Q1"],
            "period_end": ["2026-06-30"],
            "release_date": [date(2026, 7, 30)],
            "gross_margin_pct": [46.0],
            "source": ["TEL_IR"],
            "data_status": ["actual"],
        }
    ).write_parquet(root / "tel_gm_quarterly.parquet")


def test_equipment_gm_multi_rebuilds_from_all_atomic_sources(tmp_path) -> None:
    runtime = DataRuntimeContext.from_root(tmp_path)
    runtime.ensure_directories()
    _write_atomic_inputs(runtime)

    result = refresh_semiconductor_equipment_gm_multi(
        _plan(),
        _results(),
        runtime=runtime,
    )

    assert result is not None
    assert result.status == "SUCCESS"
    output = pl.read_parquet(
        runtime.curated_root
        / "industry"
        / "semiconductor"
        / "equipment"
        / "semiconductor_equipment_gm_multi.parquet"
    )
    assert sorted(output.get_column("company").to_list()) == ["AMAT", "KLAC", "LRCX", "TEL"]


def test_equipment_gm_multi_rebuild_is_blocked_when_one_source_fails(tmp_path) -> None:
    runtime = DataRuntimeContext.from_root(tmp_path)
    runtime.ensure_directories()
    _write_atomic_inputs(runtime)
    target = (
        runtime.curated_root
        / "industry"
        / "semiconductor"
        / "equipment"
        / "semiconductor_equipment_gm_multi.parquet"
    )
    original = pl.DataFrame({"company": ["OLD"]})
    target.parent.mkdir(parents=True, exist_ok=True)
    original.write_parquet(target)

    failed = _results()
    failed[-1] = SyncExecutionResult(
        data_source="industry",
        endpoint="tel_gm_quarterly",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 9, 30),
        records=0,
        duration_s=0.1,
        status="FAILED",
        error="源端失败",
    )
    result = refresh_semiconductor_equipment_gm_multi(_plan(), failed, runtime=runtime)

    assert result is not None
    assert result.status == "BLOCKED"
    assert pl.read_parquet(target).equals(original)
