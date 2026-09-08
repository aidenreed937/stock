"""商品→公司暴露度映射（company_exposure_map.csv）加载与校验测试。"""

from pathlib import Path

import pytest

from stock_data.fetcher.industry.customs.parsers.company_exposure import (
    ALLOWED_EMPTY_PRODUCTS,
    COMPANY_EXPOSURE_REQUIRED_COLUMNS,
    load_company_exposure_map,
    load_taxline_segments,
)

_HEADER = ",".join(COMPANY_EXPOSURE_REQUIRED_COLUMNS)


def _write_map(path: Path, rows: list[str]) -> Path:
    path.write_text("\n".join([_HEADER, *rows]) + "\n", encoding="utf-8-sig")
    return path


def test_load_map_parses_rows_and_indexes_by_product(tmp_path: Path) -> None:
    map_path = _write_map(
        tmp_path / "map.csv",
        [
            "transformer,变压器,002028.SZ,思源电气,0.7,电网设备,估计,estimated",
            "transformer,变压器,688676.SH,金盘科技,0.8,电网设备,估计,estimated",
            "optical_module,光通信收发模块,300308.SZ,中际旭创,0.9,通信设备,估计,estimated",
        ],
    )
    catalog = tmp_path / "catalog.csv"
    catalog.write_text(
        "category_key,category_name,product_key,product_name,hs_code,hs_name,quantity_unit,"
        "target_l1_code,target_l1_name,target_l2_codes,target_l2_names\n"
        "t,变压器,transformer,变压器,85042100,x,u,630000.SI,电力设备,630800.SI,电网设备\n"
        "o,通信,optical_module,光通信收发模块,85176221,x,u,730000.SI,通信,730200.SI,通信设备\n",
        encoding="utf-8-sig",
    )

    mapping = load_company_exposure_map(
        map_path=map_path, catalog_path=catalog, require_known_product=True
    )
    assert len(mapping.entries) == 3
    tr = mapping.companies_for("transformer")
    assert len(tr) == 2
    assert {e.company_name for e in tr} == {"思源电气", "金盘科技"}
    assert mapping.product_keys == {"transformer", "optical_module"}


def test_load_map_rejects_unknown_product_key(tmp_path: Path) -> None:
    map_path = _write_map(
        tmp_path / "map.csv",
        ["ghost_product,幽灵商品,002028.SZ,思源电气,0.7,电网设备,估计,estimated"],
    )
    catalog = tmp_path / "catalog.csv"
    catalog.write_text(
        "category_key,category_name,product_key,product_name,hs_code,hs_name,quantity_unit,"
        "target_l1_code,target_l1_name,target_l2_codes,target_l2_names\n"
        "t,变压器,transformer,变压器,85042100,x,u,630000.SI,电力设备,630800.SI,电网设备\n",
        encoding="utf-8-sig",
    )
    with pytest.raises(ValueError, match="不在 catalog 中"):
        load_company_exposure_map(
            map_path=map_path, catalog_path=catalog, require_known_product=True
        )
    # 宽松模式不校验产品键
    mapping = load_company_exposure_map(
        map_path=map_path, catalog_path=catalog, require_known_product=False
    )
    assert len(mapping.entries) == 1


def test_load_map_allows_empty_product_whitelist(tmp_path: Path) -> None:
    assert frozenset({"comm_equipment_mixed"}) == ALLOWED_EMPTY_PRODUCTS
    map_path = _write_map(tmp_path / "map.csv", [])
    catalog = tmp_path / "catalog.csv"
    catalog.write_text(
        "category_key,category_name,product_key,product_name,hs_code,hs_name,quantity_unit,"
        "target_l1_code,target_l1_name,target_l2_codes,target_l2_names\n"
        "c,通信,comm_equipment_mixed,通信设备混合,851762,x,u,730000.SI,通信,730200.SI,通信设备\n",
        encoding="utf-8-sig",
    )
    # 空映射文件 + 白名单产品在 catalog 中存在 → 不报错
    mapping = load_company_exposure_map(
        map_path=map_path, catalog_path=catalog, require_known_product=True
    )
    assert len(mapping.entries) == 0


