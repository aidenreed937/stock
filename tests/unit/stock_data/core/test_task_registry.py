"""TaskRegistry 与 is_task_partitioned 单元测试。"""

import pytest

from stock_data.core.task_registry import (
    expand_task_targets,
    is_per_symbol_task,
    is_task_partitioned,
    list_available_bundles,
    list_available_tasks,
    resolve_bundle,
    resolve_task,
)


def test_is_task_partitioned_rules() -> None:
    # 1. 验证 fred / lixinger 免分区
    assert not is_task_partitioned("fred", "CPIAUCSL")
    assert not is_task_partitioned("fred", "macro_indicators")
    assert not is_task_partitioned("lixinger", "sw_2021_fundamental")

    # 2. 验证 tushare 静态基本面与宏观单表免分区
    assert not is_task_partitioned("tushare", "stock_basic")
    assert not is_task_partitioned("tushare", "index_basic")
    assert not is_task_partitioned("tushare", "cn_cpi")
    assert not is_task_partitioned("tushare", "shibor_lpr")

    # 3. 验证 tushare 高频日行情 / 估值 / 资金流必须分区
    assert is_task_partitioned("tushare", "stock_daily_bar")
    assert is_task_partitioned("tushare", "daily_basic")
    assert is_task_partitioned("tushare", "moneyflow")
    assert is_task_partitioned("tushare", "adj_factor")
    assert is_task_partitioned("tushare", "stk_limit")
    assert is_task_partitioned("tushare", "limit_list_d")
    for statement in ("income", "fina_indicator", "balancesheet", "cashflow"):
        assert is_task_partitioned("tushare", statement)


def test_is_per_symbol_task_rules() -> None:
    # 1. 验证按标的拉取模式 (指数、两融明细等)
    assert is_per_symbol_task("tushare", "index_daily")
    assert not is_per_symbol_task("tushare", "margin_detail")
    assert is_per_symbol_task("fred", "CPIAUCSL")
    assert is_per_symbol_task("yfinance", "stock_daily_bar")

    # 2. 验证按日全市场拉取模式 (股票行情、每日估值、资金流等)
    assert not is_per_symbol_task("tushare", "stock_daily_bar")
    assert not is_per_symbol_task("tushare", "daily_basic")
    assert not is_per_symbol_task("tushare", "moneyflow")
    assert not is_per_symbol_task("tushare", "adj_factor")
    assert not is_per_symbol_task("tushare", "stk_limit")
    assert not is_per_symbol_task("tushare", "limit_list_d")
    assert not is_per_symbol_task("tushare", "hk_hold")

    for endpoint in (
        "stk_holdernumber",
        "top10_floatholders",
        "dividend",
        "cyq_perf",
        "cyq_chips",
        "stk_managers",
        "stk_surv",
        "dc_concept_cons",
    ):
        assert is_per_symbol_task("tushare", endpoint)


def test_tushare_financial_statements_use_vip_period_routes() -> None:
    for statement in ("income", "fina_indicator", "balancesheet", "cashflow"):
        task = resolve_task("tushare", statement)
        assert task.api_name == f"{statement}_vip"
        assert task.fetch_mode == "per_period"
        assert task.required_pool is None
        assert task.query_mode == "period"


def test_list_available_tasks() -> None:
    tushare_tasks = list_available_tasks("tushare")
    assert "stock_daily_bar" in tushare_tasks
    assert "daily_basic" in tushare_tasks
    assert "adj_factor" in tushare_tasks
    assert "stk_limit" in tushare_tasks
    assert "limit_list_d" in tushare_tasks
    assert "limit_list" not in tushare_tasks
    assert "income" in tushare_tasks
    assert "income_vip" not in tushare_tasks
    assert "bak_daily" not in tushare_tasks
    assert "pledge_detail" not in tushare_tasks
    for endpoint in (
        "stk_holdernumber",
        "top10_floatholders",
        "dividend",
        "cyq_perf",
        "cyq_chips",
        "top_list",
        "top_inst",
        "dc_concept",
        "dc_concept_cons",
        "stk_managers",
        "stk_surv",
    ):
        assert endpoint not in tushare_tasks
    assert "pledge_stat" not in tushare_tasks

    lixinger_tasks = list_available_tasks("lixinger")
    assert "sw_2021_fundamental" in lixinger_tasks
    assert "pledge_info" in lixinger_tasks
    assert "regulatory_measures" not in lixinger_tasks
    assert "exchange_inquiry" not in lixinger_tasks
    assert "unlock_summary" not in lixinger_tasks

    regulatory = resolve_task("lixinger", "regulatory_measures")
    assert regulatory.fetch_mode == "per_symbol"
    assert regulatory.required_pool is None
    assert regulatory.frequency == "event"
    assert regulatory.primary_keys == ("stockCode", "date", "type", "linkUrl")

    unlock = resolve_task("lixinger", "unlock_summary")
    assert unlock.fetch_mode == "per_symbol"
    assert unlock.frequency == "static"
    assert unlock.primary_keys == ("stockCode",)


