import pytest

from stock_strategy.industry.live import (
    inspect_live_industry_signal,
    load_industry_etf_map,
)


def test_load_industry_etf_map() -> None:
    etf_map = load_industry_etf_map()
    assert len(etf_map) >= 27
    assert "801010.SI" in etf_map
    assert etf_map["801010.SI"]["symbol"] == "159825.SZ"


def test_inspect_live_industry_signal() -> None:
    # 轮动策略池已于 2026-08-31 停用：指定已下架策略应抛出 ValueError（友好失败）
    with pytest.raises(ValueError, match=r"未找到行业策略配置|已停用|未知策略"):
        inspect_live_industry_signal(
            strategy_key="industry_momentum",
            total_capital=200_000.0,
        )
