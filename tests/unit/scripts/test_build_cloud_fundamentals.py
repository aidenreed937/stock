"""云厂商 SEC 基本面汇总测试。"""

from datetime import date

from scripts.build_cloud_fundamentals import _aggregate_financials


def test_aggregate_financials_keeps_capex_and_fundamentals_on_same_company_set() -> None:
    rows = [
        {
            "symbol": "MSFT",
            "trade_date": date(2026, 6, 30),
            "revenue_billion_usd": 90.007,
            "operating_cash_flow_billion_usd": 55.441,
            "capex_billion_usd": 35.802,
            "financials_source": "SEC_CompanyFacts",
        },
        {
            "symbol": "GOOGL",
            "trade_date": date(2026, 6, 30),
            "revenue_billion_usd": 119.796,
            "operating_cash_flow_billion_usd": 39.069,
            "capex_billion_usd": 44.924,
            "financials_source": "SEC_CompanyFacts",
        },
        {
            "symbol": "META",
            "trade_date": date(2026, 6, 30),
            "revenue_billion_usd": 60.801,
            "operating_cash_flow_billion_usd": 31.862,
            "capex_billion_usd": 30.116,
            "financials_source": "SEC_CompanyFacts",
        },
        {
            "symbol": "AMZN",
            "trade_date": date(2026, 6, 30),
            "revenue_billion_usd": 200.606,
            "operating_cash_flow_billion_usd": 45.387,
            "capex_billion_usd": 54.208,
            "financials_source": "SEC_CompanyFacts",
        },
    ]

    row = _aggregate_financials(rows).to_dicts()[0]

    assert row["num_companies"] == 4
    assert row["total_revenue_billion_usd"] == 471.21
    assert abs(row["total_ocf_billion_usd"] - 171.759) < 1e-6
    assert abs(row["total_fcf_billion_usd"] - 6.709) < 1e-6
    assert row["financial_capex_billion_usd"] == 165.05
