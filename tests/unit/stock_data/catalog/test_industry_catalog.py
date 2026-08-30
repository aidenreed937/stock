from datetime import date

from stock_data.catalog.service import DataCatalog
from stock_data.core.task_bundles import list_available_bundles, resolve_bundle
from stock_data.core.task_registry import list_available_tasks, resolve_task


def test_industry_task_registry() -> None:
    tasks = list_available_tasks("industry")
    assert "semiconductor_sales" in tasks
    assert "nev_monthly_sales" in tasks
    assert "solar_capacity" in tasks
    assert "non_ferrous_metals" in tasks
    assert "customs_trade" in tasks
    assert "pharma_license_out" in tasks
    assert "cloud_capex_quarterly" in tasks
    assert "construction_machinery" in tasks
    assert "shipping_indices" in tasks

    spec = resolve_task("industry", "semiconductor_sales")
    assert spec.provider == "industry"
    assert spec.dataset == "semiconductor_sales"
    assert spec.primary_keys == ("report_month",)
    assert "trade_date" in spec.date_columns
    assert "global_sales_usd" in spec.required_columns
    assert spec.update_delay_days == 35

    spec_metals = resolve_task("industry", "non_ferrous_metals")
    assert spec_metals.provider == "industry"
    assert spec_metals.dataset == "non_ferrous_metals"
    assert spec_metals.primary_keys == ("trade_date",)
    assert "shfe_copper_price" in spec_metals.required_columns
    assert spec_metals.update_delay_days == 0

    spec_customs = resolve_task("industry", "customs_trade")
    assert spec_customs.primary_keys == ("product_key", "hs_code", "report_month")
    assert "export_value_usd" in spec_customs.required_columns
    assert spec_customs.update_delay_days == 20

    spec_pharma = resolve_task("industry", "pharma_license_out")
    assert spec_pharma.primary_keys == ("report_month",)
    assert "monthly_upfront_million_usd" in spec_pharma.required_columns
    assert spec_pharma.update_delay_days == 15

    spec_capex = resolve_task("industry", "cloud_capex_quarterly")
    assert spec_capex.primary_keys == ("report_quarter",)
    assert "total_capex_billion_usd" in spec_capex.required_columns
    assert spec_capex.update_delay_days == 25

    spec_mach = resolve_task("industry", "construction_machinery")
    assert spec_mach.primary_keys == ("report_month",)
    assert "excavator_total_units" in spec_mach.required_columns
    assert spec_mach.update_delay_days == 8

    spec_ship = resolve_task("industry", "shipping_indices")
    assert spec_ship.primary_keys == ("trade_date",)
    assert "bdi_index" in spec_ship.required_columns
    assert spec_ship.update_delay_days == 0


def test_industry_task_bundle() -> None:
    bundles = list_available_bundles("industry")
    assert "industry_monthly_bundle" in bundles

    bundle = resolve_bundle("industry", "industry_monthly_bundle")
    assert "semiconductor_sales" in bundle.tasks
    assert "nev_monthly_sales" in bundle.tasks
    assert "solar_capacity" in bundle.tasks
    assert "non_ferrous_metals" in bundle.tasks
    assert "customs_trade" in bundle.tasks
    assert "pharma_license_out" in bundle.tasks
    assert "cloud_capex_quarterly" in bundle.tasks
    assert "construction_machinery" in bundle.tasks
    assert "shipping_indices" in bundle.tasks


def test_industry_datacatalog_read() -> None:
    cat = DataCatalog(data_source="industry")
    datasets = cat.list_datasets()
    assert "semiconductor_sales" in datasets

    df = cat.load_dataset("semiconductor_sales", start_date=date(2025, 1, 1))
    assert len(df) > 0
    assert "global_sales_usd" in df.columns
    assert "trade_date" in df.columns