def test_task_spec_properties() -> None:
    task = resolve_task("tushare", "stock_daily_bar")
    assert task.dataset == "stock_daily_bar"
    assert task.quality_profile == "bar"
    assert task.partitioned is True
    assert task.fetch_mode == "per_day"

    stk_limit = resolve_task("tushare", "stk_limit")
    assert stk_limit.api_name == "stk_limit"
    assert stk_limit.dataset == "stk_limit"
    assert stk_limit.quality_profile == "market_indicator"
    assert not stk_limit.is_single_sync

    limit_list = resolve_task("tushare", "limit_list_d")
    assert limit_list.api_name == "limit_list_d"
    assert limit_list.dataset == "limit_list_d"
    assert limit_list.quality_profile == "event"
    assert not limit_list.is_single_sync

    dividend = resolve_task("tushare", "dividend")
    assert dividend.fetch_mode == "per_symbol"
    assert dividend.frequency == "event"
    assert dividend.partitioned is True
    assert dividend.is_single_sync is False
    assert dividend.query_mode == "symbol"

    top_list = resolve_task("tushare", "top_list")
    assert top_list.fetch_mode == "per_day"
    assert top_list.frequency == "daily"
    assert top_list.request_window_days == 1

    theme_cons = resolve_task("tushare", "dc_concept_cons")
    assert theme_cons.fetch_mode == "per_symbol"
    assert theme_cons.partitioned is True
    assert theme_cons.request_window_days == 1


def test_tushare_research_tasks_are_available_with_source_dates() -> None:
    from stock_data.core.constants import ENDPOINT_START_DATE_OVERRIDES

    assert ENDPOINT_START_DATE_OVERRIDES["cyq_perf"] == "2018-01-01"
    assert ENDPOINT_START_DATE_OVERRIDES["cyq_chips"] == "2018-01-01"
    assert ENDPOINT_START_DATE_OVERRIDES["dc_concept"] == "2026-02-03"


def test_yfinance_macro_task_uses_macro_quality_profile() -> None:
    task = resolve_task("yfinance", "macro_indicators")

    assert task.quality_profile == "macro"


def test_alphavantage_fx_task_uses_registered_route_and_global_market() -> None:
    task = resolve_task("alphavantage", "fx_daily")

    assert task.api_name == "FX_DAILY"
    assert task.dataset == "macro_indicators"
    assert task.fetch_mode == "per_symbol"
    assert task.is_single_sync is True
    assert task.partitioned is False
    assert "FX_DAILY" not in list_available_tasks("alphavantage")

    from stock_data.core.task_registry import get_endpoint_market

    assert get_endpoint_market("alphavantage", "fx_daily") == "GLOBAL"


def test_lixinger_l2_task_uses_the_documented_shared_api_route() -> None:
    task = resolve_task("lixinger", "sw_2021_l2_fundamental")

    assert task.api_name == "cn/industry/fundamental/sw_2021"


def test_lixinger_task_bundles() -> None:
    assert list_available_bundles("lixinger") == [
        "market_bundle",
        "industry_bundle",
        "company_bundle",
        "company_risk_event_bundle",
        "macro_daily_bundle",
        "macro_monthly_bundle",
    ]
    industry = resolve_bundle("lixinger", "industry_bundle")
    assert industry.provider == "lixinger"
    assert industry.tasks == (
        "sw_2021_constituents",
        "sw_2021_fundamental",
        "sw_2021_l2_fundamental",
        "sw_2021_fs_non_financial",
        "sw_2021_fs_bank",
        "sw_2021_fs_security",
        "sw_2021_fs_insurance",
    )
    assert "industry_bundle" not in list_available_tasks("lixinger")
    assert "index_fundamental" not in {
        task
        for bundle_name in list_available_bundles("lixinger")
        for task in resolve_bundle("lixinger", bundle_name).tasks
    }

    assert expand_task_targets("lixinger", ["macro_monthly_bundle"]) == [
        "investor_accounts",
        "cn_m",
        "sf_month",
    ]
    assert resolve_bundle("lixinger", "company_risk_event_bundle").tasks == (
        "regulatory_measures",
        "exchange_inquiry",
    )


