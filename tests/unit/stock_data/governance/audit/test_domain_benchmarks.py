"""审计领域、周期与统一事实基准体系单元测试。"""

from datetime import date
from unittest.mock import MagicMock, patch

import polars as pl

from stock_data.governance.audit.benchmarks.calendar import MacroCalendarBenchmarkProvider
from stock_data.governance.audit.benchmarks.equity import EquityDailyBenchmarkProvider
from stock_data.governance.audit.benchmarks.index import IndexDailyBenchmarkProvider
from stock_data.governance.audit.benchmarks.industry import IndustryDailyBenchmarkProvider
from stock_data.governance.audit.domains import AuditDomain, AuditFrequency
from stock_data.governance.audit.engine import (
    UniversalAuditEngine,
    extract_identity_keys,
    print_audit_summary_report,
)
from stock_data.governance.audit.registry import (
    DatasetAuditSpec,
    get_audit_spec,
    resolve_benchmark_provider,
)


def test_domains_and_frequency_enums() -> None:
    assert AuditDomain.EQUITY == "equity"
    assert AuditDomain.INDUSTRY == "industry"
    assert AuditDomain.INDEX == "index"
    assert AuditFrequency.DAILY == "daily"
    assert AuditFrequency.MONTHLY == "monthly"


def test_registry_lookup() -> None:
    spec = get_audit_spec("stock_daily_bar")
    assert spec.domain == AuditDomain.EQUITY
    assert spec.frequency == AuditFrequency.DAILY
    assert spec.min_expected_ratio >= 0.99

    spec_unknown = get_audit_spec("unknown_table")
    assert spec_unknown.domain == AuditDomain.UNSUPPORTED
    assert spec_unknown.frequency == AuditFrequency.DAILY


def test_equity_benchmark_provider() -> None:
    mock_catalog = MagicMock()
    # 模拟真实落盘中 suspend_d 的 trade_date 为 Date 类型
    mock_catalog.load_dataset.side_effect = lambda name, **kw: (
        pl.DataFrame({"symbol": ["000001.SZ", "600000.SH"], "list_date": ["19910403", "19991110"]})
        if name == "stock_basic"
        else pl.DataFrame({"symbol": ["600000.SH"], "trade_date": [date(2026, 8, 14)]})
    )

    with patch(
        "stock_data.governance.audit.benchmarks.equity.get_trading_calendar",
        return_value=[date(2026, 8, 14)],
    ):
        provider = EquityDailyBenchmarkProvider(catalog=mock_catalog)
        expected_df = provider.get_expected_keys(date(2026, 8, 14), date(2026, 8, 14))
        assert len(expected_df) == 2
        assert "symbol" in expected_df.columns
        assert "trade_date" in expected_df.columns

        suspended_df = provider.get_suspended_keys(date(2026, 8, 14), date(2026, 8, 14))
        assert len(suspended_df) == 1
        assert suspended_df["symbol"][0] == "600000.SH"
        assert suspended_df["trade_date"][0] == "20260814"


def test_industry_benchmark_provider() -> None:
    mock_catalog = MagicMock()
    mock_catalog.load_dataset.return_value = pl.DataFrame()
    with patch(
        "stock_data.governance.audit.benchmarks.industry.get_trading_calendar",
        return_value=[date(2026, 8, 14)],
    ):
        # TuShare 申万行业
        provider = IndustryDailyBenchmarkProvider(catalog=mock_catalog, data_source="tushare")
        expected_df = provider.get_expected_keys(date(2026, 8, 14), date(2026, 8, 14))
        assert len(expected_df) == 31
        assert "801010.SI" in expected_df["symbol"].to_list()

        # LiXinger 申万行业 (32 个节点)
        lx_provider = IndustryDailyBenchmarkProvider(catalog=mock_catalog, data_source="lixinger")
        lx_expected_df = lx_provider.get_expected_keys(date(2026, 8, 14), date(2026, 8, 14))
        assert len(lx_expected_df) == 32
        assert "110000" in lx_expected_df["symbol"].to_list()


def test_index_benchmark_provider() -> None:
    mock_catalog = MagicMock()
    with patch(
        "stock_data.governance.audit.benchmarks.index.get_trading_calendar",
        return_value=[date(2026, 8, 14)],
    ):
        provider = IndexDailyBenchmarkProvider(catalog=mock_catalog)
        expected_df = provider.get_expected_keys(date(2026, 8, 14), date(2026, 8, 14))
        symbols = expected_df["symbol"].to_list()
        assert "000300.SH" in symbols
        assert "000688.SH" in symbols
        assert "688981.SH" not in symbols


