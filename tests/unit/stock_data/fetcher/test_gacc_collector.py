"""GACC 人工导出、RAW manifest 与 CSV 回放测试。"""

from pathlib import Path

import pytest

from stock_data.fetcher.industry.customs.collectors.gacc import GaccCollector
from stock_data.fetcher.industry.customs.collectors.gacc_storage import GaccRawStore
from stock_data.fetcher.industry.customs.models import (
    DEFAULT_INDUSTRY_OUTPUT_FIELDS,
    GaccQueryParams,
)
from stock_data.fetcher.industry.customs.parsers.gacc import parse_gacc_csv


def _catalog() -> dict[str, dict[str, str]]:
    return {
        "280461": {
            "category_key": "power_and_new_energy",
            "category_name": "新能源与电力设备",
            "product_key": "polysilicon",
            "product_name": "多晶硅",
            "hs_code": "28046190",
            "hs_name": "多晶硅",
            "quantity_unit": "kg",
            "target_l1_code": "801730.SI",
            "target_l1_name": "电力设备",
            "target_l2_codes": "801735.SI",
            "target_l2_names": "光伏设备",
        }
    }


def _write_catalog(path: Path) -> None:
    path.write_text(
        "category_key,category_name,product_key,product_name,hs_code,hs_name,quantity_unit,"
        "target_l1_code,target_l1_name,target_l2_codes,target_l2_names\n"
        "power_and_new_energy,新能源与电力设备,polysilicon,多晶硅,28046190,多晶硅,kg,"
        "801730.SI,电力设备,801735.SI,光伏设备\n",
        encoding="utf-8-sig",
    )


def _csv_bytes() -> bytes:
    return (
        "数据年月,商品编码,商品名称,第一数量,第一计量单位,美元\n"
        '202501,28046190,多晶硅,50000,千克,"1,200"\n'
        '202501,28046190,多晶硅,30000,千克,"800"\n'
    ).encode("utf-8-sig")


def test_gacc_query_params_have_stable_fingerprint() -> None:
    first = GaccQueryParams(year=2025, month_start=1, month_end=1)
    second = GaccQueryParams(year=2025, month_start=1, month_end=1)

    assert first.period == "2025-01"
    assert first.fingerprint() == second.fingerprint()
    assert first.to_dict()["flow_type"] == "export"


def test_gacc_endpoint_is_explicit_and_registered() -> None:
    from stock_data.core.task_bundles import resolve_bundle
    from stock_data.core.task_resolution import resolve_task
    from stock_data.fetcher.industry.registry import get_endpoint_spec

    task = resolve_task("industry", "gacc_trade")
    spec = get_endpoint_spec("gacc_trade")

    assert task.dataset == "customs_trade_gacc"
    assert task.primary_keys[-1] == "trade_value_currency"
    assert spec.domain == "customs"
    assert spec.target_file == "customs_trade_gacc.parquet"
    assert resolve_bundle("industry", "industry_gacc_bundle").tasks == ("gacc_trade",)


def test_parse_gacc_csv_aggregates_hs8_rows_and_keeps_lineage(tmp_path: Path) -> None:
    csv_path = tmp_path / "gacc.csv"
    csv_path.write_bytes(_csv_bytes())
    params = GaccQueryParams(year=2025, month_start=1, month_end=1)

    records = parse_gacc_csv(csv_path, params=params, catalog_map=_catalog())

    assert len(records) == 1
    record = records[0]
    assert record.report_month == "2025-01"
    assert record.trade_direction == "export"
    assert record.trade_value_currency == "USD"
    assert record.export_value_usd == 2000.0
    assert record.export_volume == 80000.0
    assert record.source == "GACC"


def test_parse_gacc_csv_uses_gacc_catalog_leaf_codes(tmp_path: Path) -> None:
    csv_path = tmp_path / "gacc.csv"
    csv_path.write_bytes(
        (
            "数据年月,商品编码,商品名称,第一数量,第一计量单位,美元\n"
            '202501,28046190,多晶硅,50000,千克,"1,200"\n'
            '202501,28046110,多晶硅,30000,千克,"800"\n'
        ).encode("utf-8-sig")
    )
    params = GaccQueryParams(year=2025, month_start=1, month_end=1)
    gacc_code_map = {
        "28046190": {
            "gacc_code": "28046190",
            "product_key": "polysilicon",
            "code_role": "leaf",
            "active": "1",
        }
    }

    records = parse_gacc_csv(
        csv_path,
        params=params,
        catalog_map=_catalog(),
        gacc_code_map=gacc_code_map,
    )

    # 28046190 走码表 product_key；28046110 未登记，回退主表 6 位前缀保留
    assert sorted(record.hs_code for record in records) == ["28046110", "28046190"]
    assert all(record.product_key == "polysilicon" for record in records)


