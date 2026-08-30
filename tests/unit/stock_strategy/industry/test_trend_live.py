from datetime import date
from pathlib import Path

import polars as pl

from stock_strategy.industry.trend_live import inspect_live_industry_trend_signal


def _make_panel() -> pl.DataFrame:
    d = date(2026, 8, 28)
    return pl.DataFrame(
        {
            "trade_date": [d, d, d],
            "industry_code": ["801080.SI", "801160.SI", "801050.SI"],
            "industry_name": ["电子", "公用事业", "有色金属"],
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
                {"symbol": "561560.SH", "trade_date": date(2026, 8, 28), "close": 1.27},
                {"symbol": "512400.SH", "trade_date": date(2026, 8, 28), "close": 0.875},
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
    assert by_code["801160.SI"].etf_symbol == "561560.SH"  # 公用事业→电力ETF
    assert by_code["801050.SI"].etf_symbol == "512400.SH"  # 有色→有色金属ETF
    # 参考价来自 mock fund_daily（非占位 1.0）
    assert abs(by_code["801080.SI"].latest_price - 1.05) < 1e-9

    # 方向层状态：仅展示非中性 50 的行业（电子 80 / 有色 20），公用事业（中性 50）不展示
    assert set(res.candidate_direction.keys()) == {"801080.SI", "801050.SI"}
    assert res.candidate_direction["801080.SI"] == 80.0
    assert res.candidate_direction["801050.SI"] == 20.0
