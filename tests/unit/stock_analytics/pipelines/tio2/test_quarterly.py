"""钛白粉季度化引擎（Phase 2）单元测试。

覆盖：
1. Q1 月频构建使用逐月现货价/成本/利用率；
2. 财务费用按最新报告期单季摊销 × 情景系数（不再年化/4 或折半）；
3. 数据缺失月份回退情景价并记录 assumption；
4. to_dataframe 输出契约。
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from stock_analytics.pipelines.tio2.projections import CompanyProjectionEngine
from stock_analytics.pipelines.tio2.quarterly import (
    QuarterlyProjectionEngine,
    quarter_months,
)

CONFIG_PATH = "config/industry/chemicals/tio2/company_projections.yaml"


class FakeCatalog:
    """兼容 DataCatalog 与鸭子类型测试替身（支持 symbols/columns 可选参数）。"""

    def __init__(self, datasets: dict[str, pl.DataFrame]) -> None:
        self._datasets = datasets

    def load_dataset(self, dataset: str, **kwargs: object) -> pl.DataFrame:
        if dataset not in self._datasets:
            return pl.DataFrame()
        return self._datasets[dataset]


def _spot_frame() -> pl.DataFrame:
    """2026-01~03 月内单快照现货（钛白粉/攀西钛精矿/湖北硫酸），release_date ≤ as_of。"""
    rows: list[dict[str, object]] = []
    specs = [
        # (月, 钛白粉, 攀西钛精矿坑口, 湖北硫酸)
        ("2026-01-15", 13827.74, 1610.0, 932.98),
        ("2026-02-15", 13900.0, 1560.0, 1014.46),
        ("2026-03-15", 14416.77, 1510.0, 1273.06),
    ]
    for d, p, ore, acid in specs:
        rows.append(
            {
                "product_name": "钛白粉",
                "symbol": "TiO2",
                "trade_date": d,
                "release_date": d,
                "spot_price_cny": p,
                "region": "国内",
                "spec": "金红石型",
            }
        )
        rows.append(
            {
                "product_name": "钛精矿",
                "symbol": "TiO2",
                "trade_date": d,
                "release_date": d,
                "spot_price_cny": ore,
                "region": "攀西",
                "spec": "46%",
            }
        )
        rows.append(
            {
                "product_name": "硫酸",
                "symbol": "H2SO4",
                "trade_date": d,
                "release_date": d,
                "spot_price_cny": acid,
                "region": "湖北",
                "spec": "98%;工业级浓硫酸",
            }
        )
    return pl.DataFrame(rows)


def _survey_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "report_month": ["2026-01", "2026-02", "2026-03"],
            "symbol": ["TiO2"] * 3,
            "operating_rate_pct": [78.0, 78.0, 78.0],
            "release_date": [date(2026, 2, 15), date(2026, 3, 15), date(2026, 4, 15)],
        }
    )


def _income_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["002145.SZ", "002145.SZ"],
            "end_date": [date(2026, 3, 31), date(2026, 6, 30)],
            "ann_date": [date(2026, 4, 29), date(2026, 8, 5)],
            "fin_exp": [1.0e8, 3.0e8],  # Q1 1.0亿；H1 3.0亿 → 单季 1.5亿
            "total_revenue": [2.0e9, 5.0e9],
        }
    )


def _balancesheet_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["002145.SZ"],
            "end_date": [date(2026, 6, 30)],
            "ann_date": [date(2026, 8, 5)],
            "total_hldr_eqy_exc_min_int": [1.2e10],
        }
    )


def _daily_basic_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["002145.SZ"],
            "trade_date": [date(2026, 9, 7)],
            "total_share": [380000.0],  # 万股 → 38 亿股
            "pb": [1.23],
        }
    )


def _mainbz_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["002145.SZ"] * 3,
            "end_date": [date(2025, 12, 31)] * 3,
            "bz_item": ["新能源材料", "磷矿", "其他主营业务"],
            "bz_sales": [3.6e8, 2.0e8, 5.0e8],
        }
    )


def _customs_export_frame() -> pl.DataFrame:
    """TiO2 出口 ASP（USD/吨）2026-01~03，供出口加权计价（RMB = USD×7.2）。"""
    return pl.DataFrame(
        {
            "report_month": ["2026-01", "2026-02", "2026-03"],
            "commodity_code": ["TiO2"] * 3,
            "commodity_name": ["钛白粉"] * 3,
            "export_asp_usd_ton": [2000.0, 2050.0, 2100.0],
        }
    )


def _make_engine(
    spot: pl.DataFrame | None = None, survey: pl.DataFrame | None = None
) -> tuple[CompanyProjectionEngine, FakeCatalog]:
    datasets = {
        "chemical_spot_price": spot if spot is not None else _spot_frame(),
        "chemical_monthly_survey": survey if survey is not None else _survey_frame(),
        "chemical_customs_export": _customs_export_frame(),
        # 提供在岸汇率 DEXCHUS=7.2（fake 确定值，阻止回退读取真实黄金表，测试可复现）
        "macro_indicators": pl.DataFrame(
            {
                "symbol": ["DEXCHUS"] * 13,
                "trade_date": [
                    "2026-01-15",
                    "2026-02-15",
                    "2026-03-15",
                    "2026-04-15",
                    "2026-05-15",
                    "2026-06-15",
                    "2026-07-15",
                    "2026-08-15",
                    "2026-09-15",
                    "2026-10-15",
                    "2026-11-15",
                    "2026-12-15",
                    "2026-09-08",
                ],
                "close": [7.2] * 13,
            }
        ),
        "income": _income_frame(),
        "balancesheet": _balancesheet_frame(),
        "daily_basic": _daily_basic_frame(),
        "fina_mainbz": _mainbz_frame(),
    }
    cat = FakeCatalog(datasets)
    engine = CompanyProjectionEngine(
        config_path=CONFIG_PATH, catalog=cat, as_of_date=date(2026, 9, 20)
    )
    return engine, cat


def test_quarter_months() -> None:
    assert quarter_months("2026Q1") == ["2026-01", "2026-02", "2026-03"]
    assert quarter_months("2026Q4") == ["2026-10", "2026-11", "2026-12"]


def test_q1_uses_monthly_spot_prices_and_utilization() -> None:
    engine, _ = _make_engine()
    qe = QuarterlyProjectionEngine(engine)
    results = qe.project_quarters("002145.SZ", "current_spot", ["2026Q1"])

    assert len(results) == 1
    r = results[0]
    assert r.quarter_key == "2026Q1"
    assert r.months_used == ["2026-01", "2026-02", "2026-03"]
    # 三个月现货/利用率均齐备：备注中仅应有财务费用摊销说明，无现货/开工率回退
    notes = "；".join(r.assumption_notes)
    assert "现货缺失" not in notes
    assert "开工率调研缺失" not in notes
    assert r.total_revenue_cny > 0
    assert r.eps_cny != 0.0

    sulfate = next(s for s in r.segments if s.segment_key == "sulfate_tio2")
    # 月均销量 = 55万吨 × 78% / 12 = 3.575 万吨；Q1 = 10.725 万吨
    assert sulfate.sales_volume_tons == pytest.approx(107250.0, rel=1e-3)
    # 出口加权实现价（w=0.35，FOB 口径不含退税）：Jan 14,028 / Feb 14,201 / Mar 14,663 → 约 14,297
    assert sulfate.unit_price_cny == pytest.approx(14297.0, rel=1e-2)
    # 单位成本 = 2.3×到厂矿 + 3×酸 + 7000 − 100（各月不同 → 加权均值）
    assert sulfate.unit_cost_cny > 0


def test_finance_expense_uses_quarterly_run_rate_with_scale() -> None:
    engine, _ = _make_engine()
    qe = QuarterlyProjectionEngine(engine)
    r = qe.project_quarters("002145.SZ", "current_spot", ["2026Q1"])[0]
    # 最新报告期 2026-06-30 fin_exp=3.0e8 → 单季 1.5e8；current_spot scale=1.0
    assert r.finance_expense_cny == pytest.approx(1.5e8, rel=1e-3)

    r_mid = qe.project_quarters("002145.SZ", "mid_cycle", ["2026Q1"])[0]
    # mid_cycle scale=0.55 → 1.5e8 × 0.55 = 8.25e7
    assert r_mid.finance_expense_cny == pytest.approx(8.25e7, rel=1e-3)


def test_missing_month_falls_back_to_scenario_with_note() -> None:
    # 只有 2026-01 现货 → Q1 的 02/03 月回退情景价并记录
    spot = _spot_frame().filter(pl.col("trade_date").cast(pl.Utf8).str.starts_with("2026-01"))
    engine, _ = _make_engine(spot=spot)
    qe = QuarterlyProjectionEngine(engine)
    r = qe.project_quarters("002145.SZ", "current_spot", ["2026Q1"])[0]

    notes = "；".join(r.assumption_notes)
    assert "2026-02" in notes
    assert "2026-03" in notes
    # 出口加权实现价：01 月用实际现货+出口ASP（含退税）；02/03 月用情景价 14,200 出口加权外推
    sulfate = next(s for s in r.segments if s.segment_key == "sulfate_tio2")
    assert 13500.0 < sulfate.unit_price_cny < 16500.0


def test_to_dataframe_contract() -> None:
    engine, _ = _make_engine()
    qe = QuarterlyProjectionEngine(engine)
    results = qe.project_quarters("002145.SZ", "current_spot", ["2026Q1", "2026Q2"])
    df = qe.to_dataframe(results)

    assert len(df) == 2
    for col in (
        "symbol",
        "company_name",
        "quarter_key",
        "scenario_key",
        "net_profit_attr_p_cny",
        "eps_cny",
        "assumption_notes",
    ):
        assert col in df.columns
    assert set(df["quarter_key"].to_list()) == {"2026Q1", "2026Q2"}
