"""全球宏观、龙虎榜、ETF 资金流、申万二级行业与梯队 2 新 Mart 单元测试。"""

from datetime import date

import polars as pl

from stock_analytics.marts.dragon_tiger import (
    build_dragon_tiger_frame,
    empty_dragon_tiger,
)
from stock_analytics.marts.etf_flow import (
    build_etf_flow_frame,
    classify_etf,
    empty_etf_flow,
)
from stock_analytics.marts.global_macro import (
    build_global_macro_daily_frame,
    empty_global_macro,
)
from stock_analytics.marts.industry_l2 import (
    build_industry_l2_frame,
    empty_industry_l2,
)
from stock_analytics.marts.industry_l2_panel import (
    build_industry_l2_panel_frame,
    empty_industry_l2_panel,
    expand_l2_financial,
)
from stock_analytics.marts.northbound_industry import (
    build_northbound_industry_frame,
    empty_northbound_industry,
)
from stock_analytics.marts.unlock_pressure import (
    build_unlock_pressure_frame,
    empty_unlock_pressure,
)


def _yf_macro() -> pl.DataFrame:
    """构造含 ^TNX / CNH=X / GC=F / ^VIX 的 yfinance 宏观长表。"""
    dates = [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)]
    rows: list[list[object]] = []
    for symbol, values in {
        "^TNX": [4.5, 4.4, 4.3],
        "CNH=X": [7.0, 6.95, 6.90],
        "GC=F": [2000.0, 2010.0, 2020.0],
        "^VIX": [20.0, 19.0, 18.0],
    }.items():
        for d, v in zip(dates, values):
            rows.append([d, symbol, v])
    return pl.DataFrame(rows, schema=["trade_date", "symbol", "close"], orient="row")


def _fred_macro() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)],
            "symbol": ["T10Y2Y"] * 3,
            "close": [0.5, 0.4, 0.3],
        }
    )


def _national_debt() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)],
            "tcm_y1": [0.015, 0.015, 0.015],
            "tcm_y5": [0.016, 0.016, 0.016],
            "tcm_y10": [0.017, 0.017, 0.017],
            "tcm_y30": [0.019, 0.019, 0.019],
        }
    )


def _shibor() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)],
            "on": [1.5, 1.4, 1.3],
            "3m": [1.8, 1.8, 1.8],
        }
    )


def _shibor_lpr() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)],
            "1y": [3.0, 3.0, 3.0],
        }
    )


# --------------------------------------------------------------------------- #
# global_macro
# --------------------------------------------------------------------------- #


def test_global_macro_units_and_spread() -> None:
    """中债小数->百分数、10Y-2Y 利差与铜金比应正确计算。"""
    frame = build_global_macro_daily_frame(
        _yf_macro(), _fred_macro(), _national_debt(), _shibor(), _shibor_lpr()
    )
    assert not frame.is_empty()
    assert frame["trade_date"].dtype == pl.Date
    row = frame.filter(pl.col("trade_date") == date(2026, 8, 3)).to_pandas().iloc[0]
    assert abs(row["cn_10y_yield"] - 1.7) < 1e-9  # 0.017 * 100
    assert abs(row["us_10y_yield"] - 4.5) < 1e-9
    assert abs(row["us_2y_yield"] - 4.0) < 1e-9  # 4.5 - 0.5
    assert abs(row["cnh_close"] - 7.0) < 1e-9
    assert abs(row["shibor_on"] - 1.5) < 1e-9
    assert abs(row["shibor_lpr_1y"] - 3.0) < 1e-9
    assert frame["cnh_return_20d"].null_count() == frame.height  # 样本不足 20 日


def test_global_macro_empty_inputs() -> None:
    frame = build_global_macro_daily_frame(
        pl.DataFrame(), pl.DataFrame(), pl.DataFrame(), pl.DataFrame(), pl.DataFrame()
    )
    assert frame.is_empty()
    assert frame.columns == list(empty_global_macro().columns)


# --------------------------------------------------------------------------- #
# dragon_tiger
# --------------------------------------------------------------------------- #


