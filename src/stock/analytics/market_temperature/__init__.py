"""市场温度计产物管线。"""

from stock.analytics.market_temperature.pipeline import (
    MarketTemperatureRunResult,
    run_market_temperature,
)

__all__ = ["MarketTemperatureRunResult", "run_market_temperature"]
