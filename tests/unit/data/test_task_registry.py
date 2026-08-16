"""TaskRegistry 与 is_task_partitioned 单元测试。"""

import pytest

from stock.data.task_registry import (
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


def test_is_per_symbol_task_rules() -> None:
    # 1. 验证按标的拉取模式 (指数、财报、两融明细等)
    assert is_per_symbol_task("tushare", "index_daily")
    assert is_per_symbol_task("tushare", "income")
    assert is_per_symbol_task("tushare", "fina_indicator")
    assert is_per_symbol_task("tushare", "margin_detail")
    assert is_per_symbol_task("fred", "CPIAUCSL")
    assert is_per_symbol_task("yfinance", "stock_daily_bar")

    # 2. 验证按日全市场拉取模式 (股票行情、每日估值、资金流等)
    assert not is_per_symbol_task("tushare", "stock_daily_bar")
    assert not is_per_symbol_task("tushare", "daily_basic")
    assert not is_per_symbol_task("tushare", "moneyflow")
    assert not is_per_symbol_task("tushare", "adj_factor")
    assert not is_per_symbol_task("tushare", "stk_limit")
    assert not is_per_symbol_task("tushare", "limit_list_d")


def test_list_available_tasks() -> None:
    tushare_tasks = list_available_tasks("tushare")
    assert "stock_daily_bar" in tushare_tasks
    assert "daily_basic" in tushare_tasks
    assert "adj_factor" in tushare_tasks
    assert "stk_limit" in tushare_tasks
    assert "limit_list_d" in tushare_tasks
    assert "limit_list" not in tushare_tasks
    assert "income" in tushare_tasks
    assert "bak_daily" not in tushare_tasks

    lixinger_tasks = list_available_tasks("lixinger")
    assert "sw_2021_fundamental" in lixinger_tasks
    assert "pledge_info" in lixinger_tasks


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

    from stock.data.task_registry import get_endpoint_market

    assert get_endpoint_market("alphavantage", "fx_daily") == "GLOBAL"


def test_lixinger_l2_task_uses_the_documented_shared_api_route() -> None:
    task = resolve_task("lixinger", "sw_2021_l2_fundamental")

    assert task.api_name == "cn/industry/fundamental/sw_2021"


def test_lixinger_task_bundles() -> None:
    assert list_available_bundles("lixinger") == [
        "market_bundle",
        "industry_bundle",
        "company_bundle",
        "macro_bundle",
        "index_bundle",
    ]
    assert list_available_bundles("tushare") == []

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

    assert expand_task_targets("lixinger", ["macro_bundle"])[-2:] == ["cn_m", "sf_month"]


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
