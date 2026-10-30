"""验证大商所 CDP 采集脚本核心功能与异常边界。"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest
from scripts.cdp.dce_cdp_automation import (
    find_chrome_ws_url,
    format_dce_inventory_text,
    format_dce_quotes_tsv,
    generate_date_range,
    get_local_cached_dates,
    is_publish_time_ready,
    resolve_smart_harvest_plan,
    save_raw_inventory,
    save_raw_quotes,
)

from stock_data.fetcher.industry.chemicals.collectors.official import (
    DEFAULT_DCE_INVENTORY_COMMODITIES,
    parse_dce_daily_text,
    parse_dce_inventory_text,
)


def test_generate_date_range_skips_weekends() -> None:
    """验证日期范围生成自动过滤周末。"""
    # 2026-09-11 (周五) 至 2026-09-15 (周二)
    start = date(2026, 9, 11)
    end = date(2026, 9, 15)
    dates = generate_date_range(start, end)
    # 应包含: 周五 (11), 周一 (14), 周二 (15)
    assert dates == [
        date(2026, 9, 11),
        date(2026, 9, 14),
        date(2026, 9, 15),
    ]


def test_save_raw_quotes(tmp_path: Path) -> None:
    """验证日行情文本保存路径与编码。"""
    t_date = date(2026, 9, 15)
    content = "品种\t合约代码\t收盘价\nEG\tEG2601\t4500\n"
    saved = save_raw_quotes(tmp_path, t_date, content)

    expected_path = (
        tmp_path / "chemicals" / "futures_daily" / "dce_daily_cache" / "2026" / "20260915.txt"
    )
    assert saved == expected_path
    assert saved.exists()
    assert saved.read_text(encoding="utf-8") == content


def test_save_raw_inventory(tmp_path: Path) -> None:
    """验证仓单日报保存路径与编码。"""
    t_date = date(2026, 9, 15)
    content = "品种：乙二醇\n总计 1000 1200 200\n"
    saved = save_raw_inventory(tmp_path, t_date, content)

    expected_path = tmp_path / "chemicals" / "futures_inventory" / "dce" / "2026" / "20260915.txt"
    assert saved == expected_path
    assert saved.exists()
    assert saved.read_text(encoding="utf-8") == content


def test_find_chrome_ws_url_unreachable() -> None:
    """验证当 Chrome 未启动或端口未开放时抛出友好提示。"""
    with pytest.raises(ConnectionRefusedError) as exc_info:
        # 指向一个大概率未开启的端口
        find_chrome_ws_url(port=65432)
    assert "无法连接到 Chrome CDP 调试端口" in str(exc_info.value)
    assert "--remote-debugging-port" in str(exc_info.value)


def test_format_dce_quotes_tsv() -> None:
    """验证 REST API 行情字典列表格式化为符合下游解析器的标准 TSV。"""
    items = [
        {
            "variety": "乙二醇",
            "contractId": "eg2610",
            "open": "6154",
            "high": "6301",
            "low": "6053",
            "close": "6096",
            "clearPrice": "6179",
            "volumn": 2542152,
            "openInterest": 248044,
        },
        {
            "variety": "聚氯乙烯",
            "contractId": "v2609",
            "open": "5400",
            "high": "5420",
            "low": "5380",
            "close": "5390",
            "clearPrice": "5395",
            "volumn": 10000,
            "openInterest": 5000,
        },
    ]

    tsv = format_dce_quotes_tsv(items)
    assert "合约代码\t今开盘\t今最高" in tsv
    assert "eg2610\t6154\t6301" in tsv

    parsed = parse_dce_daily_text(tsv, ("EG", "V"))
    assert "EG" in parsed
    assert "V" in parsed
    assert parsed["EG"][0]["contract"] == "eg2610"
    assert parsed["EG"][0]["close"] == 6096.0
    assert parsed["EG"][0]["settle"] == 6179.0
    assert parsed["EG"][0]["volume"] == 2542152.0
    assert parsed["EG"][0]["open_interest"] == 248044.0


def test_format_dce_inventory_text() -> None:
    """验证 REST API 仓单 entityList 格式化为符合下游解析器的标准官方日报文本。"""
    entities = [
        {
            "varietyOrder": "eb",
            "variety": "苯乙烯",
            "whAbbr": "连云港石化",
            "lastWbillQty": 0,
            "wbillQty": 300,
            "diff": 300,
        },
        {
            "varietyOrder": "eb",
            "variety": "苯乙烯小计",
            "whAbbr": None,
            "lastWbillQty": 0,
            "wbillQty": 300,
            "diff": 300,
        },
        {
            "varietyOrder": "eg",
            "variety": "乙二醇",
            "whAbbr": "中海壳牌石油",
            "lastWbillQty": 400,
            "wbillQty": 400,
            "diff": 0,
        },
        {
            "varietyOrder": "eg",
            "variety": "乙二醇小计",
            "whAbbr": None,
            "lastWbillQty": 2244,
            "wbillQty": 2244,
            "diff": 0,
        },
    ]

    text = format_dce_inventory_text(entities)
    assert "品种：苯乙烯" in text
    assert "品种：乙二醇" in text
    assert "总计\t2244\t2244\t0" in text

    parsed = parse_dce_inventory_text(text, DEFAULT_DCE_INVENTORY_COMMODITIES)
    assert parsed["EB"] == (300.0, 300.0)
    assert parsed["EG"] == (2244.0, 0.0)


def test_is_publish_time_ready() -> None:
    """验证交易所时效保护逻辑（周末跳过、收盘前跳过、收盘后通过）。"""
    # 1. 周末 (2026-09-19 周六)
    ready, msg = is_publish_time_ready(date(2026, 9, 19), "all")
    assert not ready
    assert "周末" in msg

    # 2. 历史交易日 (2026-09-15)
    now = datetime(2026, 9, 18, 10, 0)
    ready, _ = is_publish_time_ready(date(2026, 9, 15), "all", now=now)
    assert ready

    # 3. 今天收盘前 (2026-09-18 14:00)
    ready_quotes, _ = is_publish_time_ready(date(2026, 9, 18), "quotes", now=now)
    assert not ready_quotes
    ready_all, _ = is_publish_time_ready(date(2026, 9, 18), "all", now=now)
    assert not ready_all

    # 4. 今天收盘后 (2026-09-18 17:00)
    now_after = datetime(2026, 9, 18, 17, 0)
    ready_quotes_after, _ = is_publish_time_ready(date(2026, 9, 18), "quotes", now=now_after)
    assert ready_quotes_after
    ready_inv_after, _ = is_publish_time_ready(date(2026, 9, 18), "inventory", now=now_after)
    assert ready_inv_after


def test_get_local_cached_dates(tmp_path: Path) -> None:
    """验证扫描指定 RAW 缓存目录识别已有日期集合。"""
    cache_dir = tmp_path / "chemicals" / "futures_daily" / "dce_daily_cache" / "2026"
    cache_dir.mkdir(parents=True)
    (cache_dir / "20260915.txt").write_text("dummy " * 50, encoding="utf-8")
    (cache_dir / "20260916.txt").write_text("dummy " * 50, encoding="utf-8")
    # 空文件不应计入
    (cache_dir / "20260917.txt").write_text("", encoding="utf-8")

    dates = get_local_cached_dates(tmp_path, "futures_daily/dce_daily_cache")
    assert dates == {date(2026, 9, 15), date(2026, 9, 16)}


def test_resolve_smart_harvest_plan(tmp_path: Path) -> None:
    """验证全自动水位增量追赶与幂等跳过。"""
    q_dir = tmp_path / "chemicals" / "futures_daily" / "dce_daily_cache" / "2026"
    i_dir = tmp_path / "chemicals" / "futures_inventory" / "dce" / "2026"
    q_dir.mkdir(parents=True)
    i_dir.mkdir(parents=True)

    # 本地最高水位到 2026-09-15
    (q_dir / "20260915.txt").write_text("dummy " * 50, encoding="utf-8")
    (i_dir / "20260915.txt").write_text("dummy " * 50, encoding="utf-8")

    # 当前时间模拟为 2026-09-17 17:00 (周四收盘后)
    now = datetime(2026, 9, 17, 17, 0)

    # 未指定任何参数时，应自动从水位+1 (2026-09-16) 追赶至 2026-09-17
    planned, meta = resolve_smart_harvest_plan(tmp_path, "all", now=now)
    assert planned == [date(2026, 9, 16), date(2026, 9, 17)]
    assert meta["max_quotes_date"] == "2026-09-15"
    assert meta["max_inv_date"] == "2026-09-15"

    # 若本地已补齐 16 和 17 日，再次规划应为 0，纯幂等
    (q_dir / "20260916.txt").write_text("dummy " * 50, encoding="utf-8")
    (i_dir / "20260916.txt").write_text("dummy " * 50, encoding="utf-8")
    (q_dir / "20260917.txt").write_text("dummy " * 50, encoding="utf-8")
    (i_dir / "20260917.txt").write_text("dummy " * 50, encoding="utf-8")

    planned_empty, meta_empty = resolve_smart_harvest_plan(tmp_path, "all", now=now)
    assert planned_empty == []
    assert meta_empty["max_quotes_date"] == "2026-09-17"