def test_load_map_rejects_bad_stock_code_and_exposure(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.csv"
    catalog.write_text(
        "category_key,category_name,product_key,product_name,hs_code,hs_name,quantity_unit,"
        "target_l1_code,target_l1_name,target_l2_codes,target_l2_names\n"
        "t,变压器,transformer,变压器,85042100,x,u,630000.SI,电力设备,630800.SI,电网设备\n",
        encoding="utf-8-sig",
    )
    # 非法代码
    bad_code = _write_map(
        tmp_path / "bad_code.csv",
        ["transformer,变压器,002028,思源电气,0.7,电网设备,估计,estimated"],
    )
    with pytest.raises(ValueError, match="非法公司代码"):
        load_company_exposure_map(map_path=bad_code, catalog_path=catalog)
    # exposure 越界
    bad_exposure = _write_map(
        tmp_path / "bad_exposure.csv",
        ["transformer,变压器,002028.SZ,思源电气,1.5,电网设备,估计,estimated"],
    )
    with pytest.raises(ValueError, match="exposure 越界"):
        load_company_exposure_map(map_path=bad_exposure, catalog_path=catalog)
    # 重复 product×stock
    dup = _write_map(
        tmp_path / "dup.csv",
        [
            "transformer,变压器,002028.SZ,思源电气,0.7,电网设备,估计,estimated",
            "transformer,变压器,002028.SZ,思源电气,0.8,电网设备,估计,estimated",
        ],
    )
    with pytest.raises(ValueError, match="重复"):
        load_company_exposure_map(map_path=dup, catalog_path=catalog)


def test_load_real_map_file(tmp_path: Path) -> None:
    """真实维护文件必须可通过严格校验（防 CSV 误改破坏下游）。"""
    mapping = load_company_exposure_map(require_known_product=True)
    assert len(mapping.entries) >= 100
    assert len(mapping.product_keys) >= 100
    tr = mapping.companies_for("transformer")
    assert len(tr) >= 5
    assert {e.company_name for e in tr} >= {"思源电气", "金盘科技", "中国西电"}


def test_load_taxline_segments_and_query(tmp_path: Path) -> None:
    """税号段定义加载与按产品/段查询。"""
    seg_path = tmp_path / "segments.csv"
    seg_path.write_text(
        "product_key,segment_key,segment_name,hs_codes,description\n"
        "transformer,transformer_small,中小容量,85042100,小型变压器\n"
        "transformer,transformer_ultra,特高压大容量,85042312;85042329,大型变压器\n"
        "semiconductor_equipment,semi_fab_wafer,晶圆制造,84861010;84861020,设备\n",
        encoding="utf-8-sig",
    )
    segs = load_taxline_segments(segments_path=seg_path)
    assert len(segs.segments) == 3
    assert segs.hs_codes_for("transformer", "transformer_ultra") == ["85042312", "85042329"]
    assert segs.hs_codes_for("transformer", "nope") == []
    assert segs.segment_keys_by_product["transformer"] == {"transformer_small", "transformer_ultra"}


def test_load_map_rejects_invalid_segment_ref(tmp_path: Path) -> None:
    """公司绑定的段引用必须存在于 taxline_segments.csv。"""
    catalog = tmp_path / "catalog.csv"
    catalog.write_text(
        "category_key,category_name,product_key,product_name,hs_code,hs_name,quantity_unit,"
        "target_l1_code,target_l1_name,target_l2_codes,target_l2_names\n"
        "t,变压器,transformer,变压器,85042100,x,u,630000.SI,电力设备,630800.SI,电网设备\n",
        encoding="utf-8-sig",
    )
    seg_path = tmp_path / "segments.csv"
    seg_path.write_text(
        "product_key,segment_key,segment_name,hs_codes,description\n"
        "transformer,transformer_small,中小容量,85042100,小型变压器\n",
        encoding="utf-8-sig",
    )
    map_path = _write_map(
        tmp_path / "bad_seg.csv",
        ["transformer,变压器,002028.SZ,思源电气,0.7,电网设备,估计,estimated,transformer_nope"],
    )
    with pytest.raises(ValueError, match="段引用"):
        load_company_exposure_map(map_path=map_path, catalog_path=catalog, segments_path=seg_path)
    # 空段引用合法（绑整个产品）
    ok_path = _write_map(
        tmp_path / "ok_seg.csv",
        ["transformer,变压器,002028.SZ,思源电气,0.7,电网设备,估计,estimated,"],
    )
    mapping = load_company_exposure_map(
        map_path=ok_path, catalog_path=catalog, segments_path=seg_path
    )
    assert mapping.entries[0].taxline_segment == ""
