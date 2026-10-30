"""任务解析、任务包与分区规则单元测试。"""

import pytest

from stock_data.core.public_tasks import expand_public_task_targets, resolve_public_task
from stock_data.core.task_bundles import list_available_bundles, resolve_bundle
from stock_data.core.task_resolution import (
    expand_task_targets,
    get_endpoint_market,
    is_per_symbol_task,
    is_task_partitioned,
    list_available_tasks,
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
    for statement in ("income", "fina_indicator", "fina_mainbz", "balancesheet", "cashflow"):
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
    assert not is_per_symbol_task("tushare", "limit_list_d")
    assert not is_per_symbol_task("tushare", "hk_hold")
    assert not is_per_symbol_task("tushare", "top10_floatholders")
    assert not is_per_symbol_task("tushare", "stk_holdernumber")
    assert not is_per_symbol_task("tushare", "cyq_perf")

    for endpoint in (
        "dividend",
        "cyq_chips",
        "stk_managers",
        "stk_surv",
        "dc_concept_cons",
    ):
        assert is_per_symbol_task("tushare", endpoint)


def test_tushare_financial_statements_use_vip_period_routes() -> None:
    for statement in ("income", "fina_indicator", "fina_mainbz", "balancesheet", "cashflow"):
        task = resolve_task("tushare", statement)
        assert task.api_name == f"{statement}_vip"
        assert task.fetch_mode == "per_period"
    assert task.required_pool is None
    assert task.query_mode == "period"

    mainbz = resolve_task("tushare", "fina_mainbz")
    assert mainbz.primary_keys == ("ts_code", "end_date", "bz_code", "bz_item")
    assert mainbz.units["bz_sales"] == "CNY"

    top10_task = resolve_task("tushare", "top10_floatholders")
    assert top10_task.api_name == "top10_floatholders"
    assert top10_task.fetch_mode == "per_period"
    assert top10_task.query_mode == "period"

    holder_num_task = resolve_task("tushare", "stk_holdernumber")
    assert holder_num_task.api_name == "stk_holdernumber"
    assert holder_num_task.fetch_mode == "per_period"
    assert holder_num_task.query_mode == "period"

    cyq_perf_task = resolve_task("tushare", "cyq_perf")
    assert cyq_perf_task.api_name == "cyq_perf"
    assert cyq_perf_task.fetch_mode == "per_day"
    assert cyq_perf_task.query_mode == "trade_date"


def test_industry_semi_equipment_uses_curated_watermark_cache() -> None:
    task = resolve_task("industry", "semiconductor_equipment_semi")
    assert task.fetch_mode == "per_period"
    assert task.frequency == "quarterly"
    assert task.refresh_current_period is False


def test_industry_automotive_task_declares_period_collection_contract() -> None:
    task = resolve_task("industry", "nev_monthly_sales")
    assert task.fetch_mode == "per_period"
    assert task.partitioned is False
    assert task.is_single_sync is True
    assert task.frequency == "monthly"
    assert task.query_mode == "period"
    assert task.primary_keys == ("report_month",)
    assert task.units["battery_installation_gwh"] == "gwh"


def test_industry_new_semiconductor_tasks_use_explicit_routes() -> None:
    channel = resolve_task("industry", "semiconductor_channel_inventory")
    assert channel.fetch_mode == "per_period"
    assert channel.frequency == "quarterly"
    assert channel.primary_keys == ("report_quarter", "symbol")
    assert "channel_doi_days" in channel.required_columns
    assert channel.update_delay_days == 45

    memory = resolve_task("industry", "semiconductor_memory_price")
    assert memory.fetch_mode == "per_period"
    assert memory.frequency == "daily"
    assert memory.primary_keys == (
        "trade_date",
        "product_family",
        "price_scope",
        "table_index",
        "item",
    )
    assert "item" in memory.required_columns
    assert memory.update_delay_days == 0

    benchmark = resolve_task("industry", "semiconductor_memory_benchmark")
    taiwan = resolve_task("industry", "semiconductor_memory_taiwan_lead")
    assert benchmark.units["price_usd"] == "USD/unit"
    assert taiwan.units["revenue_ntd_million"] == "million_NTD"


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
    assert "fina_mainbz" not in tushare_tasks
    assert "fina_mainbz_vip" not in tushare_tasks
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

    industry_tasks = list_available_tasks("industry")
    assert "solar_cell_nbs" in industry_tasks
    assert "solar_cell_production" not in industry_tasks
    assert "futures_inventory" not in industry_tasks
    assert "futures_daily" not in industry_tasks
    assert "customs_trade_gacc" not in industry_tasks
    assert expand_public_task_targets("industry") == industry_tasks
    assert all(resolve_task("industry", task).task_name == task for task in industry_tasks)
    assert resolve_public_task("industry", "solar_cell_production").task_name == "solar_cell_nbs"

    lixinger_tasks = list_available_tasks("lixinger")
    assert "sw_2021_fundamental" in lixinger_tasks
    assert "pledge_info" in lixinger_tasks
    assert "gold_price" in lixinger_tasks
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

    assert resolve_task("tushare", "stk_holdertrade").sync_lookback_days == 31
    assert resolve_task("tushare", "repurchase").sync_lookback_days == 31
    assert resolve_task("tushare", "block_trade").sync_lookback_days == 5
    assert resolve_task("tushare", "share_float").sync_lookback_days == 31


def test_tushare_research_tasks_are_available_with_source_dates() -> None:
    from stock_data.core.constants import ENDPOINT_START_DATE_OVERRIDES

    assert ENDPOINT_START_DATE_OVERRIDES["cyq_perf"] == "2018-01-01"
    assert ENDPOINT_START_DATE_OVERRIDES["cyq_chips"] == "2018-01-01"
    assert ENDPOINT_START_DATE_OVERRIDES["dc_concept"] == "2026-02-03"


def test_yfinance_macro_task_uses_macro_quality_profile() -> None:
    task = resolve_task("yfinance", "macro_indicators")

    assert task.quality_profile == "macro"


def test_yfinance_financial_tasks_use_report_period_query_mode() -> None:
    for endpoint in ("financials", "balance_sheet", "cashflow"):
        task = resolve_task("yfinance", endpoint)
        assert task.frequency == "quarterly"
        assert task.query_mode == "period"
        assert task.fetch_mode == "per_symbol"
        assert task.partitioned is False
        assert task.is_single_sync is True


def test_fred_series_tasks_use_provider_metadata_contract() -> None:
    task = resolve_task("fred", "CPIAUCSL")

    assert task.api_name == "CPIAUCSL"
    assert task.dataset == "macro_indicators"
    assert task.fetch_mode == "per_symbol"
    assert task.partitioned is False
    assert task.is_single_sync is True
    assert task.query_mode == "trade_date"

    macro = resolve_task("fred", "macro_indicators")
    assert macro.dataset == "macro_indicators"
    assert macro.quality_profile == "macro"
    assert macro.partitioned is False
    assert macro.is_single_sync is True


def test_alphavantage_fx_task_uses_registered_route_and_global_market() -> None:
    task = resolve_task("alphavantage", "fx_daily")

    assert task.api_name == "FX_DAILY"
    assert task.dataset == "macro_indicators"
    assert task.fetch_mode == "per_symbol"
    assert task.is_single_sync is True
    assert task.partitioned is False
    assert "FX_DAILY" not in list_available_tasks("alphavantage")

    assert get_endpoint_market("alphavantage", "fx_daily") == "GLOBAL"


def test_alphavantage_stock_task_uses_daily_route_and_us_market() -> None:
    task = resolve_task("alphavantage", "stock_daily_bar")

    assert task.api_name == "TIME_SERIES_DAILY"
    assert task.dataset == "stock_daily_bar"
    assert task.quality_profile == "bar"
    assert task.fetch_mode == "per_symbol"
    assert task.max_increment_days == 90
    assert get_endpoint_market("alphavantage", "stock_daily_bar") == "US"


def test_endpoint_market_uses_provider_registry_and_fallbacks() -> None:
    assert get_endpoint_market("tushare", "stock_daily_bar") == "CN"
    assert get_endpoint_market("yfinance", "macro_indicators") == "GLOBAL"
    assert get_endpoint_market("lixinger", "hk/company/fundamental") == "HK"
    assert get_endpoint_market("unknown_provider", "any_endpoint") == "MULTI"


def test_lixinger_gold_price_task_uses_documented_macro_route() -> None:
    task = resolve_task("lixinger", "gold_price")

    assert task.api_name == "macro/gold-price"
    assert task.dataset == "gold_price"
    assert task.frequency == "daily"
    assert task.fetch_mode == "per_symbol"
    assert task.is_single_sync is True
    assert task.partitioned is False
    assert task.primary_keys == ("date",)
    assert task.date_columns == ("date",)
    assert task.required_columns == ("date",)


def test_lixinger_industry_tasks_use_the_documented_shared_api_route() -> None:
    task = resolve_task("lixinger", "sw_2021_l2_fundamental")
    assert task.api_name == "cn/industry/fundamental/sw_2021"

    for sec in ("non_financial", "bank", "security", "insurance"):
        task_fs = resolve_task("lixinger", f"sw_2021_fs_{sec}")
        assert task_fs.api_name == f"cn/industry/fs/sw_2021/{sec}"
        assert task_fs.fetch_mode == "per_period"
        assert task_fs.frequency == "quarterly"
        assert task_fs.query_mode == "period"
        assert task_fs.is_single_sync is True
        assert task_fs.partitioned is False
        assert task_fs.max_codes_per_request == 100

        task_l2_fs = resolve_task("lixinger", f"sw_2021_l2_fs_{sec}")
        assert task_l2_fs.api_name == f"cn/industry/fs/sw_2021/{sec}"
        assert task_l2_fs.fetch_mode == "per_period"
        assert task_l2_fs.frequency == "quarterly"
        assert task_l2_fs.query_mode == "period"
        assert task_l2_fs.is_single_sync is True
        assert task_l2_fs.max_codes_per_request == 100

        task_l3_fs = resolve_task("lixinger", f"sw_2021_l3_fs_{sec}")
        assert task_l3_fs.api_name == f"cn/industry/fs/sw_2021/{sec}"
        assert task_l3_fs.fetch_mode == "per_period"
        assert task_l3_fs.frequency == "quarterly"
        assert task_l3_fs.query_mode == "period"
        assert task_l3_fs.is_single_sync is True
        assert task_l3_fs.max_codes_per_request == 100


def test_lixinger_task_bundles() -> None:
    assert list_available_bundles("lixinger") == [
        "market_bundle",
        "industry_bundle",
        "industry_financial_bundle",
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
    )
    financial = resolve_bundle("lixinger", "industry_financial_bundle")
    assert financial.provider == "lixinger"
    assert financial.tasks == (
        "sw_2021_fs_non_financial",
        "sw_2021_fs_bank",
        "sw_2021_fs_security",
        "sw_2021_fs_insurance",
        "sw_2021_l2_fs_non_financial",
        "sw_2021_l2_fs_bank",
        "sw_2021_l2_fs_security",
        "sw_2021_l2_fs_insurance",
        "sw_2021_l3_fs_non_financial",
        "sw_2021_l3_fs_bank",
        "sw_2021_l3_fs_security",
        "sw_2021_l3_fs_insurance",
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
        "energy",
        "price_index",
    ]
    assert expand_task_targets("lixinger", ["macro_daily_bundle"]) == [
        "national_debt",
        "interest_rates",
        "non_ferrous_metals",
        "crude_oil",
        "gold_price",
    ]
    assert resolve_bundle("lixinger", "company_risk_event_bundle").tasks == (
        "regulatory_measures",
        "exchange_inquiry",
    )


def test_tushare_task_bundles() -> None:
    assert list_available_bundles("tushare") == [
        "daily_market_bundle",
        "fund_daily_bundle",
        "fund_portfolio_bundle",
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
        "us_market_bundle",
    ]

    market = resolve_bundle("tushare", "daily_market_bundle")
    assert market.tasks == (
        "stock_daily_bar",
        "index_daily_bar",
        "daily_basic",
        "adj_factor",
        "stk_limit",
        "limit_list_d",
        "suspend_d",
        "sw_daily",
        "moneyflow",
    )
    assert resolve_bundle("tushare", "fund_daily_bundle").tasks == (
        "fund_daily",
        "fund_adj",
        "etf_share_size",
    )
    assert resolve_bundle("tushare", "fund_portfolio_bundle").tasks == ("fund_portfolio",)
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
        "dividend",
        "stk_managers",
        "stk_surv",
    )
    assert resolve_bundle("tushare", "research_daily_bundle").tasks == ("cyq_perf",)
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
        "stock_daily_bar",
        "index_daily_bar",
        "daily_basic",
        "adj_factor",
        "stk_limit",
        "limit_list_d",
        "suspend_d",
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
    ]
    assert expand_task_targets("lixinger", ["industry_financial_bundle"]) == [
        "sw_2021_fs_non_financial",
        "sw_2021_fs_bank",
        "sw_2021_fs_security",
        "sw_2021_fs_insurance",
        "sw_2021_l2_fs_non_financial",
        "sw_2021_l2_fs_bank",
        "sw_2021_l2_fs_security",
        "sw_2021_l2_fs_insurance",
        "sw_2021_l3_fs_non_financial",
        "sw_2021_l3_fs_bank",
        "sw_2021_l3_fs_security",
        "sw_2021_l3_fs_insurance",
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
    assert list_available_bundles("fred") == [
        "global_macro_daily_bundle",
        "macro_monthly_bundle",
    ]
    assert resolve_bundle("fred", "global_macro_daily_bundle").tasks == (
        "DFF",
        "DGS10",
        "DGS3MO",
        "T10Y2Y",
        "VIXCLS",
        "DCOILWTICO",
        "DTWEXBGS",
        "PCOPPUSDM",
    )
    assert resolve_bundle("fred", "macro_monthly_bundle").tasks == (
        "FEDFUNDS",
        "CPIAUCSL",
        "UNRATE",
        "PAYEMS",
        "MANEMP",
        "OECDLOLITOAASTSAM",
        "USALOLITOAASTSAM",
        "CHNLOLITOAASTSAM",
        "DGORDER",
        "AMTMVS",
    )
    assert expand_task_targets("fred", ["global_macro_daily_bundle"]) == [
        "DFF",
        "DGS10",
        "DGS3MO",
        "T10Y2Y",
        "VIXCLS",
        "DCOILWTICO",
        "DTWEXBGS",
        "PCOPPUSDM",
    ]
    assert "macro_indicators" not in expand_task_targets(
        "fred", ["macro_monthly_bundle", "macro_daily_bundle"]
    )
    assert "macro_indicators" not in list_available_tasks("fred")
    assert resolve_task("fred", "macro_indicators").dataset == "macro_indicators"


def test_fred_series_tasks_share_the_aggregate_curated_dataset() -> None:
    for series_id in (
        "FEDFUNDS",
        "CPIAUCSL",
        "UNRATE",
        "PAYEMS",
        "GDP",
        "T10Y2Y",
        "WALCL",
        "MANEMP",
        "OECDLOLITOAASTSAM",
        "USALOLITOAASTSAM",
        "CHNLOLITOAASTSAM",
        "DGORDER",
        "AMTMVS",
    ):
        task = resolve_task("fred", series_id)
        assert task.dataset == "macro_indicators"


def test_task_bundles_cover_registered_tasks_except_explicit_aggregate_routes() -> None:
    expected_unbundled = {
        "tushare": {
            "report_rc",
            "index_dailybasic",
            "index_weight",
            "fund_share",
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
        "lixinger": {"index_fundamental", "fund_holder_structure"},
        "yfinance": {
            "index_valuation",
            "stock_daily_bar",
            "index_daily_bar",
            "cashflow",
            "institutional_holders",
        },
        "fred": {
            "GDP",
            "WALCL",
            "DEXTAUS",
            "DEXCHUS",
            "DEXJPUS",
            "DEXUSEU",
            "DEXKOUS",
        },
    }
    for provider, unbundled in expected_unbundled.items():
        bundled = {
            task
            for bundle_name in list_available_bundles(provider)
            for task in resolve_bundle(provider, bundle_name).tasks
        }
        assert set(list_available_tasks(provider)) - bundled == unbundled


def test_task_bundle_members_have_scheduling_metadata() -> None:
    from stock_data.pipeline.scheduler import DataUpdateScheduler

    for (provider, _), bundle in {
        (provider_name, name): resolve_bundle(provider_name, name)
        for provider_name in ("tushare", "lixinger", "yfinance", "fred")
        for name in list_available_bundles(provider_name)
    }.items():
        for task_name in bundle.tasks:
            task = resolve_task(provider, task_name)
            meta = DataUpdateScheduler.get_endpoint_update_meta(provider, task_name)
            assert meta.task_name == task.task_name
            assert meta.api_name == task.api_name
            assert meta.frequency == task.frequency


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

    fund_portfolio = resolve_task("tushare", "fund_portfolio")
    assert fund_portfolio.api_name == "fund_portfolio"
    # 上游无 period 参数（传入被静默忽略 → 退化为前 8000 行切片），只能按基金代码逐只采集
    assert fund_portfolio.fetch_mode == "per_symbol"
    assert fund_portfolio.frequency == "quarterly"
    assert fund_portfolio.partitioned is True
    assert fund_portfolio.required_pool == "fund_basic"

    fund_holder_structure = resolve_task("lixinger", "fund_holder_structure")
    assert fund_holder_structure.api_name == "cn/fund/shareholders-structure"
    assert fund_holder_structure.dataset == "fund_holder_structure"
    assert fund_holder_structure.fetch_mode == "per_symbol"
    assert not fund_holder_structure.partitioned
    assert fund_holder_structure.is_single_sync is True

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
