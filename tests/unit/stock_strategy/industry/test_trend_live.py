from datetime import date
from pathlib import Path

import polars as pl

from stock_strategy.industry.trend_live import inspect_live_industry_trend_signal


def _make_panel() -> pl.DataFrame:
    """方向层产业池（默认 candidate_pool=direction 的候选行业）。"""
    d = date(2026, 8, 28)
    return pl.DataFrame(
        {
            "trade_date": [d, d, d],
            "industry_code": ["801080.SI", "801770.SI", "801750.SI"],
            "industry_name": ["电子", "通信", "计算机"],
            "trend_momentum": [15.8, 14.8, 13.9],
            "supply_demand_score": [80.0, 70.0, 60.0],
            "crowding_score": [30.0, 20.0, 10.0],
            "direction_score": [80.0, 50.0, 20.0],
            "prosperity_score": [70.0, 60.0, 50.0],
            "composite_trend_score": [60.0, 55.0, 50.0],
        }
    )


def test_inspect_live_industry_trend_signal(monkeypatch) -> None:
    # mock 因子面板
    monkeypatch.setattr(
        "stock_strategy.industry.trend_live.load_latest_industry_trend_panel",
        lambda factor_root: (Path("."), _make_panel(), {}),
    )

    # mock DataCatalog（fund_daily 最新价）
    class FakeCatalog:
        def __init__(self, data_source: str) -> None:
            self.data_source = data_source

        def load_dataset(self, dataset: str, symbols=None):
            rows = [
                {"symbol": "512480.SH", "trade_date": date(2026, 8, 28), "close": 1.05},
                {"symbol": "515880.SH", "trade_date": date(2026, 8, 28), "close": 1.27},
                {"symbol": "512720.SH", "trade_date": date(2026, 8, 28), "close": 0.9},
            ]
            return pl.DataFrame(rows)

    monkeypatch.setattr("stock_strategy.industry.trend_live.DataCatalog", FakeCatalog)

    res = inspect_live_industry_trend_signal(
        strategy_key="industry_trend_momentum", total_capital=100_000.0
    )

    # 3 个行业 trend_momentum 均 > 0，Top3 全选
    assert res.has_rebalance
    assert len(res.instructions) == 3
    assert "产业趋势跟踪" in res.markdown_card
    assert "方向层状态" in res.markdown_card

    # ETF 映射正确
    by_code = {inst.industry_code: inst for inst in res.instructions}
    assert by_code["801080.SI"].etf_symbol == "512480.SH"  # 电子→半导体芯片ETF
    assert by_code["801770.SI"].etf_symbol == "515880.SH"  # 通信→通信ETF
    assert by_code["801750.SI"].etf_symbol == "512720.SH"  # 计算机→计算机ETF
    # 参考价来自 mock fund_daily（非占位 1.0）
    assert abs(by_code["801080.SI"].latest_price - 1.05) < 1e-9

    # 方向层状态：仅展示非中性 50 的行业（电子 80 / 计算机 20），通信（中性 50）不展示
    assert set(res.candidate_direction.keys()) == {"801080.SI", "801750.SI"}
    assert res.candidate_direction["801080.SI"] == 80.0
    assert res.candidate_direction["801750.SI"] == 20.0


def test_inspect_live_with_unmapped_industry(monkeypatch) -> None:
    """无对应 ETF 的行业（如纺织服饰）→ 提示无映射，不生成可执行手数。"""
    d = date(2026, 8, 28)
    panel = pl.DataFrame(
        {
            "trade_date": [d, d],
            "industry_code": ["801080.SI", "801130.SI"],
            "industry_name": ["电子", "纺织服饰"],
            "trend_momentum": [15.8, 14.8],
            "supply_demand_score": [80.0, 70.0],
            "crowding_score": [30.0, 20.0],
            "direction_score": [80.0, 50.0],
            "prosperity_score": [70.0, 60.0],
            "composite_trend_score": [60.0, 55.0],
        }
    )
    monkeypatch.setattr(
        "stock_strategy.industry.trend_live.load_latest_industry_trend_panel",
        lambda factor_root: (Path("."), panel, {}),
    )

    class FakeCatalog:
        def __init__(self, data_source: str) -> None:
            self.data_source = data_source

        def load_dataset(self, dataset: str, symbols=None):
            return pl.DataFrame(
                [
                    {"symbol": "512480.SH", "trade_date": d, "close": 1.05},
                ]
            )

    monkeypatch.setattr("stock_strategy.industry.trend_live.DataCatalog", FakeCatalog)

    res = inspect_live_industry_trend_signal(
        strategy_key="industry_trend_momentum", total_capital=100_000.0
    )
    by_code = {inst.industry_code: inst for inst in res.instructions}
    # 纺织服饰不在方向层池 → 只剩电子 1 条指令（candidate_pool 默认 direction）
    assert set(by_code.keys()) == {"801080.SI"}
    assert by_code["801080.SI"].etf_symbol == "512480.SH"
    assert by_code["801080.SI"].recommended_lots is not None
