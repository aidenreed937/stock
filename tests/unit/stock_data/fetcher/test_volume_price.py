"""volume_price 单位归一化与量价分离的单元测试。"""

from __future__ import annotations

import polars as pl

from stock_data.fetcher.industry.customs.transforms.volume_price import (
    MIXED_UNIT_PRODUCTS,
    UNIT_CANONICAL,
    flag_volume_aggregable,
    industry_volume_price_corr,
    normalize_quantity_unit,
)


def test_unit_canonical_mapping() -> None:
    """同义单位应归一到规范单位（含 UN Comtrade 计量单位代码）。"""
    assert UNIT_CANONICAL["千克"] == "kg"
    assert UNIT_CANONICAL["公斤"] == "kg"
    assert UNIT_CANONICAL["台"] == "units"
    assert UNIT_CANONICAL["个"] == "units"
    assert UNIT_CANONICAL["辆"] == "units"
    assert UNIT_CANONICAL["艘"] == "units"
    assert UNIT_CANONICAL["平方米"] == "sqm"
    assert UNIT_CANONICAL["吨"] == "ton"
    # UN Comtrade 计量单位代码（2026-09 补充）
    assert UNIT_CANONICAL["u"] == "units"
    assert UNIT_CANONICAL["l"] == "l"
    assert UNIT_CANONICAL["m²"] == "sqm"
    assert UNIT_CANONICAL["条"] == "units"


def test_normalize_quantity_unit() -> None:
    """quantity_unit 归一化：同义合并，未知名单位标记。"""
    frame = pl.DataFrame(
        {
            "product_key": ["solar_cell", "solar_cell", "mystery"],
            "hs_code": ["85414300", "85414000", "99999999"],
            "quantity_unit": ["个", "units", "floz"],
        }
    )
    out = normalize_quantity_unit(frame)
    # 同义单位归一到规范单位；规范形式本身已知；未知单位保留原值但 unit_known=False
    assert out["quantity_unit_norm"].to_list() == ["units", "units", "floz"]
    assert out["unit_known"].to_list() == [True, True, False]


def test_normalize_comtrade_code_units() -> None:
    """Comtrade 计量单位代码 u/l/m²/条 应归一到规范单位且标记已知。"""
    frame = pl.DataFrame(
        {
            "product_key": ["server", "refined_products", "flat_glass", "knit_apparel"],
            "hs_code": ["84714940", "27101210", "70052100", "61091000"],
            "quantity_unit": ["u", "l", "m²", "条"],
        }
    )
    out = normalize_quantity_unit(frame)
    assert out["quantity_unit_norm"].to_list() == ["units", "l", "sqm", "units"]
    assert out["unit_known"].to_list() == [True, True, True, True]


def test_mixed_unit_products_flagged() -> None:
    """真混用单位产品应在排除集内（数量不可加总）。"""
    assert "semiconductor_equipment" in MIXED_UNIT_PRODUCTS
    assert "pcb" in MIXED_UNIT_PRODUCTS
    assert "auto_glass" in MIXED_UNIT_PRODUCTS


def test_flag_volume_aggregable() -> None:
    """产品级数量可加总标注：同义单位归一后唯一 → 可加总；真混用/未知 → 不可。"""
    frame = pl.DataFrame(
        {
            "product_key": ["solar_cell", "solar_cell", "semi_equip", "semi_equip", "mystery"],
            "hs_code": ["85414300", "85414000", "84861000", "84862000", "99999999"],
            "quantity_unit": ["个", "units", "units", "kg", "floz"],
            "export_volume": [100.0, 200.0, 50.0, 60.0, 70.0],
        }
    )
    out = flag_volume_aggregable(normalize_quantity_unit(frame))
    agg = out.group_by("product_key").agg(pl.col("volume_aggregable").first())
    got = dict(zip(agg["product_key"].to_list(), agg["volume_aggregable"].to_list()))
    # 同义单位（个/units）归一后唯一 → 可加总；真混用（units vs kg）→ 不可；未知单位 → 不可
    assert got["solar_cell"] is True
    assert got["semi_equip"] is False
    assert got["mystery"] is False


def test_flag_volume_aggregable_ignores_zero_volume_rows() -> None:
    """0 量占位行（N/A/mixed 无数量）不应参与单位判定。"""
    frame = pl.DataFrame(
        {
            "product_key": ["solar_cell", "solar_cell", "solar_cell"],
            "hs_code": ["85414300", "85414000", "85414000"],
            "quantity_unit": ["个", "units", "mixed"],
            "export_volume": [100.0, 200.0, 0.0],
        }
    )
    out = flag_volume_aggregable(normalize_quantity_unit(frame))
    agg = out.group_by("product_key").agg(pl.col("volume_aggregable").first())
    # mixed 行无数量（0 量占位）→ 不参与判定，产品仍可加总
    assert agg.filter(pl.col("product_key") == "solar_cell")["volume_aggregable"][0] is True


def test_volume_price_corr_detects_price_dominated() -> None:
    """价格主导行业（量价相关低）应被标记，量价一致行业不标记。"""
    dates = pl.date_range(pl.date(2021, 1, 31), pl.date(2023, 12, 31), interval="1mo", eager=True)
    n = len(dates)
    # 行业 A：量价一致（数量与金额同向）
    vol_a = [float(100 + i * 10) for i in range(n)]
    val_a = [v * 2.0 for v in vol_a]
    # 行业 B：价格主导（金额由独立价格驱动，与数量无关）
    import math

    vol_b = [float(100 + i * 5) for i in range(n)]
    # 价格围绕均值波动但相位与数量错开（正弦，周期约 8 个月），金额与数量低相关
    price = [2.0 + 1.5 * math.sin(i / 8.0 * 2 * math.pi) for i in range(n)]
    val_b = [v * p for v, p in zip(vol_b, price)]

    frame = pl.DataFrame(
        {
            "industry_code": ["A"] * n + ["B"] * n,
            "trade_date": list(dates) + list(dates),
            "export_value_usd": val_a + val_b,
            "export_volume": vol_a + vol_b,
        }
    )
    out = industry_volume_price_corr(frame)
    a = out.filter(pl.col("industry_code") == "A")
    b = out.filter(pl.col("industry_code") == "B")
    assert a["price_dominated"][0] is False
    assert a["corr_value_volume"][0] > 0.9
    assert a["volume_signal_ok"][0] is True
    assert b["price_dominated"][0] is True
    assert b["corr_value_volume"][0] < 0.5
    assert b["volume_signal_ok"][0] is True