def _top_inst() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 3)] * 4,
            "symbol": ["600000.SH", "600000.SH", "600001.SH", "600001.SH"],
            "exalter": [
                "机构专用",
                "机构专用",
                "东方财富证券股份有限公司拉萨团结路第二证券营业部",
                "东方财富证券股份有限公司拉萨团结路第二证券营业部",
            ],
            "side": ["1", "0", "1", "0"],
            "buy": [100_000_000.0, 0.0, 90_000_000.0, 0.0],
            "sell": [0.0, 40_000_000.0, 0.0, 20_000_000.0],
            "net_buy": [100_000_000.0, -40_000_000.0, 90_000_000.0, -20_000_000.0],
        }
    )


def _top_list() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 3)] * 2,
            "symbol": ["600000.SH", "600001.SH"],
            "amount": [500_000_000.0, 300_000_000.0],
            "net_amount": [50_000_000.0, 30_000_000.0],
        }
    )


def test_dragon_tiger_aggregation() -> None:
    market_turnover = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 3)],
            "market_amount": [4_000_000_000.0],  # 全市场 40 亿元
        }
    )
    frame = build_dragon_tiger_frame(_top_inst(), _top_list(), market_turnover=market_turnover)
    assert not frame.is_empty()
    row = frame.filter(pl.col("trade_date") == date(2026, 8, 3)).to_pandas().iloc[0]
    assert abs(row["inst_buy_amount"] - 100_000_000.0) < 1e-6
    assert abs(row["inst_sell_amount"] - 40_000_000.0) < 1e-6
    assert abs(row["inst_net_buy_amount"] - 60_000_000.0) < 1e-6
    assert row["inst_active_stock_count"] == 1
    assert row["inst_heavy_buy_count"] == 1  # 600000 净买入 6000 万 >= 5000 万
    # 游资口径独立：拉萨两笔合并净买入 7000 万
    assert abs(row["hot_money_net_buy_amount"] - 70_000_000.0) < 1e-6
    assert row["top_list_issue_count"] == 2
    assert abs(row["top_list_total_amount"] - 800_000_000.0) < 1e-6
    # 占比：8 亿 / 40 亿 = 20%
    assert abs(row["market_amount"] - 4_000_000_000.0) < 1e-6
    assert abs(row["top_list_turnover_share"] - 20.0) < 1e-6


def test_dragon_tiger_turnover_share_missing() -> None:
    """未提供全市场成交额时占比保持缺失，不伪造分母。"""
    frame = build_dragon_tiger_frame(_top_inst(), _top_list())
    col = frame.filter(pl.col("trade_date") == date(2026, 8, 3))["top_list_turnover_share"]
    assert col.null_count() == 1


def test_dragon_tiger_empty() -> None:
    assert build_dragon_tiger_frame(pl.DataFrame(), _top_list()).is_empty()
    assert build_dragon_tiger_frame(pl.DataFrame(), pl.DataFrame()).columns == list(
        empty_dragon_tiger().columns
    )


# --------------------------------------------------------------------------- #
# etf_flow
# --------------------------------------------------------------------------- #


def _etf_share() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)] * 2,
            "symbol": ["510300.SH"] * 3 + ["159995.SZ"] * 3,
            "etf_name": ["华泰柏瑞沪深300ETF"] * 3 + ["华夏国证半导体芯片ETF"] * 3,
            "total_share": [100.0, 105.0, 105.0, 200.0, 200.0, 195.0],  # 万份
            "close": [4.0, 4.1, 4.2, 1.0, 1.0, 1.1],
        }
    )


def _fund_daily() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)] * 2,
            "symbol": ["510300.SH"] * 3 + ["159995.SZ"] * 3,
            "close": [4.0, 4.1, 4.2, 1.0, 1.0, 1.1],
        }
    )


def test_etf_flow_amount_and_buckets() -> None:
    universe = ["510300.SH", "159995.SZ"]
    frame = build_etf_flow_frame(_etf_share(), _fund_daily(), etf_universe=universe)
    assert not frame.is_empty()
    row_4 = frame.filter(pl.col("trade_date") == date(2026, 8, 4)).to_pandas().iloc[0]
    # 300ETF: Δ份额 5(万份) * 1e4(份/万份) * 4.1(元/份) = 205,000 元
    assert abs(row_4["etf_300_inflow"] - 205_000.0) < 1.0
    row_5 = frame.filter(pl.col("trade_date") == date(2026, 8, 5)).to_pandas().iloc[0]
    # 芯片: Δ-5 万份 * 1e4 * 1.1(元/份) = -55,000 元
    assert abs(row_5["sector_etf_net_inflow"] + 55_000.0) < 1.0
    assert abs(row_5["total_etf_net_inflow"] + 55_000.0) < 1.0
    assert row_5["top_inflow_sector_name"] in ("芯片", "半导体", None)


