from datetime import date

from stock_strategy.industry.assembly import assemble_industry_panel, load_industry_price_panel


def test_assemble_industry_panel_returns_expected_columns() -> None:
    panel = assemble_industry_panel(start_date=date(2026, 8, 1))
    assert not panel.is_empty()
    assert "trade_date" in panel.columns
    assert "industry_code" in panel.columns
    assert "ind_momentum" in panel.columns
    assert "panic_index" in panel.columns
    assert "benchmark_close" in panel.columns


def test_load_industry_price_panel() -> None:
    prices = load_industry_price_panel(
        symbols=["801010.SI", "801030.SI"],
        start_date=date(2026, 8, 1),
    )
    assert not prices.is_empty()
    assert set(prices["symbol"].unique().to_list()) == {"801010.SI", "801030.SI"}
    assert "close" in prices.columns
