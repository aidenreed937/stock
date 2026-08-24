"""个股量化诊断核心引擎单元测试。"""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from stock_analytics.pipelines.stock_diagnostics import (
    CapitalFlowSnapshot,
    FinancialsSnapshot,
    MarketContextSnapshot,
    ScreenSnapshot,
    StockDiagnosticsResult,
    TechnicalsSnapshot,
    ValuationSnapshot,
    run_stock_diagnostics,
)
from stock_analytics.pipelines.stock_diagnostics.sources import (
    compute_percentile,
    load_10y_treasury_yield,
    load_screen_status,
    resolve_symbol_meta,
)


def test_compute_percentile() -> None:
    s = pl.Series("val", [10.0, 20.0, 30.0, 40.0, 50.0])
    p = compute_percentile(s, 30.0)
    assert p == 60.0

    p_min = compute_percentile(s, 5.0)
    assert p_min == 0.0

    p_max = compute_percentile(s, 60.0)
    assert p_max == 100.0

    assert compute_percentile(pl.Series("empty", []), 10.0) is None


def test_missing_treasury_data_does_not_invent_a_rate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class _MissingCatalog:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def load_dataset(self, dataset: str) -> pl.DataFrame:
            raise RuntimeError(f"missing {dataset}")

    from stock_analytics.pipelines.stock_diagnostics import sources

    monkeypatch.setattr(sources, "DataCatalog", _MissingCatalog)

    assert load_10y_treasury_yield(tmp_path) is None


