from datetime import date

import polars as pl

from stock_analytics.pipelines.macro_risk import MacroRiskPipeline
from stock_analytics.pipelines.macro_risk.config import FactorConfig, MacroRiskConfig


def test_macro_risk_pipeline_init() -> None:
    pipeline = MacroRiskPipeline()
    assert "erp" in pipeline.config.factors
    assert "fund_issue_pct" in pipeline.config.factors
    assert "repurchase" in pipeline.config.factors
    assert "insider_net" in pipeline.config.factors
    assert "cb_price" in pipeline.config.factors
    assert "copper_gold" in pipeline.config.factors
    assert "us_yield_curve" in pipeline.config.factors

    assert "breadth" in pipeline.config.dims
    assert "corporate" in pipeline.config.dims
    assert "cross_asset" in pipeline.config.dims
    assert "fear" in pipeline.config.dims
    assert "euphoria" in pipeline.config.dims
    assert "overheat_index" in pipeline.config.indices
    assert "panic_index" in pipeline.config.indices
    assert pipeline.config.factors["erp"].window == 2500


def test_macro_risk_completeness_full() -> None:
    """核心字段齐全时完整性报告 complete=true。"""
    from stock_analytics.pipelines.macro_risk.pipeline import _check_data_completeness

    row = {
        "overheat_index": 69.2,
        "panic_index": 33.9,
        "dim_valuation": 47.2,
        "dim_leverage": 84.9,
        "dim_fear": 28.8,
        "dim_flow": 35.7,
        "dim_crowding": 78.4,
        "dim_breadth": 37.0,
    }
    rep = _check_data_completeness(row)
    assert rep["complete"] is True
    assert rep["missing_fields"] == []
    assert rep["total"] == 8 and rep["available"] == 8


def test_macro_risk_completeness_valuation_gap() -> None:
    """估值冷启动期 dim_valuation 缺失 → complete=false 且列入 missing_fields。"""
    from stock_analytics.pipelines.macro_risk.pipeline import _check_data_completeness

    row = {
        "overheat_index": 85.4,
        "panic_index": 21.9,
        "dim_valuation": None,  # 2015-01~2016-08 冷启动缺口
        "dim_leverage": 90.8,
        "dim_fear": 40.0,
        "dim_flow": 50.0,
        "dim_crowding": 98.3,
        "dim_breadth": 30.0,
    }
    rep = _check_data_completeness(row)
    assert rep["complete"] is False
    assert "dim_valuation" in rep["missing_fields"]
    assert rep["available"] == 7


def test_macro_risk_pipeline_does_not_asof_fund_issuance(monkeypatch) -> None:
    """公募新发按交易日精确连接，不能把最后一个有效月度值向未来延续。"""
    pipeline = MacroRiskPipeline()
    pipeline.config = MacroRiskConfig(
        factors={
            "fund_issue_pct": FactorConfig(
                series="fund_issuance",
                column="fund_issue_pct5y",
                window=10,
                min_periods=1,
                direction="raw",
            )
        },
        dims={},
        indices={},
    )
    axis = pl.DataFrame({"trade_date": [date(2026, 5, 28), date(2026, 5, 29), date(2026, 6, 1)]})
    fund_issuance = pl.DataFrame(
        {
            "trade_date": [date(2026, 5, 28), date(2026, 5, 29)],
            "fund_issue_pct5y": [70.0, 88.0],
        }
    )

    monkeypatch.setattr(pipeline, "_market_daily", lambda: axis)
    monkeypatch.setattr(pipeline, "_get_raw_series", lambda name: fund_issuance)

    result = pipeline.run(as_of=date(2026, 6, 1), output_dir=None)
    may_score = result.filter(pl.col("trade_date") == date(2026, 5, 29))["fund_issue_pct_score"][0]
    jun_score = result.filter(pl.col("trade_date") == date(2026, 6, 1))["fund_issue_pct_score"][0]
    assert may_score is not None
    assert jun_score is None
