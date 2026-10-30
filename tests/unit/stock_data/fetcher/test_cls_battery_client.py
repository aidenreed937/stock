"""财联社（CLS）动力电池电报采集客户端单元测试。"""

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from stock_data.fetcher.industry.automotive.clients.cabia import CabiaOnlineClient
from stock_data.fetcher.industry.automotive.clients.cls import (
    ClsBatteryClient,
    generate_cls_sign,
)


def test_generate_cls_sign() -> None:
    """验证财联社 API 的双哈希签名生成正确性。"""
    params = {
        "app": "CailianpressWeb",
        "category": "telegraph",
        "os": "web",
        "refresh_type": "1",
        "rn": "20",
        "sv": "8.4.6",
    }
    sign = generate_cls_sign(params)
    assert isinstance(sign, str)
    assert len(sign) == 32  # MD5 16进制长度
    # 相同输入应幂等
    assert generate_cls_sign(params) == sign


def test_parse_valid_telegraph_item(tmp_path: Path) -> None:
    """验证标准 CABIA 动力电池装车量电报的解析。"""
    client = ClsBatteryClient(raw_dir=tmp_path)
    item = {
        "id": "2142231",
        "ctime": 1757558400,  # 对应 2025-09-11
        "title": "中国汽车动力电池产业创新联盟：8月我国动力电池装车量62.5GWh 同比增长32.4%",
        "content": (
            "财联社9月11日电，中国汽车动力电池产业创新联盟发布数据显示，"
            "8月，我国动力和其他电池合计产量为123.5GWh，环比增长14.3%，同比增长47.9%。"
            "其中，动力电池装车量62.5GWh，环比增长11.8%，同比增长32.4%。"
        ),
    }
    parsed = client._parse_telegraph_item(item)
    assert parsed is not None
    assert parsed["report_month"] == "2025-08"
    assert parsed["battery_installation_gwh"] == 62.5
    assert parsed["battery_installation_gwh_raw"] == "62.5"
    assert parsed["yoy_growth"] == 0.324
    assert parsed["source"] == "CABIA"
    assert "cls.cn/detail/2142231" in parsed["source_url"]


def test_parse_rejects_non_installation_news(tmp_path: Path) -> None:
    """验证仅有产量或总销量而没有装车量的电报被安全拦截。"""
    client = ClsBatteryClient(raw_dir=tmp_path)
    # 仅报道电池产量
    production_item = {
        "id": "1001",
        "ctime": 1757558400,
        "title": "中国汽车动力电池产业创新联盟：8月我国动力和其他电池合计产量为123.5GWh",
        "content": "8月我国动力和储能电池合计产量123.5GWh，同比增长47.9%，未披露其他细节。",
    }
    assert client._parse_telegraph_item(production_item) is None

    # 不相关的非动力电池新闻
    irrelevant_item = {
        "id": "1002",
        "ctime": 1757558400,
        "title": "某地储能电站并网运行",
        "content": "某市首个电网侧独立储能电站顺利并网，规模 100MW/200MWh。",
    }
    assert client._parse_telegraph_item(irrelevant_item) is None


def test_parse_threshold_gate(tmp_path: Path) -> None:
    """验证装车量门禁校验 [40.0, 150.0] GWh。"""
    client = ClsBatteryClient(raw_dir=tmp_path)

    # 低于门禁 (例如 15.0 GWh，可能是局部数据或老旧年份数据)
    too_low_item = {
        "id": "2001",
        "ctime": 1757558400,
        "title": "中国汽车动力电池产业创新联盟：我国某类动力电池装车量15.0GWh",
        "content": "我国某类动力电池装车量15.0GWh，同比增长10%。",
    }
    assert client._parse_telegraph_item(too_low_item) is None

    # 高于门禁 (例如 200.0 GWh，通常是产量或合计销量被误匹配)
    too_high_item = {
        "id": "2002",
        "ctime": 1757558400,
        "title": "中国汽车动力电池产业创新联盟：动力电池装车量200.0GWh",
        "content": "动力电池装车量达到200.0GWh，同比增长50%。",
    }
    assert client._parse_telegraph_item(too_high_item) is None

    # 合法临界值
    valid_low_item = {
        "id": "2003",
        "ctime": 1757558400,
        "title": "中国汽车动力电池产业创新联盟：2026年1月动力电池装车量42.0GWh",
        "content": "2026年1月，我国动力电池装车量42.0GWh，同比增长8.4%。",
    }
    parsed = client._parse_telegraph_item(valid_low_item)
    assert parsed is not None
    assert parsed["battery_installation_gwh"] == 42.0