def test_tushare_task_bundles() -> None:
    assert list_available_bundles("tushare") == [
        "daily_market_bundle",
        "fund_daily_bundle",
        "hsgt_flow_bundle",
        "financial_statement_bundle",
        "pit_bundle",
        "macro_daily_bundle",
        "macro_monthly_bundle",
        "metadata_bundle",
        "corporate_action_bundle",
        "shareholder_event_bundle",
        "research_daily_bundle",
        "market_behavior_bundle",
        "pledge_bundle",
    ]

    market = resolve_bundle("tushare", "daily_market_bundle")
    assert market.tasks == (
        "daily_basic",
        "adj_factor",
        "limit_list_d",
        "sw_daily",
        "moneyflow",
    )
    assert resolve_bundle("tushare", "fund_daily_bundle").tasks == (
        "fund_daily",
        "fund_adj",
        "etf_share_size",
    )
    assert resolve_bundle("tushare", "hsgt_flow_bundle").tasks == (
        "moneyflow_hsgt",
        "hsgt_top10",
    )
    assert resolve_bundle("tushare", "financial_statement_bundle").tasks == (
        "income",
        "fina_indicator",
        "balancesheet",
        "cashflow",
    )
    assert resolve_bundle("tushare", "corporate_action_bundle").tasks == (
        "stk_holdertrade",
        "repurchase",
        "block_trade",
        "share_float",
    )
    assert resolve_bundle("tushare", "shareholder_event_bundle").tasks == (
        "stk_holdernumber",
        "top10_floatholders",
        "dividend",
        "stk_managers",
        "stk_surv",
    )
    assert resolve_bundle("tushare", "research_daily_bundle").tasks == (
        "cyq_perf",
        "cyq_chips",
    )
    assert resolve_bundle("tushare", "market_behavior_bundle").tasks == (
        "top_list",
        "top_inst",
        "dc_concept",
    )

    monthly = resolve_bundle("tushare", "macro_monthly_bundle")
    assert monthly.tasks == (
        "cn_cpi",
        "cn_ppi",
        "cn_pmi",
        "cn_m",
        "sf_month",
        "shibor_lpr",
        "cn_schedule",
    )
    pit = resolve_bundle("tushare", "pit_bundle")
    assert pit.tasks == ("forecast", "express")
    assert [resolve_task("tushare", task).frequency for task in pit.tasks] == [
        "quarterly",
        "quarterly",
    ]

    for bundle_name in list_available_bundles("tushare"):
        bundle = resolve_bundle("tushare", bundle_name)
        assert bundle_name not in list_available_tasks("tushare")
        for task_name in bundle.tasks:
            task = resolve_task("tushare", task_name)
            assert task.task_name == task_name
            assert task.provider == "tushare"


def test_expand_tushare_task_bundles_keeps_order_and_deduplicates() -> None:
    assert expand_task_targets(
        "tushare",
        [
            "daily_market_bundle",
            "fund_daily_bundle",
            "hsgt_flow_bundle",
            "daily_market_bundle",
        ],
    ) == [
        "daily_basic",
        "adj_factor",
        "limit_list_d",
        "sw_daily",
        "moneyflow",
        "fund_daily",
        "fund_adj",
        "etf_share_size",
        "moneyflow_hsgt",
        "hsgt_top10",
    ]


def test_expand_task_targets_keeps_atomic_tasks_and_deduplicates() -> None:
    assert expand_task_targets("lixinger", ["industry_bundle", "sw_2021_fundamental"]) == [
        "sw_2021_constituents",
        "sw_2021_fundamental",
        "sw_2021_l2_fundamental",
        "sw_2021_fs_non_financial",
        "sw_2021_fs_bank",
        "sw_2021_fs_security",
        "sw_2021_fs_insurance",
    ]

    assert expand_task_targets("tushare", ["convertible_bond_bundle"]) == [
        "cb_basic",
        "cb_daily",
    ]


def test_yfinance_task_bundles_follow_endpoint_families() -> None:
    assert list_available_bundles("yfinance") == [
        "fundamental_bundle",
        "corporate_action_bundle",
        "research_daily_bundle",
        "research_event_bundle",
    ]
    assert resolve_bundle("yfinance", "fundamental_bundle").tasks == (
        "financials",
        "balance_sheet",
    )
    assert expand_task_targets("yfinance", ["corporate_action_bundle"]) == [
        "dividends",
        "splits",
    ]


def test_fred_task_bundles_do_not_duplicate_aggregate_task() -> None:
    assert list_available_bundles("fred") == ["macro_monthly_bundle"]
    assert resolve_bundle("fred", "macro_monthly_bundle").tasks == (
        "FEDFUNDS",
        "CPIAUCSL",
        "UNRATE",
        "PAYEMS",
    )
    assert "macro_indicators" not in expand_task_targets(
        "fred", ["macro_monthly_bundle", "macro_daily_bundle"]
    )
    assert "macro_indicators" not in list_available_tasks("fred")
    assert resolve_task("fred", "macro_indicators").dataset == "macro_indicators"