def test_parse_gacc_csv_fallback_keeps_main_prefix_and_drops_unmapped(tmp_path: Path) -> None:
    """全量导出模式：码表未命中的码按主表 6 位前缀归属，主表无映射的码丢弃。"""
    csv_path = tmp_path / "gacc.csv"
    csv_path.write_bytes(
        (
            "数据年月,商品编码,商品名称,第一数量,第一计量单位,美元\n"
            '202501,28046110,多晶硅,30000,千克,"800"\n'
            '202501,99999999,冷门商品,10,千克,"5"\n'
        ).encode("utf-8-sig")
    )
    params = GaccQueryParams(year=2025, month_start=1, month_end=1)
    gacc_code_map: dict[str, dict[str, str]] = {}

    records = parse_gacc_csv(
        csv_path,
        params=params,
        catalog_map=_catalog(),
        gacc_code_map=gacc_code_map,
    )

    assert [record.hs_code for record in records] == ["28046110"]
    assert records[0].product_key == "polysilicon"


def test_gacc_raw_store_rejects_tampered_cache(tmp_path: Path) -> None:
    store = GaccRawStore(tmp_path / "gacc")
    params = GaccQueryParams(year=2025, month_start=1, month_end=1)
    store.save_download(params, _csv_bytes(), source_url="http://stats.customs.gov.cn")

    assert store.find_cached(params) is not None
    store.snapshot_path(params).write_bytes(b"tampered")
    assert store.find_cached(params) is None


def test_gacc_collector_ignores_detail_dimension_manifest_for_fact_table(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.csv"
    _write_catalog(catalog_path)
    store = GaccRawStore(tmp_path / "raw" / "customs" / "gacc")
    store.save_download(
        GaccQueryParams(year=2025, month_start=1, month_end=1, output_fields=("CODE_TS",)),
        _csv_bytes(),
        source_url="http://stats.customs.gov.cn",
    )
    store.save_download(
        GaccQueryParams(
            year=2025,
            month_start=1,
            month_end=1,
            output_fields=("CODE_TS", "ORIGIN_COUNTRY"),
        ),
        _csv_bytes(),
        source_url="http://stats.customs.gov.cn",
    )

    collector = GaccCollector(
        raw_dir=tmp_path / "raw",
        catalog_path=catalog_path,
    )
    records = collector.load_from_raw_snapshots()

    assert len(records) == 1


def test_gacc_collector_imports_and_reuses_matching_month_cache(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.csv"
    _write_catalog(catalog_path)
    source_path = tmp_path / "manual-export.csv"
    source_path.write_bytes(_csv_bytes())
    collector = GaccCollector(
        raw_dir=tmp_path / "raw",
        catalog_path=catalog_path,
    )

    first = collector.import_csv(
        source_path,
        start_month="2025-01",
        end_month="2025-01",
        flow_type="export",
    )
    second = collector.import_csv(
        source_path,
        start_month="2025-01",
        end_month="2025-01",
        flow_type="export",
    )
    forced = collector.import_csv(
        source_path,
        start_month="2025-01",
        end_month="2025-01",
        flow_type="export",
        force=True,
    )

    assert first.fetched_periods == ("export:2025-01",)
    assert second.cached_periods == ("export:2025-01",)
    assert forced.fetched_periods == ("export:2025-01",)
    assert len(second.records) == 1


def test_gacc_collector_replays_gacc_directory_cache(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.csv"
    _write_catalog(catalog_path)
    raw_dir = tmp_path / "raw" / "customs" / "gacc"
    store = GaccRawStore(raw_dir)
    store.save_download(
        GaccQueryParams(
            year=2025,
            month_start=1,
            month_end=1,
            output_fields=DEFAULT_INDUSTRY_OUTPUT_FIELDS,
        ),
        _csv_bytes(),
        source_url="http://stats.customs.gov.cn",
    )
    collector = GaccCollector(
        raw_dir=tmp_path / "raw",
        catalog_path=catalog_path,
    )
    result = collector.collect(start_month="2025-01", end_month="2025-01", flow_type="export")

    assert result.cached_periods == ("export:2025-01",)
    assert result.fetched_periods == ()


def test_gacc_raw_store_partitions_snapshots_by_direction(tmp_path: Path) -> None:
    store = GaccRawStore(tmp_path / "data" / "raw" / "industry" / "customs" / "gacc")

    export_path = store.snapshot_path(
        GaccQueryParams(flow_type="export", year=2025, month_start=1, month_end=1)
    )
    import_path = store.snapshot_path(
        GaccQueryParams(flow_type="import", year=2025, month_start=1, month_end=1)
    )

    assert export_path.parent.name == "export"
    assert import_path.parent.name == "import"
    assert export_path.parent.parent.name == "gacc"
    assert export_path != import_path


def test_gacc_collector_rejects_cny_until_cny_schema_exists(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.csv"
    _write_catalog(catalog_path)
    collector = GaccCollector(
        raw_dir=tmp_path / "raw",
        catalog_path=catalog_path,
    )

    with pytest.raises(ValueError, match="USD"):
        collector.collect(start_month="2025-01", currency="CNY")
