from stock.analytics.metrics import DiagnosticLevel
from stock.analytics.metrics.outputs import build_missing_data_diagnostic


def test_missing_data_diagnostic_uses_enum_level() -> None:
    diagnostic = build_missing_data_diagnostic("return_1d", "stock_daily_bar")

    assert diagnostic.level is DiagnosticLevel.WARNING
    assert diagnostic.metric_id == "return_1d"