def test_fred_series_tasks_share_the_aggregate_curated_dataset() -> None:
    for series_id in ("FEDFUNDS", "CPIAUCSL", "UNRATE", "PAYEMS", "GDP", "T10Y2Y", "WALCL"):
        task = resolve_task("fred", series_id)
        assert task.dataset == "macro_indicators"


def test_task_bundles_cover_registered_tasks_except_explicit_aggregate_routes() -> None:
    expected_unbundled = {
        "tushare": {
            "stock_daily_bar",
            "report_rc",
            "index_daily_bar",
            "index_dailybasic",
            "stk_limit",
            "suspend_d",
            "index_weight",
            "fund_basic",
            "fund_share",
            "fut_index_daily",
            "opt_basic",
            "opt_daily",
            "trade_cal",
            "hk_hold",
            "margin",
            "margin_detail",
            "cn_gdp",
            "cb_basic",
            "cb_daily",
        },
        "lixinger": {"index_fundamental"},
        "yfinance": {
            "macro_indicators",
            "index_valuation",
            "stock_daily_bar",
            "index_daily_bar",
            "cashflow",
            "institutional_holders",
        },
        "fred": {"GDP", "T10Y2Y", "WALCL"},
    }
    for provider, unbundled in expected_unbundled.items():
        bundled = {
            task
            for bundle_name in list_available_bundles(provider)
            for task in resolve_bundle(provider, bundle_name).tasks
        }
        assert set(list_available_tasks(provider)) - bundled == unbundled


def test_task_bundle_members_share_scheduling_contract() -> None:
    from stock_data.pipeline.scheduler import DataUpdateScheduler

    for (provider, _), bundle in {
        (provider_name, name): resolve_bundle(provider_name, name)
        for provider_name in ("tushare", "lixinger", "yfinance", "fred")
        for name in list_available_bundles(provider_name)
    }.items():
        signatures = set()
        for task_name in bundle.tasks:
            task = resolve_task(provider, task_name)
            meta = DataUpdateScheduler.get_endpoint_update_meta(provider, task_name)
            signatures.add(
                (
                    task.frequency,
                    task.fetch_mode,
                    task.partitioned,
                    task.is_single_sync,
                    task.required_pool,
                    meta.update_time,
                    meta.update_delay_days,
                    meta.delay_in_trading_days,
                )
            )
        assert len(signatures) == 1, f"{provider}/{bundle.bundle_name}: {signatures}"


def test_tushare_index_daily_alias_is_not_a_second_public_task() -> None:
    assert "index_daily" not in list_available_tasks("tushare")
    assert resolve_task("tushare", "index_daily").task_name == "index_daily_bar"
    assert expand_task_targets("tushare", ["index_daily", "index_daily_bar"]) == ["index_daily_bar"]


def test_removed_lixinger_bundle_names_are_rejected() -> None:
    assert expand_task_targets("tushare", ["index_bundle"]) == [
        "index_daily_bar",
        "index_dailybasic",
    ]
    for bundle_name in ("macro_bundle", "index_bundle"):
        with pytest.raises(ValueError, match="未知任务包"):
            resolve_bundle("lixinger", bundle_name)


def test_resolve_task_rejects_bundle_name() -> None:
    with pytest.raises(ValueError, match="任务包"):
        resolve_task("lixinger", "industry_bundle")


def test_registered_new_data_source_tasks_have_explicit_routes() -> None:
    opt_daily = resolve_task("tushare", "opt_daily")
    assert opt_daily.api_name == "opt_daily"
    assert opt_daily.quality_profile == "options_daily"
    assert opt_daily.partitioned is True

    investor_accounts = resolve_task("lixinger", "investor_accounts")
    assert investor_accounts.api_name == "macro/investor"
    assert investor_accounts.frequency == "monthly"
    assert investor_accounts.partitioned is False
    assert investor_accounts.is_single_sync is True

    money = resolve_task("lixinger", "cn_m")
    assert money.api_name == "macro/money-supply"
    assert money.dataset == "cn_m"
    assert money.frequency == "monthly"
    assert not money.partitioned

    social_financing = resolve_task("lixinger", "sf_month")
    assert social_financing.api_name == "macro/social-financing"
    assert social_financing.dataset == "sf_month"
    assert social_financing.frequency == "monthly"
    assert not social_financing.partitioned

    with pytest.raises(ValueError, match="已停用"):
        resolve_task("tushare", "stk_account")
