from stock_data.capability_registry import (
    DATA_SOURCE_CAPABILITY_REGISTRY,
    get_capability,
)


def test_capability_registry_keeps_native_and_non_native_support_distinct() -> None:
    assert get_capability("yfinance", "implied_volatility").status == "native_raw"
    assert get_capability("tushare", "implied_volatility").status == "raw_inputs"
    assert get_capability("lixinger", "implied_volatility").status == "unsupported"


def test_capability_registry_registers_investor_accounts_and_hg_f() -> None:
    assert get_capability("lixinger", "new_investor_accounts").endpoint_names == (
        "macro/investor",
    )
    assert get_capability("tushare", "new_investor_accounts").status == "historical_only"
    assert get_capability("yfinance", "HG=F").endpoint_names == ("macro_indicators",)
    assert get_capability("yfinance", "GC=F").status == "native"
    assert get_capability("yfinance", "CL=F").status == "native"
    assert len(DATA_SOURCE_CAPABILITY_REGISTRY) == 11
