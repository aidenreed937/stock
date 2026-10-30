"""SEAJ 爬虫与 PDF 解析器单元测试。"""

from datetime import date

from stock_data.fetcher.industry.semiconductor.parsers import (
    parse_seaj_historical_xls,
    parse_seaj_pdf_text,
)


def test_seaj_pdf_parser_basic() -> None:
    # 模拟真实 SEAJ 官方速报 PDF 文本流
    sample_text = """
日本製 半導体製造装置 2026 年 7 月度の販売高は 556,220 百万円
単位：百万円
販売 (3 ヶ月平均) 前月比 (％) 前年比 (％)
2026/2 423,103 -1.0% 2.7%
2026/3 480,182 13.5% 11.1%
2026/4 510,155 6.2% 14.1%
2026/5 526,352 3.2% 17.9%
2026/6(確定値) 513,610 -2.4% 26.9%
2026/7(暫定値) 556,220 8.3% 35.4%
    """

    rows = parse_seaj_pdf_text(sample_text, release_date=date(2026, 8, 21))
    assert len(rows) == 1
    latest = rows[-1]
    assert latest["report_month"] == "2026-07"
    assert latest["sales_3mma_raw"] == "556,220"
    assert latest["mom_growth_3mma_raw"] == "8.3%"
    assert latest["yoy_growth_3mma_raw"] == "35.4%"
    assert latest["billings_3mma_jpy"] == 556.22
    assert "billings_jpy_billion" not in latest
    assert latest["mom_growth_3mma"] == 0.083
    assert latest["yoy_growth_3mma"] == 0.354
    assert latest["release_date"] == date(2026, 8, 21)
    assert "yoy_growth" not in latest


def test_seaj_historical_xls_parser_keeps_source_3mma_values(monkeypatch) -> None:
    import pandas as pd

    frame = pd.DataFrame(
        [
            ["Year", "Month", None, None, "Billings", "Growth"],
            [2025, 1, None, None, 416789.6666666667, 0.3236656624],
            [None, "2R", None, None, 412065.0, 0.2981791604],
            [2026, 1, None, None, 427507.6666666667, 0.0257156088],
            [None, 2, None, None, None, None],
        ]
    )
    monkeypatch.setattr(pd, "read_excel", lambda *args, **kwargs: frame)

    rows = parse_seaj_historical_xls(b"xls", start_year=2025, end_year=2026)

    assert [row["report_month"] for row in rows] == ["2025-01", "2025-02", "2026-01"]
    assert rows[0]["billings_3mma_jpy"] == 416.79
    assert rows[0]["yoy_growth_3mma"] == 0.3237
    assert rows[0]["sales_3mma_raw"] == str(frame.iloc[1, 4])
    assert rows[1]["report_month"] == "2025-02"
