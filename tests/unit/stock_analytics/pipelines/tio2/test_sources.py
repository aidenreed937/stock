"""钛白粉数据读取层测试（FakeCatalog）。

覆盖 GACC 海关出口加载器的数量单位归一化（千克→吨）与月频调研加载（源优先级/连续去库月数）。
"""

from __future__ import annotations

import polars as pl
import pytest

from stock_analytics.pipelines.tio2.market_sources import load_monthly_survey
from stock_analytics.pipelines.tio2.sources import load_customs_export, load_spot_price


class FakeCatalog:
    """鸭子类型 DataCatalog：load_dataset 返回预置帧或抛 KeyError。"""

    def __init__(self, datasets: dict[str, pl.DataFrame]) -> None:
        self._datasets = datasets

    def load_dataset(self, dataset: str) -> pl.DataFrame:
        if dataset not in self._datasets:
            raise KeyError(f"fake dataset missing: {dataset}")
        return self._datasets[dataset]


def _customs_frame_kilogram() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "report_month": ["2024-01-01", "2024-01-15", "2024-02-01"],
            "hs_code": ["32061110", "32061110", "32061110"],
            "product_key": ["tio2", "tio2", "tio2"],
            "export_quantity": [120_000.0, 80_000.0, 150_000.0],
            "export_value_usd": [400_000.0, 200_000.0, 450_000.0],
            "quantity_unit": ["千克", "千克", "千克"],
            "quantity_unit_norm": ["kg", "kg", "kg"],
            "yoy_growth": [15.0, 15.0, 18.0],
        }
    )


def test_load_customs_export_converts_kilogram_to_tons() -> None:
    cat = FakeCatalog({"customs_trade_gacc": _customs_frame_kilogram()})
    df = load_customs_export(cat, "customs_trade_gacc", "customs_trade")

    assert df["report_month"].to_list() == ["2024-01", "2024-02"]
    assert df["export_qty_tons"].to_list() == [200.0, 150.0]
    assert df["export_unit_price_usd"].to_list() == [3000.0, 3000.0]
    assert df["export_qty_yoy"].to_list() == [15.0, 18.0]


def test_load_customs_export_detects_chinese_kilogram_unit() -> None:
    """生产环境数据只有中文单位列时也必须正确折算（回归用例）。"""
    frame = _customs_frame_kilogram().drop("quantity_unit_norm")
    cat = FakeCatalog({"customs_trade_gacc": frame})
    df = load_customs_export(cat, "customs_trade_gacc", "customs_trade")

    assert df["export_qty_tons"].to_list() == [200.0, 150.0]
    assert df["export_unit_price_usd"].to_list() == [3000.0, 3000.0]


def test_load_customs_export_without_unit_column_passes_through() -> None:
    """无单位列时按吨透传（既有兼容行为）。"""
    frame = _customs_frame_kilogram().drop(["quantity_unit", "quantity_unit_norm"])
    cat = FakeCatalog({"customs_trade_gacc": frame})
    df = load_customs_export(cat, "customs_trade_gacc", "customs_trade")

    assert df["export_qty_tons"].to_list() == [200_000.0, 150_000.0]


def test_load_customs_export_excludes_import_rows() -> None:
    """出口口径回归：trade_direction=import 行不得混入出口量价（2026-09-20 修复）。"""
    frame = pl.DataFrame(
        {
            "report_month": ["2026-07", "2026-07", "2026-08", "2026-08"],
            "hs_code": ["32061119", "32061119", "32061119", "32061119"],
            "product_key": ["tio2", "tio2", "tio2", "tio2"],
            "trade_direction": ["export", "import", "export", "import"],
            "export_volume": [100_000.0, 5_000.0, 90_000.0, 6_000.0],
            "export_value_usd": [200_000.0, 20_000.0, 210_000.0, 25_000.0],
            "quantity_unit_norm": ["kg", "kg", "kg", "kg"],
        }
    )
    cat = FakeCatalog({"customs_trade_gacc": frame})
    df = load_customs_export(cat, "customs_trade_gacc", "customs_trade")

    assert df["report_month"].to_list() == ["2026-07", "2026-08"]
    assert df["export_qty_tons"].to_list() == [100.0, 90.0]
    assert df["export_unit_price_usd"].to_list() == [2000.0, 2333.3333333333335]


