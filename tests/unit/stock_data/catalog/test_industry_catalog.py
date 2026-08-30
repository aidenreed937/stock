from datetime import date

from stock_data.catalog.service import DataCatalog
from stock_data.core.task_bundles import list_available_bundles, resolve_bundle
from stock_data.core.task_registry import list_available_tasks, resolve_task


def test_industry_task_registry() -> None:
    tasks = list_available_tasks("industry")
    assert "semiconductor_sales" in tasks
    assert "nev_monthly_sales" in tasks
    assert "solar_capacity" in tasks

    spec = resolve_task("industry", "semiconductor_sales")
    assert spec.provider == "industry"
    assert spec.dataset == "semiconductor_sales"
    assert spec.primary_keys == ("report_month",)
    assert "trade_date" in spec.date_columns
    assert "global_sales_usd" in spec.required_columns


def test_industry_task_bundle() -> None:
    bundles = list_available_bundles("industry")
    assert "industry_monthly_bundle" in bundles

    bundle = resolve_bundle("industry", "industry_monthly_bundle")
    assert "semiconductor_sales" in bundle.tasks
    assert "nev_monthly_sales" in bundle.tasks
    assert "solar_capacity" in bundle.tasks


def test_industry_datacatalog_read() -> None:
    cat = DataCatalog(data_source="industry")
    datasets = cat.list_datasets()
    assert "semiconductor_sales" in datasets

    df = cat.load_dataset("semiconductor_sales", start_date=date(2025, 1, 1))
    assert len(df) > 0
    assert "global_sales_usd" in df.columns
    assert "trade_date" in df.columns
