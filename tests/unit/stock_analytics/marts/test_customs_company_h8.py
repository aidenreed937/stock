from datetime import date
from pathlib import Path

import polars as pl
import pytest

from stock_analytics.marts.customs_company_h8 import (
    build_company_h8_exposure_mart,
    build_company_product_mapping,
    load_h8_catalog,
    save_customs_company_h8_marts,
)


def _catalog() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "hs_code": ["85042100", "85171300"],
            "hs_parent_code": ["850421", "851713"],
            "category_name": ["电气设备", "消费电子"],
            "product_key": ["transformer", "smartphone"],
            "product_name": ["变压器", "智能手机"],
            "hs_level": ["8", "8"],
            "hs_name": ["液体介质变压器", "无线网络智能手机"],
            "description": ["变压器出口", "智能手机出口"],
            "target_l1_code": ["801890.SI", "801080.SI"],
            "target_l1_name": ["机械设备", "电子"],
            "target_l2_codes": ["801890.SI", "801082.SI"],
            "target_l2_names": ["电网设备", "消费电子"],
            "target_l3_codes": ["850381.SI", "850851.SI"],
            "target_l3_names": ["输变电设备", "消费电子零部件及组装"],
            "quantity_unit": ["unit", "unit"],
        }
    )


def _mainbz() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["600000.SH"] * 5,
            "end_date": [
                date(2025, 12, 31),
                date(2025, 12, 31),
                date(2026, 6, 30),
                date(2026, 6, 30),
                date(2026, 6, 30),
            ],
            "bz_item": ["变压器", "智能手机", "变压器", "智能手机", "其他业务"],
            "bz_sales": [80.0, 20.0, 50.0, 50.0, 100.0],
            "bz_code": ["P"] * 5,
        }
    )


def _company_table() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["600000.SH"],
            "company_name": ["测试公司"],
            "stock_industry": ["电气设备"],
            "list_date": [date(2000, 1, 1)],
        }
    )


def _customs_trade() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "report_month": ["2026-01", "2026-01", "2026-03", "2026-03", "2026-07", "2026-07"],
            "trade_direction": ["export"] * 6,
            "hs_level": ["8"] * 6,
            "hs_code": ["85042100", "85171300"] * 3,
            "export_value_usd": [100.0, 200.0, 300.0, 400.0, 500.0, 600.0],
            "export_volume": [1.0] * 6,
            "quantity_unit_norm": ["unit"] * 6,
            "unit_known": [True] * 6,
        }
    )


def test_load_h8_catalog_rejects_wrong_parent(tmp_path: Path) -> None:
    path = tmp_path / "good_h8_codes.csv"
    _catalog().with_columns(pl.lit("999999").alias("hs_parent_code")).write_csv(path)
    with pytest.raises(ValueError, match="H8/H6 父码不一致"):
        load_h8_catalog(path)


def test_build_mapping_uses_report_period_and_catalog_industry() -> None:
    unknown_company = pl.DataFrame(
        {
            "symbol": ["999999.SZ"],
            "end_date": [date(2026, 6, 30)],
            "bz_item": ["变压器"],
            "bz_sales": [100.0],
            "bz_code": ["P"],
        }
    )
    mapping = build_company_product_mapping(
        _mainbz().vstack(unknown_company), _company_table(), _catalog()
    )
    assert mapping["symbol"].unique().to_list() == ["600000.SH"]
    selected = mapping.filter(pl.col("match_status") == "selected")
    assert selected.select("product_key").unique().sort("product_key")["product_key"].to_list() == [
        "smartphone",
        "transformer",
    ]
    old = selected.filter(pl.col("report_period") == date(2025, 12, 31)).sort("product_key")
    new = selected.filter(pl.col("report_period") == date(2026, 6, 30)).sort("product_key")
    assert old["product_exposure"].to_list() == [0.2, 0.8]
    assert new["product_exposure"].to_list() == [0.5, 0.5]
    assert mapping.filter(pl.col("bz_item") == "其他业务")["match_status"].to_list() == ["generic"]
    assert old["target_l3_names"].to_list() == ["消费电子零部件及组装", "输变电设备"]