def test_load_spot_price_month_end_uses_latest_snapshot() -> None:
    """month_end 应按 trade_date 排序取当月最新快照，不依赖输入行序（2026-09-20 修复）。"""
    frame = pl.DataFrame(
        {
            "symbol": ["TiO2"] * 4,
            "trade_date": ["2026-09-10", "2026-09-08", "2026-09-15", "2026-09-12"],
            "spot_price_cny": [14060.0, 14060.0, 14200.0, 14200.0],
        }
    )
    cat = FakeCatalog({"chemical_spot_price": frame})
    df = load_spot_price(cat, "chemical_spot_price")

    row = df.filter(pl.col("report_month") == "2026-09").to_dicts()[0]
    assert row["tio2_spot_price_cny"] == pytest.approx(14130.0)
    assert row["tio2_spot_price_month_end"] == pytest.approx(14200.0)


def _monthly_survey_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "report_month": ["2026-05", "2026-06", "2026-07", "2026-07", "2026-08", "2026-08"],
            "product_name": ["钛白粉"] * 6,
            "symbol": ["TiO2"] * 6,
            "production_w_tons": [35.38, 39.66, 33.87, 38.54, 33.97, 38.34],
            "operating_rate_pct": [80.0, 74.39, None, 72.29, None, 73.3],
            "factory_inventory_w_tons": [26.3, None, 30.68, None, None, None],
            "inventory_mom_pct": [14.1, None, 23.26, None, 0.34, None],
            "inventory_yoy_pct": [None, None, -22.01, None, None, None],
            "source": ["SMM", "Longzhong", "SMM", "Mysteel", "SMM", "Longzhong"],
            "source_url": [""] * 6,
            "release_date": [None] * 6,
        }
    )


def test_load_monthly_survey_aggregates_by_source_priority() -> None:
    cat = FakeCatalog({"chemical_monthly_survey": _monthly_survey_frame()})
    df = load_monthly_survey(cat, "chemical_monthly_survey")

    assert df["report_month"].to_list() == ["2026-05", "2026-06", "2026-07", "2026-08"]
    # 产能利用率同月多源时按 隆众 > Mysteel > SMM 取优
    assert df["operating_rate_pct_monthly"].to_list() == [80.0, 74.39, 72.29, 73.3]
    assert df["factory_inventory_w_tons_monthly"].to_list() == [26.3, None, 30.68, None]
    assert df["monthly_survey_as_of"].to_list() == ["2026-08"] * 4
    # 05→07 库存累增、07→08 环比 +0.34% → 无连续去库
    assert df["consecutive_destock_months"].to_list() == [0, 0, 0, 0]


def test_load_monthly_survey_counts_consecutive_destock_months() -> None:
    frame = pl.DataFrame(
        {
            "report_month": ["2026-05", "2026-06", "2026-07"],
            "product_name": ["钛白粉"] * 3,
            "symbol": ["TiO2"] * 3,
            "production_w_tons": [None] * 3,
            "operating_rate_pct": [None] * 3,
            "factory_inventory_w_tons": [30.0, 28.0, 26.0],
            "inventory_mom_pct": [None] * 3,
            "inventory_yoy_pct": [None] * 3,
            "source": ["SMM"] * 3,
            "source_url": [""] * 3,
            "release_date": [None] * 3,
        }
    )
    cat = FakeCatalog({"chemical_monthly_survey": frame})
    df = load_monthly_survey(cat, "chemical_monthly_survey")
    row = df.filter(pl.col("report_month") == "2026-07").to_dicts()[0]
    assert row["consecutive_destock_months"] == 2
    assert row["monthly_survey_as_of"] == "2026-07"
