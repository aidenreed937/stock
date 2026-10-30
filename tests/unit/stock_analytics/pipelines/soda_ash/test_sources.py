"""纯碱数据读取层测试（FakeCatalog + tmp CSV）。"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from stock_analytics.pipelines.soda_ash.market_sources import (
    load_company_panel,
    load_futures_daily,
    load_hold_rank,
    load_spot_benchmark,
    load_spreads,
)
from stock_analytics.pipelines.soda_ash.sources import (
    load_capacity_projects,
    load_customs_export,
    load_factory_inventory,
    load_nbs_plate_glass,
    load_nbs_soda_ash,
    load_warehouse_receipts,
)


class FakeCatalog:
    """鸭子类型 DataCatalog：load_dataset 返回预置帧或抛 KeyError。"""

    def __init__(self, datasets: dict[str, pl.DataFrame]) -> None:
        self._datasets = datasets

    def load_dataset(self, dataset: str) -> pl.DataFrame:
        if dataset not in self._datasets:
            raise KeyError(f"fake dataset missing: {dataset}")
        return self._datasets[dataset]


def _customs_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "period": ["2024-01-01", "2024-01-15", "2024-02-01"],
            "hs_code": ["28362000", "28362000", "28362000"],
            "product_key": ["soda_ash", "soda_ash", "soda_ash"],
            "export_quantity": [10.0, 20.0, 30.0],
            "export_value_usd": [1000.0, 2000.0, 3000.0],
            "yoy_growth": [1.0, 2.0, 3.0],
        }
    )


def test_load_nbs_soda_ash(tmp_path: Path) -> None:
    p = tmp_path / "nbs_soda_ash_monthly.csv"
    p.write_text(
        "report_month,output_current,output_yoy\n2024-01,200.0,5.0\n2024-02,210.0,6.0\n",
        encoding="utf-8",
    )
    df = load_nbs_soda_ash(p)
    assert df.columns == ["report_month", "soda_output_w_tons", "soda_output_yoy"]
    assert df["soda_output_w_tons"].to_list() == [200.0, 210.0]


def test_load_nbs_plate_glass(tmp_path: Path) -> None:
    p = tmp_path / "nbs_plate_glass_monthly.csv"
    p.write_text(
        "report_month,output_current,output_yoy\n2024-01,7000.0,3.0\n",
        encoding="utf-8",
    )
    df = load_nbs_plate_glass(p)
    assert df["glass_output_w_cases"].to_list() == [7000.0]


def test_load_customs_export_aggregates_by_month() -> None:
    cat = FakeCatalog({"customs_trade_gacc": _customs_frame()})
    df = load_customs_export(cat, "customs_trade_gacc", "customs_trade")
    assert df["report_month"].to_list() == ["2024-01", "2024-02"]
    assert df["export_qty_tons"].to_list() == [30.0, 30.0]
    assert df["export_qty_yoy"].to_list() == [1.5, 3.0]


def _customs_frame_gacc_contract() -> pl.DataFrame:
    """真实 customs_trade_gacc 契约：export_volume(kg) + quantity_unit_norm，无逐月同比列。"""
    months = [f"2024-{m:02d}" for m in range(1, 13)] + ["2025-01", "2025-02"]
    return pl.DataFrame(
        {
            "report_month": months,
            "hs_code": ["28362000"] * 14,
            "product_key": ["soda_ash"] * 14,
            "trade_direction": ["export"] * 14,
            "export_volume": [1.0e7] * 14,  # 1e7 kg = 1 万吨
            "quantity_unit_norm": ["kg"] * 14,
            "export_value_usd": [3.0e6] * 14,
        }
    )


def test_load_customs_export_real_gacc_contract() -> None:
    """对齐真实 GACC 契约：export_volume 千克归一为吨，缺失同比列时自算滞后 12 期 YoY。"""
    cat = FakeCatalog({"customs_trade_gacc": _customs_frame_gacc_contract()})
    df = load_customs_export(cat, "customs_trade_gacc", "customs_trade")
    assert df.height == 14
    # 1e7 kg = 1e4 吨 = 1 万吨
    assert df["export_qty_tons"].to_list() == [10000.0] * 14
    yoy = df["export_qty_yoy"].to_list()
    # 前 12 期无滞后基期；2025-01/02 与上年同月持平 → 0%
    assert yoy[:12] == [None] * 12
    assert yoy[12:] == [0.0, 0.0]


def test_load_customs_export_excludes_import_rows() -> None:
    frame = pl.DataFrame(
        {
            "report_month": ["2024-01", "2024-01"],
            "hs_code": ["28362000", "28362000"],
            "trade_direction": ["export", "import"],
            "export_volume": [1.0e7, 5.0e7],
            "quantity_unit_norm": ["kg", "kg"],
            "export_value_usd": [3.0e6, 1.5e7],
        }
    )
    cat = FakeCatalog({"customs_trade_gacc": frame})
    df = load_customs_export(cat, "customs_trade_gacc", "customs_trade")
    # 仅统计出口行，进口的 5e7 kg 不得混入
    assert df["export_qty_tons"].to_list() == [10000.0]


def test_load_warehouse_receipts_monthly() -> None:
    cat = FakeCatalog(
        {
            "futures_inventory": pl.DataFrame(
                {
                    "trade_date": ["2024-01-02", "2024-01-31", "2024-02-28"],
                    "symbol": ["SA", "SA", "SA"],
                    "inventory": [100.0, 110.0, 120.0],
                }
            )
        }
    )
    df = load_warehouse_receipts(cat, "futures_inventory")
    assert df["warehouse_receipt_month_end"].to_list() == [110.0, 120.0]
    assert df["warehouse_receipt_avg"].to_list() == [105.0, 120.0]


def test_load_factory_inventory_implied_shipment_rate() -> None:
    cat = FakeCatalog(
        {
            "chemical_weekly_survey": pl.DataFrame(
                {
                    "report_date": ["2024-01-05", "2024-01-12"],
                    "product_name": ["纯碱", "纯碱"],
                    "factory_inventory_w_tons": [100.0, 90.0],
                    "weekly_output_w_tons": [50.0, 50.0],
                    "shipment_rate_pct": [None, None],
                    "operating_rate_pct": [80.0, 82.0],
                }
            )
        }
    )
    df = load_factory_inventory(cat, "chemical_weekly_survey")
    assert df["factory_inv_month_end_w_tons"].to_list() == [90.0]
    # 补算: (50 - (90-100))/50 = 120%
    assert df["survey_shipment_rate_pct"].to_list() == [120.0]


def test_load_spreads_monthly() -> None:
    cat = FakeCatalog(
        {
            "chemical_spreads": pl.DataFrame(
                {
                    "trade_date": ["2024-01-02", "2024-01-31"],
                    "symbol": ["SA", "SA"],
                    "product_price_cny": [1800.0, 1820.0],
                    "byproduct_price_cny": [800.0, 820.0],
                    "spread_margin_cny": [100.0, 120.0],
                    "margin_regime": ["normal", "normal"],
                }
            )
        }
    )
    df = load_spreads(cat, "chemical_spreads")
    assert df["double_ton_margin_cny"].to_list() == [110.0]
    assert df["soda_spot_price_cny"].to_list() == [1810.0]


def test_load_hold_rank_and_futures_daily() -> None:
    cat = FakeCatalog(
        {
            "futures_hold_rank": pl.DataFrame(
                {
                    "trade_date": ["2024-01-31"],
                    "symbol": ["SA"],
                    "top20_net_long_vol": [1234.0],
                    "smart_money_bias": ["bullish"],
                }
            ),
            "futures_daily": pl.DataFrame(
                {
                    "trade_date": ["2024-01-02", "2024-01-31"],
                    "symbol": ["SA", "SA"],
                    "settle": [1700.0, 1720.0],
                }
            ),
        }
    )
    hold = load_hold_rank(cat, "futures_hold_rank")
    assert hold["top20_net_long_vol"].to_list() == [1234.0]
    fut = load_futures_daily(cat, "futures_daily")
    assert fut["futures_settle_month_end"].to_list() == [1720.0]
    assert fut["futures_settle_avg"].to_list() == [1710.0]


def test_load_spot_benchmark_basis() -> None:
    cat = FakeCatalog(
        {
            "chemical_spot_price": pl.DataFrame(
                {
                    "trade_date": ["2024-01-31", "2024-01-31", "2024-01-31"],
                    "symbol": ["SA", "SA_light", "UR"],
                    "spot_price_cny": [1800.0, 1750.0, 2200.0],
                }
            ),
            "futures_daily": pl.DataFrame(
                {
                    "trade_date": ["2024-01-31"],
                    "symbol": ["SA"],
                    "settle": [1700.0],
                }
            ),
        }
    )
    result = load_spot_benchmark(cat, "chemical_spot_price", "futures_daily")
    assert result["sa_heavy_price"] == 1800.0
    assert result["basis_cny"] == 100.0
    assert result["basis_rate_pct"] == 5.88


def test_load_company_panel_returns_empty_without_fallback() -> None:
    cat = FakeCatalog({})
    df = load_company_panel(cat, "mart/soda_ash_company_panel", tushare_factory=None)
    assert df.is_empty()


def test_load_capacity_projects_missing_file(tmp_path: Path) -> None:
    assert load_capacity_projects(tmp_path / "missing.yaml") == []
