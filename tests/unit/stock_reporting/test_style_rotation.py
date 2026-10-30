"""风格轮动观察段落：指标计算与日报挂载单元测试。"""

from datetime import date, timedelta

import polars as pl

import stock_reporting.templates.macro_risk_report as macro_risk_report
from stock_reporting.interpretation.macro_risk.style_rotation import (
    compute_style_rotation,
    render_style_rotation_section,
)


def _synthetic_bars() -> pl.DataFrame:
    """合成约 400 行日频行情：创业板稳步走强 > 中证全指 > 中证红利（行移位口径即可）。"""
    n = 400
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n)]
    rows = []
    for sym, drift in (("000985.CSI", 1.0005), ("399006.SZ", 1.001), ("000922.CSI", 1.0001)):
        rows.extend(
            {
                "symbol": sym,
                "trade_date": d,
                "close": 100.0 * drift**i,
                "volume": 1.0e8,
                "amount": 1.0e9 * (1.0 + 0.001 * i),
            }
            for i, d in enumerate(dates)
        )
    return pl.DataFrame(rows)


def test_compute_style_rotation_synthetic() -> None:
    bars = _synthetic_bars()
    computed = compute_style_rotation(bars)
    assert computed is not None
    sc = computed["scissors"]
    # 创业板累计收益/红利累计收益 > 1 且走扩
    assert sc["ratio"] > 1.0
    assert sc["sc12"] is not None and sc["sc12"] > 0
    assert sc["delta"] is not None
    metrics = computed["metrics"]
    # 创业板动量强于红利
    assert metrics["399006.SZ"]["r60"] > metrics["000922.CSI"]["r60"] > 0
    # 常量递增成交额在样本内处于高分位
    assert metrics["399006.SZ"]["amt_pct"] >= 50
    assert computed["as_of"] == str(bars["trade_date"].max())


def test_render_style_rotation_section_contains_headers() -> None:
    computed = compute_style_rotation(_synthetic_bars())
    assert computed is not None
    md = render_style_rotation_section(computed)
    assert "## 风格轮动观察" in md
    assert "剪刀差（创业板指 vs 中证红利）" in md
    assert "三指数速度/加速度/量价" in md
    assert "中证全指" in md and "创业板指" in md and "中证红利" in md
    assert "非 v5 信号" in md


def test_render_appends_style_section(monkeypatch) -> None:
    """宏观日报渲染后自动追加风格轮动段落（挂载点 hermetic 验证）。"""
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 28)],
            "overheat_index": [69.2],
            "panic_index": [33.9],
            "dim_valuation": [47.2],
            "dim_leverage": [84.9],
            "dim_fear": [28.8],
            "dim_crowding": [78.4],
            "dim_breadth": [37.0],
            "dim_flow": [35.7],
        }
    )
    monkeypatch.setattr(
        macro_risk_report, "build_style_rotation_section", lambda d: "TEST_STYLE_SECTION_MARKER"
    )
    md = macro_risk_report.render_macro_risk_report(df, date(2026, 8, 28))
    assert "TEST_STYLE_SECTION_MARKER" in md
