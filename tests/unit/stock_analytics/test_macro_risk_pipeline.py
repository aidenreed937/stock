from stock_analytics.pipelines.macro_risk import MacroRiskPipeline


def test_macro_risk_pipeline_init() -> None:
    pipeline = MacroRiskPipeline()
    assert "erp" in pipeline.config.factors
    assert "breadth" in pipeline.config.dims
    assert "overheat_index" in pipeline.config.indices
    assert pipeline.config.factors["erp"].window == 2500