def test_corrupt_screen_snapshot_is_unscreened(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    snapshot_dir = tmp_path / "data/analytics/stock_screen/latest"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "excluded.csv").write_text("symbol\n600519.SH\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    from stock_analytics.pipelines.stock_diagnostics import sources

    def _raise_read_csv(_path: Path) -> pl.DataFrame:
        raise RuntimeError("corrupt snapshot")

    monkeypatch.setattr(sources.pl, "read_csv", _raise_read_csv)

    result = load_screen_status("600519.SH")

    assert result.status == "unscreened"
    assert result.reasons == ["排雷快照读取失败: excluded.csv"]


def test_resolve_symbol_meta_with_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_basic = pl.DataFrame(
        {
            "symbol": ["600519.SH", "000001.SZ"],
            "name": ["贵州茅台", "平安银行"],
            "industry": ["白酒", "银行"],
            "area": ["贵州", "深圳"],
            "market": ["主板", "主板"],
        }
    )

    class _MockCatalog:
        def load_dataset(self, dataset: str, **kwargs: object) -> pl.DataFrame:
            if dataset == "stock_basic":
                return mock_basic
            return pl.DataFrame()

    catalog = _MockCatalog()
    sym, name, industry, _area, _market = resolve_symbol_meta(catalog, "600519")  # type: ignore
    assert sym == "600519.SH"
    assert name == "贵州茅台"
    assert industry == "白酒"

    # 未匹配回退
    sym2, name2, ind2, _, _ = resolve_symbol_meta(catalog, "999999")  # type: ignore
    assert sym2 == "999999"
    assert name2 == "999999"
    assert ind2 == "未知行业"


def test_diagnostics_result_serialization() -> None:
    res = StockDiagnosticsResult(
        symbol="600519.SH",
        name="贵州茅台",
        as_of_date="2026-08-20",
        industry="白酒",
        area="贵州",
        market="主板",
        technicals=TechnicalsSnapshot(
            close=1432.5,
            pre_close=1430.0,
            pct_chg=0.17,
            ma20=1460.0,
            ma60=1400.0,
            rsi14=52.0,
            trend_description="多头排列",
        ),
        valuation=ValuationSnapshot(
            pe_ttm=21.8,
            pe_percentile_5y=32.4,
            pb=8.5,
            dv_ttm=3.65,
            treasury_10y_yield=1.68,
            dividend_spread_10y=1.97,
            total_mv_billion=18000.0,
            circ_mv_billion=18000.0,
            value_trap_warning=False,
        ),
        financials=FinancialsSnapshot(
            report_date="2026-06-30",
            roe=27.4,
            netprofit_yoy=9.6,
            revenue_yoy=8.2,
            gross_margin=91.5,
            debt_to_assets=12.3,
            growth_deceleration=False,
            latest_forecast={"type": "预增", "p_change_min": 10.0, "p_change_max": 15.0},
        ),
        capital_flow=CapitalFlowSnapshot(
            main_net_inflow_20d_billion=3.5,
            northbound_hold_ratio=6.8,
        ),
        screen=ScreenSnapshot(status="passed", reasons=[]),
        market_context=MarketContextSnapshot(
            as_of_date="2026-08-20",
            temperature_score=45.0,
            temperature_band="中性偏冷",
            industry_name="白酒",
        ),
    )

    d = res.to_dict()
    assert d["symbol"] == "600519.SH"
    assert d["valuation"]["pe_ttm"] == 21.8
    assert d["financials"]["roe"] == 27.4
    assert d["capital_flow"]["main_net_inflow_20d_billion"] == 3.5

    md = res.to_markdown()
    assert "贵州茅台" in md
    assert "600519.SH" in md
    assert "1432.50" in md
    assert "21.80" in md
    assert "27.40%" in md
    assert "预增" in md


def test_run_stock_diagnostics_mock(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    trade_dates = [date(2026, 8, d) for d in range(1, 21)]
    prices = [100.0 + i for i in range(20)]

    mock_bars = pl.DataFrame(
        {
            "symbol": ["600519.SH"] * 20,
            "trade_date": trade_dates,
            "close": prices,
            "pre_close": [99.0] + prices[:-1],
            "pct_chg": [1.0] * 20,
            "volume": [1000] * 20,
            "amount": [100000.0] * 20,
        }
    )

    mock_daily_basic = pl.DataFrame(
        {
            "symbol": ["600519.SH"] * 20,
            "trade_date": trade_dates,
            "close": prices,
            "pe_ttm": [20.0 + i * 0.1 for i in range(20)],
            "pb": [3.0] * 20,
            "ps_ttm": [5.0] * 20,
            "dv_ttm": [2.5] * 20,
            "total_mv": [1000000.0] * 20,
            "circ_mv": [1000000.0] * 20,
            "turnover_rate": [1.2] * 20,
        }
    )

    mock_fina = pl.DataFrame(
        {
            "symbol": ["600519.SH"],
            "ann_date": [date(2026, 7, 15)],
            "end_date": [date(2026, 6, 30)],
            "roe": [25.0],
            "netprofit_yoy": [10.0],
            "tr_yoy": [8.0],
            "grossprofit_margin": [90.0],
            "debt_to_assets": [15.0],
        }
    )

    mock_basic = pl.DataFrame(
        {
            "symbol": ["600519.SH"],
            "name": ["贵州茅台"],
            "industry": ["白酒"],
            "area": ["贵州"],
            "market": ["主板"],
        }
    )

    class _MockDataCatalog:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def load_dataset(self, dataset: str, **kwargs: object) -> pl.DataFrame:
            if dataset == "stock_basic":
                return mock_basic
            if dataset == "stock_daily_bar":
                return mock_bars
            if dataset == "daily_basic":
                return mock_daily_basic
            if dataset == "fina_indicator":
                return mock_fina
            return pl.DataFrame()

    from stock_analytics.pipelines.stock_diagnostics import pipeline

    monkeypatch.setattr(pipeline, "DataCatalog", _MockDataCatalog)
    monkeypatch.setattr(pipeline, "load_10y_treasury_yield", lambda _storage_dir: 1.68)

    result = run_stock_diagnostics("600519", target_date=date(2026, 8, 20))
    assert result.symbol == "600519.SH"
    assert result.name == "贵州茅台"
    assert result.technicals.close == 119.0
    assert result.valuation.pe_ttm is not None
    assert result.financials.roe == 25.0
    assert result.valuation.dividend_spread_10y is not None
