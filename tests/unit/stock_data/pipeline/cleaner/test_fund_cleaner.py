"""基金持仓占比取值域清洗测试。"""

import polars as pl

from stock_data.pipeline.cleaner.fund_cleaner import sanitize_fund_portfolio_ratios


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "fund_code": ["005827.OF", "005827.OF", "005827.OF", "110011.OF"],
            "symbol": ["600519.SH", "000568.SZ", "600809.SH", "600519.SH"],
            "stk_mkv_ratio": [10.43, 100.02, 101.5, -1.0],
            "stk_float_ratio": [0.2, 99.9, 130.0, 1.5],
        }
    )


def test_out_of_range_ratio_is_nulled_not_dropped() -> None:
    out = sanitize_fund_portfolio_ratios(_frame())

    assert out.height == 4  # 不丢整条持仓记录
    assert out["stk_float_ratio"].to_list() == [0.2, 99.9, None, 1.5]
    assert out["stk_mkv_ratio"].to_list()[0] == 10.43
    # 101.5 > 100.5 视为异常；-1.0 视为异常
    assert out["stk_mkv_ratio"].to_list()[2] is None
    assert out["stk_mkv_ratio"].to_list()[3] is None


def test_rounding_within_tolerance_is_kept() -> None:
    """年报全持仓加总存在 100.02 这类四舍五入，必须在容差内保留。"""
    out = sanitize_fund_portfolio_ratios(_frame())

    assert out["stk_mkv_ratio"].to_list()[1] == 100.02


def test_empty_frame_and_missing_columns_are_safe() -> None:
    assert sanitize_fund_portfolio_ratios(pl.DataFrame()).is_empty()

    partial = pl.DataFrame({"symbol": ["600519.SH"], "stk_float_ratio": [130.0]})
    out = sanitize_fund_portfolio_ratios(partial)
    assert out["stk_float_ratio"].to_list() == [None]
