"""中观产业量化诊断核心引擎单元测试。"""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from stock_analytics.pipelines.industry_diagnostics import (
    IndustryConstituentsSnapshot,
    IndustryDiagnosticsResult,
    IndustryFinancialsSnapshot,
    IndustryTechnicalsSnapshot,
    IndustryValuationSnapshot,
    IndustryValueChainSnapshot,
    run_industry_diagnostics,
)
from stock_analytics.pipelines.industry_diagnostics.sources import (
    load_value_chain_map,
    resolve_industry_meta,
)


def test_resolve_industry_meta_mock() -> None:
    mock_ic = pl.DataFrame(
        {
            "index_code": ["801120.SI", "801125.SI"],
            "industry_name": ["食品饮料", "白酒Ⅱ"],
            "level": ["L1", "L2"],
            "industry_code": ["340000", "340500"],
        }
    )

    class _MockCatalog:
        def load_dataset(self, dataset: str, **kwargs: object) -> pl.DataFrame:
            if dataset == "index_classify":
                return mock_ic
            return pl.DataFrame()

    catalog = _MockCatalog()
    c1, n1, l1, _ = resolve_industry_meta(catalog, "食品饮料")  # type: ignore
    assert c1 == "801120.SI"
    assert n1 == "食品饮料"
    assert l1 == "申万一级"

    c2, n2, l2, _ = resolve_industry_meta(catalog, "白酒")  # type: ignore
    assert c2 == "801125.SI"
    assert n2 == "白酒Ⅱ"
    assert l2 == "申万二级"


def test_load_value_chain_map() -> None:
    vc = load_value_chain_map("食品饮料")
    assert len(vc.upstream) > 0
    assert "高粱/小麦/大麦等农产品" in vc.upstream[0]
    assert len(vc.high_frequency_indicators) > 0


def test_industry_diagnostics_serialization() -> None:
    res = IndustryDiagnosticsResult(
        industry_code="801120.SI",
        industry_name="食品饮料",
        level="申万一级",
        as_of_date="2026-08-21",
        technicals=IndustryTechnicalsSnapshot(close=13788.89, pct_chg=-1.36),
        valuation=IndustryValuationSnapshot(pe_ttm=19.76, pe_percentile_5y=12.5),
        financials=IndustryFinancialsSnapshot(report_date="2026-06-30"),
        constituents=IndustryConstituentsSnapshot(
            total_count=120,
            top_market_cap_leaders=[
                {"symbol": "600519.SH", "name": "贵州茅台", "total_mv_billion": 15911.4}
            ],
        ),
        value_chain=IndustryValueChainSnapshot(upstream=["农产品"], downstream=["消费终端"]),
    )

    d = res.to_dict()
    assert d["industry_code"] == "801120.SI"
    assert d["valuation"]["pe_ttm"] == 19.76

    md = res.to_markdown()
    assert "食品饮料" in md
    assert "801120.SI" in md
    assert "13788.89" in md
    assert "贵州茅台" in md


def test_run_industry_diagnostics_mock(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    trade_dates = [date(2026, 8, d) for d in range(1, 21)]
    mock_sw_df = pl.DataFrame(
        {
            "symbol": ["801120.SI"] * 20,
            "trade_date": trade_dates,
            "close": [10000.0 + i * 10 for i in range(20)],
            "pct_change": [1.0] * 20,
            "pe": [20.0 + i * 0.1 for i in range(20)],
            "pb": [3.0] * 20,
        }
    )

    mock_ic = pl.DataFrame(
        {
            "index_code": ["801120.SI"],
            "industry_name": ["食品饮料"],
            "level": ["L1"],
            "industry_code": ["340000"],
        }
    )

    class _MockCatalog:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def load_dataset(self, dataset: str, **kwargs: object) -> pl.DataFrame:
            if dataset == "index_classify":
                return mock_ic
            if dataset == "sw_daily":
                return mock_sw_df
            return pl.DataFrame()

    from stock_analytics.pipelines.industry_diagnostics import pipeline

    monkeypatch.setattr(pipeline, "DataCatalog", _MockCatalog)

    result = run_industry_diagnostics("食品饮料", target_date=date(2026, 8, 20))
    assert result.industry_code == "801120.SI"
    assert result.industry_name == "食品饮料"
    assert result.technicals.close == 10190.0
    assert result.valuation.pe_ttm is not None
