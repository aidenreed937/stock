from stock_analytics.pipelines.macro_risk import MacroRiskPipeline


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
    assert "sentiment" in pipeline.config.dims
    assert "overheat_index" in pipeline.config.indices
    assert "panic_index" in pipeline.config.indices
    assert pipeline.config.factors["erp"].window == 2500