def test_etf_flow_classify() -> None:
    assert classify_etf("华泰柏瑞沪深300ETF") == "broad"
    assert classify_etf("国泰CES半导体芯片ETF") == "sector"
    assert classify_etf("华安日日鑫货币ETF") == "other"


def test_etf_flow_empty() -> None:
    assert build_etf_flow_frame(pl.DataFrame(), pl.DataFrame()).is_empty()
    assert build_etf_flow_frame(pl.DataFrame(), _fund_daily()).is_empty()
    assert build_etf_flow_frame(pl.DataFrame(), pl.DataFrame()).columns == list(
        empty_etf_flow().columns
    )


# --------------------------------------------------------------------------- #
# industry_l2
# --------------------------------------------------------------------------- #


def _sw_daily() -> pl.DataFrame:
    # 1250+ 个自然日采样（2021-01-04 起），尾部覆盖 2026-08 窗口（满足 5Y 分位门槛）
    all_dates = pl.date_range(
        date(2021, 1, 4), date(2026, 8, 26), interval="1d", eager=True
    ).to_list()
    dates = all_dates[:1250]
    # 确保尾部包含 2026-08-01 及之后，用于 cutoff 断言
    tail = [d for d in all_dates if d >= date(2026, 8, 1)]
    dates = dates[: len(dates) - len(tail)] + tail if tail else dates
    dates = sorted(set(dates))
    rows: list[list[object]] = []
    for lvl, code, parent, name in (
        ("L1", "640000", "0", "机械设备"),
        ("L2", "640200", "640000", "专用设备"),
        ("L3", "640300", "640200", "三级设备"),
    ):
        for i, d in enumerate(dates):
            rows.append([d, f"8010{i % 100}.SI", name, lvl, code, parent, 10.0 + i * 0.01, 1e8])
    return pl.DataFrame(
        rows,
        schema=[
            "trade_date",
            "symbol",
            "name",
            "industry_level",
            "industry_code",
            "parent_code",
            "close",
            "amount",
        ],
        orient="row",
    )


def _l2_fundamental() -> pl.DataFrame:
    dates = _sw_daily().filter(pl.col("industry_level") == "L2")["trade_date"].to_list()
    return pl.DataFrame(
        {
            "trade_date": dates,
            "symbol": ["640200"] * len(dates),
            "pe_ttm.ew": [float(i) for i in range(len(dates))],
            "pb.ew": [1.0] * len(dates),
            "dyr.ew": [0.02] * len(dates),
            "mc": [1e10] * len(dates),
        }
    )


def test_industry_l2_levels_returns_and_percentile() -> None:
    frame = build_industry_l2_frame(
        _sw_daily(), _l2_fundamental(), percentile_cutoff=date(2026, 8, 1)
    )
    assert not frame.is_empty()
    assert frame.columns == list(empty_industry_l2().columns)
    # 只保留 L2
    assert frame["industry_code"].unique().to_list() == ["640200"]
    assert frame["parent_l1_name"].unique().to_list() == ["机械设备"]
    # 收益与分位存在
    assert frame["return_5d"].is_not_null().any()
    assert frame["pe_ttm_ew_percentile_5y"].is_not_null().any()
    # cutoff 前分位为 null，cutoff 后非 null
    before = frame.filter(pl.col("trade_date") < date(2026, 8, 1))
    after = frame.filter(pl.col("trade_date") >= date(2026, 8, 1))
    assert before["pe_ttm_ew_percentile_5y"].null_count() == before.height
    assert after["pe_ttm_ew_percentile_5y"].null_count() == 0


def test_industry_l2_empty() -> None:
    assert build_industry_l2_frame(pl.DataFrame(), _l2_fundamental()).is_empty()
    assert build_industry_l2_frame(pl.DataFrame(), pl.DataFrame()).columns == list(
        empty_industry_l2().columns
    )


