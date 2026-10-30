from datetime import date
from unittest.mock import MagicMock

import pandas as pd

from stock_data.core.task_resolution import get_endpoint_market, resolve_task
from stock_data.fetcher.tushare.stock_fetcher import TuShareStockFetcher


def test_tushare_us_daily_task_uses_us_market_and_us_daily_api() -> None:
    task = resolve_task("tushare", "us_stock_daily_bar")

    assert task.api_name == "us_daily"
    assert task.dataset == "stock_daily_bar"
    assert task.quality_profile == "bar"
    assert get_endpoint_market("tushare", "us_stock_daily_bar") == "US"
    assert resolve_task("tushare", "us_stock_daily_bar").provider == "tushare"


def test_tushare_stock_fetcher_routes_us_daily_without_new_client() -> None:
    client = MagicMock()
    client.paginate_threshold = 2000
    client.query.return_value = pd.DataFrame(
        {
            "ts_code": ["AAPL"],
            "trade_date": ["20261007"],
            "open": [335.0],
            "high": [338.0],
            "low": [334.0],
            "close": [336.67],
            "vol": [1000.0],
            "amount": [336670.0],
        }
    )
    fetcher = TuShareStockFetcher(client=client)

    frame = fetcher.fetch_daily_bars_df(
        "AAPL",
        date(2026, 10, 1),
        date(2026, 10, 7),
        endpoint="us_daily",
    )

    assert frame.get_column("symbol").to_list() == ["AAPL"]
    assert frame.get_column("close").to_list() == [336.67]
    assert client.query.call_args.args[0] == "us_daily"
    assert client.query.call_args.kwargs["ts_code"] == "AAPL"
