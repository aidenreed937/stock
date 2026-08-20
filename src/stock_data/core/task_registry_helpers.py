"""任务注册表的轻量共享判定辅助函数。"""

PER_PERIOD_DATASETS: frozenset[str] = frozenset(
    {"income", "fina_indicator", "balancesheet", "cashflow"}
)


def is_tushare_internal_api(name: str) -> bool:
    """判断名称是否为财务报表 VIP 内部接口。"""
    return name.endswith("_vip") and name.removesuffix("_vip") in PER_PERIOD_DATASETS
