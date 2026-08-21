"""理杏仁公司风险接口任务注册参数。"""

from typing import Any

LIXINGER_RISK_TASK_NAMES = frozenset({"regulatory_measures", "exchange_inquiry", "unlock_summary"})
LIXINGER_WATCHLIST_ONLY_TASK_NAMES = frozenset({"regulatory_measures", "exchange_inquiry"})

LIXINGER_RISK_TASK_SPECS: tuple[dict[str, object], ...] = (
    {
        "task": "regulatory_measures",
        "api": "cn/company/measures",
        "dataset": "regulatory_measures",
        "frequency": "event",
    },
    {
        "task": "exchange_inquiry",
        "api": "cn/company/inquiry",
        "dataset": "exchange_inquiry",
        "frequency": "event",
    },
    {
        "task": "unlock_summary",
        "api": "cn/company/hot/elr",
        "dataset": "unlock_summary",
        "frequency": "static",
    },
)


def build_lixinger_risk_tasks(make_spec: Any) -> dict[tuple[str, str], Any]:
    """使用任务注册表的统一构造器生成风险任务。"""
    return {
        ("lixinger", str(item["task"])): make_spec(
            str(item["task"]),
            "lixinger",
            str(item["api"]),
            str(item["dataset"]),
            fetch_mode="per_symbol",
            partitioned=False,
            is_single_sync=True,
            required_pool=item.get("required_pool"),
            frequency=str(item["frequency"]),
        )
        for item in LIXINGER_RISK_TASK_SPECS
    }
