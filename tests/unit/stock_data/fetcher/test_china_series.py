"""semiconductor_china_series 推算引擎单元测试。"""

from __future__ import annotations

import polars as pl

from stock_data.fetcher.industry.semiconductor.china_series import (
    build_china_series,
    parse_sia_china_enriched,
)


def _mk_record(month: str, yoy: float | None = None, mom: float | None = None) -> dict:
    return {
        "report_month": month,
        "china_yoy_growth": yoy,
        "china_mom_growth": mom,
        "china_sales_usd": None,
        "anchor_year": None,
        "china_year_sales_usd": None,
        "release_date": None,
        "source_url": f"http://test/{month}",
    }


def test_parse_sia_china_enriched_without_anchor() -> None:
    # 真实 SIA 新闻句式: 报告月由 "in <Month> <Year>" 识别, 增速由百分比 + China 关联识别
    html = (
        "WASHINGTON, Aug. 7, 2026 — Global semiconductor sales in June 2026 reached a record. "
        "Month-to-month sales increased in China (10.4%), Asia Pacific/All Other (9.8%), "
        "and the Americas (9.6%). Year-to-year sales in China (28.8%) also grew."
    )
    r = parse_sia_china_enriched(html, "http://test/1")
    assert r is not None
    assert r["report_month"] == "2026-06"
    assert r["china_yoy_growth"] == 0.288
    assert r["china_mom_growth"] == 0.104


def test_build_series_anchor_year_satisfies_total() -> None:
    """锚点年 12 个月推算合计必须严格等于年度 anchor。"""
    records = [_mk_record(f"2020-{mo:02d}", mom=0.01) for mo in range(1, 13)]
    records.append(
        {
            "report_month": "2021-01",
            "china_yoy_growth": 0.05,
            "china_mom_growth": 0.02,
            "china_sales_usd": None,
            "anchor_year": 2020,
            "china_year_sales_usd": 150.0,
            "release_date": None,
            "source_url": "http://test/anchor",
        }
    )
    df = build_china_series(records, start_month="2019-12", end_month="2021-02")
    assert not df.is_empty()
    year_2020 = df.filter(pl.col("report_month").str.slice(0, 4) == "2020")
    assert year_2020.height == 12
    total = year_2020["china_sales_usd"].sum()
    assert abs(total - 150.0) < 0.5
    # anchor 年不做 YoY 校准 (保持年合计约束)
    assert year_2020["calc_flag"].is_in(["anchor", "backward"]).all()


def test_build_series_forward_mom_chain() -> None:
    """未来段 MoM 链: month_k = month_{k-1} * (1+mom_k)。"""
    records = [
        _mk_record("2022-01", mom=0.0),
        _mk_record("2022-02", mom=0.10),
        _mk_record("2022-03", mom=0.05),
        {
            "report_month": "2023-01",
            "china_yoy_growth": 0.10,
            "china_mom_growth": 0.02,
            "china_sales_usd": None,
            "anchor_year": 2022,
            "china_year_sales_usd": 180.0,
            "release_date": None,
            "source_url": "http://test/anchor",
        },
        _mk_record("2023-02", mom=0.01),
    ]
    df = build_china_series(records, start_month="2022-01", end_month="2023-02")
    assert not df.is_empty()
    r = {row["report_month"]: row["china_sales_usd"] for row in df.to_dicts()}
    assert r["2022-01"] is not None and r["2023-02"] is not None
    # 2023-02 = 2023-01 * 1.01
    assert abs(r["2023-02"] / r["2023-01"] - 1.01) < 0.01


def test_build_series_empty_without_anchor() -> None:
    """无年度锚点时返回空帧。"""
    records = [_mk_record("2020-01", yoy=0.05, mom=0.01)]
    df = build_china_series(records)
    assert df.is_empty()