# --------------------------------------------------------------------------- #
# industry_l2_panel（量价齐升供需层接入）
# --------------------------------------------------------------------------- #


def _l2_daily_panel_input() -> pl.DataFrame:
    """构造 industry_l2_daily 面板输入（3 行业 × 3 交易日，截面分位有意义）。"""
    return pl.DataFrame(
        {
            "trade_date": [
                date(2026, 8, 3),
                date(2026, 8, 3),
                date(2026, 8, 3),
                date(2026, 8, 4),
                date(2026, 8, 4),
                date(2026, 8, 4),
                date(2026, 8, 5),
                date(2026, 8, 5),
                date(2026, 8, 5),
            ],
            "industry_code": [
                "270100",
                "630500",
                "710100",
                "270100",
                "630500",
                "710100",
                "270100",
                "630500",
                "710100",
            ],
            "industry_name": [
                "半导体",
                "光伏设备",
                "计算机设备",
                "半导体",
                "光伏设备",
                "计算机设备",
                "半导体",
                "光伏设备",
                "计算机设备",
            ],
            "parent_l1_code": [
                "270000",
                "630000",
                "710000",
                "270000",
                "630000",
                "710000",
                "270000",
                "630000",
                "710000",
            ],
            "parent_l1_name": [
                "电子",
                "电力设备",
                "计算机",
                "电子",
                "电力设备",
                "计算机",
                "电子",
                "电力设备",
                "计算机",
            ],
            "close": [100.0, 50.0, 80.0, 101.0, 49.0, 82.0, 102.0, 48.0, 84.0],
            "amount_yi": [20.0, 5.0, 10.0, 22.0, 6.0, 11.0, 18.0, 7.0, 12.0],
            "return_20d": [5.0, -2.0, 3.0, 6.0, -3.0, 4.0, 7.0, -4.0, 5.0],
            "return_60d": [10.0, -8.0, 6.0, 11.0, -9.0, 7.0, 12.0, -10.0, 8.0],
            "pe_ttm_ew_percentile_5y": [40.0, 60.0, 50.0, 41.0, 61.0, 51.0, 42.0, 62.0, 52.0],
            "pb_ew_percentile_5y": [30.0, 50.0, 40.0, 31.0, 51.0, 41.0, 32.0, 52.0, 42.0],
        }
    )


def _l2_financial_input() -> pl.DataFrame:
    """构造已展开的 L2 财务事实帧（expand_l2_financial 输出口径）。"""
    return pl.DataFrame(
        {
            "eff_date": [
                date(2026, 4, 30),
                date(2026, 4, 30),
                date(2026, 4, 30),
                date(2026, 8, 14),
                date(2026, 8, 14),
                date(2026, 8, 14),
            ],
            "industry_code": ["270100", "630500", "710100", "270100", "630500", "710100"],
            "revenue_growth_ttm": [0.15, -0.05, 0.08, 0.18, -0.08, 0.10],
            "profit_growth_ttm": [0.12, 0.02, 0.05, 0.20, -0.10, 0.06],
            "gross_margin_ttm": [0.35, 0.18, 0.28, 0.36, 0.17, 0.29],
        }
    )


