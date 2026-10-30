"""芯片交付周期 (Chip Lead Time) 采集器、数据模型与任务包测试 (纯 Mock/无硬编码事实)。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import polars as pl

from stock_data.core.task_bundles import expand_task_targets
from stock_data.fetcher.industry import (
    CHIP_LEAD_TIME_SCHEMA,
    ChipLeadTimeCollector,
    empty_chip_lead_time,
    execute_single_industry_task,
    records_to_chip_lead_time_frame,
)
from stock_data.fetcher.industry.models import ChipLeadTimeRecord
from stock_data.fetcher.industry.semiconductor.collectors.susquehanna import (
    SusquehannaLeadTimeCollector,
)
from stock_data.fetcher.industry.semiconductor.lineage import raw_content_sha256
from stock_data.fetcher.industry.semiconductor.parsers import (
    aggregate_category_lead_times,
    is_valid_lead_time_weeks,
    parse_lead_time_string_to_weeks,
    parse_susquehanna_lead_time_article,
    parse_susquehanna_rss_feed,
)
from stock_data.fetcher.industry.semiconductor.transforms import (
    records_to_raw_chip_lead_time_frame,
)


def test_parse_lead_time_string() -> None:
    """验证分销商交期字符串解析。"""
    assert parse_lead_time_string_to_weeks("18 Weeks") == 18.0
    assert parse_lead_time_string_to_weeks("24.5 weeks") == 24.5
    assert parse_lead_time_string_to_weeks("70 Days") == 10.0
    assert parse_lead_time_string_to_weeks("12 周") == 12.0
    assert parse_lead_time_string_to_weeks("") is None


def test_lead_time_validity_filters_cap_and_zero() -> None:
    """0 天缺货标记与 >=52 周封顶值均不视为有效真实交期。"""
    assert is_valid_lead_time_weeks(10.0)
    assert is_valid_lead_time_weeks(51.9)
    assert not is_valid_lead_time_weeks(0.0)
    assert not is_valid_lead_time_weeks(52.0)
    assert not is_valid_lead_time_weeks(52.1)
    assert not is_valid_lead_time_weeks(None)


def test_aggregate_category_lead_times_excludes_dirty_values() -> None:
    """聚合时剔除 0 天与封顶 SKU，并重新归一化品类权重。"""
    sku_details = {
        "MCU_A": {"category": "mcu", "lead_time_weeks": 40.0, "lead_time_raw": "280 天数"},
        "MCU_B": {"category": "mcu", "lead_time_weeks": 8.6, "lead_time_raw": "60 天数"},
        "ANA_ZERO": {"category": "analog", "lead_time_weeks": 0.0, "lead_time_raw": "0 天数"},
        "ANA_OK": {"category": "analog", "lead_time_weeks": 9.0, "lead_time_raw": "63 天数"},
        "ANA_CAP": {"category": "analog", "lead_time_weeks": 52.1, "lead_time_raw": "365 天数"},
        "DIS_OK1": {"category": "discrete", "lead_time_weeks": 21.0, "lead_time_raw": "147 天数"},
        "DIS_OK2": {"category": "discrete", "lead_time_weeks": 26.0, "lead_time_raw": "182 天数"},
    }
    categories = {
        "mcu": {"weight": 0.25},
        "analog": {"weight": 0.30},
        "discrete": {"weight": 0.20},
        "compute": {"weight": 0.25},
    }
    cat_avg, avg_val, excluded = aggregate_category_lead_times(sku_details, categories)

    # analog 均值只由 ANA_OK 构成（0 天与封顶均剔除）
    assert cat_avg == {"mcu": 24.3, "analog": 9.0, "discrete": 23.5}
    expected = round((24.3 * 0.25 + 9.0 * 0.30 + 23.5 * 0.20) / 0.75, 2)
    assert avg_val == expected
    assert set(excluded) == {"ANA_ZERO", "ANA_CAP"}


def test_aggregate_category_lead_times_all_excluded_returns_empty() -> None:
    """全部 SKU 无效时聚合返回空，不生成记录。"""
    sku_details = {
        "A": {"category": "analog", "lead_time_weeks": 0.0, "lead_time_raw": "0 天数"},
        "D": {"category": "discrete", "lead_time_weeks": 52.0, "lead_time_raw": "364 天数"},
    }
    cat_avg, avg_val, excluded = aggregate_category_lead_times(sku_details)
    assert cat_avg == {}
    assert avg_val is None
    assert set(excluded) == {"A", "D"}


def test_parse_susquehanna_public_report_article() -> None:
    """只提取正文明确给出的报告月份与总交期。"""
    parsed = parse_susquehanna_lead_time_article(
        "Chip industry lead time continues to accelerate",
        "Susquehanna said lead times rose in June to 19.4 weeks.",
        "https://seekingalpha.com/news/test",
        date(2026, 7, 20),
    )

    assert parsed is not None
    assert parsed["report_month"] == "2026-06"
    assert parsed["avg_lead_time_weeks"] == 19.4
    assert parsed["release_date"] == date(2026, 7, 20)
    assert parsed["source"] == "Susquehanna/Seeking Alpha"


def test_parse_susquehanna_rss_feed_keeps_discovery_fields() -> None:
    feed = """
    <rss><channel><item>
      <title>Susquehanna lead time update</title>
      <link>https://seekingalpha.com/news/test</link>
      <pubDate>Mon, 20 Jul 2026 10:41:00 GMT</pubDate>
      <description><![CDATA[lead times in June reached 19.4 weeks]]></description>
      <source url="https://seekingalpha.com">Seeking Alpha</source>
    </item></channel></rss>
    """

    items = parse_susquehanna_rss_feed(feed)

    assert items == [
        {
            "title": "Susquehanna lead time update",
            "link": "https://seekingalpha.com/news/test",
            "description": "lead times in June reached 19.4 weeks",
            "pub_date": "Mon, 20 Jul 2026 10:41:00 GMT",
            "source": "Seeking Alpha",
        }
    ]


def test_susquehanna_collector_online_incremental_and_raw_lineage(
    tmp_path: Path,
) -> None:
    """在线抓取公开报道、按月份归档并返回源文档血缘。"""
    feed_url = "https://news.example.test/susquehanna.xml"
    article_url = "https://seekingalpha.com/news/test"
    feed = f"""
    <rss><channel><item>
      <title>Chip industry lead time continues to accelerate</title>
      <link>{article_url}</link>
      <pubDate>Mon, 20 Jul 2026 10:41:00 GMT</pubDate>
      <description>Susquehanna said lead times rose in June to 19.4 weeks.</description>
      <source url="https://seekingalpha.com">Seeking Alpha</source>
    </item></channel></rss>
    """
    article = (
        b"<html><body><p>Susquehanna said semiconductor lead times rose in June "
        b"to 19.4 weeks.</p></body></html>"
    )

    def on_get(url: str, **kwargs) -> MagicMock:
        response = MagicMock()
        response.status_code = 200
        if url == feed_url:
            response.content = feed.encode("utf-8")
            response.url = feed_url
        else:
            response.content = article
            response.url = article_url
        return response

    config_path = tmp_path / "chip_lead_time.yaml"
    config_path.write_text(
        "susquehanna_online:\n"
        f"  rss_urls: [{feed_url}]\n"
        "  source_domains: [seekingalpha.com]\n"
        "  max_feed_items: 10\n",
        encoding="utf-8",
    )

    with patch(
        "stock_data.fetcher.industry.semiconductor.collectors.susquehanna_online.requests.get",
        side_effect=on_get,
    ):
        records = SusquehannaLeadTimeCollector(
            raw_dir=tmp_path / "raw", config_path=config_path
        ).collect(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
        )

    assert len(records) == 1
    record = records[0]
    assert record.report_month == "2026-06"
    assert record.trade_date == date(2026, 6, 30)
    assert record.avg_lead_time_weeks == 19.4
    assert record.source == "Susquehanna/Seeking Alpha"
    assert record.release_date == date(2026, 7, 20)
    assert record.raw_snapshot_path.startswith("semiconductor/lead_time/susquehanna_2026-06_")
    assert record.raw_snapshot_path.endswith(".html")
    raw_path = tmp_path / "raw" / record.raw_snapshot_path
    assert raw_path.read_bytes() == article
    assert record.raw_content_sha256 == raw_content_sha256(article)

    metadata_path = tmp_path / "raw" / "semiconductor" / "lead_time" / "chip_lead_time_2026-06.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["raw_snapshot_path"] == record.raw_snapshot_path
    assert metadata["source_kind"] == "article_html"


def test_chip_lead_time_collector_live_mock(tmp_path: Path, monkeypatch) -> None:
    """验证配置 API Key 时在线抓取、加权计算及 RAW 快照落盘。"""
    monkeypatch.setenv("MOUSER_SEARCH_API_KEY", "mock-test-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "LastUpdated": "2026-08-20",
        "SearchResults": {
            "Parts": [{"LeadTime": "20 Weeks", "Manufacturer": "STMicroelectronics"}]
        },
    }

    with patch("requests.post", return_value=mock_resp):
        collector = ChipLeadTimeCollector(raw_dir=tmp_path / "raw")
        records = collector.collect()

    assert len(records) == 1
    r = records[0]
    assert r.trade_date == date.today()
    assert r.avg_lead_time_weeks == 20.0
    assert r.mcu_lead_time_weeks == 20.0
    assert r.analog_lead_time_weeks == 20.0
    assert r.lead_time_status == "tight"
    assert r.unit == "weeks"
    assert r.source == "Mouser/Distributor"
    assert r.release_date == date(2026, 8, 20)

    # 验证 RAW 快照文件已创建在 data/raw/semiconductor/lead_time/
    raw_files = list((tmp_path / "raw" / "semiconductor" / "lead_time").glob("*.json"))
    assert len(raw_files) == 1
    saved_data = json.loads(raw_files[0].read_text(encoding="utf-8"))
    assert saved_data["avg_lead_time_weeks"] == 20.0
    assert saved_data["release_date"] == "2026-08-20"
    assert r.raw_content_sha256 == raw_content_sha256(raw_files[0].read_bytes())
    assert r.raw_snapshot_path == f"semiconductor/lead_time/{raw_files[0].name}"


def test_chip_lead_time_collector_from_raw_snapshots(tmp_path: Path, monkeypatch) -> None:
    """验证未配置 API Key 时自动回退读取本地 RAW 快照。"""
    monkeypatch.delenv("MOUSER_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("MOUSER_API_KEY", raising=False)
    monkeypatch.setattr("stock_data.core.settings.data_settings.mouser_search_api_key", None)
    monkeypatch.setattr("stock_data.core.settings.data_settings.mouser_api_key", None)

    lead_dir = tmp_path / "raw" / "lead_time"
    lead_dir.mkdir(parents=True, exist_ok=True)

    # 写入 2 个月度真实快照
    (lead_dir / "chip_lead_time_2026-05.json").write_text(
        json.dumps(
            {
                "report_month": "2026-05",
                "trade_date": "2026-05-15",
                "release_date": "2026-05-20",
                "avg_lead_time_weeks": 21.0,
                "category_averages": {
                    "mcu": 20.0,
                    "analog": 18.0,
                    "discrete": 16.0,
                    "compute": 30.0,
                },
            }
        ),
        encoding="utf-8",
    )
    (lead_dir / "chip_lead_time_2026-06.json").write_text(
        json.dumps(
            {
                "report_month": "2026-06",
                "trade_date": "2026-06-16",
                "release_date": "2026-06-20",
                "avg_lead_time_weeks": 21.5,
                "category_averages": {
                    "mcu": 20.5,
                    "analog": 18.5,
                    "discrete": 16.5,
                    "compute": 30.5,
                },
            }
        ),
        encoding="utf-8",
    )

    collector = ChipLeadTimeCollector(raw_dir=tmp_path / "raw")
    records = collector.collect()

    assert len(records) == 2
    assert records[0].report_month == "2026-05"
    assert records[0].trade_date == date(2026, 5, 15)
    assert records[0].avg_lead_time_weeks == 21.0
    assert records[0].release_date == date(2026, 5, 20)
    assert records[0].collected_at == ""
    assert records[0].raw_snapshot_path == "lead_time/chip_lead_time_2026-05.json"
    assert records[0].raw_content_sha256 == raw_content_sha256(
        (lead_dir / "chip_lead_time_2026-05.json").read_bytes()
    )
    assert records[1].report_month == "2026-06"
    assert records[1].trade_date == date(2026, 6, 16)
    assert records[1].avg_lead_time_weeks == 21.5


def test_chip_lead_time_raw_snapshot_without_trade_date_is_skipped(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """RAW 快照缺少观测日期时不使用 report_month 推导日期。"""
    monkeypatch.delenv("MOUSER_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("MOUSER_API_KEY", raising=False)
    monkeypatch.setattr("stock_data.core.settings.data_settings.mouser_search_api_key", None)
    monkeypatch.setattr("stock_data.core.settings.data_settings.mouser_api_key", None)

    lead_dir = tmp_path / "raw" / "lead_time"
    lead_dir.mkdir(parents=True, exist_ok=True)
    (lead_dir / "chip_lead_time_2026-05.json").write_text(
        json.dumps({"report_month": "2026-05", "avg_lead_time_weeks": 21.0}),
        encoding="utf-8",
    )

    collector = ChipLeadTimeCollector(raw_dir=tmp_path / "raw")
    assert collector.collect() == []


def test_chip_lead_time_collector_empty_when_no_key_and_no_raw(tmp_path: Path, monkeypatch) -> None:
    """验证未配置 Key 且本地无 RAW 快照时安全返回空列表。"""
    monkeypatch.delenv("MOUSER_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("MOUSER_API_KEY", raising=False)
    monkeypatch.setattr("stock_data.core.settings.data_settings.mouser_search_api_key", None)
    monkeypatch.setattr("stock_data.core.settings.data_settings.mouser_api_key", None)

    collector = ChipLeadTimeCollector(raw_dir=tmp_path / "raw")
    records = collector.collect()
    assert records == []


def test_chip_lead_time_transform_and_empty() -> None:
    """验证 DataFrame 转换与空表骨架。"""
    df_empty = empty_chip_lead_time()
    assert df_empty.schema == CHIP_LEAD_TIME_SCHEMA
    assert df_empty.height == 0

    records = [
        ChipLeadTimeRecord(
            report_month="2026-07",
            trade_date=date(2026, 7, 31),
            avg_lead_time_weeks=21.32,
            mcu_lead_time_weeks=19.5,
            analog_lead_time_weeks=18.0,
            discrete_lead_time_weeks=16.5,
            compute_lead_time_weeks=31.0,
            lead_time_status="tight",
            release_date=date(2026, 8, 20),
        )
    ]
    df = records_to_chip_lead_time_frame(records)
    assert df.height == 1
    assert df["avg_lead_time_weeks"][0] == 21.32

    raw_df = records_to_raw_chip_lead_time_frame(records)
    assert "raw_content_sha256" in raw_df.columns
    assert "raw_snapshot_path" in raw_df.columns


def test_chip_lead_time_yoy_mom_skip_cross_source_switch() -> None:
    """数据源切换（Susquehanna -> Mouser）时 yoy/mom 置 None，不跨源相减。"""
    # 构造 2025-07 ~ 2026-08 连续 14 个月：前 13 个月 Susquehanna，末月切换 Mouser
    records: list[ChipLeadTimeRecord] = []
    for offset in range(13):
        base = date(2025, 7, 1)
        month_idx = (base.year * 12 + base.month - 1) + offset
        month = date(month_idx // 12, month_idx % 12 + 1, 1)
        records.append(
            ChipLeadTimeRecord(
                report_month=f"{month.year:04d}-{month.month:02d}",
                trade_date=date(month.year, month.month, 28),
                avg_lead_time_weeks=17.8 + offset * 0.15,
                source="Susquehanna Monthly Report",
                release_date=date(month.year, month.month, 28),
            )
        )
    records.append(
        ChipLeadTimeRecord(
            report_month="2026-08",
            trade_date=date(2026, 8, 31),
            avg_lead_time_weeks=23.93,
            source="Mouser/Distributor",
            release_date=date(2026, 8, 31),
        )
    )
    df = records_to_chip_lead_time_frame(records)
    by_month = {r["report_month"]: r for r in df.iter_rows(named=True)}

    # 2026-07 与 2025-07 同源 Susquehanna，同比正常计算（17.8 + 12*0.15 = 19.6）
    assert by_month["2026-07"]["lead_time_yoy_weeks"] == round(19.6 - 17.8, 2)
    # 2026-08 为 Mouser 新源，与历史非同源：yoy/mom 均置 None
    assert by_month["2026-08"]["lead_time_yoy_weeks"] is None
    assert by_month["2026-08"]["lead_time_mom_weeks"] is None


def test_execute_single_industry_task_chip_lead_time(tmp_path: Path, monkeypatch) -> None:
    """验证 execute_single_industry_task 分发 Susquehanna 在线端点并生成 parquet。"""
    feed_url = "https://news.example.test/susquehanna.xml"
    article_url = "https://seekingalpha.com/news/test"
    feed = f"""
    <rss><channel><item>
      <title>Susquehanna lead time update</title>
      <link>{article_url}</link>
      <pubDate>Mon, 20 Jul 2026 10:41:00 GMT</pubDate>
      <description>lead times in June reached 19.4 weeks</description>
      <source url="https://seekingalpha.com">Seeking Alpha</source>
    </item></channel></rss>
    """

    def on_get(url: str, **kwargs) -> MagicMock:
        response = MagicMock()
        response.status_code = 200
        response.content = (
            feed.encode("utf-8")
            if url == feed_url
            else b"<html><body>Susquehanna lead times in June reached 19.4 weeks.</body></html>"
        )
        response.url = feed_url if url == feed_url else article_url
        return response

    with (
        patch(
            "stock_data.fetcher.industry.semiconductor.collectors.susquehanna_online.requests.get",
            side_effect=on_get,
        ),
        patch(
            "stock_data.fetcher.industry.semiconductor.collectors.susquehanna.load_chip_lead_time_config",
            return_value={
                "thresholds": {"overheating": 26.0, "tight": 18.0, "normal": 13.0},
                "susquehanna_online": {
                    "rss_urls": [feed_url],
                    "source_domains": ["seekingalpha.com"],
                },
            },
        ),
    ):
        count = execute_single_industry_task(
            endpoint="chip_lead_time",
            raw_dir=tmp_path / "raw",
            curated_dir=tmp_path / "curated",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
        )

    assert count == 1
    parquet_path = tmp_path / "curated" / "semiconductor" / "capacity" / "chip_lead_time.parquet"
    assert parquet_path.exists()
    df = pl.read_parquet(parquet_path)
    assert df.height == 1
    assert df["avg_lead_time_weeks"][0] == 19.4


def test_task_bundles_includes_chip_lead_time() -> None:
    """验证 task_bundles 中 industry_tech 与 industry_all 包含 chip_lead_time。"""
    tech_tasks = expand_task_targets("industry", ["industry_tech"])
    assert "chip_lead_time" in tech_tasks

    all_tasks = expand_task_targets("industry", ["industry_all"])
    assert "chip_lead_time" in all_tasks


def test_susquehanna_request_retries_transient_timeout(monkeypatch) -> None:
    from stock_data.fetcher.industry.semiconductor.collectors import susquehanna_online

    response = MagicMock(status_code=200)
    attempts = 0

    def fake_get(url: str, **kwargs: object) -> MagicMock:
        nonlocal attempts
        del url, kwargs
        attempts += 1
        if attempts == 1:
            raise TimeoutError("temporary RSS timeout")
        return response

    monkeypatch.setattr(susquehanna_online.requests, "get", fake_get)

    assert susquehanna_online._get("https://example.test/feed.xml", timeout=1) is response
    assert attempts == 2


def test_susquehanna_proxy_is_forwarded(monkeypatch) -> None:
    from stock_data.fetcher.industry.semiconductor.collectors import susquehanna_online

    response = MagicMock(status_code=200)
    captured: dict[str, object] = {}

    def fake_get(url: str, **kwargs: object) -> MagicMock:
        del url
        captured.update(kwargs)
        return response

    monkeypatch.setattr(susquehanna_online.requests, "get", fake_get)

    proxy = "http://proxy.example.test:3128"
    assert (
        susquehanna_online._get("https://example.test/feed.xml", timeout=1, proxy=proxy) is response
    )
    assert captured["proxies"] == {"http": proxy, "https": proxy}
