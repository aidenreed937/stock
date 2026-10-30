"""台积电月度营收采集器 (TsmcLeadCollector) 与英文年度 HTML 解析测试 (纯 Mock/无网络)。"""

from __future__ import annotations

import gzip
import re
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import polars as pl

from stock_data.fetcher.industry.semiconductor.collectors.tsmc import (
    TsmcLeadCollector,
    _next_month_release_date,
)
from stock_data.fetcher.industry.semiconductor.lineage import raw_content_sha256
from stock_data.fetcher.industry.semiconductor.models import SemiconductorLeadRecord
from stock_data.fetcher.industry.semiconductor.parsers import (
    parse_tsmc_monthly_revenue_html,
)
from stock_data.fetcher.industry.semiconductor.paths import TSMC_MONTHLY_HTML_FILENAME
from stock_data.fetcher.industry.semiconductor.schemas import SEMICONDUCTOR_LEAD_RAW_SCHEMA
from stock_data.fetcher.industry.semiconductor.transforms import records_to_semiconductor_lead_frame
from stock_data.fetcher.industry.semiconductor.transforms.lead import _is_consecutive_month


def _year_html(year: int, years: list[int]) -> str:
    """构造含多个目标年度 article 的年度页面片段。"""
    articles = []
    for y in years:
        articles.append(
            f'<article id="tab-{y}"><table class="basicTable"><tr><th>Month</th>'
            "<th>Net Revenue</th><th>YoY Change</th></tr>"
            "<tr><td><div>Jan.</div></td><td>20,000</td><td>20%</td></tr>"
            "<tr><td><div>Feb.</div></td><td>25,000</td><td>30%</td></tr>"
            "<tr><td><div>Mar.</div></td><td>30,000</td><td>15%</td></tr>"
            f"</table></article>"
        )
    return f"<html><body><h3>{year} Monthly Revenue</h3>{''.join(articles)}</body></html>"


def test_tsmc_parser_handles_multi_year_and_year_arg() -> None:
    html = (
        '<article id="tab-2024"><table class="basicTable">'
        "<tr><th>Month</th><th>Net Revenue</th><th>YoY</th></tr>"
        "<tr><td><div>Dec.</div></td><td>9,999</td><td>9%</td></tr></table></article>"
        '<article id="tab-2025"><table class="basicTable">'
        "<tr><th>Month</th><th>Net Revenue</th><th>YoY</th></tr>"
        "<tr><td><div>Jan.</div></td><td>20,000</td><td>20%</td></tr></table></article>"
    )
    parsed_2025 = parse_tsmc_monthly_revenue_html(html, year=2025)
    assert parsed_2025 == [
        {
            "report_month": "2025-01",
            "tsmc_revenue_ntd_million": 20000.0,
            "tsmc_revenue_yoy": 0.2,
            "month_raw": "Jan.",
            "net_revenue_raw": "20,000",
            "yoy_change_raw": "20%",
        }
    ]


def test_tsmc_collector_live_mock_builds_records_and_archives(tmp_path: Path, monkeypatch) -> None:
    """在线采集: 逐年拉取 HTML 构建月度闭环记录并 Gzip 归档原始快照。"""

    def on_get(url, **kwargs):
        year = int(re.search(r"/monthly-revenue/(\d+)$", url).group(1))
        resp = MagicMock()
        resp.status_code = 200
        resp.text = _year_html(year, [year])
        return resp

    from datetime import date as _date

    start_year = _date.today().year
    with patch(
        "stock_data.fetcher.industry.semiconductor.collectors.tsmc.requests.get",
        side_effect=on_get,
    ) as mocked_get:
        monkeypatch.setattr(
            "stock_data.fetcher.industry.semiconductor.collectors.tsmc.START_YEAR",
            start_year,
        )
        records = TsmcLeadCollector(raw_dir=tmp_path / "raw").collect()

    assert len(records) == 3
    assert records[0].report_month == f"{start_year}-01"
    assert records[0].trade_date == date(start_year, 1, 31)
    assert records[0].tsmc_revenue_ntd_million == 20000.0
    assert records[0].tsmc_revenue_yoy == 0.2
    assert records[0].tsmc_revenue_mom is None
    assert records[0].release_date == date(start_year, 2, 10)
    assert records[0].source_url.endswith(f"/monthly-revenue/{start_year}")
    assert records[0].raw_content_sha256 == raw_content_sha256(
        _year_html(start_year, [start_year]).encode("utf-8")
    )
    assert records[0].raw_snapshot_path == (
        f"semiconductor/tsmc/{TSMC_MONTHLY_HTML_FILENAME.format(year=start_year)}"
    )

    # Collector 不计算派生 MoM；首月、次月和第三月均保持空值。
    assert records[0].tsmc_revenue_mom is None
    assert records[1].tsmc_revenue_mom is None
    assert records[2].tsmc_revenue_mom is None

    # 仅消费当前年一个年度页面
    assert mocked_get.call_count == 1

    # 原始 HTML 已 Gzip 归档到 {raw_root}/semiconductor/tsmc/ 供对账校验
    snapshot = (
        tmp_path
        / "raw"
        / "semiconductor"
        / "tsmc"
        / TSMC_MONTHLY_HTML_FILENAME.format(year=start_year)
    )
    assert snapshot.exists()
    with gzip.open(snapshot, "rt", encoding="utf-8") as f:
        assert f"tab-{start_year}" in f.read()

    # 结构化 RAW 表可经 raw_transform 产出
    from stock_data.fetcher.industry.semiconductor.transforms import (
        records_to_raw_semiconductor_lead_frame,
    )

    raw_df = records_to_raw_semiconductor_lead_frame(records)
    assert raw_df.height == 3
    assert raw_df.columns == list(SEMICONDUCTOR_LEAD_RAW_SCHEMA)
    assert raw_df["net_revenue_raw"].to_list() == ["20,000", "25,000", "30,000"]
    assert raw_df["yoy_change_raw"].to_list() == ["20%", "30%", "15%"]
    assert raw_df["raw_content_sha256"].to_list() == [records[0].raw_content_sha256] * 3
    assert raw_df["raw_snapshot_path"].to_list() == [records[0].raw_snapshot_path] * 3
    assert sorted(raw_df["report_month"].to_list()) == [
        f"{start_year}-01",
        f"{start_year}-02",
        f"{start_year}-03",
    ]


