"""financial_ttm_rebuild 差分重建 TTM 的单元测试。"""

from __future__ import annotations

import polars as pl

from stock_analytics.marts.shared.industry_structure.financial_ttm_rebuild import (
    FINANCIAL_TTM_SCHEMA,
    PROFIT_SOURCE_COL,
    REVENUE_SOURCE_COL,
    _rebuild_ttm_from_cumulative,
    expand_financial_with_ttm_rebuild,
)


def _make_frame(
    *,
    toi_t: list[float | None] | None = None,
    ttm_y2y: list[float | None] | None = None,
    c_y2y: list[float | None] | None = None,
    include_gp: bool = True,
) -> pl.DataFrame:
    """构造理杏仁 L3 财务帧（单行业 110101，8 期：2021Q1..2022FY）。"""
    n = 8
    stds = [
        "2021-03-30T00:00:00+08:00",
        "2021-06-29T00:00:00+08:00",
        "2021-09-29T00:00:00+08:00",
        "2021-12-30T00:00:00+08:00",
        "2022-03-30T00:00:00+08:00",
        "2022-06-29T00:00:00+08:00",
        "2022-09-29T00:00:00+08:00",
        "2022-12-30T00:00:00+08:00",
    ]
    types = [
        "first_quarterly_report",
        "interim_report",
        "third_quarterly_report",
        "annual_report",
        "first_quarterly_report",
        "interim_report",
        "third_quarterly_report",
        "annual_report",
    ]
    # 默认 YTD 累计值（Q1 起递增，模拟源端 t 语义）
    default_t = [100.0, 220.0, 340.0, 480.0, 110.0, 250.0, 400.0, 560.0]
    default_ttm = [0.05, 0.06, 0.07, 0.08, 0.10, 0.11, 0.12, 0.13]
    default_c = [0.04, 0.05, 0.06, 0.07, 0.09, 0.10, 0.11, 0.12]

    toi_t = default_t if toi_t is None else toi_t
    ttm_y2y = default_ttm if ttm_y2y is None else ttm_y2y
    c_y2y = default_c if c_y2y is None else c_y2y

    q_rows = []
    for i in range(n):
        toi = {"t": toi_t[i], "ttm_y2y": ttm_y2y[i], "c_y2y": c_y2y[i]}
        np_ = {"t": toi_t[i], "ttm_y2y": ttm_y2y[i], "c_y2y": c_y2y[i]}
        ps = {"toi": toi, "np": np_}
        if include_gp:
            ps["gp_m"] = {"ttm": 0.30}
        q_rows.append({"ps": ps, "m": {"roe": {"ttm": 0.10}}})

    return pl.DataFrame(
        {
            "reportDate": [
                "2021-04-29T00:00:00+08:00",
                "2021-08-27T00:00:00+08:00",
                "2021-10-29T00:00:00+08:00",
                "2022-04-28T00:00:00+08:00",
                "2022-04-28T00:00:00+08:00",
                "2022-08-29T00:00:00+08:00",
                "2022-10-28T00:00:00+08:00",
                "2023-04-28T00:00:00+08:00",
            ],
            "symbol": ["110101"] * n,
            "reportType": types,
            "standardDate": stds,
            "q": q_rows,
        }
    )


def test_rebuild_from_cumulative_matches_official() -> None:
    """官方 ttm_y2y 非缺失时，t 差分重建值应与官方完全一致（0 差）。"""
    frame = _make_frame()
    rebuilt, precise = _rebuild_ttm_from_cumulative(frame, "toi")
    # 8 期数据：只有最后 1 期（2022FY）同时具备 TTM 分子（前 4 期单季和）
    # 与分母（再前 4 期单季和）→ 仅该期可精确重建
    assert precise.sum() == 1
    assert precise[7]
    # 2022FY: 单季 2021Q1..2022FY = 100,120,120,140,110,140,150,160
    # TTM(2022FY) = 110+140+150+160 = 560；TTM(2021FY) = 100+120+120+140 = 480
    assert abs(rebuilt[7] - (560 / 480 - 1)) < 1e-9
    # 前 7 期无完整分母 → null
    assert rebuilt[:7].null_count() == 7


def test_rebuild_uses_absolute_negative_ttm_base() -> None:
    """负基数时对齐理杏仁的 (本期-上期) / abs(上期) 口径。"""
    frame = _make_frame(
        toi_t=[-100, -200, -300, -400, 100, 200, 300, 400],
        ttm_y2y=[None] * 8,
    )
    rebuilt, _ = _rebuild_ttm_from_cumulative(frame, "toi")

    assert rebuilt[7] == 2.0


def test_expand_official_priority_and_sources() -> None:
    """official 优先：ttm_y2y 非空时直接采用并标记 official。"""
    frame = _make_frame()
    out = expand_financial_with_ttm_rebuild(frame)
    assert out.columns == list(FINANCIAL_TTM_SCHEMA)
    assert out.height == 8
    assert out[REVENUE_SOURCE_COL].to_list() == ["official"] * 8
    assert out[PROFIT_SOURCE_COL].to_list() == ["official"] * 8
    # official 值原样保留
    assert out["revenue_growth_ttm"][0] == 0.05
    assert out["gross_margin_ttm"][0] == 0.30


def test_expand_derived_when_official_missing() -> None:
    """ttm_y2y 缺失时用 t 差分重建并标记 derived。"""
    ttm = [None] * 8
    frame = _make_frame(ttm_y2y=ttm)
    out = expand_financial_with_ttm_rebuild(frame)
    # 仅最后 1 期（2022FY）有完整去年同期 → derived；其余走 proxy
    sources = out[REVENUE_SOURCE_COL].to_list()
    assert sources[:7] == ["proxy"] * 7
    assert sources[7] == "derived"
    # 2022FY 重建值 = TTM(2022FY)/TTM(2021FY) - 1 = 560/480 - 1
    assert abs(out["revenue_growth_ttm"][7] - (560 / 480 - 1)) < 1e-9


def test_expand_proxy_when_t_missing() -> None:
    """t 也缺失时用 c_y2y 四期滚动均值并标记 proxy。"""
    frame = _make_frame(ttm_y2y=[None] * 8, toi_t=[None] * 8)
    out = expand_financial_with_ttm_rebuild(frame)
    sources = out[REVENUE_SOURCE_COL].to_list()
    assert sources == ["proxy"] * 8
    # c_y2y 四期滚动均值：前 3 期 null（min_samples=4），第 4 期起 = mean(0.04..0.07)
    vals = out["revenue_growth_ttm"].to_list()
    assert vals[0] is None and vals[1] is None and vals[2] is None
    assert abs(vals[3] - (0.04 + 0.05 + 0.06 + 0.07) / 4) < 1e-9


def test_expand_bank_without_gp_m() -> None:
    """银行源无 gp_m 字段 → 毛利率 null，不报错。"""
    frame = _make_frame(include_gp=False)
    out = expand_financial_with_ttm_rebuild(frame)
    assert out["gross_margin_ttm"].null_count() == 8


def test_expand_empty_frame() -> None:
    """空帧返回稳定 schema。"""
    frame = pl.DataFrame(schema={"reportDate": pl.Date, "symbol": pl.Utf8, "q": pl.Object})
    out = expand_financial_with_ttm_rebuild(frame)
    assert out.height == 0
    assert out.columns == list(FINANCIAL_TTM_SCHEMA)
