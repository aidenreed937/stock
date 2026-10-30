"""理杏仁项目级手工任务映射。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

MakeTaskSpec = Callable[..., Any]

_FINANCIAL_SECTORS = ("non_financial", "bank", "security", "insurance")


def build_lixinger_manual_tasks(make_spec: MakeTaskSpec) -> dict[tuple[str, str], Any]:
    """生成理杏仁市场、公司、行业和基金类手工任务。"""
    return {
        ("lixinger", "stock_daily_bar"): make_spec(
            "stock_daily_bar",
            "lixinger",
            "cn/company/candlestick",
            "stock_daily_bar",
            "bar",
            fetch_mode="per_symbol",
            partitioned=False,
        ),
        ("lixinger", "index_daily_bar"): make_spec(
            "index_daily_bar",
            "lixinger",
            "cn/index/candlestick",
            "index_daily_bar",
            "bar",
            fetch_mode="per_symbol",
            partitioned=False,
        ),
        ("lixinger", "company_fundamental"): make_spec(
            "company_fundamental",
            "lixinger",
            "cn/company/fundamental/non_financial",
            "company_fundamental",
            fetch_mode="per_symbol",
            partitioned=False,
            is_single_sync=True,
        ),
        ("lixinger", "index_fundamental"): make_spec(
            "index_fundamental",
            "lixinger",
            "cn/index/fundamental",
            "index_fundamental",
            fetch_mode="per_symbol",
            partitioned=False,
            is_single_sync=True,
        ),
        ("lixinger", "sw_2021_fundamental"): make_spec(
            "sw_2021_fundamental",
            "lixinger",
            "cn/industry/fundamental/sw_2021",
            "sw_2021_fundamental",
            fetch_mode="per_symbol",
            partitioned=False,
            is_single_sync=True,
        ),
        ("lixinger", "sw_2021_l2_fundamental"): make_spec(
            "sw_2021_l2_fundamental",
            "lixinger",
            "cn/industry/fundamental/sw_2021",
            "sw_2021_l2_fundamental",
            fetch_mode="per_symbol",
            partitioned=False,
            is_single_sync=True,
        ),
        ("lixinger", "sw_2021_constituents"): make_spec(
            "sw_2021_constituents",
            "lixinger",
            "cn/industry/constituents/sw_2021",
            "sw_2021_constituents",
            fetch_mode="per_symbol",
            partitioned=False,
            is_single_sync=True,
        ),
        **{
            ("lixinger", f"sw_2021_{pfx}fs_{sec}"): make_spec(
                f"sw_2021_{pfx}fs_{sec}",
                "lixinger",
                f"cn/industry/fs/sw_2021/{sec}",
                f"sw_2021_{pfx}fs_{sec}",
                fetch_mode="per_period",
                partitioned=False,
                is_single_sync=True,
                frequency="quarterly",
                query_mode="period",
            )
            for pfx in ("", "l2_", "l3_")
            for sec in _FINANCIAL_SECTORS
        },
        **{
            ("lixinger", f"fs_{sec}"): make_spec(
                f"fs_{sec}",
                "lixinger",
                f"cn/company/fs/{sec}",
                f"fs_{sec}",
                fetch_mode="per_symbol",
                partitioned=False,
                is_single_sync=True,
            )
            for sec in _FINANCIAL_SECTORS
        },
        ("lixinger", "pledge_info"): make_spec(
            "pledge_info",
            "lixinger",
            "cn/company/hot/ple",
            "pledge_info",
            fetch_mode="per_symbol",
            partitioned=False,
            is_single_sync=True,
        ),
        ("lixinger", "fund_holder_structure"): make_spec(
            "fund_holder_structure",
            "lixinger",
            "cn/fund/shareholders-structure",
            "fund_holder_structure",
            fetch_mode="per_symbol",
            partitioned=False,
            is_single_sync=True,
        ),
    }


__all__ = ["build_lixinger_manual_tasks"]