def test_tsmc_collector_skips_failed_year_pages(tmp_path: Path, monkeypatch) -> None:
    """单个年度页面抓取失败时跳过，不影响其余年份。"""

    def on_get(url, **kwargs):
        year = int(re.search(r"/monthly-revenue/(\d+)$", url).group(1))
        resp = MagicMock()
        if year == 2014:
            resp.status_code = 500
            return resp
        resp.status_code = 200
        resp.text = _year_html(year, [year])
        return resp

    with patch(
        "stock_data.fetcher.industry.semiconductor.collectors.tsmc.requests.get",
        side_effect=on_get,
    ):
        monkeypatch.setattr(
            "stock_data.fetcher.industry.semiconductor.collectors.tsmc.START_YEAR", 2014
        )
        records = TsmcLeadCollector(raw_dir=tmp_path / "raw").collect()

    # 2014 抓取失败跳过, 2015 起逐年成功 (至少包含 2015)
    assert len(records) >= 3
    assert records[0].report_month == "2015-01"


def test_tsmc_release_date_is_next_month_tenth() -> None:
    assert _next_month_release_date("2025-01") == date(2025, 2, 10)


def test_tsmc_collector_limits_year_pages_and_months(tmp_path: Path, monkeypatch) -> None:
    calls: list[int] = []

    def on_get(url, **kwargs):
        year = int(re.search(r"/monthly-revenue/(\d+)$", url).group(1))
        calls.append(year)
        response = MagicMock()
        response.status_code = 200
        response.text = _year_html(year, [year])
        return response

    with patch(
        "stock_data.fetcher.industry.semiconductor.collectors.tsmc.requests.get",
        side_effect=on_get,
    ):
        records = TsmcLeadCollector(raw_dir=tmp_path / "raw").collect(
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 28),
        )

    assert calls == [2026]
    assert [record.report_month for record in records] == ["2026-02"]


def test_tsmc_incremental_transform_keeps_history_and_recomputes_mom() -> None:
    existing = records_to_semiconductor_lead_frame(
        [
            SemiconductorLeadRecord("2026-07", date(2026, 7, 31), 1000.0, 100.0),
            SemiconductorLeadRecord("2026-08", date(2026, 8, 31), 1200.0, 120.0),
        ]
    )
    incremental = records_to_semiconductor_lead_frame(
        [SemiconductorLeadRecord("2026-09", date(2026, 9, 30), 1500.0, 150.0)],
        existing_df=existing,
    )

    assert incremental.height == 3
    assert incremental.filter(pl.col("report_month") == "2026-09")["tsmc_revenue_mom"][0] == 0.25
    assert _next_month_release_date("2025-12") == date(2026, 1, 10)


def test_tsmc_consecutive_month_check() -> None:
    assert _is_consecutive_month("2025-01", "2025-02") is True
    assert _is_consecutive_month("2025-12", "2026-01") is True
    assert _is_consecutive_month("2025-01", "2025-03") is False
    assert _is_consecutive_month("2025-02", "2024-03") is False


def test_tsmc_collector_empty_when_no_http(tmp_path: Path, monkeypatch) -> None:
    """无网络返回时安全返回空列表。"""
    with patch(
        "stock_data.fetcher.industry.semiconductor.collectors.tsmc.requests.get",
        side_effect=RuntimeError("network down"),
    ):
        monkeypatch.setattr(
            "stock_data.fetcher.industry.semiconductor.collectors.tsmc.START_YEAR", 2099
        )
        records = TsmcLeadCollector(raw_dir=tmp_path / "raw").collect()
    assert records == []