def test_macro_calendar_benchmark_provider() -> None:
    monthly_provider = MacroCalendarBenchmarkProvider(frequency="monthly")
    m_df = monthly_provider.get_expected_keys(date(2026, 1, 1), date(2026, 3, 31))
    assert len(m_df) == 3
    assert m_df["trade_date"].to_list() == ["202601", "202602", "202603"]

    quarterly_provider = MacroCalendarBenchmarkProvider(frequency="quarterly")
    q_df = quarterly_provider.get_expected_keys(date(2026, 1, 1), date(2026, 6, 30))
    assert len(q_df) == 2
    assert q_df["trade_date"].to_list() == ["20260331", "20260630"]


def test_universal_audit_engine_single_day() -> None:
    mock_catalog = MagicMock()
    mock_catalog.data_source = "tushare"
    mock_catalog.load_dataset.side_effect = lambda name, **kw: (
        pl.DataFrame({"symbol": ["000001.SZ", "600000.SH"], "list_date": ["19910403", "19991110"]})
        if name == "stock_basic"
        else (
            pl.DataFrame({"symbol": ["600000.SH"], "trade_date": [date(2026, 8, 14)]})
            if name == "suspend_d"
            else pl.DataFrame(
                {"symbol": ["000001.SZ"], "trade_date": [date(2026, 8, 14)], "close": [10.5]}
            )
        )
    )

    with patch(
        "stock_data.governance.audit.benchmarks.equity.get_trading_calendar",
        return_value=[date(2026, 8, 14)],
    ):
        engine = UniversalAuditEngine(catalog=mock_catalog)
        report = engine.audit_single_day(
            "stock_daily_bar", date(2026, 8, 14), data_source="tushare"
        )

        assert report.dataset == "stock_daily_bar"
        assert report.expected_count == 2
        assert report.actual_count == 1
        assert report.suspended_count == 1
        assert report.missing_count == 0
        assert report.integrity_rate == 100.0
        assert report.status == "PASSED"

        # 测试报告打印函数
        print_audit_summary_report([report])


def test_extract_identity_keys_empty() -> None:
    df_empty = pl.DataFrame()
    res = extract_identity_keys(df_empty)
    assert res.is_empty()


def test_resolve_benchmark_provider_routing() -> None:
    spec_eq = DatasetAuditSpec(
        dataset="test_eq",
        data_source="tushare",
        domain=AuditDomain.EQUITY,
        frequency=AuditFrequency.DAILY,
    )
    assert isinstance(resolve_benchmark_provider(spec_eq), EquityDailyBenchmarkProvider)

    spec_ind = DatasetAuditSpec(
        dataset="test_ind",
        data_source="tushare",
        domain=AuditDomain.INDUSTRY,
        frequency=AuditFrequency.DAILY,
    )
    ind_provider = resolve_benchmark_provider(spec_ind)
    assert isinstance(ind_provider, IndustryDailyBenchmarkProvider)
    assert ind_provider.data_source == "tushare"

    spec_ind_lx = DatasetAuditSpec(
        dataset="sw_2021_fundamental",
        data_source="lixinger",
        domain=AuditDomain.INDUSTRY,
        frequency=AuditFrequency.DAILY,
    )
    lx_ind_provider = resolve_benchmark_provider(spec_ind_lx)
    assert isinstance(lx_ind_provider, IndustryDailyBenchmarkProvider)
    assert lx_ind_provider.data_source == "lixinger"

    spec_idx = DatasetAuditSpec(
        dataset="test_idx",
        data_source="tushare",
        domain=AuditDomain.INDEX,
        frequency=AuditFrequency.DAILY,
    )
    assert isinstance(resolve_benchmark_provider(spec_idx), IndexDailyBenchmarkProvider)


def test_lixinger_industry_audit_levels_match_expected_code_sets() -> None:
    l1 = get_audit_spec("sw_2021_fundamental", data_source="lixinger")
    l2 = get_audit_spec("sw_2021_l2_fundamental", data_source="lixinger")

    assert l1.industry_level == "L1"
    assert l2.industry_level == "L2"

    mock_catalog = MagicMock()
    mock_catalog.data_source = "lixinger"
    mock_catalog.load_dataset.return_value = pl.DataFrame(
        {"symbol": ["110000", "110100"], "industryCode": ["110000", "110100"]}
    )
    l1_provider = IndustryDailyBenchmarkProvider(
        catalog=mock_catalog, data_source="lixinger", level=l1.industry_level
    )
    l2_provider = IndustryDailyBenchmarkProvider(
        catalog=mock_catalog, data_source="lixinger", level=l2.industry_level
    )
    assert l1_provider._get_industry_codes() == ["110000"]
    assert l2_provider._get_industry_codes() == ["110100"]
