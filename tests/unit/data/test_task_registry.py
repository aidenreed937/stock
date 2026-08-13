"""TaskRegistry 与 is_task_partitioned 单元测试。"""

from stock.data.task_registry import (
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


def test_list_available_tasks() -> None:
    tushare_tasks = list_available_tasks("tushare")
    assert "stock_daily_bar" in tushare_tasks
    assert "daily_basic" in tushare_tasks
    assert "adj_factor" in tushare_tasks
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
