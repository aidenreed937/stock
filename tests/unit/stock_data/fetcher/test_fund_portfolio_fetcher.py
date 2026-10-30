"""fund_portfolio 按基金代码采集的契约测试。

上游 fund_portfolio 没有 period 参数，传入会被静默忽略并退化为「默认排序前 8000 行」
切片——这正是历史 Curated 每只基金每报告期只剩 1 条持仓的根因。以下测试锁定修复后的
调用参数，防止再次回退到 period 查询。
"""

from datetime import date

import pandas as pd

from stock_data.fetcher.tushare.registry import TUSHARE_API_REGISTRY
from stock_data.fetcher.tushare.research_fetcher import fetch_fund_portfolio_data

_COLUMNS = [
    "ts_code",
    "ann_date",
    "end_date",
    "symbol",
    "mkv",
    "amount",
    "stk_mkv_ratio",
    "stk_float_ratio",
]


class _RecordingClient:
    """记录请求参数并按顺序返回预置响应的假客户端。"""

    def __init__(self, frames: list[pd.DataFrame]) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._frames = frames or [pd.DataFrame(columns=_COLUMNS)]

    def query(self, api_name: str, **kwargs: object) -> pd.DataFrame:
        self.calls.append((api_name, kwargs))
        index = min(len(self.calls) - 1, len(self._frames) - 1)
        return self._frames[index]


def _rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ["005827.OF", "20251028", "20250930", "000568.SZ", 3.5e9, 2.6e7, 10.34, 1.81],
            ["005827.OF", "20251028", "20250930", "000858.SZ", 3.4e9, 2.8e7, 10.23, 0.74],
        ],
        columns=_COLUMNS,
    )


def test_symbol_query_uses_ts_code_and_never_sends_period() -> None:
    meta = TUSHARE_API_REGISTRY["fund_portfolio"]
    client = _RecordingClient([_rows()])

    frame = fetch_fund_portfolio_data(
        client,  # type: ignore[arg-type]
        "005827.OF",
        date(2010, 1, 1),
        date(2026, 9, 30),
        meta,
        {},
    )

    api_name, kwargs = client.calls[0]
    assert api_name == "fund_portfolio"
    assert kwargs["ts_code"] == "005827.OF"
    assert kwargs["start_date"] == "20100101"
    assert kwargs["end_date"] == "20260930"
    assert "period" not in kwargs
    assert frame.height == 2
    assert "ts_code" in frame.columns


def test_market_wide_query_iterates_quarters_without_period() -> None:
    meta = TUSHARE_API_REGISTRY["fund_portfolio"]
    client = _RecordingClient([pd.DataFrame(columns=_COLUMNS)])

    fetch_fund_portfolio_data(
        client,  # type: ignore[arg-type]
        "",
        date(2025, 1, 1),
        date(2025, 12, 31),
        meta,
        {},
    )

    assert len(client.calls) == 4
    for _, kwargs in client.calls:
        assert "period" not in kwargs
        assert "ts_code" not in kwargs
    assert client.calls[0][1]["start_date"] == "20250331"


def test_quarter_ends_helper_is_inclusive() -> None:
    from stock_data.fetcher.tushare.research_fetcher import _quarter_ends

    assert _quarter_ends(date(2025, 3, 31), date(2025, 9, 30)) == [
        date(2025, 3, 31),
        date(2025, 6, 30),
        date(2025, 9, 30),
    ]