def test_build_company_h8_exposure_is_asof_and_weighted() -> None:
    catalog = _catalog()
    mapping = build_company_product_mapping(_mainbz(), _company_table(), catalog)
    mart = build_company_h8_exposure_mart(mapping, _customs_trade(), catalog)

    jan = mart.filter((pl.col("report_month") == "2026-01") & (pl.col("hs_code") == "85042100"))
    jul = mart.filter((pl.col("report_month") == "2026-07") & (pl.col("hs_code") == "85042100"))
    assert jan.height == 1 and jul.height == 1
    assert jan["company_h8_export_value_usd"].item() == 80.0
    assert jul["company_h8_export_value_usd"].item() == 250.0
    assert jan["mapping_report_period"].item() == date(2025, 12, 31)
    assert jul["mapping_report_period"].item() == date(2026, 6, 30)
    assert mart.filter(pl.col("mapping_report_period") >= pl.col("report_date")).is_empty()
    assert (
        mart.group_by(["symbol", "report_month", "hs_code"])
        .len()
        .filter(pl.col("len") > 1)
        .is_empty()
    )


def test_score_item_downgrades_part_downstream_head() -> None:
    from stock_analytics.marts.customs_company_h8 import _candidate_index, _score_item

    catalog = pl.DataFrame(
        {
            "hs_code": ["85042100", "84672100", "84271010", "84862010", "87112010"],
            "product_key": [
                "transformer",
                "power_tools",
                "forklift",
                "semiconductor_equipment",
                "motorcycle",
            ],
            "product_name": ["变压器", "电动工具", "叉车", "半导体设备", "摩托车"],
            "category_name": [
                "电气设备",
                "消费家电与工具",
                "工程机械",
                "半导体",
                "汽车整车与零部件",
            ],
            "hs_name": ["液体介质变压器", "电动工具", "叉车", "半导体设备", "摩托车"],
            "description": ["", "", "", "", ""],
            "target_l1_name": ["", "", "", "", ""],
            "target_l2_names": ["", "", "", "", ""],
            "target_l3_names": ["", "", "", "", ""],
        }
    )
    cands = {c.product_key: c for c in _candidate_index(catalog)}
    # 头词是部件/下游词 → 压到 selected 阈值以下（回退 ambiguous，不误归整机/商品）
    assert _score_item("电动工具零部件", cands["power_tools"]) < 88
    assert _score_item("叉车用柴油发动机", cands["forklift"]) < 88
    # 部件词只在宽泛行业词里（category"汽车整车与零部件"），不在产品特定语料里 → 仍降级
    assert _score_item("摩托车零部件", cands["motorcycle"]) < 88
    # 头词是产品本身、或产品语料含"设备" → 保留高置信
    assert _score_item("变压器系列", cands["transformer"]) >= 88
    assert _score_item("半导体设备", cands["semiconductor_equipment"]) >= 88


def test_attach_segment_filters_bound_h8_codes() -> None:
    from stock_analytics.marts.customs_company_h8 import _attach_segment

    exposure = pl.DataFrame(
        {
            "symbol": ["600000.SH", "600000.SH"],
            "product_key": ["transformer", "transformer"],
            "hs_code": ["85042100", "85042312"],
            "report_month": ["2026-07", "2026-07"],
            "report_date": [date(2026, 7, 1), date(2026, 7, 1)],
            "export_value_usd": [100.0, 200.0],
        }
    )
    binding = pl.DataFrame(
        {
            "product_key": ["transformer"],
            "segment_key": ["transformer_ultra"],
            "stock_code": ["600000.SH"],
        }
    )
    taxline = pl.DataFrame(
        {
            "product_key": ["transformer"],
            "segment_key": ["transformer_ultra"],
            "segment_name": ["特高压大容量(≥220MVA)"],
            "hs_codes": ["85042312;85042313"],
        }
    )
    out = _attach_segment(exposure, binding, taxline)
    assert out.height == 1  # 只保留 ultra 段 H8 码
    assert out["hs_code"].to_list() == ["85042312"]
    assert out["segment_key"].to_list() == ["transformer_ultra"]
    assert out["segment_name"].to_list() == ["特高压大容量(≥220MVA)"]


