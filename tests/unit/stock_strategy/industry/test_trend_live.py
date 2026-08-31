from datetime import date
from pathlib import Path

import polars as pl

from stock_strategy.industry.trend_live import (
    inspect_live_industry_trend_signal,
    load_l2_etf_map,
)


def _make_panel() -> pl.DataFrame:
    """方向池 6 个申万二级行业截面（industry_l2_panel_daily 口径，含池内去重后成员）。"""
    d = date(2026, 8, 28)
    return pl.DataFrame(
        {
            "trade_date": [d] * 6,
            "industry_code": ["270100", "730200", "710100", "220200", "630700", "280500"],
            "industry_name": ["半导体", "通信设备", "计算机设备", "化学原料", "电池", "乘用车"],
            "return_60d": [15.8, 14.8, 13.9, 3.0, 5.0, -2.0],
            "pe_ttm_ew_percentile_5y": [40.0, 50.0, 60.0, 95.0, 30.0, 20.0],
            "revenue_growth_ttm": [0.15, 0.18, 0.05, -0.10, 0.27, 0.03],
            "profit_growth_ttm": [0.29, 0.72, 0.22, -0.20, 0.74, -0.32],
            "direction_score": [80.0, 44.0, 20.0, 2.8, 8.3, 8.3],
        }
    )


def _make_theme_etf_direction() -> pl.DataFrame:
    """theme_etf_direction 最新归属（方向池 6 行业 → ETF）。"""
    d = date(2026, 8, 28)
    return pl.DataFrame(
        {
            "trade_date": [d] * 6,
            "etf_symbol": [
                "512480.SH",
                "515880.SH",
                "512720.SH",
                "516020.SH",
                "159755.SZ",
                "516110.SH",
            ],
            "theme": ["半导体", "通信设备", "计算机设备", "化学原料", "电池", "汽车"],
            "direction_score": [80.0, 44.0, 20.0, 2.8, 8.3, 8.3],
        }
    )


def test_load_l2_etf_map_from_theme_direction(monkeypatch, tmp_path: Path) -> None:
    """方向池 15 行业应具备标准 1:1 ETF 映射及代理属性（去重后）。"""
    etf_map = load_l2_etf_map()
    assert etf_map["270100"]["symbol"] == "512480.SH"  # 半导体
    assert etf_map["730200"]["symbol"] == "515880.SH"  # 通信设备
    assert etf_map["710100"]["symbol"] == "512720.SH"  # 计算机设备
    assert etf_map["630700"]["symbol"] == "159755.SZ"  # 电池
    assert etf_map["630800"]["symbol"] == "159326.SZ"  # 电网设备
    assert etf_map["280500"]["symbol"] == "516110.SH"  # 汽车
    assert etf_map["240400"]["symbol"] == "159562.SZ"  # 贵金属 (黄金股)
    assert etf_map["240300"]["symbol"] == "512400.SH"  # 工业金属 (有色)
    assert etf_map["640600"]["symbol"] == "560280.SH"  # 工程机械 (工程机械主题ETF)
    assert etf_map["421100"]["symbol"] == "159666.SZ"  # 航运港口 (交通运输ETF)
    assert etf_map["370600"]["symbol"] == "512170.SH"  # 医疗服务 (医疗ETF 主题代理)
    assert etf_map["220200"]["symbol"] == "516020.SH"  # 化学原料 (细分化工ETF 代理)

    # 去重出池行业不应再在映射基准中
    assert "630500" not in etf_map  # 光伏设备（去重剔除）
    assert "370300" not in etf_map  # 生物制品（去重剔除）
    assert "220300" not in etf_map  # 化学制品（去重剔除）
    assert "220500" not in etf_map  # 塑料（去重剔除）

    assert etf_map["630800"]["match_type"] == "pure_l2"
    assert etf_map["640600"]["match_type"] == "pure_l2"
    assert etf_map["421100"]["match_type"] == "proxy_l1"
    assert etf_map["220200"]["match_type"] == "proxy_l2"


def test_inspect_live_industry_trend_signal(monkeypatch, tmp_path: Path) -> None:
    # mock 二级基本面面板与 theme_etf_direction
    import stock_strategy.industry.trend_live as tl

    panel_mart = tmp_path / "industry_l2_panel_daily.parquet"
    _make_panel().write_parquet(panel_mart)
    theme_mart = tmp_path / "theme_etf_direction.parquet"
    _make_theme_etf_direction().write_parquet(theme_mart)
    monkeypatch.setattr(tl, "_L2_PANEL_MART", panel_mart)
    monkeypatch.setattr(tl, "_THEME_ETF_DIRECTION_MART", theme_mart)

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
        strategy_key="industry_l2_direction", total_capital=100_000.0
    )

    # Top3 动量（return_60d）：270100/730200/710100（pe5y<=90），630500 因 pe5y=95 剔除
    assert res.has_rebalance
    assert len(res.instructions) == 3
    assert "产业趋势跟踪" in res.markdown_card
    assert "方向层状态" in res.markdown_card

    # ETF 映射正确
    by_code = {inst.industry_code: inst for inst in res.instructions}
    assert by_code["270100"].etf_symbol == "512480.SH"  # 半导体→半导体ETF
    assert by_code["730200"].etf_symbol == "515880.SH"  # 通信设备→通信ETF
    assert by_code["710100"].etf_symbol == "512720.SH"  # 计算机设备→计算机ETF
    # 参考价来自 mock fund_daily（非占位 1.0）
    assert abs(by_code["270100"].latest_price - 1.05) < 1e-9

    # 方向层状态：仅展示非中性 50 的行业（6 行业方向分均非 50）
    assert set(res.candidate_direction.keys()) == {
        "270100",
        "730200",
        "710100",
        "220200",
        "630700",
        "280500",
    }
    assert res.candidate_direction["270100"] == 80.0


def test_inspect_live_with_unmapped_industry(monkeypatch, tmp_path: Path) -> None:
    """面板中出现未配置的未知行业编码 → 过滤或优雅处理。"""
    import stock_strategy.industry.trend_live as tl

    d = date(2026, 8, 28)
    panel = pl.DataFrame(
        {
            "trade_date": [d] * 2,
            "industry_code": ["270100", "999999"],
            "industry_name": ["半导体", "未知行业"],
            "return_60d": [15.8, 14.8],
            "pe_ttm_ew_percentile_5y": [40.0, 50.0],
            "revenue_growth_ttm": [0.15, 0.18],
            "profit_growth_ttm": [0.29, 0.72],
            "direction_score": [80.0, 50.0],
        }
    )
    panel_mart = tmp_path / "industry_l2_panel_daily.parquet"
    panel.write_parquet(panel_mart)
    theme_mart = tmp_path / "theme_etf_direction.parquet"
    _make_theme_etf_direction().write_parquet(theme_mart)
    monkeypatch.setattr(tl, "_L2_PANEL_MART", panel_mart)
    monkeypatch.setattr(tl, "_THEME_ETF_DIRECTION_MART", theme_mart)

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
        strategy_key="industry_l2_direction", total_capital=100_000.0
    )
    by_code = {inst.industry_code: inst for inst in res.instructions}
    # 999999 不在方向池 13 行业（面板过滤后仅 270100 进入候选）→ 仅 1 条指令
    assert set(by_code.keys()) == {"270100"}
    assert by_code["270100"].etf_symbol == "512480.SH"
    assert by_code["270100"].recommended_lots is not None