def test_expand_l2_financial_nested_fields() -> None:
    """嵌套 q 结构应展开为营收/净利 TTM 同比与毛利率（含非金融 gp_m 与非金融缺失容错）。"""
    # 非金融源：含 gp_m
    non_fin = pl.DataFrame(
        {
            "reportDate": [date(2026, 4, 30)],
            "symbol": ["270100"],
            "q": [
                {
                    "ps": {
                        "toi": {"ttm_y2y": 0.15, "c_y2y": 0.1},
                        "gp_m": {"ttm": 0.35},
                        "np": {"ttm_y2y": 0.12, "c_y2y": 0.08},
                    },
                    "m": {"roe": {"ttm": 0.15}},
                }
            ],
        }
    )
    out = expand_l2_financial(non_fin)
    assert not out.is_empty()
    assert out.columns == [
        "eff_date",
        "industry_code",
        "revenue_growth_ttm",
        "profit_growth_ttm",
        "gross_margin_ttm",
    ]
    row = out.to_pandas().iloc[0]
    assert abs(row["revenue_growth_ttm"] - 0.15) < 1e-9
    assert abs(row["profit_growth_ttm"] - 0.12) < 1e-9
    assert abs(row["gross_margin_ttm"] - 0.35) < 1e-9

    # 银行源：无 gp_m → 毛利率 null，不报错
    bank = pl.DataFrame(
        {
            "reportDate": [date(2026, 4, 30)],
            "symbol": ["480200"],
            "q": [
                {
                    "ps": {
                        "toi": {"ttm_y2y": 0.05, "c_y2y": 0.03},
                        "np": {"ttm_y2y": 0.04, "c_y2y": 0.02},
                    },
                    "m": {"roe": {"ttm": 0.10}},
                }
            ],
        }
    )
    out_bank = expand_l2_financial(bank)
    assert out_bank["gross_margin_ttm"].null_count() == 1
    assert abs(out_bank["revenue_growth_ttm"][0] - 0.05) < 1e-9


def test_industry_l2_panel_qlq_and_bargaining() -> None:
    """量价齐升（双正）供需层 + 议价权分应按 skill 口径计算，报告期按发布日生效。"""
    frame = build_industry_l2_panel_frame(_l2_daily_panel_input(), _l2_financial_input())
    assert not frame.is_empty()
    assert frame.columns == list(empty_industry_l2_panel().columns)

    # 08-03：2026-04-30 报告期生效 → 半导体/计算机量价齐升，光伏供给收缩（-0.05/0.02）
    d3 = frame.filter(pl.col("trade_date") == date(2026, 8, 3)).to_pandas()
    semi3 = d3[d3["industry_code"] == "270100"].iloc[0]
    pv3 = d3[d3["industry_code"] == "630500"].iloc[0]
    comp3 = d3[d3["industry_code"] == "710100"].iloc[0]
    # 量价齐升门内：双增速之和横截面分位（全截面 3 行业：-0.03/0.13/0.27 → 0/50/100）
    assert semi3["supply_demand_score"] == 100.0  # 半导体 0.27 最高
    assert comp3["supply_demand_score"] == 50.0  # 计算机 0.13 居中
    # 供给收缩惩罚分 20
    assert pv3["supply_demand_score"] == 20.0
    # 议价权：量价齐升门内 (净利−营收) 分位；半导体 +0.12-0.15=-0.03，计算机 +0.05-0.08=-0.03 相同 → 中性 50
    assert 0.0 <= semi3["bargaining_score"] <= 100.0
    assert pv3["bargaining_score"] == 30.0  # 门外中性分
    # 半导体营收同比最高 → 双增速分位最高
    assert semi3["revenue_growth_ttm"] > comp3["revenue_growth_ttm"]

    # 08-05：2026-08-14 报告期尚未发布 → 仍用 04-30 报告期（滞后生效，无前视）
    d5 = frame.filter(pl.col("trade_date") == date(2026, 8, 5)).to_pandas()
    semi5 = d5[d5["industry_code"] == "270100"].iloc[0]
    assert abs(semi5["revenue_growth_ttm"] - 0.15) < 1e-9  # 仍是 04-30 期
    assert semi5["profit_growth_ttm"] == 0.12

    # 财务事实与方向中性（未传 direction_map → 全 50）
    assert frame["direction_score"].unique().to_list() == [50.0]
    assert frame["revenue_growth_ttm"].is_not_null().any()
    # 拥挤度：成交额截面分位（3 行业非空）
    assert frame["crowding_score"].is_not_null().all()


def test_industry_l2_panel_direction_map() -> None:
    """传入 direction_map（global_resonance_l2_map）时方向层应替换中性 50，缺失回退中性。"""
    direction_map = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 3), date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 4)],
            "industry_code": ["270100", "710100", "270100", "710100"],
            "direction_score": [80.0, 60.0, 85.0, 55.0],
        }
    )
    frame = build_industry_l2_panel_frame(
        _l2_daily_panel_input(), _l2_financial_input(), direction_map=direction_map
    )
    assert not frame.is_empty()
    assert frame["direction_score"].unique().to_list() != [50.0]

    # 08-03：270100 → 80（映射），710100 → 60（映射），630500 无映射 → 中性 50
    d3 = frame.filter(pl.col("trade_date") == date(2026, 8, 3)).to_pandas()

    def get_score(code: str) -> float:
        return float(d3[d3["industry_code"] == code].iloc[0]["direction_score"])

    assert get_score("270100") == 80.0
    assert get_score("710100") == 60.0
    assert get_score("630500") == 50.0  # 缺失回退中性

    # 08-05：direction_map 无该日 → 全部回退中性 50
    d5 = frame.filter(pl.col("trade_date") == date(2026, 8, 5))
    assert d5["direction_score"].unique().to_list() == [50.0]