def test_cls_fetch_flow_and_snapshot(tmp_path: Path) -> None:
    """验证正常拉取电报并落盘 RAW 快照的完整流程。"""
    client = ClsBatteryClient(raw_dir=tmp_path)
    mock_item = {
        "id": "9999",
        "ctime": 1757558400,
        "title": "中国汽车动力电池产业创新联盟：8月我国动力电池装车量62.5GWh 同比增长32.4%",
        "content": "8月我国动力电池装车量62.5GWh，同比增长32.4%……",
    }
    mock_payload = {
        "data": {
            "roll_data": [mock_item],
        }
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_payload

    with patch(
        "stock_data.fetcher.industry.automotive.clients.cls.requests.get", return_value=mock_resp
    ):
        results = client.fetch(start_date=date(2025, 8, 1), end_date=date(2025, 8, 31))

    assert "2025-08" in results
    rec = results["2025-08"]
    assert rec["battery_installation_gwh"] == 62.5
    assert rec["raw_content_sha256"] != ""
    # 验证 RAW 快照文件已落盘
    snapshot_file = tmp_path / "automotive" / "cabia" / "cls_telegraph_2025-08.json"
    assert snapshot_file.exists()


def test_cls_fetch_graceful_degradation(tmp_path: Path) -> None:
    """验证网络异常或接口报错时安全降级而不抛出异常。"""
    client = ClsBatteryClient(raw_dir=tmp_path)

    # 1. 网络抛出异常
    with patch(
        "stock_data.fetcher.industry.automotive.clients.cls.requests.get",
        side_effect=RuntimeError("Connection reset"),
    ):
        results = client.fetch()
        assert results == {}
        assert len(client.last_errors) == 1
        assert "Connection reset" in client.last_errors[0]

    # 2. HTTP 500 状态码
    bad_resp = MagicMock()
    bad_resp.status_code = 500
    with patch(
        "stock_data.fetcher.industry.automotive.clients.cls.requests.get", return_value=bad_resp
    ):
        results = client.fetch()
        assert results == {}
        assert any("500" in err for err in client.last_errors)


def test_cabia_online_client_delegates_to_cls(tmp_path: Path) -> None:
    """验证 CabiaOnlineClient 直接委托 ClsBatteryClient 进行增量采集。"""
    cabia_client = CabiaOnlineClient(raw_dir=tmp_path)

    mock_cls_results = {
        "2026-07": {
            "report_month": "2026-07",
            "release_date": date(2026, 8, 11),
            "battery_installation_gwh": 74.6,
            "battery_installation_gwh_raw": "74.6",
            "yoy_growth": 0.335,
            "yoy_growth_raw": "33.5%",
            "source": "CABIA",
            "source_url": "https://www.cls.cn/detail/2301889",
        }
    }

    with patch.object(
        cabia_client.cls_client, "fetch", return_value=mock_cls_results
    ) as mock_cls_fetch:
        results = cabia_client.fetch(
            start_date=date(2026, 7, 1), end_date=date(2026, 7, 31), max_pages=1
        )

    assert mock_cls_fetch.called
    assert "2026-07" in results
    assert results["2026-07"]["battery_installation_gwh"] == 74.6
    assert cabia_client.last_fetched_periods == ("2026-07",)