def test_attach_segment_merges_multiple_binding_rows() -> None:
    from stock_analytics.marts.customs_company_h8 import _attach_segment

    exposure = pl.DataFrame(
        {
            "symbol": ["600000.SH"] * 3,
            "product_key": ["transformer"] * 3,
            "hs_code": ["85042100", "85042312", "85171300"],
            "report_month": ["2026-07"] * 3,
            "report_date": [date(2026, 7, 1)] * 3,
            "export_value_usd": [100.0, 200.0, 300.0],
        }
    )
    binding = pl.DataFrame(
        {
            "product_key": ["transformer", "transformer"],
            "segment_key": ["transformer_ultra", "transformer_small"],
            "stock_code": ["600000.SH", "600000.SH"],
        }
    )
    taxline = pl.DataFrame(
        {
            "product_key": ["transformer", "transformer"],
            "segment_key": ["transformer_ultra", "transformer_small"],
            "segment_name": ["特高压大容量(≥220MVA)", "中小容量(≤650kVA)"],
            "hs_codes": ["85042312;85042313", "85042100"],
        }
    )
    out = _attach_segment(exposure, binding, taxline)
    # 同一 (公司,产品) 多行绑定必须合并：small(85042100) 与 ultra(85042312) 都保留，
    # 段外码 85171300 被过滤；不能只生效最后一行
    assert out.height == 2
    assert out["hs_code"].to_list() == ["85042100", "85042312"]
    assert out["segment_key"].to_list() == [
        "transformer_ultra;transformer_small",
        "transformer_ultra;transformer_small",
    ]
    assert out["segment_name"].to_list() == [
        "特高压大容量(≥220MVA);中小容量(≤650kVA)",
        "特高压大容量(≥220MVA);中小容量(≤650kVA)",
    ]


def test_generic_item_prefix_other_and_total() -> None:
    from stock_analytics.marts.customs_company_h8 import ProductMatcher, _candidate_index

    matcher = ProductMatcher(_candidate_index(_catalog()))
    for item in ("其他业务收入", "其他收入", "其他产品", "其他收益", "合计收入"):
        assert matcher.match(item).status == "generic"
    assert matcher.match("变压器").status == "selected"


def test_build_company_h8_exposure_attaches_overseas_revenue() -> None:
    catalog = _catalog()
    mapping = build_company_product_mapping(_mainbz(), _company_table(), catalog)
    overseas = pl.DataFrame(
        {
            "symbol": ["600000.SH", "600000.SH", "600000.SH"],
            "end_date": [date(2025, 6, 30), date(2025, 12, 31), date(2026, 6, 30)],
            "ann_date": [date(2025, 8, 31), date(2026, 4, 30), date(2026, 8, 31)],
            "overseas_revenue": [80.0, 100.0, 200.0],
        }
    )
    mart = build_company_h8_exposure_mart(mapping, _customs_trade(), catalog, overseas)

    jan = mart.filter((pl.col("report_month") == "2026-01") & (pl.col("hs_code") == "85042100"))
    jul = mart.filter((pl.col("report_month") == "2026-07") & (pl.col("hs_code") == "85042100"))
    # 2026-01: 用 2025-06 报告（ann 2025-08 <= 月末），product_exposure=0.8，H8 份额=1
    assert jan["company_h8_overseas_rev_est"].item() == pytest.approx(80.0 * 0.8)
    # 2026-07: 用 2025-12 报告（ann 2026-04 <= 月末）；2026-06 报告 ann 2026-08 未披露，不得使用
    assert jul["company_h8_overseas_rev_est"].item() == pytest.approx(100.0 * 0.5)
    assert jul["overseas_report_period"].item() == date(2025, 12, 31)


def test_save_customs_company_h8_marts(tmp_path: Path) -> None:
    catalog = _catalog()
    mapping = build_company_product_mapping(_mainbz(), _company_table(), catalog)
    exposure = build_company_h8_exposure_mart(mapping, _customs_trade(), catalog)
    paths = save_customs_company_h8_marts(mapping, exposure, tmp_path)
    assert set(paths) == {"mapping", "mapping_latest", "exposure", "exposure_latest"}
    assert all(path.exists() for path in paths.values())


def test_load_segment_binding_reads_merged_override(tmp_path: Path) -> None:
    from stock_analytics.marts.customs_company_h8 import _load_segment_binding

    path = tmp_path / "company_segment_binding.csv"
    pl.DataFrame(
        {
            "product_key": ["battery", "battery", "auto_parts"],
            "segment_key": ["battery_lithium", "battery_flow", "auto_parts_rest"],
            "stock_code": ["300014.SZ", "600517.SH", "601689.SH"],
            "company_name": ["亿纬锂能", "国网英大", "拓普集团"],
            "exposure": ["0.86", "", ""],
            "evidence": ["动力电池+储能电池占比86%，待财报校准", "", ""],
        }
    ).write_csv(path)
    out = _load_segment_binding(path)
    assert out.columns == [
        "product_key",
        "segment_key",
        "stock_code",
        "company_name",
        "exposure",
        "evidence",
    ]
    assert out.filter(pl.col("stock_code") == "300014.SZ")["exposure"].to_list() == ["0.86"]
    assert out.filter(pl.col("stock_code") == "601689.SH")["exposure"].to_list() == [""]