def test_industry_l2_panel_cutoff_and_empty() -> None:
    """增量 cutoff 只输出指定日期之后；空输入返回空面板。"""
    frame = build_industry_l2_panel_frame(
        _l2_daily_panel_input(), _l2_financial_input(), percentile_cutoff=date(2026, 8, 4)
    )
    assert not frame.is_empty()
    assert frame["trade_date"].min() == date(2026, 8, 4)

    assert build_industry_l2_panel_frame(pl.DataFrame(), _l2_financial_input()).is_empty()
    assert build_industry_l2_panel_frame(pl.DataFrame(), pl.DataFrame()).columns == list(
        empty_industry_l2_panel().columns
    )


def test_industry_l2_panel_no_financial_neutral() -> None:
    """无财务数据时供需/议价权中性、方向中性，仅输出行情/动量/拥挤度。"""
    frame = build_industry_l2_panel_frame(_l2_daily_panel_input(), pl.DataFrame())
    assert not frame.is_empty()
    assert frame.columns == list(empty_industry_l2_panel().columns)
    assert frame["supply_demand_score"].unique().to_list() == [50.0]
    assert frame["bargaining_score"].unique().to_list() == [30.0]
    assert frame["direction_score"].unique().to_list() == [50.0]
    assert frame["revenue_growth_ttm"].null_count() == frame.height


# --------------------------------------------------------------------------- #
# unlock_pressure
# --------------------------------------------------------------------------- #


def _share_float() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": [
                "600000.SH",
                "600000.SH",
                "600001.SH",
                "600002.SH",
            ],
            "float_date": [
                date(2026, 8, 3),
                date(2026, 8, 3),
                date(2026, 8, 3),
                date(2026, 8, 8),  # 周六，非交易日，close 应顺延至 08-07
            ],
            "float_share": [10_000_000.0, 20_000_000.0, 50_000_000.0, 1_000_000.0],  # 股
            "float_ratio": [1.0, 2.0, 5.0, 0.5],  # %
        }
    )


def _daily_close() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["600000.SH", "600001.SH", "600002.SH"],
            "trade_date": [date(2026, 8, 3), date(2026, 8, 3), date(2026, 8, 7)],
            "close": [10.0, 8.0, 20.0],
        }
    )


def test_unlock_pressure_amount_asof_and_large() -> None:
    frame = build_unlock_pressure_frame(_share_float(), _daily_close(), large_threshold=2e8)
    assert not frame.is_empty()
    assert frame.columns == list(empty_unlock_pressure().columns)
    row_3 = frame.filter(pl.col("trade_date") == date(2026, 8, 3)).to_pandas().iloc[0]
    assert row_3["unlock_count"] == 2
    assert row_3["unlock_batch_count"] == 3
    assert abs(row_3["unlock_share_amount"] - 80_000_000.0) < 1e-6
    # 3000 万股 × 10 + 5000 万股 × 8 = 7 亿元
    assert abs(row_3["unlock_amount"] - 700_000_000.0) < 1e-6
    # 大额（≥2 亿元）：600000 3 亿、600001 4 亿
    assert row_3["large_unlock_count"] == 2
    assert abs(row_3["avg_float_ratio"] - (1.0 + 2.0 + 5.0) / 3.0) < 1e-9
    assert abs(row_3["max_float_ratio"] - 5.0) < 1e-9
    # 非交易日顺延：08-08（周六）取 08-07 收盘价 20 元 → 100 万股 × 20 = 2000 万元
    row_8 = frame.filter(pl.col("trade_date") == date(2026, 8, 8)).to_pandas().iloc[0]
    assert abs(row_8["unlock_amount"] - 20_000_000.0) < 1e-6
    assert row_8["unlock_count"] == 1


