"""理杏仁宏观与大宗商品任务注册定义。"""

from typing import Any

LIXINGER_MACRO_TASK_SPECS: tuple[dict[str, object], ...] = (
    {
        "task": "national_debt",
        "api": "macro/national-debt",
        "dataset": "national_debt",
        "qp": "macro_daily",
        "frequency": "daily",
    },
    {
        "task": "interest_rates",
        "api": "macro/interest-rates",
        "dataset": "interest_rates",
        "qp": "macro_daily",
        "frequency": "daily",
    },
    {
        "task": "non_ferrous_metals",
        "api": "macro/non-ferrous-metals",
        "dataset": "non_ferrous_metals",
        "qp": "macro_daily",
        "frequency": "daily",
    },
    {
        "task": "crude_oil",
        "api": "macro/crude-oil",
        "dataset": "crude_oil",
        "qp": "macro_daily",
        "frequency": "daily",
    },
    {
        "task": "investor_accounts",
        "api": "macro/investor",
        "dataset": "investor_accounts",
        "qp": "generic",
        "frequency": "monthly",
    },
    {
        "task": "cn_m",
        "api": "macro/money-supply",
        "dataset": "cn_m",
        "qp": "macro_monthly",
        "frequency": "monthly",
    },
    {
        "task": "sf_month",
        "api": "macro/social-financing",
        "dataset": "sf_month",
        "qp": "macro_monthly",
        "frequency": "monthly",
    },
    {
        "task": "energy",
        "api": "macro/energy",
        "dataset": "energy",
        "qp": "macro_monthly",
        "frequency": "monthly",
    },
    {
        "task": "price_index",
        "api": "macro/price-index",
        "dataset": "price_index",
        "qp": "macro_monthly",
        "frequency": "monthly",
    },
)


def build_lixinger_macro_tasks(make_spec: Any) -> dict[tuple[str, str], Any]:
    """使用统一构造器生成理杏仁宏观与能源任务映射。"""
    return {
        ("lixinger", str(item["task"])): make_spec(
            str(item["task"]),
            "lixinger",
            str(item["api"]),
            str(item["dataset"]),
            qp=str(item.get("qp", "generic")),
            frequency=str(item.get("frequency", "daily")),
            partitioned=False,
            is_single_sync=True,
        )
        for item in LIXINGER_MACRO_TASK_SPECS
    }
