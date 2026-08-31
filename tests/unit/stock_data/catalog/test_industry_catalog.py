from datetime import date

import polars as pl

from stock_data.catalog.service import DataCatalog
from stock_data.core.task_bundles import list_available_bundles, resolve_bundle
from stock_data.core.task_registry import list_available_tasks, resolve_task
from stock_data.storage.compat import StorageCompat


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


def test_industry_dedup_keys_follow_task_primary_keys() -> None:
    """industry 源去重键应来自任务契约主键, 而非退化为仅日期列。"""
    df = pl.DataFrame(
        {
            "product_key": ["A", "A", "B"],
            "hs_code": ["hs1", "hs1", "hs2"],
            "report_month": ["202501", "202501", "202501"],
            "trade_date": [date(2025, 1, 31)] * 3,
            "export_value_usd": [1.0, 2.0, 3.0],
        }
    )
    keys = StorageCompat.resolve_dedup_keys("customs_trade", "industry", "industry", df)
    assert keys == ["product_key", "hs_code", "report_month"]
    assert len(df.unique(subset=keys, keep="last")) == 2


def test_industry_customs_trade_dedup_keeps_detail_rows(tmp_path) -> None:
    """同一 trade_date 的多条明细 (不同产品) 默认去重后不应被折叠。"""
    partition = tmp_path / "industry"
    partition.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "product_key": ["A", "B", "C"],
            "hs_code": ["hs1", "hs2", "hs3"],
            "report_month": ["202501", "202501", "202501"],
            "trade_date": [date(2025, 1, 31)] * 3,
            "export_value_usd": [1.0, 2.0, 3.0],
        }
    ).write_parquet(partition / "customs_trade.parquet")

    catalog = DataCatalog(data_source="industry", storage_dir=tmp_path)
    df = catalog.load_dataset("customs_trade")
    assert len(df) == 3


def test_industry_subdir_dataset_aliases() -> None:
    """energy/ 子目录内文件可返回独立寻址别名, 普通数据集不受影响。"""
    assert StorageCompat.subdir_dataset_aliases("global_power_generation", "industry") == (
        "energy/global_power_generation",
    )
    assert StorageCompat.subdir_dataset_aliases("energy_cross_source_audit", "industry") == (
        "energy/energy_cross_source_audit",
    )
    assert StorageCompat.subdir_dataset_aliases("semiconductor_sales", "industry") == ()
    assert StorageCompat.subdir_dataset_aliases("global_power_generation", "tushare") == ()


def test_industry_energy_subdir_addressing(tmp_path) -> None:
    """energy/ 子目录文件可按文件名独立加载, 同时保留 "energy" 聚合数据集。"""
    partition = tmp_path / "industry" / "energy"
    partition.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "geo_code": ["CN", "US"],
            "trade_date": [date(2025, 1, 1), date(2025, 1, 2)],
            "technology": ["solar", "wind"],
            "generation_twh": [1.0, 2.0],
        }
    ).write_parquet(partition / "global_power_generation.parquet")
    pl.DataFrame(
        {
            "geo_code": ["CN", "US"],
            "year": [2024, 2024],
            "technology": ["solar", "wind"],
            "capacity_gw": [100.0, 200.0],
        }
    ).write_parquet(partition / "global_renewable_capacity.parquet")
    # 顶层文件, 验证不受子目录定位影响
    pl.DataFrame(
        {
            "report_month": ["202501"],
            "trade_date": [date(2025, 1, 31)],
            "global_sales_usd": [10.0],
        }
    ).write_parquet(tmp_path / "industry" / "semiconductor_sales.parquet")

    catalog = DataCatalog(data_source="industry", storage_dir=tmp_path)

    single = catalog.load_dataset("global_power_generation", dedup=False)
    assert len(single) == 2
    assert "generation_twh" in single.columns

    aggregated = catalog.load_dataset("energy", dedup=False)
    assert len(aggregated) == 4  # 聚合数据集仍合并 energy/ 下全部文件

    top_level = catalog.load_dataset("semiconductor_sales", dedup=False)
    assert len(top_level) == 1

    entries = {entry.dataset: entry for entry in catalog.available_datasets()}
    assert entries["energy"].files  # 聚合数据集仍存在
    assert len(entries["energy"].files) == 2
    assert "global_power_generation" not in entries  # 不新增独立注册名