def test_unlock_pressure_missing_close_excluded_from_amount() -> None:
    """无当日行情的批次不计入市值，但家数与股数统计不受影响。"""
    share_float = _share_float().filter(pl.col("symbol") == "600000.SH")
    close = _daily_close().filter(pl.col("symbol") == "600000.SH")
    # 000001.SH 无行情 -> 该批金额为 null
    frame = build_unlock_pressure_frame(
        pl.concat(
            [
                share_float,
                pl.DataFrame(
                    {
                        "symbol": ["600001.SH"],
                        "float_date": [date(2026, 8, 3)],
                        "float_share": [50_000_000.0],
                        "float_ratio": [5.0],
                    }
                ),
            ]
        ),
        close,
    )
    row = frame.filter(pl.col("trade_date") == date(2026, 8, 3)).to_pandas().iloc[0]
    assert row["unlock_count"] == 2
    assert row["unlock_batch_count"] == 3
    assert abs(row["unlock_share_amount"] - 80_000_000.0) < 1e-6
    # 仅 600000 两批可计价：3000 万股 × 10 = 3 亿元
    assert abs(row["unlock_amount"] - 300_000_000.0) < 1e-6


def test_unlock_pressure_no_close_prices() -> None:
    """完全无 close 输入时金额保持缺失，其余列仍输出（null 合法）。"""
    frame = build_unlock_pressure_frame(_share_float(), pl.DataFrame())
    assert not frame.is_empty()
    row = frame.filter(pl.col("trade_date") == date(2026, 8, 3)).to_pandas().iloc[0]
    assert row["unlock_count"] == 2
    assert row["unlock_amount"] is None or row["unlock_amount"] != row["unlock_amount"]


def test_unlock_pressure_empty() -> None:
    assert build_unlock_pressure_frame(pl.DataFrame(), _daily_close()).is_empty()
    assert build_unlock_pressure_frame(pl.DataFrame(), pl.DataFrame()).columns == list(
        empty_unlock_pressure().columns
    )


def test_unlock_pressure_zero_fills_explicit_window_without_events() -> None:
    close = pl.DataFrame(
        {
            "symbol": ["600000.SH"] * 2,
            "trade_date": [date(2026, 8, 4), date(2026, 8, 5)],
            "close": [10.5, 11.0],
        }
    )
    frame = build_unlock_pressure_frame(
        pl.DataFrame(), close, start_date=date(2026, 8, 4), end_date=date(2026, 8, 5)
    )

    assert frame["trade_date"].to_list() == [date(2026, 8, 4), date(2026, 8, 5)]
    assert frame["unlock_count"].to_list() == [0, 0]
    assert frame["unlock_amount"].to_list() == [0.0, 0.0]


def test_unlock_pressure_zero_fill_for_trading_days_without_unlocks() -> None:
    """交易日历中无解禁事件的交易日应合规填充 0 值。"""
    share_float = pl.DataFrame(
        {
            "symbol": ["600000.SH"],
            "float_date": [date(2026, 8, 3)],
            "float_share": [10_000_000.0],
            "float_ratio": [1.0],
        }
    )
    # 构造 3 个交易日：08-03 (有解禁), 08-04 (无解禁), 08-05 (无解禁)
    close = pl.DataFrame(
        {
            "symbol": ["600000.SH"] * 3,
            "trade_date": [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)],
            "close": [10.0, 10.5, 11.0],
        }
    )
    frame = build_unlock_pressure_frame(share_float, close)
    assert len(frame) == 3
    # 08-03 有解禁
    row_3 = frame.filter(pl.col("trade_date") == date(2026, 8, 3)).to_pandas().iloc[0]
    assert row_3["unlock_count"] == 1
    assert abs(row_3["unlock_share_amount"] - 10_000_000.0) < 1e-6

    # 08-04 无解禁，应全为 0
    row_4 = frame.filter(pl.col("trade_date") == date(2026, 8, 4)).to_pandas().iloc[0]
    assert row_4["unlock_count"] == 0
    assert row_4["unlock_batch_count"] == 0
    assert row_4["unlock_share_amount"] == 0.0
    assert row_4["unlock_amount"] == 0.0
    assert row_4["large_unlock_count"] == 0
    assert row_4["avg_float_ratio"] == 0.0
    assert row_4["max_float_ratio"] == 0.0


