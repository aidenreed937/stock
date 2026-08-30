from stock_strategy.industry.live import (
    inspect_live_industry_signal,
    load_industry_etf_map,
)


def test_load_industry_etf_map() -> None:
    etf_map = load_industry_etf_map()
    assert len(etf_map) >= 27
    assert "801010.SI" in etf_map
    assert etf_map["801010.SI"]["symbol"] == "159825.SZ"


def test_inspect_live_industry_signal() -> None:
    res = inspect_live_industry_signal(
        strategy_key="industry_momentum",
        total_capital=200_000.0,
    )
    assert res.strategy_key == "industry_momentum"
    assert res.markdown_card != ""
    assert "实盘巡检卡片" in res.markdown_card