# --------------------------------------------------------------------------- #
# northbound_industry
# --------------------------------------------------------------------------- #


def _hk_hold() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "trade_date": [
                date(2026, 8, 3),
                date(2026, 8, 3),
                date(2026, 8, 3),
                date(2026, 8, 4),
                date(2026, 8, 4),
            ],
            "symbol": [
                "600000.SH",
                "600001.SH",
                "00700.HK",  # 港股通南向，应被过滤
                "600000.SH",
                "600001.SH",
            ],
            "vol": [10_000_000.0, 20_000_000.0, 50_000_000.0, 10_000_000.0, 20_000_000.0],
            "ratio": [1.0, 2.0, 3.0, 1.0, 2.0],
        }
    )


def _sw_constituents() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "con_code": ["600000.SH", "600001.SH"],
            "index_code": ["801010.SI", "801020.SI"],
            "in_date": [date(2019, 1, 1), date(2019, 1, 1)],
            "out_date": [None, date(2026, 8, 3)],  # 600001 于 08-03 剔除
        }
    )


def _sw_l1() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["801010.SI", "801020.SI"],
            "industry_code": ["610000", "620000"],
            "name": ["农林牧渔", "食品饮料"],
        }
    )


def _northbound_close() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["600000.SH", "600001.SH"] * 2,
            "trade_date": [
                date(2026, 8, 3),
                date(2026, 8, 3),
                date(2026, 8, 4),
                date(2026, 8, 4),
            ],
            "close": [10.0, 5.0, 11.0, 6.0],
        }
    )


def test_northbound_industry_aggregation_and_filter() -> None:
    frame = build_northbound_industry_frame(
        _hk_hold(), _sw_constituents(), _sw_l1(), _northbound_close()
    )
    assert not frame.is_empty()
    assert frame.columns == list(empty_northbound_industry().columns)
    row_3 = frame.filter(pl.col("trade_date") == date(2026, 8, 3))
    assert row_3.height == 2
    row_610000 = row_3.filter(pl.col("industry_code") == "610000").to_pandas().iloc[0]
    assert row_610000["industry_name"] == "农林牧渔"
    assert row_610000["hold_symbol_count"] == 1
    assert abs(row_610000["hold_share_amount"] - 10_000_000.0) < 1e-6
    assert abs(row_610000["hold_value"] - 100_000_000.0) < 1e-6  # 1000 万股 × 10
    # 港股权重不进入；两行业各占 1 亿 / 总 2 亿 = 50%
    assert abs(row_610000["hold_value_pct"] - 50.0) < 1e-6

    # 08-04：600001 已剔除（out_date<=08-04）不再属于食品饮料
    row_4 = frame.filter(pl.col("trade_date") == date(2026, 8, 4))
    assert row_4["industry_code"].to_list() == ["610000"]
    row_4_610000 = row_4.to_pandas().iloc[0]
    assert abs(row_4_610000["hold_value"] - 110_000_000.0) < 1e-6
    assert abs(row_4_610000["hold_value_chg"] - 10_000_000.0) < 1e-6
    assert abs(row_4_610000["hold_value_pct_chg"] - 10.0) < 1e-6


def test_northbound_industry_a_share_filter_only() -> None:
    """全部为港股时输出为空（不伪造 A 股行业持仓）。"""
    hk = _hk_hold().filter(pl.col("symbol") == "00700.HK")
    frame = build_northbound_industry_frame(hk, _sw_constituents(), _sw_l1(), _northbound_close())
    assert frame.is_empty()
    assert frame.columns == list(empty_northbound_industry().columns)


def test_northbound_industry_empty() -> None:
    assert build_northbound_industry_frame(
        pl.DataFrame(), _sw_constituents(), _sw_l1(), _northbound_close()
    ).is_empty()
    assert build_northbound_industry_frame(
        pl.DataFrame(), pl.DataFrame(), pl.DataFrame(), pl.DataFrame()
    ).columns == list(empty_northbound_industry().columns)
